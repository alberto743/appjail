# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Command line interface."""

import argparse
import hashlib
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone

from . import appimage, github, jail, manifest, store, textsafe

MAX_ASSET = 2 * 1024 ** 3
YOUNG_ACCOUNT_DAYS = 90
FEW_STARS = 10


class Abort(Exception):
    """The user declined, or the operation cannot continue; message is shown as is."""


class Console:
    """Terminal I/O. Every line goes through textsafe, so callers cannot leak escapes."""

    def out(self, line=""):
        print(textsafe.clean(line))

    def warn(self, line):
        print("WARNING: " + textsafe.clean(line))

    def ask(self, prompt):
        try:
            return input(prompt).strip()
        except EOFError:
            raise Abort("no input available") from None

    def confirm(self, prompt, default=False):
        answer = self.ask(f"{prompt} [{'Y/n' if default else 'y/N'}] ").lower()
        return default if not answer else answer in ("y", "yes")

    def choose(self, prompt, options):
        for i, o in enumerate(options, 1):
            self.out(f"  {i}. {o}")
        answer = self.ask(f"{prompt} [1-{len(options)}, empty to cancel] ")
        if not answer:
            raise Abort("cancelled")
        if not answer.isdigit() or not 1 <= int(answer) <= len(options):
            raise Abort("invalid choice")
        return int(answer) - 1


def human_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def default_name(repo):
    name = re.sub(r"[^a-z0-9._-]", "-", repo.lower()).lstrip("._-")[:64]
    return name if manifest.NAME_RE.fullmatch(name or "!") else ""


def show_review(console, info, now=None):
    """Typosquat check: who owns this repo, how old and how popular is it."""
    days = github.age_days(info.owner_created_at, now)
    console.out(f"Repository : {info.full_name}  {info.html_url}")
    if info.description:
        console.out(f"About      : {info.description}")
    console.out(f"Owner      : {info.owner} ({info.owner_type}, id {info.owner_id}), account created "
                f"{info.owner_created_at[:10]} ({days} days ago)")
    console.out(f"Stars      : {info.stars}")
    if info.renamed:
        console.warn(f"GitHub reports this repository as {info.full_name}: it was renamed or transferred")
    if info.fork:
        console.warn(f"this is a fork of {info.parent or 'another repository'}")
    if info.archived:
        console.warn("this repository is archived (no longer maintained)")
    if days < YOUNG_ACCOUNT_DAYS:
        console.warn(f"the owner account is only {days} days old")
    if info.stars < FEW_STARS:
        console.warn("the repository has very few stars")


def permissions_from_args(args):
    allowed = set(args.allow)
    return manifest.Permissions(
        network="network" in allowed, portals="portals" in allowed,
        audio=not args.no_audio, gpu=not args.no_gpu,
        display=args.display,
    )


def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_add(args, client, console, download=jail.download, now=None):
    name = args.name or default_name(args.source.partition("/")[2])
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")

    info = client.repo_info(args.source)
    show_review(console, info, now)
    if info.renamed and not console.confirm(f"Continue with {info.full_name}?"):
        raise Abort("cancelled")
    source = info.full_name

    release = client.latest_release(source, args.prerelease)
    console.out(f"Release    : {release.tag}, published {release.published_at}"
                + ("  (pre-release)" if release.prerelease else ""))
    console.out(f"             {release.html_url}")
    candidates = github.appimage_candidates(release)
    if not candidates:
        names = ", ".join(a.name for a in release.assets[:15]) or "no assets"
        raise Abort(f"no x86_64 AppImage asset in this release ({names})")
    if len(candidates) == 1:
        asset = candidates[0]
    else:
        console.out("Several AppImage assets match; choose one:")
        asset = candidates[console.choose("Asset", [f"{a.name} ({human_size(a.size)})" for a in candidates])]
    if not 0 < asset.size <= MAX_ASSET:
        raise Abort(f"unexpected asset size ({asset.size} bytes)")

    attestation = "not checked"
    if asset.sha256:
        try:
            attestation = "present (not verified)" if client.has_attestation(source, asset.sha256) else "none found"
        except github.GitHubError:
            attestation = "lookup failed"
    console.out(f"Asset      : {asset.name} ({human_size(asset.size)})")
    console.out(f"GitHub sha256 digest: {asset.sha256 or 'none'}   attestation: {attestation}")
    tier = 3 if asset.sha256 else 4
    if tier == 4:
        console.warn("GitHub gives no digest for this asset: trust on first use only (tier 4)")
    perms = permissions_from_args(args)
    granted = [f"{k}={v}" for k, v in vars(perms).items() if v not in ((), False)]
    console.out("Permissions: " + ", ".join(granted))

    if not console.confirm(f"Download {asset.name} from github.com in a network-only jail?"):
        raise Abort("cancelled")

    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged = download(asset.url, stage, "download.AppImage", asset.size)
        if staged.stat().st_size != asset.size:
            raise Abort("downloaded size differs from the size GitHub announced")
        digest = hash_file(staged)
        if asset.sha256 and digest != asset.sha256:
            raise Abort(f"sha256 mismatch: downloaded {digest}, GitHub digest {asset.sha256}")
        try:
            appimage.appimage_type(staged)
        except appimage.NotAnAppImage as e:
            raise Abort(f"downloaded file is not a usable AppImage: {e}") from e
        record = manifest.Manifest(
            name=name, source=source, asset_pattern=github.suggest_pattern(asset.name, release.tag),
            version=release.tag, sha256=digest, evidence_tier=tier, published_at=release.published_at,
            owner_id=info.owner_id, permissions=perms)
        manifest.validate(record)
        dest = store.appimage_path(name)
        dest.parent.mkdir(parents=True, mode=0o700)
        try:
            os.replace(staged, dest)
            manifest.dump(store.manifest_path(name), record)
        except BaseException:
            shutil.rmtree(dest.parent, ignore_errors=True)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    console.out(f"Added '{name}' {release.tag}: sha256 {digest}, evidence tier {tier}")
    console.out(f"Manifest   : {store.manifest_path(name)}")


def build_parser():
    p = argparse.ArgumentParser(prog="bjail", description="Sandboxed AppImage manager")
    sub = p.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add an app from a GitHub owner/repo")
    add.add_argument("source", help="GitHub owner/repo")
    add.add_argument("--name", help="local app name (default: repo name)")
    add.add_argument("--prerelease", action="store_true", help="allow pre-releases")
    add.add_argument("--allow", action="append", default=[], choices=["network", "portals"],
                     help="grant a permission (repeatable); audio and gpu are on by default")
    add.add_argument("--no-audio", action="store_true", help="do not grant audio")
    add.add_argument("--no-gpu", action="store_true", help="do not grant GPU access")
    add.add_argument("--display", choices=manifest.DISPLAYS, default="wayland")
    return p


def main(argv=None, client=None, console=None):
    args = build_parser().parse_args(argv)
    console = console or Console()
    try:
        if args.command == "add":
            if not manifest.SOURCE_RE.fullmatch(args.source):
                raise Abort("source must be a GitHub owner/repo")
            cmd_add(args, client or github.Client(), console)
    except Abort as e:
        console.out(str(e))
        return 1
    except (github.GitHubError, jail.JailError, manifest.ManifestError, OSError) as e:
        console.out(f"error: {e}")
        return 1
    return 0
