# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail open`: what the menu entry runs; every file is bound alone, read-only unless asked."""

import pytest

from appjail import cli, cmd_open, desktop, grants, runner

from .helpers import Script


@pytest.fixture
def launched(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    calls = []
    monkeypatch.setattr(runner, "launch", lambda name, args, **kw: calls.append((name, list(args), kw)) or 0)
    notes = []
    monkeypatch.setattr(cmd_open, "notify", notes.append)
    return calls, notes


def open_(argv, console=None):
    return cli.main(argv, console=console or Script())


def test_files_are_bound_read_only_by_default(h, launched, tmp_path):
    h.add()
    calls, _ = launched
    f = tmp_path / "doc.txt"
    f.write_text("x")
    assert open_(["open", "app", "--", str(f)]) == 0
    assert calls == [("app", [], {"say": calls[0][2]["say"], "extra_files": (f"{f}:ro",)})]


def test_rw_is_explicit(h, launched, tmp_path):
    h.add()
    f = tmp_path / "doc.txt"
    f.write_text("x")
    open_(["open", "app", "--rw", "--", str(f)])
    assert launched[0][0][2]["extra_files"] == (f"{f}:rw",)


def test_a_file_named_like_a_mode_suffix_keeps_the_requested_mode(h, launched, tmp_path):
    h.add()
    f = tmp_path / "evil:rw"
    f.write_text("x")
    open_(["open", "app", "--", str(f)])
    spec = launched[0][0][2]["extra_files"][0]
    assert spec == f"{f}:ro" and grants.split_file_mode(spec) == (str(f), "")


def test_a_dash_leading_name_after_the_separator_is_a_file(h, launched, tmp_path, monkeypatch):
    h.add()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-x").write_text("x")
    open_(["open", "app", "--", "-x"])
    assert launched[0][0][2]["extra_files"] == (f"{tmp_path}/-x:ro",)


def test_several_files_and_no_files(h, launched, tmp_path):
    h.add()
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("1")
    b.write_text("2")
    open_(["open", "app", "--", str(a), str(b)])
    assert launched[0][0][2]["extra_files"] == (f"{a}:ro", f"{b}:ro")
    open_(["open", "app", "--"])  # a launch from the menu without a file is a plain start
    assert launched[0][1][2]["extra_files"] == ()


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "https://example.org/x", "/nonexistent/file"])
def test_urls_and_missing_files_are_refused_and_notified(h, launched, bad):
    h.add()
    calls, notes = launched
    assert open_(["open", "app", "--", bad]) == 1
    assert calls == [] and len(notes) == 1


def test_directories_are_refused(h, launched, tmp_path):
    h.add()
    assert open_(["open", "app", "--", str(tmp_path)]) == 1 and launched[0] == []


def test_unknown_app(h, launched):
    assert open_(["open", "ghost"]) == 1
    assert "unknown app" in launched[1][0]


def test_a_removed_app_deletes_its_dangling_entry(h, launched, tmp_path):
    path = desktop.entry_path("gone")
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Gone\nX-Appjail-App=gone\n")
    console = Script()
    assert open_(["open", "gone", "--", "x"], console) == 1
    assert not path.exists() and "was removed" in console.text
