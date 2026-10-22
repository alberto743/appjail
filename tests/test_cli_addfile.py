# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os

import pytest

from appjail import appimage, cli, cmd_addimage, manifest, store
from appjail.cli import Abort

from .helpers import FAKE_APPIMAGE, NOW, SHA, Script


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "My-App-1.0-x86_64.AppImage"
    path.write_bytes(FAKE_APPIMAGE)
    return path


def add_file(h, path, *extra, answers=("y",), extract_ok=lambda: True):
    console = Script(answers)
    args = cli.build_parser().parse_args(["add", "--file", str(path), *extra])
    cmd_addimage.cmd_add_file(args, console, extract=h.extract, extract_ok=extract_ok, now=NOW)
    return console


def test_file_install_is_tier5_without_a_hash(h, image):
    console = add_file(h, image)
    m = manifest.load(store.manifest_path("my-app-1.0-x86_64"))
    assert (m.source, m.sha256, m.evidence_tier) == ("file:My-App-1.0-x86_64.AppImage", SHA, 5)
    assert (m.version, m.published_at, m.asset_pattern, m.owner_id) == (f"sha256:{SHA[:12]}", "2026-10-17T00:00:00Z", None, None)
    assert store.appimage_path("my-app-1.0-x86_64").read_bytes() == FAKE_APPIMAGE
    assert store.root_marker("my-app-1.0-x86_64").read_text().strip() == SHA
    assert store.tree_marker("my-app-1.0-x86_64").read_text().strip() == appimage.tree_digest(store.root_path("my-app-1.0-x86_64"))
    assert "nothing identifies who published" in console.text
    assert list(store.staging_root().iterdir()) == []
    assert image.read_bytes() == FAKE_APPIMAGE  # the original is untouched


def test_matching_sha256_is_tier4(h, image):
    console = add_file(h, image, "--name", "x", "--sha256", SHA.upper())
    assert manifest.load(store.manifest_path("x")).evidence_tier == 4
    assert "matches --sha256" in console.text


def test_sha256_prefix_is_accepted(h, image):
    add_file(h, image, "--name", "x", "--sha256", "sha256:" + SHA)
    assert manifest.load(store.manifest_path("x")).evidence_tier == 4


def test_sha256_mismatch_installs_nothing(h, image):
    with pytest.raises(Abort, match="sha256 mismatch"):
        add_file(h, image, "--name", "x", "--sha256", "0" * 64)
    h.assert_nothing_installed("x")


@pytest.mark.parametrize("bad", ["abc", "g" * 64, "a" * 63])
def test_bad_sha256_is_refused(h, image, bad):
    with pytest.raises(Abort, match="64 hexadecimal"):
        add_file(h, image, "--name", "x", "--sha256", bad)


def test_declining_copies_nothing(h, image):
    with pytest.raises(Abort, match="cancelled"):
        add_file(h, image, "--name", "x", answers=("n",))
    h.assert_nothing_installed("x")


def test_permission_options_apply(h, image):
    add_file(h, image, "--name", "x", "--allow", "network", "--no-gpu", "--display", "xwayland")
    p = manifest.load(store.manifest_path("x")).permissions
    assert (p.network, p.audio, p.gpu, p.display) == (True, True, False, "xwayland")


def test_not_an_appimage_is_refused(h, tmp_path):
    bad = tmp_path / "x.AppImage"
    bad.write_bytes(b"#!/bin/sh\necho hi\n")
    with pytest.raises(Abort, match="not a usable AppImage"):
        add_file(h, bad, "--name", "x")
    h.assert_nothing_installed("x")


def test_symlink_to_a_regular_file_is_followed(h, image, tmp_path):
    link = tmp_path / "link.AppImage"
    link.symlink_to(image)
    add_file(h, link)
    assert manifest.load(store.manifest_path("my-app-1.0-x86_64")).source == "file:My-App-1.0-x86_64.AppImage"


def test_directory_fifo_and_missing_are_refused(h, tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for bad in (tmp_path, fifo, tmp_path / "missing"):
        with pytest.raises(Abort, match="--file"):
            add_file(h, bad, "--name", "x")
    h.assert_nothing_installed("x")


def test_existing_name_is_refused(h, image):
    add_file(h, image, "--name", "x")
    with pytest.raises(Abort, match="already added"):
        add_file(h, image, "--name", "x")


def test_name_must_be_derivable(h, tmp_path):
    odd = tmp_path / "!!!.AppImage"
    odd.write_bytes(FAKE_APPIMAGE)
    with pytest.raises(Abort, match="pass --name"):
        add_file(h, odd)


def test_extraction_failure_keeps_nothing(h, image):
    def broken(*a, **k):
        raise appimage.ExtractError("boom")
    console = Script(["y"])
    args = cli.build_parser().parse_args(["add", "--file", str(image), "--name", "x"])
    with pytest.raises(Abort, match="cannot extract"):
        cmd_addimage.cmd_add_file(args, console, extract=broken, extract_ok=lambda: True, now=NOW)
    h.assert_nothing_installed("x")


@pytest.mark.parametrize("argv,message", [
    (["add", "o/r", "--file", "x"], "give either"),
    (["add", "--file", "x", "--url", "https://x.org/a"], "give either"),
    (["add"], "owner/repo"),
    (["add", "o/r", "--sha256", SHA], "apply to --file / --url only"),
])
def test_dispatch_rejects_bad_combinations(sandbox, argv, message):
    console = Script()
    assert cli.main(argv, console=console) == 1
    assert message in console.text


def test_a_failure_after_extraction_removes_the_whole_new_app(h, image, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(manifest, "dump", broken)
    with pytest.raises(OSError, match="disk full"):
        add_file(h, image, "--name", "x")
    h.assert_nothing_installed("x")
