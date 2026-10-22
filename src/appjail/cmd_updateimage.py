# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail update` for apps installed from a URL or a local file (DESIGN.md "`add --file` / `add --url` and their
`update`").

`url:` apps are checked cheaply first (conditional request, then a few sampled windows of the file); a full download
happens only when something differs, and the candidate then waits out the quarantine, kept on disk so the end of the
quarantine needs no second download. `file:` apps are replaced by `update APP --file PATH`, with no quarantine
(the user holds the bytes).
"""

import shutil
from dataclasses import replace
from urllib.parse import urlsplit

from . import appimage, history, jail, manifest, store, updater
from .cmd_add import MAX_ASSET, swap_in
from .cmd_desktop import refresh_after_update
from .console import Abort, human_size
from .imagesrc import (
    DEFAULT_MAX_MIB,
    check_appimage,
    check_download_info,
    check_expected,
    parse_sha256,
    regular_file,
    timestamp,
    url_fingerprint,
    version_of,
)
from .permargs import granted_summary

DOWNGRADE = ("EVIDENCE DOWNGRADE: tier 4 -> 5 (this app was added with a matching --sha256, the new content has none). "
             "Pass --sha256 HEX with the hash the publisher gives for the new file to keep tier 4.")


def header(run):
    m = run.m
    run.console.out(f"{run.name}: {m.target}, installed {m.version} (installed {m.published_at}, tier {m.evidence_tier})")


def confirm_installed_hash(run, expected):
    """`--sha256` equal to the installed bytes: a tier 5 app becomes tier 4 without fetching anything.
    Returns True when the option was about the installed bytes."""
    m = run.m
    if expected is None or expected != m.sha256:
        return False
    if m.evidence_tier == 5:
        manifest.dump(store.manifest_path(run.name), replace(m, evidence_tier=4))
        history.record(f"tier {run.name} 5 -> 4 (--sha256 matches the installed file)")
        run.console.out("  --sha256 matches the installed file: evidence tier 5 -> 4")
    else:
        run.console.out("  --sha256 matches the installed file")
    return True


def show_diff(console, m, digest, tier, size=None):
    console.out(f"  sha256     : {m.sha256}\n            -> {digest}" + (f"  ({human_size(size)})" if size else ""))
    console.out(f"  evidence   : tier {m.evidence_tier} -> {tier}")
    console.out(f"  permissions: unchanged ({granted_summary(m.permissions) or 'none'})")


def install(run, staged, stage, record):
    """Extract and swap in `staged`; the previous version is restored if anything fails."""
    name, m = run.name, run.m
    if not run.svc.extract_ok():
        raise Abort("install squashfs-tools (apt install squashfs-tools) and retry")
    entries, size = swap_in(name, staged, stage, record, run.svc.extract, False)
    updater.clear_pending(name)
    history.record(f"update {name} {m.version} -> {record.version} (tier {record.evidence_tier})")
    run.console.out(f"  updated {name}: {m.version} -> {record.version}, sha256 {record.sha256}, {entries} entries, {human_size(size)}")
    refresh_after_update(name, run.console)
    return "updated"


# -- file: ---------------------------------------------------------------------------------------


def update_file(run):
    name, m, args, console = run.name, run.m, run.args, run.console
    header(run)
    expected = parse_sha256(args.sha256)
    if not args.file:
        if not confirm_installed_hash(run, expected):
            console.out("  installed from a file: there is no source to check; "
                        f"`appjail update {name} --file PATH` replaces it")
        return "current"
    if not args.app:
        raise Abort("--file needs an app name")
    real, st = regular_file(args.file)
    if not 0 < st.st_size <= MAX_ASSET:
        raise Abort(f"unexpected file size ({st.st_size} bytes)")
    stage = store.new_staging_dir()
    try:
        staged = stage / "download.AppImage"
        shutil.copyfile(real, staged)
        digest = appimage.sha256_file(staged)
        if digest == m.sha256:
            if not confirm_installed_hash(run, expected):
                console.out("  this is the installed file already")
            return "current"
        check_appimage(staged)
        if m.evidence_tier == 4 and expected is None:
            console.warn(DOWNGRADE)
            return "blocked"
        tier = check_expected(digest, expected)
        console.out(f"  file       : {real}")
        show_diff(console, m, digest, tier, st.st_size)
        if not console.confirm(f"Replace {name} with this file?"):
            return "declined"
        record = replace(m, source=f"file:{real.name}", version=version_of(digest), sha256=digest,
                         published_at=timestamp(run.now), evidence_tier=tier)
        manifest.validate(record)
        return install(run, staged, stage, record)
    finally:
        appimage.remove_tree(stage)


# -- url: ----------------------------------------------------------------------------------------
#
# Where the file at the URL stands, from probe():
#   installed  the server serves what is installed          -> up to date
#   pending    the server serves the waiting candidate      -> wait, or install it from disk
#   unknown    no range support: nothing can be told cheaply -> a full download decides
#   new        something else                                -> a full download, a new candidate


def reference(m, pending):
    """What the server is compared with: the waiting candidate if there is one, else the installed file."""
    if pending and "chunks" in pending:
        return "pending", pending.get("etag"), pending.get("last_modified")
    if pending:
        return "pending", None, None
    return "installed", m.fingerprint.etag, m.fingerprint.last_modified


def probe(run, pending):
    m = run.m
    which, etag, modified = reference(m, pending)
    stage = store.new_staging_dir()
    try:
        res = run.svc.check_url(m.target, stage, etag, modified)
    finally:
        appimage.remove_tree(stage)
    if res["status"] == "unchanged":
        return which, res
    if res["status"] == "no-range":
        return "unknown", res
    now = (res["size"], res["chunks"])
    if now == (m.fingerprint.size, m.fingerprint.chunks):
        return "installed", res
    if pending and "chunks" in pending and now == (pending["size"], pending["chunks"]):
        return "pending", res
    return "new", res


def refresh_validators(run, res):
    """Same content, new validators: keep the cheap 304 test working."""
    etag, modified = res.get("etag"), res.get("last_modified")
    f = run.m.fingerprint
    if (etag or modified) and (etag, modified) != (f.etag, f.last_modified):
        manifest.dump(store.manifest_path(run.name), replace(run.m, fingerprint=replace(f, etag=etag, last_modified=modified)))


def download_cap(m):
    """How much an update may download: the default limit of `add --url`, or twice the installed file if that is more
    (the limit given at `add` time is not stored)."""
    return min(MAX_ASSET, max(DEFAULT_MAX_MIB * 1024 ** 2, 2 * m.fingerprint.size))


def fetch_candidate(run, expected):
    """Download the URL in the jail into a new stage; returns (stage, staged path, sha256, server info)."""
    m, console = run.m, run.console
    stage = store.new_staging_dir()
    try:
        staged, info = run.svc.download_url(m.target, stage, "download.AppImage", download_cap(m))
    except jail.JailError as e:
        appimage.remove_tree(stage)
        raise Abort(str(e)) from e
    try:
        digest = appimage.sha256_file(staged)
        console.out(f"  downloaded : {human_size(info['size'])}, sha256 {digest}")
        if expected is not None and digest != expected:
            raise Abort(f"sha256 mismatch: the download is {digest}, --sha256 says {expected}")
        check_appimage(staged)
        check_download_info(console, m.target, info, 4 if expected is not None else 5)
    except BaseException:
        appimage.remove_tree(stage)
        raise
    return stage, staged, digest, info


def report_waiting(console, pending, due, why):
    console.out(f"  candidate  : {pending['tag']}, first seen {pending['first_seen']}; {why}")
    console.out(f"  quarantine : can be installed from {updater.stamp(due)}")
    return "waiting"


def update_url(run):
    name, m, args, console = run.name, run.m, run.args, run.console
    header(run)
    if args.file:
        raise Abort("--file applies to an app installed from a file")
    expected = parse_sha256(args.sha256)
    if confirm_installed_hash(run, expected):
        return "current"
    pending = updater.load_pending(name)
    if pending and not updater.pending_image(name).is_file():
        pending = None
        updater.clear_pending(name)
    where, res = probe(run, pending)
    if where == "installed":
        updater.clear_pending(name)
        if res["status"] == "fingerprint":
            refresh_validators(run, res)
        console.out("  up to date")
        return "current"
    if m.evidence_tier == 4 and expected is None and where != "unknown":
        console.out("  the file at the URL changed" + (f" (size {human_size(res['size'])})" if res.get("size") else ""))
        console.warn(DOWNGRADE)
        return "blocked"
    if pending and not args.verify:
        due = updater.quarantine_ends(updater.parse_stamp(pending["first_seen"]), args.quarantine)
        if where == "pending":
            if run.now < due:
                return report_waiting(console, pending, due, "still the same file")
            return install_pending(run, pending, expected)
        if where == "unknown" and run.now < due:
            return report_waiting(console, pending, due, "the server cannot be asked cheaply")
    return download_and_decide(run, pending, where, expected)


def download_and_decide(run, pending, where, expected):
    """A full download: of a new candidate, or of the waiting one to compare it with what was recorded."""
    m, console = run.m, run.console
    comparing = bool(pending) and where != "new"
    if not console.confirm(f"Download {'the candidate' if comparing else 'the file'} from {urlsplit(m.target).hostname} "
                           "in a network-only jail" + (" to compare it with the one recorded during the quarantine?" if comparing else "?")):
        return "declined"
    stage, staged, digest, info = fetch_candidate(run, expected)
    try:
        if digest == m.sha256:
            updater.clear_pending(run.name)
            refresh_validators(run, info)
            console.out("  up to date (same content as the installed file)")
            return "current"
        if m.evidence_tier == 4 and expected is None:
            console.warn(DOWNGRADE)
            return "blocked"
        if comparing and pending["sha256"] == digest:
            return conclude(run, stage, staged, digest, info, expected)
        if pending:
            console.warn(f"CHANGED DURING QUARANTINE: the file hashed {pending['sha256']} when first seen but is "
                         f"{digest} now. Nothing was installed; the quarantine starts again for the new content.")
        return start_quarantine(run, stage, staged, digest, info, expected)
    finally:
        appimage.remove_tree(stage)


def start_quarantine(run, stage, staged, digest, info, expected):
    """A new candidate: keep it on disk, start its clock, and install at once only when the quarantine is 0."""
    fp = url_fingerprint(staged, info)
    tier = check_expected(digest, expected)
    show_diff(run.console, run.m, digest, tier, info["size"])
    updater.clear_pending(run.name)
    shutil.copyfile(staged, updater.pending_image(run.name))
    updater.record_url_candidate(run.name, version_of(digest), run.now, digest, fp, info["etag"], info["last_modified"])
    days = run.args.quarantine
    if days > 0:
        due = updater.quarantine_ends(run.now.replace(microsecond=0), days)
        run.console.out(f"  quarantine : first seen {updater.stamp(run.now)}; can be installed from {updater.stamp(due)} "
                        f"({days} days; --quarantine DAYS to change)")
        return "waiting"
    return conclude(run, stage, staged, digest, info, expected)


def install_pending(run, pending, expected):
    """The quarantine is over and the server still serves the waiting candidate: install the file kept on disk."""
    image = updater.pending_image(run.name)
    if appimage.sha256_file(image) != pending["sha256"]:
        updater.clear_pending(run.name)
        raise Abort("the stored candidate does not match its recorded hash; it was dropped, run update again")
    if not run.console.confirm(f"Install {pending['tag']} (kept since {pending['first_seen']})?"):
        return "declined"
    stage = store.new_staging_dir()
    try:
        staged = stage / "download.AppImage"
        shutil.copyfile(image, staged)
        info = {"etag": pending.get("etag"), "last_modified": pending.get("last_modified")}
        return conclude(run, stage, staged, pending["sha256"], info, expected, ask=False)
    finally:
        appimage.remove_tree(stage)


def conclude(run, stage, staged, digest, info, expected, ask=True):
    tier = check_expected(digest, expected)
    if run.args.quarantine < updater.DEFAULT_QUARANTINE_DAYS:
        run.console.warn(f"quarantine shortened to {run.args.quarantine} days")
    show_diff(run.console, run.m, digest, tier)
    if tier == 5:
        run.console.out("  trust on first use (tier 5): nothing outside the download confirms these bytes")
    if ask and not run.console.confirm("Install this version?"):
        return "declined"
    record = replace(run.m, version=version_of(digest), sha256=digest, published_at=timestamp(run.now), evidence_tier=tier,
                     fingerprint=url_fingerprint(staged, info))
    manifest.validate(record)
    return install(run, staged, stage, record)
