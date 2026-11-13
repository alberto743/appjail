# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail update`."""

from dataclasses import replace
from datetime import UTC, datetime

from . import github, history, manifest, store, updater
from .cmd_updateimage import update_file, update_url
from .console import INDENTED_LABEL, Abort, human_size
from .errors import JailError
from .install import (
    MAX_ASSET,
    NEED_SQUASHFS,
    check_record,
    choose_asset,
    download_verified,
    finish_update,
    gather_evidence,
    show_change,
    show_quarantine,
    swap_in,
)
from .services import Services, UpdateRun


def pick_asset(console, release, pattern):
    """The release asset the manifest's pattern selects (ask when several match)."""
    found = [a for a in github.match_assets(release, pattern) if a.name.lower().endswith(".appimage")]
    if not found:
        names = ", ".join(a.name for a in release.assets[:15]) or "no assets"
        raise Abort(f"no asset in {release.tag} matches '{pattern}' ({names})")
    return choose_asset(console, found, "Several assets match the pattern; choose one:")


def hash_candidate(asset, download):
    """Download the candidate in the jail only to learn its sha256 (nothing is installed); the stage is removed."""
    with store.staging() as stage:
        return download_verified(download, asset, stage)[1]


def apply_channel(name, m, args, console):
    """`--channel` changes the policy and saves it; returns the manifest with it applied."""
    if args.channel and args.channel != m.channel:
        m = replace(m, channel=args.channel)
        manifest.dump(store.manifest_path(name), m)
        history.record(f"channel {name} {m.channel}")
        console.out(f"  update channel is now {m.channel}")
    return m


def is_current(m, release, asset):
    """GitHub's digest equals the pin, or, without a digest, the same tag and publication time."""
    return asset.sha256 == m.sha256 if asset.sha256 else (release.tag == m.version and release.published_at == m.published_at)


def describe_candidate(console, m, release, asset):
    console.kv("  candidate", f"{release.tag}, published {release.published_at}" + ("  (pre-release)" if release.prerelease else ""), INDENTED_LABEL)
    console.kv("", release.html_url, INDENTED_LABEL)
    console.kv("  asset", f"{asset.name} ({human_size(asset.size)})", INDENTED_LABEL)
    show_change(console, m, asset.sha256 or "unknown until downloaded (no GitHub digest)", asset.base_tier)


def wait_in_quarantine(run, asset, key, first, due):
    name, console = run.name, run.console
    show_quarantine(console, first, due, run.args.quarantine)
    pending = updater.load_pending(name)
    if not asset.sha256 and not (pending and pending.get("sha256")):
        # no GitHub digest to catch a swapped asset: fix its hash now, compare it when installing
        if console.confirm(f"Download {asset.name} in the network-only jail now, only to record its sha256 "
                           "so a change during the quarantine is detected?"):
            digest = hash_candidate(asset, run.svc.download)
            updater.record_hash(name, key, digest)
            console.out(f"  sha256 recorded for the quarantine: {digest}")
        else:
            console.warn("no hash recorded: a change of this asset during the quarantine will not be detected")
    return "waiting"


def install_release(run, client, info, release, asset, key):
    name, m, args, console, svc = run.name, run.m, run.args, run.console, run.svc
    if args.quarantine < updater.DEFAULT_QUARANTINE_DAYS:
        console.warn(f"quarantine shortened to {args.quarantine} days")
    if not svc.extract_ok():
        raise Abort(NEED_SQUASHFS)
    if not console.confirm(f"Download {asset.name} from github.com in a network-only jail and install {release.tag}?"):
        return "declined"

    with store.staging() as stage:
        staged, digest = download_verified(svc.download, asset, stage)
        pending = updater.load_pending(name)
        if not asset.sha256 and pending and pending["key"] == key and pending.get("sha256") not in (None, digest):
            console.warn(f"CHANGED DURING QUARANTINE: the asset hashed {pending['sha256']} when first seen but downloads "
                         f"as {digest} now. Nothing was installed; the quarantine starts again for the new content.")
            updater.clear_pending(name)
            updater.note_seen(name, key, release.tag, run.now)
            updater.record_hash(name, key, digest)
            return "blocked"
        tier, why = gather_evidence(client, info, staged, digest, asset.base_tier, console, svc.verify)
        if m.evidence_tier == 1 and tier != 1:
            raise Abort(f"EVIDENCE DOWNGRADE: the previous release was build-attested but this one could not be verified ({why or 'no attestation'}); nothing was installed")
        if why:
            console.warn(f"attestation not counted: {why}")
        if tier == 4:
            console.out(f"  downloaded sha256: {digest}  (trust on first use, tier 4)")
            if not console.confirm("Install this version?"):
                return "declined"
        record = replace(m, version=release.tag, sha256=digest, published_at=release.published_at,
                         evidence_tier=tier, source=manifest.github_source(info.full_name), owner_id=info.owner_id)
        check_record(record, "this release")
        entries, size = swap_in(name, staged, stage, record, svc.extract, False)
    return finish_update(run, record, entries, size)


