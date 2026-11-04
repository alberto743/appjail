# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path

import pytest

from appjail import (
    appimage,
    manifest,
    runner,
    store,
)
from appjail.errors import RunError

from .helpers import (
    NO_RESTRICTION,
    Extractor,
    install,
    pairs,
)

SHA = "a" * 64


# -- prepare: pin verification and re-extraction -----------------------------------------


def test_unknown_app(sandbox):
    with pytest.raises(RunError, match="unknown app"):
        runner.prepare("ghost")


def test_tampered_appimage_refused_before_anything_runs(sandbox):
    install(sandbox, sha="b" * 64)
    ex = Extractor()
    with pytest.raises(RunError, match="does not match the pinned sha256"):
        runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 0 and not store.root_path("app").exists()


def test_extracts_once_then_reuses_the_tree(sandbox):
    digest = install(sandbox)
    ex = Extractor()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 1
    assert store.root_marker("app").read_text().strip() == digest


def test_stale_or_missing_marker_forces_reextraction(sandbox):
    install(sandbox)
    ex = Extractor()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    store.root_marker("app").write_text("0" * 64 + "\n")
    runner.prepare("app", extract=ex, say=lambda *_: None)
    store.root_marker("app").unlink()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 3


def test_modified_tree_is_extracted_again(sandbox):
    install(sandbox)
    ex, said = Extractor(), []
    runner.prepare("app", extract=ex, say=said.append)
    (store.root_path("app") / "usr" / "evil").write_text("x")
    runner.prepare("app", extract=ex, say=said.append)
    assert ex.calls == 2 and not (store.root_path("app") / "usr" / "evil").exists()
    assert any("modified" in m and m.startswith("! warning: ") for m in said)
    warned = []
    (store.root_path("app") / "usr" / "evil").write_text("x")
    runner.prepare("app", extract=ex, say=lambda *_: None, warn=warned.append)  # the console's warn gets the bare text
    assert len(warned) == 1 and warned[0].startswith("the extracted tree")


def test_tree_digest_sees_content_mode_and_links(tmp_path):
    (tmp_path / "f").write_text("a")
    (tmp_path / "l").symlink_to("f")
    base = appimage.tree_digest(tmp_path)
    assert appimage.tree_digest(tmp_path) == base
    (tmp_path / "f").write_text("b")
    changed = appimage.tree_digest(tmp_path)
    assert changed != base
    os.chmod(tmp_path / "f", 0o755)
    assert appimage.tree_digest(tmp_path) != changed
    mode = appimage.tree_digest(tmp_path)
    (tmp_path / "l").unlink()
    (tmp_path / "l").symlink_to("/etc/passwd")
    assert appimage.tree_digest(tmp_path) != mode


def test_extraction_error_becomes_run_error(sandbox):
    install(sandbox)

    def bad(image, dest, fallback=False):
        raise appimage.ExtractError("boom")

    with pytest.raises(RunError, match="cannot extract app: boom"):
        runner.prepare("app", extract=bad, say=lambda *_: None)


def test_passwd_and_private_home_created(sandbox):
    install(sandbox)
    _, _, home, etc = runner.prepare("app", extract=Extractor(), say=lambda *_: None)
    assert f"app:x:{os.getuid()}:" in (etc / "passwd").read_text()
    assert home.stat().st_mode & 0o777 == 0o700


def test_launch_merges_temporary_directories_without_touching_the_manifest(sandbox, runtime, monkeypatch):
    install(sandbox)
    fake_home = sandbox / "fakehome"
    granted = fake_home / "granted"
    granted.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    captured = []
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    said = []
    code = runner.launch("app", ["--x"], host_env=env, extract=Extractor(), say=said.append,
                         runner=lambda argv: captured.append(argv) or 0, extra_dirs=("~/granted:rw",),
                         restricted=NO_RESTRICTION)
    assert code == 0
    assert any("wp_security_context_v1" in m for m in said)
    argv = captured[0]
    assert (str(granted), "/home/app/granted") in pairs(argv, "--bind")
    assert argv[-2:] == ["/app/AppRun", "--x"]
    assert any("Temporary access" in line for line in said)
    assert manifest.load(store.manifest_path("app")).permissions.dirs == ()
