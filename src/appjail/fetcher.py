# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Standalone downloader that runs INSIDE the network-only jail (python3 -I fetcher.py).

Usage: fetcher.py URL OUTFILE EXPECTED_SIZE
Only https URLs on github.com / *.githubusercontent.com are followed, at most 5 hops.
The file is written with exclusive create and aborted if it would exceed EXPECTED_SIZE.
Stdlib only; it must not import anything from the appjail package.
"""

import sys
import urllib.error
import urllib.parse
import urllib.request

HOSTS = ("github.com", "githubusercontent.com")
MAX_HOPS = 5
CHUNK = 64 * 1024


def allowed(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    return (p.scheme == "https" and p.username is None and p.port in (None, 443)
            and any(host == h or host.endswith("." + h) for h in HOSTS))


class _Guard(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_HOPS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise urllib.error.URLError(f"redirect to a disallowed host: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main(argv):
    if len(argv) != 4:
        print("usage: fetcher.py URL OUTFILE EXPECTED_SIZE", file=sys.stderr)
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
