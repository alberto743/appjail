# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail update`."""

import secrets
from dataclasses import replace
from datetime import datetime, timezone

from . import appimage, attest, github, history, jail, manifest, store, updater
from .cmd_add import MAX_ASSET, download_verified, gather_evidence, pick_asset, swap_in
from .console import Abort, human_size
from .permargs import granted_summary



def hash_candidate(asset, download):
    """Download the candidate in the jail only to learn its sha256 (nothing is installed); the stage is removed."""
    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        return download_verified(download, asset, stage)[1]
    finally:
        appimage.remove_tree(stage)


def update_app(name, args, client, console, download, now, extract, extract_ok, verify=attest.verify):
    """Update one app. Returns 'updated', 'current', 'pinned', 'waiting', 'blocked' or 'declined'."""
    m = manifest.load(store.manifest_path(name))
    info = client.repo_info(m.source)
    console.out(f"{name}: {info.full_name}, installed {m.version} (published {m.published_at}, tier {m.evidence_tier})")
    if args.channel and args.channel != m.channel:
        m = replace(m, channel=args.channel)
        manifest.dump(store.manifest_path(name), m)
        history.record(f"channel {name} {m.channel}")
        console.out(f"  update channel is now {m.channel}")
    if m.channel == "pinned":
        console.out(f"  pinned to {m.version}: not checked (use --channel stable or prerelease to follow releases)")
        return "pinned"
    prerelease = args.prerelease or m.channel == "prerelease"
    release = client.latest_release(info.full_name, prerelease)
    asset = pick_asset(console, release, m.asset_pattern)
    key = updater.candidate_key(release, asset)
    same = asset.sha256 == m.sha256 if asset.sha256 else (
        release.tag == m.version and release.published_at == m.published_at)
    if same:
        updater.clear_pending(name)
        console.out("  up to date")
        return "current"
    if not updater.is_newer(m, release):
        console.out(f"  the latest {'release' if prerelease else 'stable release'} ({release.tag}, "
                    f"{release.published_at}) is older than the installed one; use --prerelease to follow pre-releases")
        return "current"
    console.out(f"  candidate  : {release.tag}, published {release.published_at}"
                + ("  (pre-release)" if release.prerelease else ""))
    console.out(f"               {release.html_url}")
    console.out(f"  asset      : {asset.name} ({human_size(asset.size)})")
    console.out(f"  sha256     : {m.sha256}\n            -> {asset.sha256 or 'unknown until downloaded (no GitHub digest)'}")
    console.out(f"  evidence   : tier {m.evidence_tier} -> {3 if asset.sha256 else 4}")
    console.out(f"  permissions: unchanged ({granted_summary(m.permissions) or 'none'})")
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
    first = updater.note_seen(name, key, release.tag, now)
    due = updater.quarantine_ends(first, args.quarantine)
    if now < due:
        console.out(f"  quarantine : first seen {updater.stamp(first)}; can be installed from {updater.stamp(due)} "
                    f"({args.quarantine} days; --quarantine DAYS to change)")
        pending = updater.load_pending(name)
        if not asset.sha256 and not (pending and pending.get("sha256")):
            # no GitHub digest to catch a swapped asset: fix its hash now, compare it when installing
            if console.confirm(f"Download {asset.name} in the network-only jail now, only to record its sha256 "
                               "so a change during the quarantine is detected?"):
                digest = hash_candidate(asset, download)
                updater.record_hash(name, key, digest)
                console.out(f"  sha256 recorded for the quarantine: {digest}")
            else:
                console.warn("no hash recorded: a change of this asset during the quarantine will not be detected")
        return "waiting"
    if args.quarantine < updater.DEFAULT_QUARANTINE_DAYS:
        console.warn(f"quarantine shortened to {args.quarantine} days")
    if not extract_ok():
        raise Abort("install squashfs-tools (apt install squashfs-tools) and retry")
    if not console.confirm(f"Download {asset.name} from github.com in a network-only jail and install {release.tag}?"):
        return "declined"

    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged, digest = download_verified(download, asset, stage)
        pending = updater.load_pending(name)
        if not asset.sha256 and pending and pending["key"] == key and pending.get("sha256") not in (None, digest):
            console.warn(f"CHANGED DURING QUARANTINE: the asset hashed {pending['sha256']} when first seen but downloads "
                         f"as {digest} now. Nothing was installed; the quarantine starts again for the new content.")
            updater.clear_pending(name)
            updater.note_seen(name, key, release.tag, now)
            updater.record_hash(name, key, digest)
            return "blocked"
        tier, why = gather_evidence(client, info, staged, digest, 3 if asset.sha256 else 4, console, verify)
        if m.evidence_tier == 1 and tier != 1:
            raise Abort(f"EVIDENCE DOWNGRADE: the previous release was build-attested but this one could not be verified ({why or 'no attestation'}); nothing was installed")
        if why:
            console.warn(f"attestation not counted: {why}")
        if tier == 4:
            console.out(f"  downloaded sha256: {digest}  (trust on first use, tier 4)")
            if not console.confirm("Install this version?"):
                return "declined"
        record = replace(m, version=release.tag, sha256=digest, published_at=release.published_at,
                         evidence_tier=tier, source=info.full_name, owner_id=info.owner_id)
        manifest.validate(record)
        entries, size = swap_in(name, staged, stage, record, extract, False)
    finally:
        appimage.remove_tree(stage)
    updater.clear_pending(name)
    history.record(f"update {name} {m.version} -> {release.tag} (tier {record.evidence_tier})")
    console.out(f"  updated {name}: {m.version} -> {release.tag}, sha256 {digest}, {entries} entries, {human_size(size)}")
    return "updated"


def cmd_update(args, client, console, download=jail.download, now=None, extract=appimage.extract,
               extract_ok=appimage.have_unsquashfs, verify=attest.verify):
    now = now or datetime.now(timezone.utc)
    if args.quarantine < 0:
        raise Abort("--quarantine must be 0 or more days")
    names = [args.app] if args.app else updater.installed()
    if args.app and not store.manifest_path(args.app).is_file():
        raise Abort(f"unknown app '{args.app}'")
    if not names:
        console.out("No apps installed.")
        return 0
    results = {}
    for i, name in enumerate(names):
        try:
            results[name] = update_app(name, args, client, console, download, now, extract, extract_ok, verify)
        except github.RateLimited as e:
            console.out(f"  {name}: {e}")
            results[name] = "failed"
            for rest in names[i + 1:]:
                results[rest] = "not checked (rate limited)"
            break
        except (Abort, github.GitHubError, jail.JailError, manifest.ManifestError, OSError) as e:
            console.out(f"  {name}: {e}")
            results[name] = "failed"
    if len(names) > 1:
        console.out("Summary: " + ", ".join(f"{n}: {r}" for n, r in results.items()))
    return 1 if any(r in ("blocked", "failed") or r.startswith("not checked") for r in results.values()) else 0
