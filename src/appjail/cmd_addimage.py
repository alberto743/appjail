# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add --file PATH` and `appjail add --url URL`: install an AppImage that has no GitHub release behind it.

There is no owner, digest or attestation to check, so the evidence is the sha256 of the bytes the user supplied:
tier 4 when `--sha256` was given and matched, tier 5 (trust on first use) otherwise. See DESIGN.md.
"""

import re
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from . import appimage, fetcher, jail, manifest, store
from .cmd_add import MAX_ASSET, ask_extractor, default_name, finish_add, place_new
from .console import Abort, human_size
from .permargs import (
    permissions_from_args,
    require_pasta,
    show_permissions,
)

DEFAULT_MAX_MIB = 1024
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


def check_download_info(console, url, info, tier):
    """What the server did on the way: where the file really came from, and whether it went through plain http."""
    final = urlsplit(info["final_url"]).hostname
    if final != urlsplit(url).hostname:
        console.out(f"Served by  : {final} (after redirects)")
    if info["http_hop"]:
        console.warn("a redirect went through plain http: anyone on the path could have changed the file")
        if tier != 4 and not console.confirm("No --sha256 confirms the bytes. Install anyway?"):
            raise Abort("cancelled")


def url_fingerprint(staged, info):
    size, chunks = fetcher.fingerprint_file(staged)
    return manifest.Fingerprint(size=size, chunks=chunks, etag=info["etag"], last_modified=info["last_modified"])


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
