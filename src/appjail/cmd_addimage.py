# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add --file PATH` and `appjail add --url URL`: install an AppImage that has no GitHub release behind it.

There is no owner, digest or attestation to check, so the evidence is the sha256 of the bytes the user supplied:
tier 4 when `--sha256` was given and matched, tier 5 (trust on first use) otherwise. See DESIGN.md.
"""

import re
import secrets
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

from . import appimage, manifest, store
from .cmd_add import MAX_ASSET, ask_extractor, default_name, finish_add, place_new
from .console import Abort, human_size
from .permargs import (
    granted_summary,
    permissions_from_args,
    require_pasta,
    warn_owned_dbus,
    warn_privileged_portals,
    warn_sensitive_dbus,
)

NO_ORIGIN = "nothing identifies who published this file: trust on first use, the hash below is only 'unchanged since now'"


def parse_sha256(value):
    """The lowercase hex digest of --sha256, or None when the option was not given."""
    if value is None:
        return None
    digest = value.strip().lower().removeprefix("sha256:")
    if not manifest.SHA256_RE.fullmatch(digest):
        raise Abort("--sha256 must be 64 hexadecimal digits")
    return digest


def app_name(args, basename):
    name = args.name or default_name(re.sub(r"\.appimage$", "", basename, flags=re.IGNORECASE))
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")
    return name


def check_expected(digest, expected):
    """Tier of the bytes: 4 when they match the hash the user gave, 5 when none was given; a mismatch aborts."""
    if expected is None:
        return 5
    if digest != expected:
        raise Abort(f"sha256 mismatch: the file is {digest}, --sha256 says {expected}")
    return 4


def check_appimage(path):
    try:
        appimage.appimage_type(path)
    except appimage.NotAnAppImage as e:
        raise Abort(f"not a usable AppImage: {e}") from e


def show_permissions(console, perms):
    console.out("Permissions: " + granted_summary(perms))
    warn_sensitive_dbus(console, perms.dbus_filter)
    warn_owned_dbus(console, perms.dbus_own)
    warn_privileged_portals(console, perms.portal_interfaces)


def timestamp(now):
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def version_of(digest):
    return f"sha256:{digest[:12]}"


def regular_file(path):
    """The resolved path of a regular file (a symlink is followed once, the target must be regular)."""
    try:
        real = Path(path).expanduser().resolve(strict=True)
        st = real.stat()
    except OSError as e:
        raise Abort(f"--file {path}: {e.strerror or e}") from e
    if not stat.S_ISREG(st.st_mode):
        raise Abort(f"--file {path}: not a regular file")
    return real, st


def cmd_add_file(args, console, extract=appimage.extract, extract_ok=appimage.have_unsquashfs, now=None):
    expected = parse_sha256(args.sha256)
    real, st = regular_file(args.file)
    name = app_name(args, real.name)
    if not 0 < st.st_size <= MAX_ASSET:
        raise Abort(f"unexpected file size ({st.st_size} bytes)")
    perms = permissions_from_args(args)  # validates --dir before anything is copied
    require_pasta(perms)

    console.out(f"File       : {real}")
    console.out(f"Size       : {human_size(st.st_size)}, modified "
                f"{datetime.fromtimestamp(st.st_mtime, UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    console.warn(NO_ORIGIN)
    show_permissions(console, perms)
    fallback = ask_extractor(console, extract_ok)
    if not console.confirm(f"Copy {real.name} into appjail's store as '{name}'?"):
        raise Abort("cancelled")

    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged = stage / "download.AppImage"
        shutil.copyfile(real, staged)
        if staged.stat().st_size != st.st_size:
            raise Abort("the file changed while it was copied")
        digest = appimage.sha256_file(staged)
        tier = check_expected(digest, expected)
        check_appimage(staged)
        console.out(f"sha256     : {digest}" + ("  (matches --sha256)" if tier == 4 else ""))
        record = manifest.Manifest(
            name=name, source=f"file:{real.name}", version=version_of(digest), sha256=digest, evidence_tier=tier,
            published_at=timestamp(now), permissions=perms)
        try:
            manifest.validate(record)
        except manifest.ManifestError as e:
            raise Abort(f"cannot record this file: {e}") from e
        entries, size = place_new(name, staged, record, extract, fallback)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    finish_add(console, args, record, entries, size)


def cmd_add_url(args, console, **kw):
    raise Abort("add --url is not available yet")
