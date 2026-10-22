# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add`, and the install steps `update` shares with it."""

import os
import re
import secrets
import shutil

from . import appimage, attest, github, history, jail, manifest, store, tools
from .cmd_desktop import install_entry
from .console import Abort, human_size
from .permargs import (
    granted_summary,
    permissions_from_args,
    require_pasta,
    warn_owned_dbus,
    warn_privileged_portals,
    warn_sensitive_dbus,
)

MAX_ASSET = 2 * 1024 ** 3
YOUNG_ACCOUNT_DAYS = 90
FEW_STARS = 10


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


def download_verified(download, asset, stage):
    """Download the asset in the jail and check what can be checked: the announced size, GitHub's digest if
    there is one, and that it is a type-2 AppImage. Returns (staged path, sha256)."""
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
    return staged, digest


def gather_evidence(client, info, staged, digest, base_tier, console, verify=attest.verify):
    """Tier for the downloaded file: 1 when a build attestation verifies, else base_tier.

    Returns (tier, reason); reason explains why an existing attestation did not count (None when
    there was none or it verified).
    """
    try:
        bundles = client.attestation_bundles(info.full_name, digest)
    except github.GitHubError as e:
        return base_tier, f"attestation lookup failed: {e}"
    if not bundles:
        return base_tier, None
    try:
        v = verify(staged, info.full_name, bundles, info.owner_id)
    except attest.AttestError as e:
        return base_tier, str(e)
    console.out(f"  attestation verified: signed by {v.workflow} (run {v.run_url or 'unknown'})")
    return 1, None


def cmd_add(args, client, console, download=jail.download, now=None, extract=appimage.extract,
            extract_ok=appimage.have_unsquashfs, verify=attest.verify):
    name = args.name or default_name(args.source.partition("/")[2])
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")

    perms = permissions_from_args(args)  # validates --dir before any network access
    require_pasta(perms)

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
            if client.has_attestation(source, asset.sha256):
                attestation = ("present (verified after the download)" if tools.status("gh") == "ok"
                               else "present, cannot be verified: run `appjail tools install gh` to enable tier 1")
            else:
                attestation = "none found"
        except github.GitHubError:
            attestation = "lookup failed"
    console.out(f"Asset      : {asset.name} ({human_size(asset.size)})")
    console.out(f"GitHub sha256 digest: {asset.sha256 or 'none'}   attestation: {attestation}")
    tier = 3 if asset.sha256 else 4
    if tier == 4:
        console.warn("GitHub gives no digest for this asset: trust on first use only (tier 4) unless an attestation verifies")
    console.out("Permissions: " + granted_summary(perms))
    warn_sensitive_dbus(console, perms.dbus_filter)
    warn_owned_dbus(console, perms.dbus_own)
    warn_privileged_portals(console, perms.portal_interfaces)

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
        staged, digest = download_verified(download, asset, stage)
        tier, why = gather_evidence(client, info, staged, digest, tier, console, verify)
        if why:
            console.warn(f"attestation not counted: {why}")
        record = manifest.Manifest(
            name=name, source=manifest.github_source(source), asset_pattern=github.suggest_pattern(asset.name, release.tag),
            version=release.tag, sha256=digest, evidence_tier=tier, published_at=release.published_at,
            owner_id=info.owner_id, permissions=perms,
            channel="pinned" if args.tag else "prerelease" if args.prerelease else "stable")
        manifest.validate(record)
        dest = store.appimage_path(name)
        dest.parent.mkdir(parents=True, mode=0o700)
        try:
            os.chmod(staged, 0o600)
            os.replace(staged, dest)
            try:
                entries, size = extract(dest, store.root_path(name), fallback)
            except appimage.EXTRACT_ERRORS as e:
                raise Abort(f"cannot extract the AppImage: {e}") from e
            store.root_marker(name).write_text(digest + "\n")
            store.tree_marker(name).write_text(appimage.tree_digest(store.root_path(name)) + "\n")
            manifest.dump(store.manifest_path(name), record)
        except BaseException:
            appimage.remove_tree(dest.parent)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    console.out(f"Extracted  : {entries} entries, {human_size(size)}")
    history.record(f"add {name} {release.tag} (tier {tier})")
    console.out(f"Added '{name}' {release.tag}: sha256 {digest}, evidence tier {tier}")
    console.out(f"Manifest   : {store.manifest_path(name)}")
    if getattr(args, "desktop", False):
        args.rw = False
        try:
            install_entry(name, console, args, yes=True, ask=False)
        except Abort as e:
            console.out(f"menu entry not created: {e} (`appjail desktop {name}` retries)")


def pick_asset(console, release, pattern):
    """The release asset the manifest's pattern selects (ask when several match)."""
    found = [a for a in github.match_assets(release, pattern) if a.name.lower().endswith(".appimage")]
    if not found:
        names = ", ".join(a.name for a in release.assets[:15]) or "no assets"
        raise Abort(f"no asset in {release.tag} matches '{pattern}' ({names})")
    if len(found) == 1:
        return found[0]
    console.out("Several assets match the pattern; choose one:")
    return found[console.choose("Asset", [f"{a.name} ({human_size(a.size)})" for a in found])]


def swap_in(name, staged, stage, record, extract, fallback):
    """Extract the new AppImage, then replace image, tree, marker and manifest; undo on failure."""
    try:
        entries, size = extract(staged, stage / "root", fallback)
    except appimage.EXTRACT_ERRORS as e:
        raise Abort(f"cannot extract the new AppImage: {e}") from e
    dest, root, marker = store.appimage_path(name), store.root_path(name), store.root_marker(name)
    old_image, old_root = stage / "old.AppImage", stage / "old-root"
    old_marker = marker.read_text() if marker.is_file() else None
    tree_mark = store.tree_marker(name)
    old_tree_mark = tree_mark.read_text() if tree_mark.is_file() else None
    os.chmod(staged, 0o600)
    placed, backups = [], []  # new things in place, and (original path, where the original went)
    try:
        if root.exists():
            os.replace(root, old_root)
            backups.append((root, old_root))
        os.replace(stage / "root", root)
        placed.append(root)
        os.replace(dest, old_image)
        backups.append((dest, old_image))
        os.replace(staged, dest)
        placed.append(dest)
        marker.write_text(record.sha256 + "\n")
        tree_mark.write_text(appimage.tree_digest(root) + "\n")
        manifest.dump(store.manifest_path(name), record)
    except BaseException:
        for path in placed:
            appimage.remove_tree(path) if path.is_dir() else path.unlink(missing_ok=True)
        for original, backup in reversed(backups):
            os.replace(backup, original)
        if old_marker is not None:
            marker.write_text(old_marker)
        if old_tree_mark is not None:
            tree_mark.write_text(old_tree_mark)
        raise
    return entries, size
