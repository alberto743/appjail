# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add --file PATH` and `appjail add --url URL`: install an AppImage that has no GitHub release behind it.

There is no owner, digest or attestation to check, so the evidence is the sha256 of the bytes the user supplied:
tier 4 when `--sha256` was given and matched, tier 5 (trust on first use) otherwise. See DESIGN.md.
"""

import re
import shutil
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from . import appimage, jail, manifest, store
from .cmd_add import MAX_ASSET, ask_extractor, default_name, finish_add, place_new
from .console import Abort, human_size
from .imagesrc import (
    DEFAULT_MAX_MIB,
    NO_ORIGIN,
    check_appimage,
    check_download_info,
    check_expected,
    parse_sha256,
    regular_file,
    timestamp,
    url_fingerprint,
    version_of,
)
from .permargs import (
    permissions_from_args,
    require_pasta,
    show_permissions,
)


def app_name(args, basename):
    name = args.name or default_name(re.sub(r"\.appimage$", "", basename, flags=re.IGNORECASE))
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("cannot derive a valid app name; pass --name")
    if store.manifest_path(name).exists() or store.app_dir(name).exists():
        raise Abort(f"'{name}' is already added")
    return name


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

    stage = store.new_staging_dir()
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


def url_basename(url):
    parts = urlsplit(url)
    return unquote(PurePosixPath(parts.path).name) or parts.hostname


def cmd_add_url(args, console, download_url=jail.download_url, extract=appimage.extract,
                extract_ok=appimage.have_unsquashfs, now=None):
    expected = parse_sha256(args.sha256)
    try:
        url = manifest.check_url(args.url)
    except manifest.ManifestError as e:
        raise Abort(f"--url: {e}") from e
    name = app_name(args, url_basename(url))
    max_mib = DEFAULT_MAX_MIB if args.max_size is None else args.max_size
    if not 0 < max_mib * 1024 ** 2 <= MAX_ASSET:
        raise Abort(f"--max-size must be between 1 and {MAX_ASSET // 1024 ** 2} MiB")
    perms = permissions_from_args(args)
    require_pasta(perms)

    console.out(f"URL        : {url}")
    console.out(f"Limit      : {human_size(max_mib * 1024 ** 2)}; redirects may go to any host, also over plain http")
    console.warn(NO_ORIGIN)
    show_permissions(console, perms)
    fallback = ask_extractor(console, extract_ok)
    if not console.confirm(f"Download {urlsplit(url).hostname} in a network-only jail?"):
        raise Abort("cancelled")

    stage = store.new_staging_dir()
    try:
        try:
            staged, info = download_url(url, stage, "download.AppImage", max_mib * 1024 ** 2)
        except jail.JailError as e:
            raise Abort(str(e)) from e
        digest = appimage.sha256_file(staged)
        tier = check_expected(digest, expected)
        check_appimage(staged)
        console.out(f"Downloaded : {human_size(info['size'])}, sha256 {digest}" + ("  (matches --sha256)" if tier == 4 else ""))
        check_download_info(console, url, info, tier)
        record = manifest.Manifest(
            name=name, source=f"url:{url}", version=version_of(digest), sha256=digest, evidence_tier=tier,
            published_at=timestamp(now), fingerprint=url_fingerprint(staged, info), permissions=perms)
        try:
            manifest.validate(record)
        except manifest.ManifestError as e:
            raise Abort(f"cannot record this download: {e}") from e
        entries, size = place_new(name, staged, record, extract, fallback)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    finish_add(console, args, record, entries, size)
