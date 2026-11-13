# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add` (from a GitHub release; `add --file/--url` are in cmd_addimage)."""

from . import appimage, attest, github, jail, manifest, store, tools
from .console import Abort, human_size
from .install import (
    MAX_ASSET,
    ask_extractor,
    choose_asset,
    download_verified,
    finish_add,
    gather_evidence,
    new_app_name,
    swap_in,
)
from .permargs import (
    permissions_from_args,
    require_network_isolation,
    show_permissions,
)

YOUNG_ACCOUNT_DAYS = 90
FEW_STARS = 10


def show_review(console, info, now=None):
    """Typosquat check: who owns this repo, how old and how popular is it."""
    days = github.age_days(info.owner_created_at, now)
    console.kv("Repository", f"{info.full_name}  {info.html_url}")
    if info.description:
        console.kv("About", info.description)
    console.kv("Owner", f"{info.owner} ({info.owner_type}, id {info.owner_id}), account created "
               f"{info.owner_created_at[:10]} ({days} days ago)")
    console.kv("Stars", info.stars)
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


def choose_release_asset(client, console, source, args):
    """The release (latest, or --tag) and the AppImage asset in it; the user chooses when several match."""
    release = (client.release_by_tag(source, args.tag) if args.tag
               else client.latest_release(source, args.prerelease))
    console.kv("Release", f"{release.tag}, published {release.published_at}" + ("  (pre-release)" if release.prerelease else ""))
    console.kv("", release.html_url)
    candidates = github.appimage_candidates(release)
    if not candidates:
        names = ", ".join(a.name for a in release.assets[:15]) or "no assets"
        raise Abort(f"no x86_64 AppImage asset in this release ({names})")
    asset = choose_asset(console, candidates, "Several AppImage assets match; choose one:")
    if not 0 < asset.size <= MAX_ASSET:
        raise Abort(f"unexpected asset size ({asset.size} bytes)")
    return release, asset


def show_asset_evidence(client, console, source, asset):
    """Print the asset, its GitHub digest and whether an attestation exists; returns the tier before the download."""
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
    console.kv("Asset", f"{asset.name} ({human_size(asset.size)})")
    console.kv("Digest", f"{asset.sha256 or 'none'} (sha256, from GitHub)")
    console.kv("Attestation", attestation)
    if not asset.sha256:
        console.warn("GitHub gives no digest for this asset: trust on first use only (tier 4) unless an attestation verifies")
    return asset.base_tier


def cmd_add(args, client, console, download=jail.download, now=None, extract=appimage.extract,
            extract_ok=appimage.have_unsquashfs, verify=attest.verify):
    name = new_app_name(args.name, args.source.partition("/")[2])

    perms = permissions_from_args(args)  # validates every option before any network access
    require_network_isolation(perms)

    info = client.repo_info(args.source)
    show_review(console, info, now)
    if info.renamed and not console.confirm(f"Continue with {info.full_name}?"):
        raise Abort("cancelled")
    source = info.full_name

    release, asset = choose_release_asset(client, console, source, args)
    tier = show_asset_evidence(client, console, source, asset)
    show_permissions(console, perms)

    fallback = ask_extractor(console, extract_ok)

    if not console.confirm(f"Download {asset.name} from github.com in a network-only jail?"):
        raise Abort("cancelled")

    stage = store.new_staging_dir()
    try:
        console.out(f"Downloading {asset.name} ...")
        staged, digest = download_verified(download, asset, stage)
        console.out("Verifying and extracting ...")
        tier, why = gather_evidence(client, info, staged, digest, tier, console, verify)
        if why:
            console.warn(f"attestation not counted: {why}")
        record = manifest.Manifest(
            name=name, source=manifest.github_source(source), asset_pattern=github.suggest_pattern(asset.name, release.tag),
            version=release.tag, sha256=digest, evidence_tier=tier, published_at=release.published_at,
            owner_id=info.owner_id, permissions=perms,
            channel="pinned" if args.tag else "prerelease" if args.prerelease else "stable")
        manifest.validate(record)
        entries, size = swap_in(name, staged, stage, record, extract, fallback)
    finally:
        appimage.remove_tree(stage)
    finish_add(console, args, record, entries, size)
