# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail add --file PATH` and `appjail add --url URL`: install an AppImage that has no GitHub release behind it.

There is no owner, digest or attestation to check, so the evidence is the sha256 of the bytes the user supplied:
tier 4 when `--sha256` was given and matched, tier 5 (trust on first use) otherwise. See docs/understand/acquisition/evidence.md.
"""

import re
import shutil
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from . import manifest, store
from .console import Abort, human_size
from .errors import JailError
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
from .install import (
    MAX_ASSET,
    ask_extractor,
    check_record,
    finish_add,
    new_app_name,
    swap_in,
)
from .permargs import (
    permissions_from_args,
    require_network_isolation,
    show_permissions,
)
from .services import Services


def app_name(args, basename):
    return new_app_name(args.name, re.sub(r"\.appimage$", "", basename, flags=re.IGNORECASE))


def cmd_add_file(args, console, svc=None, now=None):
    svc = svc or Services()
    expected = parse_sha256(args.sha256)
    real, st = regular_file(args.file)
    name = app_name(args, real.name)
    if not 0 < st.st_size <= MAX_ASSET:
        raise Abort(f"unexpected file size ({st.st_size} bytes)")
    perms = permissions_from_args(args)  # validates every option before anything is copied
    require_network_isolation(perms)

    console.kv("File", real)
    console.kv("Size", f"{human_size(st.st_size)}, modified "
               f"{datetime.fromtimestamp(st.st_mtime, UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    console.warn(NO_ORIGIN)
    show_permissions(console, perms)
    fallback = ask_extractor(console, svc.extract_ok)
    if not console.confirm(f"Copy {real.name} into appjail's store as '{name}'?"):
        raise Abort("cancelled")

    with store.staging() as stage:
        staged = stage / "download.AppImage"
        shutil.copyfile(real, staged)
        if staged.stat().st_size != st.st_size:
            raise Abort("the file changed while it was copied")
        digest = store.sha256_file(staged)
        tier = check_expected(digest, expected)
        check_appimage(staged)
        console.kv("sha256", digest + ("  (matches --sha256)" if tier == 4 else ""))
        record = manifest.Manifest(
            name=name, source=f"file:{real.name}", version=version_of(digest), sha256=digest, evidence_tier=tier,
            published_at=timestamp(now), permissions=perms)
        check_record(record, "this file")
        entries, size = swap_in(name, staged, stage, record, svc.extract, fallback)
    finish_add(console, args, record, entries, size)


def url_basename(url):
    parts = urlsplit(url)
    return unquote(PurePosixPath(parts.path).name) or parts.hostname


def cmd_add_url(args, console, svc=None, now=None):
    svc = svc or Services()
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
    require_network_isolation(perms)

    console.kv("URL", url)
    console.kv("Limit", f"{human_size(max_mib * 1024 ** 2)}; redirects may go to any host, also over plain http")
    console.warn(NO_ORIGIN)
    show_permissions(console, perms)
    fallback = ask_extractor(console, svc.extract_ok)
    if not console.confirm(f"Download {urlsplit(url).hostname} in a network-only jail?"):
        raise Abort("cancelled")

    with store.staging() as stage:
        try:
            staged, info = svc.download_url(url, stage, "download.AppImage", max_mib * 1024 ** 2)
        except JailError as e:
            raise Abort(str(e)) from e
        digest = store.sha256_file(staged)
        tier = check_expected(digest, expected)
        check_appimage(staged)
        console.kv("Downloaded", f"{human_size(info['size'])}, sha256 {digest}" + ("  (matches --sha256)" if tier == 4 else ""))
        check_download_info(console, url, info, tier)
        record = manifest.Manifest(
            name=name, source=f"url:{url}", version=version_of(digest), sha256=digest, evidence_tier=tier,
            published_at=timestamp(now), fingerprint=url_fingerprint(staged, info), permissions=perms)
        check_record(record, "this download")
        entries, size = swap_in(name, staged, stage, record, svc.extract, fallback)
    finish_add(console, args, record, entries, size)
