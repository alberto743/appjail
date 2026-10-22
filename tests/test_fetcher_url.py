# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The URL modes of fetcher.py against a real local HTTP server (the https-only start rule is main()'s, tested apart)."""

import contextlib
import hashlib
import http.server
import io
import random
import threading
import urllib.error
import urllib.request

import pytest

from appjail import fetcher

from .helpers import stub

PAYLOAD = stub(b"hsqs" + random.Random(1).randbytes(300_000))
ETAG = '"v1"'
MODIFIED = "Tue, 20 Oct 2026 08:00:00 GMT"


class Handler(http.server.BaseHTTPRequestHandler):
    body = PAYLOAD
    ranges = True
    lie_length = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/file")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/creds"):
            self.send_response(302)
            self.send_header("Location", f"http://user:pw@127.0.0.1:{self.server.server_port}/file")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.headers.get("If-None-Match") == ETAG:
            self.send_response(304)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, status = self.body, 200
        rng = self.headers.get("Range")
        extra = {}
        if rng and self.ranges:
            start, _, end = rng.removeprefix("bytes=").partition("-")
            start, end = int(start), min(int(end), len(body) - 1)
            extra["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
            body, status = body[start:end + 1], 206
        self.send_response(status)
        self.send_header("ETag", ETAG)
        self.send_header("Last-Modified", MODIFIED)
        self.send_header("Content-Length", str(self.lie_length if self.lie_length is not None else len(body)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


@pytest.fixture
def server():
    for attr in ("body", "ranges", "lie_length"):
        setattr(Handler, attr, {"body": PAYLOAD, "ranges": True, "lie_length": None}[attr])
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def opener():
    return urllib.request.build_opener(fetcher._Guard(fetcher.allowed_any))


# -- download --any -----------------------------------------------------------------------


def test_download_any_follows_an_http_redirect_and_reports_it(server, tmp_path):
    out = tmp_path / "f"
    guard = fetcher._Guard(fetcher.allowed_any)
    info = fetcher.download_any(server + "/redirect", str(out), 10 ** 7, urllib.request.build_opener(guard))
    assert out.read_bytes() == PAYLOAD
    assert info["size"] == len(PAYLOAD) and info["etag"] == ETAG and info["last_modified"] == MODIFIED
    assert info["final_url"].endswith("/file")


def test_download_any_flags_an_http_hop(server, tmp_path):
    # the Guard in download_any is its own; the redirect lands on http, so the flag must be set
    info = fetcher.download_any(server + "/redirect", str(tmp_path / "f"), 10 ** 7)
    assert info["http_hop"] is True
    info = fetcher.download_any(server + "/file", str(tmp_path / "g"), 10 ** 7)
    assert info["http_hop"] is False


def test_download_any_cap_is_enforced(server, tmp_path):
    with pytest.raises(ValueError, match="limit"):
        fetcher.download_any(server + "/file", str(tmp_path / "f"), 1000)


def test_download_any_cap_without_content_length(server, tmp_path):
    Handler.protocol_version = "HTTP/1.0"
    try:
        with pytest.raises(ValueError, match="limit"):
            fetcher.download_any(server + "/file", str(tmp_path / "f"), 1000)
    finally:
        Handler.protocol_version = "HTTP/1.1"


def test_download_any_content_length_must_match(server, tmp_path):
    Handler.lie_length = len(PAYLOAD) + 5
    with pytest.raises((ValueError, OSError, urllib.error.URLError)):
        fetcher.download_any(server + "/file", str(tmp_path / "f"), 10 ** 7)


def test_download_any_refuses_redirect_loops_and_credentials(server, tmp_path):
    with pytest.raises(urllib.error.HTTPError):
        fetcher.download_any(server + "/loop", str(tmp_path / "f"), 10 ** 7)
    with pytest.raises(urllib.error.URLError, match="disallowed"):
        fetcher.download_any(server + "/creds", str(tmp_path / "g"), 10 ** 7)


@pytest.mark.parametrize("url,first,ok", [
    ("https://example.org/a", True, True), ("http://example.org/a", True, False),
    ("http://example.org/a", False, True), ("https://u:p@example.org/a", False, False),
    ("ftp://example.org/a", False, False), ("file:///etc/passwd", False, False), ("https:///a", True, False),
])
def test_allowed_any(url, first, ok):
    assert fetcher.allowed_any(url, first) is ok


def test_main_any_refuses_plain_http_start():
    with contextlib.redirect_stderr(io.StringIO()):
        assert fetcher.main(["f", "--any", "http://example.org/a", "/nonexistent", "5"]) == 2
        assert fetcher.main(["f", "--check", "http://example.org/a"]) == 2
        assert fetcher.main(["f", "--bogus"]) == 2


# -- the fingerprint ----------------------------------------------------------------------


def test_remote_fingerprint_equals_the_local_one(server, tmp_path):
    path = tmp_path / "f"
    path.write_bytes(PAYLOAD)
    size, chunks = fetcher.fingerprint_file(path)
    got = fetcher.check(server + "/file", opener=opener())
    assert got == {"status": "fingerprint", "size": size, "chunks": chunks, "etag": ETAG, "last_modified": MODIFIED}
    assert size == len(PAYLOAD)


def test_fingerprint_changes_with_the_content_at_a_sampled_offset(server, tmp_path):
    base = fetcher.fingerprint_file(_write(tmp_path / "a", PAYLOAD))
    for pos in (70, len(PAYLOAD) // 2, len(PAYLOAD) - 3):  # superblock, middle, end
        changed = bytearray(PAYLOAD)
        changed[pos] ^= 1
        assert fetcher.fingerprint_file(_write(tmp_path / f"c{pos}", bytes(changed))) != base


def test_fingerprint_misses_a_change_between_the_windows(tmp_path):
    base = fetcher.fingerprint_file(_write(tmp_path / "a", PAYLOAD))
    changed = bytearray(PAYLOAD)
    changed[1000] ^= 1  # not sampled: the documented limit
    assert fetcher.fingerprint_file(_write(tmp_path / "b", bytes(changed))) == base


def test_windows_of_a_small_file_stay_inside_it():
    assert fetcher.windows(100, None) == [(0, 100)]
    assert all(0 <= s and s + n <= 100 for s, n in fetcher.windows(100, 64))
    assert all(n > 0 for _, n in fetcher.windows(10, None))


def _write(path, data):
    path.write_bytes(data)
    return path


# -- check --------------------------------------------------------------------------------


def test_check_unchanged_on_a_304(server):
    assert fetcher.check(server + "/file", etag=ETAG, opener=opener()) == {"status": "unchanged"}


def test_check_a_different_etag_gives_the_fingerprint(server):
    got = fetcher.check(server + "/file", etag='"old"', opener=opener())
    assert got["status"] == "fingerprint"


def test_check_without_range_support(server):
    Handler.ranges = False
    got = fetcher.check(server + "/file", opener=opener())
    assert got == {"status": "no-range", "etag": ETAG, "last_modified": MODIFIED}


def test_check_follows_an_http_redirect(server):
    assert fetcher.check(server + "/redirect", opener=opener())["status"] == "fingerprint"


def test_fingerprint_hash_is_over_the_window_hashes():
    assert fetcher.combine(64, ["a", "b"]) == hashlib.sha256(b"64\na\nb").hexdigest()