def update_github(name, m, args, client, console, svc, now):
    info = client.repo_info(m.target)
    console.out(f"== {name} ==")
    console.kv("  repository", info.full_name, INDENTED_LABEL)
    console.kv("  installed", f"{m.version} (published {m.published_at}, tier {m.evidence_tier})", INDENTED_LABEL)
    m = apply_channel(name, m, args, console)
    if m.channel == "pinned":
        console.out(f"  pinned to {m.version}: not checked (use --channel stable or prerelease to follow releases)")
        return "pinned"
    run = UpdateRun(name, m, args, console, svc, now)
    prerelease = args.prerelease or m.channel == "prerelease"
    release = client.latest_release(info.full_name, prerelease)
    asset = pick_asset(console, release, m.asset_pattern)
    if is_current(m, release, asset):
        updater.clear_pending(name)
        console.out("  up to date")
        return "current"
    if not updater.is_newer(m, release):
        console.out(f"  the latest {'release' if prerelease else 'stable release'} ({release.tag}, "
                    f"{release.published_at}) is older than the installed one; use --prerelease to follow pre-releases")
        return "current"
    describe_candidate(console, m, release, asset)
    attested = None
    if m.evidence_tier == 1:  # a build-attested app must stay build-attested
        attested = bool(asset.sha256 and client.has_attestation(info.full_name, asset.sha256))
    reasons = updater.blocks(m, info, asset, attested)
    for reason in reasons:
        console.warn(reason)
    if reasons:
        console.out("  update BLOCKED. If this is expected, remove the app and add it again after checking the repository.")
        return "blocked"
    if not 0 < asset.size <= MAX_ASSET:
        raise Abort(f"unexpected asset size ({asset.size} bytes)")
    for note in updater.cautions(m, info):
        console.warn(note)
    key = updater.candidate_key(release, asset)
    first = updater.note_seen(name, key, release.tag, now)
    due = updater.quarantine_ends(first, args.quarantine)
    if now < due:
        return wait_in_quarantine(run, asset, key, first, due)
    return install_release(run, client, info, release, asset, key)


def update_app(name, args, client, console, svc, now):
    """Update one app. Returns 'updated', 'current', 'pinned', 'waiting', 'blocked' or 'declined'."""
    m = manifest.load(store.manifest_path(name))
    if m.kind in ("file", "url"):
        if args.channel:
            raise Abort("--channel applies to apps installed from a GitHub release: a file or a URL has no releases to follow")
        run = UpdateRun(name, m, args, console, svc, now)
        return (update_file if m.kind == "file" else update_url)(run)
    if args.file or args.sha256:
        raise Abort("--file and --sha256 apply to apps installed from a file or a URL")
    return update_github(name, m, args, client, console, svc, now)


def cmd_update(args, client, console, svc=None, now=None):
    svc = svc or Services()
    now = now or datetime.now(UTC)
    if args.quarantine < 0:
        raise Abort("--quarantine must be 0 or more days")
    for flag, value in (("--file", args.file), ("--sha256", args.sha256), ("--channel", args.channel)):
        if value and not args.app:
            raise Abort(f"{flag} needs an app name")
    if args.app:
        manifest.check_name(args.app)
    names = [args.app] if args.app else updater.installed()
    if args.app and not store.manifest_path(args.app).is_file():
        raise Abort(f"unknown app '{args.app}'")
    if not names:
        console.out("No apps installed.")
        return 0
    results = {}
    for i, name in enumerate(names):
        try:
            results[name] = update_app(name, args, client, console, svc, now)
        except github.RateLimited as e:
            console.error(f"{name}: {e}")
            results[name] = "failed"
            for rest in names[i + 1:]:
                results[rest] = "not checked (rate limited)"
            break
        except (Abort, github.GitHubError, JailError, manifest.ManifestError, OSError) as e:
            console.error(f"{name}: {e}")
            results[name] = "failed"
    if len(names) > 1:
        console.out()
        console.table(("APP", "RESULT"), list(results.items()))
    return 1 if any(r in ("blocked", "failed") or r.startswith("not checked") for r in results.values()) else 0
