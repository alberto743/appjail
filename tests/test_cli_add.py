# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
from unittest import mock

import pytest

from appjail import appimage, cli, cmd_add, github, manifest, store
from appjail.cli import Abort

from .helpers import (
    FAKE_APPIMAGE,
    SHA,
    FakeClient,
    Script,
    asset,
    info,
    outside_dir,
    release,
)

# -- success paths -----------------------------------------------------------------------


def test_success_with_digest(h):
    console = h.add()
    m = manifest.load(store.manifest_path("app"))
    assert (m.source, m.version, m.sha256, m.evidence_tier, m.owner_id) == ("github:o/App", "v1.0", SHA, 3, 42)
    assert m.asset_pattern == "App-*-x86_64.AppImage"
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert store.appimage_path("app").stat().st_mode & 0o777 == 0o600
    assert h.downloads[0][0] == asset().url
    assert list(store.staging_root().iterdir()) == []
    assert "attestation: present, cannot be verified" in console.text


def test_extraction_runs_on_the_staged_file_and_marks_source_hash(h):
    h.add()
    staged, dest, fallback = h.extractions[0]
    assert (staged.name, dest.name, fallback) == ("download.AppImage", "root", False)
    assert store.root_path("app").is_dir()
    assert store.root_marker("app").read_text().strip() == SHA
    assert store.tree_marker("app").read_text().strip() == appimage.tree_digest(store.root_path("app"))


def test_default_permissions_are_minimal(h):
    h.add()
    p = manifest.load(store.manifest_path("app")).permissions
    assert (p.network, p.audio, p.gpu, p.portals, p.display, p.dirs) == (False, True, True, False, "wayland", ())


def test_permission_flags(h):
    h.add(extra=["--allow", "network", "--no-audio", "--display", "xwayland"])
    p = manifest.load(store.manifest_path("app")).permissions
    assert (p.network, p.audio, p.gpu, p.display) == (True, False, True, "xwayland")


def test_rootful_display_and_its_size(h):
    h.add(extra=["--display", "xwayland-rootful", "--display-size", "1024x768"])
    p = manifest.load(store.manifest_path("app")).permissions
    assert (p.display, p.display_size) == ("xwayland-rootful", "1024x768")


@pytest.mark.parametrize("flag", [f for f in cli.PERMISSION_FLAGS if f not in ("audio", "gpu")])
def test_every_allow_choice_reaches_the_permissions(flag):
    args = cli.build_parser().parse_args(["add", "o/r", "--allow", flag])
    assert getattr(cmd_add.permissions_from_args(args), flag) is True


def test_allow_linger_is_written_to_the_manifest(h):
    h.add(extra=["--allow", "linger"])
    assert manifest.load(store.manifest_path("app")).permissions.linger is True


def test_no_digest_is_tier4_with_warning(h):
    console = h.add(client=FakeClient(release_=release(asset(sha=""))))
    assert manifest.load(store.manifest_path("app")).evidence_tier == 4
    assert "trust on first use" in console.text


def test_tag_selects_that_release(h):
    client = FakeClient(release_=release(asset(), tag="v0.9"))
    h.add(client=client, extra=["--tag", "v0.9"])
    assert ("release_by_tag", "o/App", "v0.9") in client.calls
    assert not any(c[0] == "latest_release" for c in client.calls)
    assert manifest.load(store.manifest_path("app")).version == "v0.9"


def test_dir_option_is_stored_canonically(h, tmp_path, monkeypatch):
    home = tmp_path / "fakehome"
    (home / "Docs").mkdir(parents=True)
    outside = outside_dir()
    monkeypatch.setattr(Path, "home", lambda: home)
    h.add(extra=["--dir", str(home / "Docs"), "--dir", f"{outside}:rw"])
    assert manifest.load(store.manifest_path("app")).permissions.dirs == ("~/Docs", f"{outside}:rw")


@pytest.mark.parametrize("spec", ["/definitely/not/here", "/", "~/", "relative-missing", "/tmp", "/var/tmp"])
def test_bad_dir_option_aborts_before_any_network(h, spec):
    client = FakeClient()
    with pytest.raises(Abort, match="--dir"):
        h.add(client=client, extra=["--dir", spec])
    assert client.calls == []


# -- failure paths leave nothing behind --------------------------------------------------


def test_digest_mismatch_aborts_and_cleans(h):
    with pytest.raises(Abort, match="sha256 mismatch"):
        h.add(client=FakeClient(release_=release(asset(sha="0" * 64))))
    h.assert_nothing_installed()


def test_size_mismatch_aborts(h):
    with pytest.raises(Abort, match="size"):
        h.add(client=FakeClient(release_=release(asset(size=5))))
    h.assert_nothing_installed()


