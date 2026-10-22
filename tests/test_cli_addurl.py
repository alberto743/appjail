# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest

from appjail import cli, cmd_addimage, fetcher, jail, manifest, store
from appjail.cli import Abort

from .helpers import FAKE_APPIMAGE, NOW, SHA, Script

URL = "https://example.org/dl/My-App-1.0-x86_64.AppImage"


def info(**kw):
    base = {"size": len(FAKE_APPIMAGE), "final_url": URL, "http_hop": False, "etag": '"v1"',
            "last_modified": "Tue, 20 Oct 2026 08:00:00 GMT"}
    return base | kw


class Downloader:
    def __init__(self, content=FAKE_APPIMAGE, **kw):
        self.content, self.kw, self.calls = content, kw, []

    def __call__(self, url, stage, filename, max_size):
        self.calls.append((url, max_size))
        path = Path(stage) / filename
        path.write_bytes(self.content)
        return path, info(**self.kw)


def add_url(h, *extra, url=URL, answers=("y",), download=None):
    console = Script(answers)
    args = cli.build_parser().parse_args(["add", "--url", url, *extra])
    cmd_addimage.cmd_add_url(args, console, download_url=download or Downloader(), extract=h.extract,
                             extract_ok=lambda: True, now=NOW)
    return console


def test_url_install_records_source_fingerprint_and_tier5(h):
    dl = Downloader()
    console = add_url(h, download=dl)
    m = manifest.load(store.manifest_path("my-app-1.0-x86_64"))
    assert (m.source, m.sha256, m.evidence_tier, m.asset_pattern, m.owner_id) == (f"url:{URL}", SHA, 5, None, None)
    assert m.version == f"sha256:{SHA[:12]}" and m.published_at == "2026-10-17T00:00:00Z"
    assert (m.fingerprint.size, m.fingerprint.etag) == (len(FAKE_APPIMAGE), '"v1"')
    assert m.fingerprint.last_modified == "Tue, 20 Oct 2026 08:00:00 GMT"
    assert dl.calls == [(URL, 1024 * 1024 ** 2)]
    assert store.appimage_path("my-app-1.0-x86_64").read_bytes() == FAKE_APPIMAGE
    assert "nothing identifies who published" in console.text
    assert list(store.staging_root().iterdir()) == []


def test_fingerprint_matches_what_the_remote_check_computes(h, tmp_path):
    add_url(h, "--name", "x")
    path = tmp_path / "f"
    path.write_bytes(FAKE_APPIMAGE)
    assert manifest.load(store.manifest_path("x")).fingerprint.chunks == fetcher.fingerprint_file(path)[1]


def test_matching_sha256_is_tier4(h):
    add_url(h, "--name", "x", "--sha256", SHA)
    assert manifest.load(store.manifest_path("x")).evidence_tier == 4


def test_mismatch_installs_nothing(h):
    with pytest.raises(Abort, match="sha256 mismatch"):
        add_url(h, "--name", "x", "--sha256", "1" * 64)
    h.assert_nothing_installed("x")


def test_http_hop_needs_extra_confirmation_without_a_hash(h):
    with pytest.raises(Abort, match="cancelled"):
        add_url(h, "--name", "x", answers=("y", "n"), download=Downloader(http_hop=True))
    h.assert_nothing_installed("x")
    console = add_url(h, "--name", "x", answers=("y", "y"), download=Downloader(http_hop=True))
    assert "plain http" in console.text and manifest.load(store.manifest_path("x")).evidence_tier == 5


def test_http_hop_with_a_matching_hash_needs_no_extra_question(h):
    console = add_url(h, "--name", "x", "--sha256", SHA, answers=("y",), download=Downloader(http_hop=True))
    assert "plain http" in console.text and manifest.load(store.manifest_path("x")).evidence_tier == 4


def test_served_by_another_host_is_shown(h):
    console = add_url(h, "--name", "x", download=Downloader(final_url="https://cdn.example.net/x"))
    assert "cdn.example.net" in console.text


@pytest.mark.parametrize("url", ["http://example.org/a.AppImage", "https://u:p@example.org/a", "ftp://x/a",
                                 "https://example.org/a#f", "not a url"])
def test_bad_urls_are_refused(h, url):
    with pytest.raises(Abort, match="--url"):
        add_url(h, "--name", "x", url=url)


def test_max_size_is_passed_and_checked(h):
    dl = Downloader()
    add_url(h, "--name", "x", "--max-size", "5", download=dl)
    assert dl.calls[0][1] == 5 * 1024 ** 2
    for bad in ("0", "-1", "999999"):
        with pytest.raises(Abort, match="--max-size"):
            add_url(h, "--name", "y", "--max-size", bad)


def test_declining_downloads_nothing(h):
    dl = Downloader()
    with pytest.raises(Abort, match="cancelled"):
        add_url(h, "--name", "x", answers=("n",), download=dl)
    assert dl.calls == []


def test_not_an_appimage_is_refused(h):
    with pytest.raises(Abort, match="not a usable AppImage"):
        add_url(h, "--name", "x", download=Downloader(content=b"<html>nope</html>"))
    h.assert_nothing_installed("x")


def test_jail_failure_is_reported_and_leaves_nothing(h):
    def failing(*a):
        raise jail.JailError("download failed: boom")
    with pytest.raises(Abort, match="boom"):
        add_url(h, "--name", "x", download=failing)
    h.assert_nothing_installed("x")


def test_name_comes_from_the_url_path(h):
    add_url(h, url="https://example.org/dl/Some%20Tool.AppImage?token=1")
    assert store.manifest_path("some-tool").exists()
