# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Standalone downloader that runs INSIDE the network-only jail (python3 -I fetcher.py).

    fetcher.py URL OUTFILE EXPECTED_SIZE           GitHub asset: only https URLs on github.com /
                                                   *.githubusercontent.com are followed, at most 5 hops; the
                                                   download is aborted if it would exceed EXPECTED_SIZE
    fetcher.py --any URL OUTFILE MAX_SIZE          any https URL (redirects may go to any host, also to
                                                   plain http); prints one JSON line about what was served
    fetcher.py --check URL [ETAG [LAST_MODIFIED]]  cheap "has it changed" test for a URL app: a conditional
                                                   range request, then the fixed windows of the file; prints one
                                                   JSON line (see check())

The file is written with exclusive create. The policy comes from the caller's choice of mode, never from the
server. Stdlib only; it must not import anything from the appjail package (the host imports this module for the
window arithmetic, so both sides compute the same fingerprint).
"""

import hashlib
import json
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

HOSTS = ("github.com", "githubusercontent.com")
MAX_HOPS = 5
CHUNK = 64 * 1024
WINDOW = 64 * 1024  # size of the middle and last windows of the fingerprint
SUPERBLOCK = 96  # SquashFS superblock: magic, inode count, build time, ..., bytes used
HEAD = 64  # the ELF header, which says where the embedded filesystem starts


def allowed(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    return (p.scheme == "https" and p.username is None and p.port in (None, 443)
            and any(host == h or host.endswith("." + h) for h in HOSTS))


def allowed_any(url, first=False):
    """The first URL must be https; a redirect may also be http. Never credentials."""
    p = urllib.parse.urlsplit(url)
    ok = p.scheme == "https" if first else p.scheme in ("http", "https")
    return ok and bool(p.hostname) and p.username is None and "@" not in p.netloc


class _Guard(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_HOPS

    def __init__(self, check=allowed):
        self.check, self.http_hop = check, False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        if not self.check(newurl):
            raise urllib.error.URLError(f"redirect to a disallowed URL: {urllib.parse.urlsplit(newurl).hostname}")
        if urllib.parse.urlsplit(newurl).scheme == "http":
            self.http_hop = True
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# -- the fingerprint ------------------------------------------------------------------------------


def elf_offset(head):
    """Where the filesystem starts, from the first bytes of a 64-bit little-endian ELF runtime (None if not one)."""
    if len(head) < HEAD or head[:4] != b"\x7fELF" or head[4] != 2 or head[5] != 1:
        return None
    shoff, = struct.unpack_from("<Q", head, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)
    return shoff + shentsize * shnum


def windows(size, offset):
    """(start, length) windows sampled from a file of `size` bytes: the superblock, the middle, the end."""
    found = []
    if offset is not None and 0 < offset and offset + SUPERBLOCK <= size:
        found.append((offset, SUPERBLOCK))
    middle = max(0, (size - WINDOW) // 2)
    found.append((middle, min(WINDOW, size - middle)))
    tail = max(0, size - WINDOW)
    found.append((tail, size - tail))
    return list(dict.fromkeys(found))


def combine(offset, hashes):
    """The single value stored as `fingerprint.chunks`."""
    return hashlib.sha256((f"{offset}\n" + "\n".join(hashes)).encode()).hexdigest()


def fingerprint_file(path):
    """(size, chunks) of a complete local file, with the same windows the remote check reads."""
    with open(path, "rb") as f:
        head = f.read(HEAD)
        size = f.seek(0, 2)
        offset = elf_offset(head)
        hashes = []
        for start, length in windows(size, offset):
            f.seek(start)
            hashes.append(hashlib.sha256(f.read(length)).hexdigest())
    return size, combine(offset, hashes)


# -- requests -------------------------------------------------------------------------------------


def _open(opener, url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "appjail", "Accept": "application/octet-stream",
                                               **(headers or {})})
    return opener.open(req, timeout=30)


def _total_from_range(value):
    """The complete size from a `Content-Range: bytes a-b/total` header (None when unknown)."""
    _, _, total = (value or "").rpartition("/")
    return int(total) if total.isdigit() else None


def _read_exactly(resp, n):
    data = b""
    while len(data) < n:
        chunk = resp.read(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _range(opener, url, start, length):
    """The bytes of one window, or None when the server does not answer 206."""
    with _open(opener, url, {"Range": f"bytes={start}-{start + length - 1}"}) as resp:
        if resp.status != 206:
            return None
        return _read_exactly(resp, length)


def check(url, etag=None, modified=None, opener=None):
    """Result of the cheap test, as a dict:
    {"status": "unchanged"}                          the server answered 304 to the stored validators
    {"status": "fingerprint", "size", "chunks", "etag", "last_modified"}   what the server serves now
    {"status": "no-range", "etag", "last_modified"}  it does not support range requests: a full download is needed
    """
    guard = _Guard(allowed_any)
    opener = opener or urllib.request.build_opener(guard)
    headers = {"Range": f"bytes=0-{HEAD - 1}"}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    try:
        resp = _open(opener, url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return {"status": "unchanged"}
        raise
    with resp:
        got = {"etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified")}
        if resp.status != 206:
            return {"status": "no-range", **got}
        head = _read_exactly(resp, HEAD)
        size = _total_from_range(resp.headers.get("Content-Range"))
    if size is None:
        return {"status": "no-range", **got}
    offset = elf_offset(head)
    hashes = []
    for start, length in windows(size, offset):
        data = _range(opener, url, start, length)
        if data is None or len(data) != length:
            return {"status": "no-range", **got}
        hashes.append(hashlib.sha256(data).hexdigest())
    return {"status": "fingerprint", "size": size, "chunks": combine(offset, hashes), **got}


def download_any(url, out, cap, opener=None):
    """Download to `out` (exclusive create); returns what the server said, or raises ValueError past the cap."""
    guard = _Guard(allowed_any)
    opener = opener or urllib.request.build_opener(guard)
    total = 0
    with _open(opener, url) as resp, open(out, "xb") as f:
        announced = resp.headers.get("Content-Length")
        if announced is not None and announced.isdigit() and int(announced) > cap:
            raise ValueError(f"the server announces {announced} bytes, over the limit of {cap}")
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise ValueError(f"the download exceeds the limit of {cap} bytes")
            f.write(chunk)
        if announced is not None and announced.isdigit() and int(announced) != total:
            raise ValueError(f"Content-Length says {announced} bytes, {total} arrived")
        return {"size": total, "final_url": resp.geturl(), "http_hop": guard.http_hop,
                "etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified")}


def main(argv):
    mode = argv[1] if len(argv) > 1 and argv[1].startswith("--") else None
    try:
        if mode == "--any" and len(argv) == 5:
            if not allowed_any(argv[2], first=True):
                print("refusing URL", file=sys.stderr)
                return 2
            print(json.dumps(download_any(argv[2], argv[3], int(argv[4]))))
            return 0
        if mode == "--check" and 3 <= len(argv) <= 5:
            if not allowed_any(argv[2], first=True):
                print("refusing URL", file=sys.stderr)
                return 2
            print(json.dumps(check(argv[2], *argv[3:])))
            return 0
    except ValueError as e:
        print(e, file=sys.stderr)
        return 3
    if mode or len(argv) != 4:
        print("usage: fetcher.py URL OUTFILE EXPECTED_SIZE | --any URL OUTFILE MAX_SIZE | --check URL [ETAG [LAST_MODIFIED]]",
              file=sys.stderr)
        return 2
    url, out, expected = argv[1], argv[2], int(argv[3])
    if not allowed(url):
        print("refusing URL", file=sys.stderr)
        return 2
    opener = urllib.request.build_opener(_Guard)
    req = urllib.request.Request(url, headers={"User-Agent": "appjail", "Accept": "application/octet-stream"})
    total = 0
    with opener.open(req, timeout=30) as resp, open(out, "xb") as f:
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > expected:
                print("download exceeds the size announced by GitHub", file=sys.stderr)
                return 3
            f.write(chunk)
    print(total)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