def test_not_an_appimage_aborts(h):
    data = b"#!/bin/sh\necho pwned\n" * 5
    with pytest.raises(Abort, match="not a usable AppImage"):
        h.add(client=FakeClient(release_=release(asset(sha="", size=len(data)))), download=h.download(data))
    h.assert_nothing_installed()


def test_extraction_failure_leaves_nothing(h):
    def bad(appimage_, dest, fallback=False):
        raise appimage.UnsupportedImage("DwarFS AppImages are not supported (only SquashFS)")

    with pytest.raises(Abort, match="DwarFS"):
        h.add(extract=bad)
    h.assert_nothing_installed()


def test_declined_downloads_nothing(h):
    with pytest.raises(Abort, match="cancelled"):
        h.add(answers=("n",))
    assert h.downloads == []
    assert not store.staging_root().exists()


def test_empty_answer_means_no(h):
    with pytest.raises(Abort):
        h.add(answers=("",))
    assert h.downloads == []


def test_existing_name_refused_before_network(h):
    h.add()
    client = FakeClient()
    with pytest.raises(Abort, match="already added"):
        h.add(client=client)
    assert client.calls == []


# -- choosing and warnings ---------------------------------------------------------------


def test_choose_between_candidates(h):
    a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
    h.add(client=FakeClient(release_=release(a, b)), answers=("2", "y"))
    assert h.downloads[0][0] == b.url


def test_invalid_choice_aborts(h):
    a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
    with pytest.raises(Abort, match="invalid choice"):
        h.add(client=FakeClient(release_=release(a, b)), answers=("9",))
    assert h.downloads == []


def test_no_candidates(h):
    other = github.Asset("App.tar.gz", 1, "", "https://github.com/o/App/releases/download/v1.0/App.tar.gz")
    with pytest.raises(Abort, match="no x86_64 AppImage"):
        h.add(client=FakeClient(release_=release(other)))


def test_renamed_repo_requires_confirmation_and_pins_canonical_name(h):
    renamed = info(full_name="new/App", renamed=True)
    console = h.add(client=FakeClient(info_=renamed), answers=("y", "y"))
    assert manifest.load(store.manifest_path("app")).source == "github:new/App"
    assert "renamed or transferred" in console.text
    with pytest.raises(Abort, match="cancelled"):
        h.add(client=FakeClient(info_=renamed), answers=("n",), extra=["--name", "other"])
    assert not store.manifest_path("other").exists()


def test_review_warnings(h):
    client = FakeClient(info_=info(fork=True, parent="up/App", archived=True, stars=1,
                                   owner_created_at="2026-10-01T00:00:00Z"))
    console = h.add(client=client)
    for text in ("fork of up/App", "archived", "very few stars", "16 days old"):
        assert text in console.text


def test_missing_unsquashfs_needs_consent_for_runtime_fallback(h):
    with pytest.raises(Abort, match="squashfs-tools"):
        h.add(answers=("n",), extract_ok=lambda: False)
    assert h.downloads == []  # asked before downloading anything
    console = h.add(answers=("y", "y"), extract_ok=lambda: False)  # fallback consent, then download
    assert h.extractions[-1][2] is True
    assert "unsquashfs is not installed" in console.text


# -- console and naming ------------------------------------------------------------------


def test_terminal_escapes_in_api_text_are_neutralised():
    out = []
    console = cli.Console()
    with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(a))):
        console.out("evil \x1b]0;pwn\x07 text")
        console.warn("a\x1b[2Jb")
    assert out == ["evil  text", "WARNING: ab"]


@pytest.mark.parametrize("repo,name", [("My_App.v2", "my_app.v2"), ("App Name!", "app-name-"), ("___", "")])
def test_default_names(repo, name):
    assert cmd_add.default_name(repo) == name


def test_main_rejects_bad_source(h):
    console = Script()
    assert cli.main(["add", "https://github.com/o/r"], client=FakeClient(), console=console) == 1
    assert "owner/repo" in console.text


def test_files_from_args_makes_absolute_paths_and_keeps_the_mode(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert cli.files_from_args(["a.txt", "a.txt:rw", "a.txt:ro"], cwd=tmp_path) == (
        str(tmp_path / "a.txt"), f"{tmp_path / 'a.txt'}:rw", str(tmp_path / "a.txt"))


@pytest.mark.parametrize("spec", ["missing.txt", "."])
def test_files_from_args_rejects_non_files(tmp_path, spec):
    with pytest.raises(cli.Abort, match="not a regular file"):
        cli.files_from_args([spec], cwd=tmp_path)
