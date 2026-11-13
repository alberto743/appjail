# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The install steps `add` and `update` share, whatever the source: naming a new app, checking a GitHub download,
the evidence tier, extracting and swapping a version in, and the report afterwards."""

import os
import re

from . import appimage, attest, github, history, manifest, store, updater
from .cmd_desktop import install_entry, refresh_after_update
from .console import ARROW, ARROW_NB, INDENTED_LABEL, Abort, human_size
from .permargs import granted_summary

MAX_ASSET = 2 * 1024 ** 3
NEED_SQUASHFS = "install squashfs-tools (apt install squashfs-tools) and retry"


def default_name(repo):
    name = re.sub(r"[^a-z0-9._-]", "-", repo.lower()).lstrip("._-")[:64]
    return name if manifest.NAME_RE.fullmatch(name or "!") else ""


def new_app_name(given, derive_from):
    """The name of an app about to be added: --name, or one made from `derive_from`. It must be free."""
    name = given or default_name(derive_from)
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")
    return name


def choose_asset(console, assets, prompt):
    """The only asset, or the one the user picks from several."""
    if len(assets) == 1:
        return assets[0]
    console.out(prompt)
    return assets[console.choose("Asset", [f"{a.name} ({human_size(a.size)})" for a in assets])]


def download_verified(download, asset, stage):
    """Download the asset in the jail and check what can be checked: the announced size, GitHub's digest if
    there is one, and that it is a type-2 AppImage. Returns (staged path, sha256)."""
    staged = download(asset.url, stage, "download.AppImage", asset.size)
    if staged.stat().st_size != asset.size:
        raise Abort("downloaded size differs from the size GitHub announced")
    digest = store.sha256_file(staged)
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


def check_record(record, what):
    """`record` if it is a valid manifest; otherwise an Abort that says what could not be recorded ("this release",
    "this file", "this download"), before anything is installed."""
    try:
        return manifest.validate(record)
    except manifest.ManifestError as e:
        raise Abort(f"cannot record {what}: {e}") from e


def ask_extractor(console, extract_ok):
    """Whether to fall back to the AppImage's own extractor (no unsquashfs); aborts when the user declines."""
    if extract_ok():
        return False
    if not console.confirm("unsquashfs is not installed. Run the AppImage's own extractor "
                           "(--appimage-extract) inside a jail with no network instead?"):
        raise Abort(NEED_SQUASHFS)
    return True


def swap_in(name, staged, stage, record, extract, fallback):
    """Extract `staged` inside `stage`, then put image, tree, markers and manifest (last) in place.

    A new app (no app directory yet) is removed again if anything fails; for an update the previous image and tree
    are kept aside until everything worked and are restored on failure. Returns (entries, size) of the tree."""
    try:
        entries, size = extract(staged, stage / "root", fallback)
    except appimage.EXTRACT_ERRORS as e:
        raise Abort(f"cannot extract the AppImage: {e}") from e
    app, dest, root = store.app_dir(name), store.appimage_path(name), store.root_path(name)
    marks = (store.root_marker(name), store.tree_marker(name))
    fresh = not app.exists()
    old_image, old_root = stage / "old.AppImage", stage / "old-root"
    old_marks = [m.read_text() if m.is_file() else None for m in marks]
    os.chmod(staged, 0o600)
    placed, backups = [], []  # new things in place, and (original path, where the original went)
    try:
        if fresh:
            store.make_private(app)
        else:
            if root.exists():
                os.replace(root, old_root)
                backups.append((root, old_root))
            os.replace(dest, old_image)
            backups.append((dest, old_image))
        os.replace(stage / "root", root)
        placed.append(root)
        os.replace(staged, dest)
        placed.append(dest)
        store.atomic_write(marks[0], record.sha256 + "\n")
        store.atomic_write(marks[1], appimage.tree_digest(root) + "\n")
        manifest.dump(store.manifest_path(name), record)
    except BaseException:
        if fresh:
            store.remove_tree(app)
        else:
            for path in placed:
                store.remove_tree(path) if path.is_dir() else path.unlink(missing_ok=True)
            for original, backup in reversed(backups):
                os.replace(backup, original)
            for mark, text in zip(marks, old_marks, strict=True):
                if text is not None:
                    store.atomic_write(mark, text)
        raise
    return entries, size


def finish_add(console, args, record, entries, size):
    """The report after an install, the history entry and the optional menu entry."""
    name = record.name
    console.kv("Extracted", f"{entries} entries, {human_size(size)}")
    history.record(f"add {name} {record.version} (tier {record.evidence_tier})")
    console.out(f"Added '{name}' {record.version}: sha256 {record.sha256}, evidence tier {record.evidence_tier}")
    console.kv("Manifest", store.manifest_path(name))
    if args.desktop:
        try:
            install_entry(name, console, args, yes=True)
        except Abort as e:
            console.out(f"menu entry not created: {e} (`appjail desktop {name}` retries)")


def finish_update(run, record, entries, size):
    """After the new version is in place: forget the pending candidate, record the change, report, refresh the menu entry."""
    name, m = run.name, run.m
    updater.clear_pending(name)
    history.record(f"update {name} {m.version} -> {record.version} (tier {record.evidence_tier})")
    run.console.out(f"  updated {name}: {m.version} → {record.version}, sha256 {record.sha256}, {entries} entries, {human_size(size)}")
    refresh_after_update(name, run.console)
    return "updated"


def show_change(console, m, new_sha256, tier, size=None):
    """The hash and evidence an update would change, and the permissions it keeps."""
    console.kv("  sha256", m.sha256, INDENTED_LABEL)
    console.kv("", f"{ARROW_NB}{new_sha256}" + (f"  ({human_size(size)})" if size else ""), INDENTED_LABEL)
    console.kv("  evidence", f"tier {m.evidence_tier} {ARROW} {tier}", INDENTED_LABEL)
    console.kv("  permissions", f"unchanged ({granted_summary(m.permissions) or 'none'})", INDENTED_LABEL)


def show_quarantine(console, first, due, days):
    console.kv("  quarantine", f"first seen {updater.stamp(first)}; can be installed from {updater.stamp(due)} "
               f"({days} days; --quarantine DAYS to change)", INDENTED_LABEL)
