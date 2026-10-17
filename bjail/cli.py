# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Command line interface."""

import argparse
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import appimage, github, jail, manifest, runner, store, textsafe

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


def dirs_from_args(specs, home=None, cwd=None):
    """Canonical, existing directories for --dir options."""
    home, cwd = home or Path.home(), cwd or Path.cwd()
    out = []
    for spec in specs:
        try:
            entry = manifest.normalize_dir(spec, home, cwd)
        except manifest.ManifestError as e:
            raise Abort(f"--dir {spec}: {e}") from e
        host = Path(home) / entry[2:] if entry.startswith("~/") else Path(entry)
        if not Path(str(host).removesuffix(":rw")).is_dir():
            raise Abort(f"--dir {spec}: not a directory")
        out.append(entry)
    return tuple(out)


def permissions_from_args(args):
    allowed = set(args.allow)
    return manifest.Permissions(
        dirs=dirs_from_args(args.dir),
        network="network" in allowed, portals="portals" in allowed,
        audio=not args.no_audio, gpu=not args.no_gpu,
        display=args.display,
    )


def cmd_add(args, client, console, download=jail.download, now=None, extract=appimage.extract,
            extract_ok=appimage.have_unsquashfs):
    name = args.name or default_name(args.source.partition("/")[2])
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")

    perms = permissions_from_args(args)  # validates --dir before any network access

    info = client.repo_info(args.source)
    show_review(console, info, now)
    if info.renamed and not console.confirm(f"Continue with {info.full_name}?"):
        raise Abort("cancelled")
    source = info.full_name

    release = (client.release_by_tag(source, args.tag) if args.tag
               else client.latest_release(source, args.prerelease))
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
    granted = [f"{k}={v}" for k, v in vars(perms).items() if v not in ((), False)]
    console.out("Permissions: " + ", ".join(granted))

    fallback = False
    if not extract_ok():
        fallback = console.confirm("unsquashfs is not installed. Run the AppImage's own extractor "
                                   "(--appimage-extract) inside a jail with no network instead?")
        if not fallback:
            raise Abort("install squashfs-tools (apt install squashfs-tools) and retry")

    if not console.confirm(f"Download {asset.name} from github.com in a network-only jail?"):
        raise Abort("cancelled")

    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged = download(asset.url, stage, "download.AppImage", asset.size)
        if staged.stat().st_size != asset.size:
            raise Abort("downloaded size differs from the size GitHub announced")
        digest = appimage.sha256_file(staged)
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
            os.chmod(staged, 0o600)
            os.replace(staged, dest)
            try:
                entries, size = extract(dest, store.root_path(name), fallback)
            except (appimage.UnsupportedImage, appimage.ExtractError, appimage.UnsafeTree) as e:
                raise Abort(f"cannot extract the AppImage: {e}") from e
            store.root_marker(name).write_text(digest + "\n")
            manifest.dump(store.manifest_path(name), record)
        except BaseException:
            appimage.remove_tree(dest.parent)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    console.out(f"Extracted  : {entries} entries, {human_size(size)}")
    console.out(f"Added '{name}' {release.tag}: sha256 {digest}, evidence tier {tier}")
    console.out(f"Manifest   : {store.manifest_path(name)}")


def build_parser():
    p = argparse.ArgumentParser(prog="bjail", description="Sandboxed AppImage manager")
    sub = p.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add an app from a GitHub owner/repo")
    add.add_argument("source", help="GitHub owner/repo")
    add.add_argument("--name", help="local app name (default: repo name)")
    add.add_argument("--prerelease", action="store_true", help="allow pre-releases")
    add.add_argument("--tag", help="use this release tag instead of the latest release")
    add.add_argument("--dir", action="append", default=[], metavar="PATH[:ro|:rw]",
                     help="let the app see this directory (read-only unless :rw); repeatable")
    add.add_argument("--allow", action="append", default=[], choices=["network", "portals"],
                     help="grant a permission (repeatable); audio and gpu are on by default")
    add.add_argument("--no-audio", action="store_true", help="do not grant audio")
    add.add_argument("--no-gpu", action="store_true", help="do not grant GPU access")
    add.add_argument("--display", choices=manifest.DISPLAYS, default="wayland")
    run = sub.add_parser("run", help="run an installed app in its jail")
    run.add_argument("name")
    run.add_argument("--dir", action="append", default=[], metavar="PATH[:ro|:rw]",
                     help="grant this directory for this run only (manifest unchanged); repeatable")
    return p


def main(argv=None, client=None, console=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app_args = []
    if "--" in argv:  # everything after -- belongs to the app
        i = argv.index("--")
        argv, app_args = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    console = console or Console()
    try:
        if args.command == "add":
            if not manifest.SOURCE_RE.fullmatch(args.source):
                raise Abort("source must be a GitHub owner/repo")
            cmd_add(args, client or github.Client(), console)
        elif args.command == "run":
            extra_dirs = dirs_from_args(args.dir)
            return runner.launch(args.name, app_args, say=console.out, extra_dirs=extra_dirs)
    except Abort as e:
        console.out(str(e))
        return 1
    except (github.GitHubError, jail.JailError, jail.RunError, manifest.ManifestError, OSError) as e:
        console.out(f"error: {e}")
        return 1
    return 0
