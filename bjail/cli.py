# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Command line interface."""

import argparse
import os
import re
import secrets
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from . import appimage, github, index, indexsync, jail, manifest, runner, store, textsafe, updater

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


def dbus_from_args(names, current=()):
    """Validated dbus_filter names merged into the current list (order kept, no duplicates)."""
    out = list(current)
    for name in names:
        try:
            manifest.check_dbus_name(name)
        except manifest.ManifestError as e:
            raise Abort(f"--dbus {name}: {e}") from e
        if name not in out:
            out.append(name)
    return tuple(out)


def warn_sensitive_dbus(console, names):
    for n in names:
        if n.startswith(manifest.DBUS_SENSITIVE):
            console.warn(f"{n} gives access to stored secrets (passwords, keys)")


def permissions_from_args(args):
    allowed = set(args.allow)
    return manifest.Permissions(
        dirs=dirs_from_args(args.dir), dbus_filter=dbus_from_args(args.dbus),
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
    warn_sensitive_dbus(console, perms.dbus_filter)

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
    except (appimage.UnsupportedImage, appimage.ExtractError, appimage.UnsafeTree) as e:
        raise Abort(f"cannot extract the new AppImage: {e}") from e
    dest, root, marker = store.appimage_path(name), store.root_path(name), store.root_marker(name)
    old_image, old_root = stage / "old.AppImage", stage / "old-root"
    old_marker = marker.read_text() if marker.is_file() else None
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
        manifest.dump(store.manifest_path(name), record)
    except BaseException:
        for path in placed:
            appimage.remove_tree(path) if path.is_dir() else path.unlink(missing_ok=True)
        for original, backup in reversed(backups):
            os.replace(backup, original)
        if old_marker is not None:
            marker.write_text(old_marker)
        raise
    return entries, size


def update_app(name, args, client, console, download, now, extract, extract_ok):
    """Update one app. Returns 'updated', 'current', 'waiting', 'blocked' or 'declined'."""
    m = manifest.load(store.manifest_path(name))
    info = client.repo_info(m.source)
    console.out(f"{name}: {info.full_name}, installed {m.version} (published {m.published_at}, tier {m.evidence_tier})")
    release = client.latest_release(info.full_name, args.prerelease)
    asset = pick_asset(console, release, m.asset_pattern)
    key = updater.candidate_key(release, asset)
    same = asset.sha256 == m.sha256 if asset.sha256 else (
        release.tag == m.version and release.published_at == m.published_at)
    if same:
        updater.clear_pending(name)
        console.out("  up to date")
        return "current"
    if not updater.is_newer(m, release):
        console.out(f"  the latest {'release' if args.prerelease else 'stable release'} ({release.tag}, "
                    f"{release.published_at}) is older than the installed one; use --prerelease to follow pre-releases")
        return "current"
    console.out(f"  candidate  : {release.tag}, published {release.published_at}"
                + ("  (pre-release)" if release.prerelease else ""))
    console.out(f"               {release.html_url}")
    console.out(f"  asset      : {asset.name} ({human_size(asset.size)})")
    console.out(f"  sha256     : {m.sha256}\n            -> {asset.sha256 or 'unknown until downloaded (no GitHub digest)'}")
    console.out(f"  evidence   : tier {m.evidence_tier} -> {3 if asset.sha256 else 4}")
    console.out(f"  permissions: unchanged ({', '.join(f'{k}={v}' for k, v in vars(m.permissions).items() if v not in ((), False)) or 'none'})")
    reasons = updater.blocks(m, info, asset)
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
        if not asset.sha256:
            console.out(f"  downloaded sha256: {digest}  (trust on first use, tier 4)")
            if not console.confirm("Install this version?"):
                return "declined"
        record = replace(m, version=release.tag, sha256=digest, published_at=release.published_at,
                         evidence_tier=3 if asset.sha256 else 4, source=info.full_name, owner_id=info.owner_id)
        manifest.validate(record)
        entries, size = swap_in(name, staged, stage, record, extract, False)
    finally:
        appimage.remove_tree(stage)
    updater.clear_pending(name)
    console.out(f"  updated {name}: {m.version} -> {release.tag}, sha256 {digest}, {entries} entries, {human_size(size)}")
    return "updated"


def cmd_update(args, client, console, download=jail.download, now=None, extract=appimage.extract,
               extract_ok=appimage.have_unsquashfs):
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
    for name in names:
        try:
            results[name] = update_app(name, args, client, console, download, now, extract, extract_ok)
        except (Abort, github.GitHubError, jail.JailError, manifest.ManifestError, OSError) as e:
            console.out(f"  {name}: {e}")
            results[name] = "failed"
    if len(names) > 1:
        console.out("Summary: " + ", ".join(f"{n}: {r}" for n, r in results.items()))
    return 1 if any(r in ("blocked", "failed") for r in results.values()) else 0


def cmd_list(console):
    names = updater.installed()
    if not names:
        console.out("No apps installed.")
    for name in names:
        try:
            m = manifest.load(store.manifest_path(name))
        except (manifest.ManifestError, OSError) as e:
            console.out(f"{name}: unreadable manifest ({e})")
            continue
        p = m.permissions
        granted = [k for k in ("network", "audio", "gpu", "portals") if getattr(p, k)] + [f"display={p.display}"]
        pending = updater.load_pending(name)
        console.out(f"{name}  {m.version}  {m.source}  tier {m.evidence_tier}  [{', '.join(granted)}]"
                    + (f"  dirs: {', '.join(p.dirs)}" if p.dirs else "")
                    + (f"  dbus: {', '.join(p.dbus_filter)}" if p.dbus_filter else "")
                    + (f"  (update seen: {pending['tag']})" if pending else ""))


def cmd_remove(args, console):
    name = args.app
    if not manifest.NAME_RE.fullmatch(name):
        raise Abort("invalid app name")
    mpath, adir = store.manifest_path(name), store.app_dir(name)
    if not mpath.exists() and not adir.exists():
        raise Abort(f"unknown app '{name}'")
    console.out(f"This deletes the manifest and the app's files, including its private home (its settings and data): {adir}")
    if not args.yes and not console.confirm(f"Remove {name}?"):
        raise Abort("cancelled")
    appimage.remove_tree(adir)
    mpath.unlink(missing_ok=True)
    console.out(f"Removed {name}.")


PERMISSION_FLAGS = ("network", "audio", "gpu", "portals")


def describe_permissions(p):
    return ", ".join([f"{k}={getattr(p, k)}" for k in PERMISSION_FLAGS] + [f"display={p.display}"]
                     + [f"dir={d}" for d in p.dirs] + [f"dbus={n}" for n in p.dbus_filter]) or "none"


def cmd_perms(args, console):
    name = args.app
    if not manifest.NAME_RE.fullmatch(name) or not store.manifest_path(name).is_file():
        raise Abort(f"unknown app '{name}'")
    m = manifest.load(store.manifest_path(name))
    p = m.permissions
    changes = {}
    for flag in args.allow + args.deny:
        if flag in args.allow and flag in args.deny:
            raise Abort(f"{flag} cannot be both allowed and denied")
    for flag in args.allow:
        changes[flag] = True
    for flag in args.deny:
        changes[flag] = False
    if args.display:
        changes["display"] = args.display
    dirs = p.dirs
    if args.rm_dir:
        drop = set()
        for spec in args.rm_dir:
            try:
                entry = manifest.normalize_dir(spec, Path.home(), Path.cwd())
            except manifest.ManifestError as e:
                raise Abort(f"--rm-dir {spec}: {e}") from e
            drop.add(entry.partition(":")[0])
        missing = drop - {d.partition(":")[0] for d in dirs}
        if missing:
            raise Abort("not granted: " + ", ".join(sorted(missing)))
        dirs = tuple(d for d in dirs if d.partition(":")[0] not in drop)
    if args.add_dir:
        dirs = manifest.merge_dirs(dirs, dirs_from_args(args.add_dir))
    if dirs != p.dirs:
        changes["dirs"] = dirs
    bus = dbus_from_args(args.add_dbus, p.dbus_filter)
    missing = [n for n in args.rm_dbus if n not in bus]
    if missing:
        raise Abort("not allowed: " + ", ".join(missing))
    bus = tuple(n for n in bus if n not in args.rm_dbus)
    if bus != p.dbus_filter:
        changes["dbus_filter"] = bus
    if not changes:
        console.out(f"{name}: {describe_permissions(p)}")
        return
    new = replace(m, permissions=replace(p, **changes))
    manifest.validate(new)
    console.out(f"{name} before: {describe_permissions(p)}")
    console.out(f"{name} after : {describe_permissions(new.permissions)}")
    for risky, text in (("network", "network access"), ("portals", "portals")):
        if getattr(new.permissions, risky) and not getattr(p, risky):
            console.warn(f"this grants {text}")
    warn_sensitive_dbus(console, set(new.permissions.dbus_filter) - set(p.dbus_filter))
    if not args.yes and not console.confirm("Save these permissions?"):
        raise Abort("cancelled")
    manifest.dump(store.manifest_path(name), new)
    console.out("Saved. The pinned release is unchanged.")


def cmd_search(args, console):
    hits, total = index.search(args.keywords, limit=args.limit if not args.all else 10 ** 9)
    commit = index.pinned_commit()
    console.out(f"{total} match(es)" + (f" in the AM index at {commit[:12]}" if commit else "")
                + (f", showing {len(hits)}" if len(hits) < total else ""))
    for h in hits:
        console.out(f"{h.name}: {h.description}")
        if h.source:
            console.out(f"    source {h.source}   ->  bjail add {h.source}")
        if h.note:
            console.out(f"    ({h.note})")
    if hits:
        console.out("A hit is only a suggestion: check the owner and repository yourself before `bjail add`.")


def cmd_index_update(args, console, fetch=indexsync.fetch):
    base = store.data_dir() / "index"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = base / f"work-{secrets.token_hex(6)}"
    work.mkdir(mode=0o700)
    try:
        console.out(f"Fetching the AM index ({args.commit}) in a network-only jail…")
        got = fetch(work, args.commit)
        if got.commit == indexsync.current():
            console.out(f"The index is already at {got.commit[:12]}.")
            return
        staged = base / f"staged-{got.commit[:12]}"
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(mode=0o700)
        try:
            copied, skipped = indexsync.collect(got.tree, staged)
            console.out(f"Fetched commit {got.commit}: {copied} install scripts"
                        + (f", {skipped} odd file names skipped" if skipped else "")
                        + (", signature header present (not verified)" if got.signed else ", unsigned"))
            old = indexsync.current()
            if old and indexsync.snapshot_path(old).is_dir():
                d = indexsync.diff(indexsync.snapshot_path(old), staged)
                show_index_diff(console, old, d)
            else:
                console.out("There is no previous index to compare with.")
            if not console.confirm("Accept this snapshot as the current index?"):
                raise Abort("cancelled; the index is unchanged")
            indexsync.install(staged, got.commit, got.signed)
        finally:
            shutil.rmtree(staged, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    console.out(f"Index pinned at {got.commit[:12]}. Previous: {(indexsync.previous() or 'none')[:12]}.")


def show_index_diff(console, old, d):
    console.out(f"Changes since {old[:12]}: {len(d.added)} apps added, {len(d.removed)} removed, "
                f"{len(d.owner_changed)} owner changes, {len(d.source_changed)} other source changes")
    for label, names in (("added", d.added), ("removed", d.removed)):
        if names:
            console.out(f"  {label}: " + ", ".join(names[:15]) + (f", … (+{len(names) - 15})" if len(names) > 15 else ""))
    for name, a, b in d.owner_changed:
        console.warn(f"OWNER CHANGE for {name}: {a} -> {b}. Check this before adding it.")
    for name, a, b in d.source_changed[:20]:
        console.out(f"  source changed: {name}: {a} -> {b}")
    if len(d.source_changed) > 20:
        console.out(f"  … and {len(d.source_changed) - 20} more source changes")


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
    add.add_argument("--dbus", action="append", default=[], metavar="NAME",
                     help="let the app talk to this session-bus name through a filtering proxy; repeatable")
    add.add_argument("--allow", action="append", default=[], choices=["network", "portals"],
                     help="grant a permission (repeatable); audio and gpu are on by default")
    add.add_argument("--no-audio", action="store_true", help="do not grant audio")
    add.add_argument("--no-gpu", action="store_true", help="do not grant GPU access")
    add.add_argument("--display", choices=manifest.DISPLAYS, default="wayland")
    search = sub.add_parser("search", help="search the local AM index (suggestions only, never installs)")
    search.add_argument("keywords", nargs="+")
    search.add_argument("--limit", type=int, default=20, help="maximum results (default 20)")
    search.add_argument("--all", action="store_true", help="show every match")
    idx = sub.add_parser("index", help="manage the local AM search index")
    isub = idx.add_subparsers(dest="index_command", required=True)
    upd = isub.add_parser("update", help="fetch the AM index, review the changes, then pin it")
    upd.add_argument("--commit", default="HEAD", help="fetch this commit (40 hex digits) instead of the remote HEAD")
    isub.add_parser("rollback", help="go back to the previous index snapshot")
    isub.add_parser("status", help="show the pinned index")
    upd_app = sub.add_parser("update", help="check for a newer release and install it after review and quarantine")
    upd_app.add_argument("app", nargs="?", help="app name (default: every installed app)")
    upd_app.add_argument("--prerelease", action="store_true", help="follow pre-releases")
    upd_app.add_argument("--quarantine", type=int, default=updater.DEFAULT_QUARANTINE_DAYS, metavar="DAYS",
                         help="days a new release must wait after it was first seen (default %(default)s; 0 = none)")
    sub.add_parser("list", help="list installed apps")
    rm = sub.add_parser("remove", help="delete an app, including its private home")
    rm.add_argument("app")
    rm.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    perms = sub.add_parser("perms", help="show or change an app's permissions (the pinned release is unchanged)")
    perms.add_argument("app")
    perms.add_argument("--allow", action="append", default=[], choices=PERMISSION_FLAGS)
    perms.add_argument("--deny", action="append", default=[], choices=PERMISSION_FLAGS)
    perms.add_argument("--display", choices=manifest.DISPLAYS)
    perms.add_argument("--add-dir", action="append", default=[], metavar="PATH[:ro|:rw]")
    perms.add_argument("--rm-dir", action="append", default=[], metavar="PATH")
    perms.add_argument("--add-dbus", action="append", default=[], metavar="NAME", help="allow talking to this session-bus name")
    perms.add_argument("--rm-dbus", action="append", default=[], metavar="NAME")
    perms.add_argument("--yes", action="store_true", help="do not ask for confirmation")
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
        elif args.command == "index":
            if args.index_command == "update":
                cmd_index_update(args, console)
            elif args.index_command == "rollback":
                a, b = indexsync.rollback()
                console.out(f"Index rolled back from {a[:12]} to {b[:12]}.")
            else:
                cur = indexsync.current()
                console.out(f"Pinned: {cur or 'no index yet'}" + (f"; previous: {indexsync.previous()}" if indexsync.previous() else ""))
        elif args.command == "search":
            cmd_search(args, console)
        elif args.command == "update":
            return cmd_update(args, client or github.Client(), console)
        elif args.command == "list":
            cmd_list(console)
        elif args.command == "remove":
            cmd_remove(args, console)
        elif args.command == "perms":
            cmd_perms(args, console)
        elif args.command == "run":
            extra_dirs = dirs_from_args(args.dir)
            return runner.launch(args.name, app_args, say=console.out, extra_dirs=extra_dirs)
    except Abort as e:
        console.out(str(e))
        return 1
    except (github.GitHubError, jail.JailError, jail.RunError, manifest.ManifestError, index.IndexProblem, indexsync.IndexRefused, OSError) as e:
        console.out(f"error: {e}")
        return 1
    return 0
