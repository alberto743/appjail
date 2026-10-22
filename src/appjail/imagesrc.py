# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What `add --file/--url` and `update` of those apps have in common: the evidence rules, the hash option, the
local-file checks and the fingerprint of a downloaded file."""

import stat
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import appimage, fetcher, manifest
from .console import Abort

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
