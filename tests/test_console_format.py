# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The layout helpers of Console and the permission formatters."""

import pytest

from appjail import console as console_mod
from appjail import manifest
from appjail.permargs import permission_changes, permission_lines


@pytest.fixture
def con(capsys):
    return console_mod.Console(), capsys


def test_kv_pads_the_label(con):
    c, cap = con
    c.kv("Size", "1 KiB")
    assert cap.readouterr().out == "Size        1 KiB\n"


def test_table_aligns_cleans_and_drops_empty_columns(con):
    c, cap = con
    c.table(("NAME", "TIER", "CHANNEL"), [("a", "3", ""), ("long-name\x1b[2J", "4", "")])
    assert cap.readouterr().out.splitlines() == ["NAME       TIER", "a          3", "long-name  4"]


def test_table_cuts_long_cells(con):
    c, cap = con
    c.table(("X",), [("y" * 100,)], max_width=10)
    assert cap.readouterr().out.splitlines()[1] == "y" * 9 + "…"


def test_warn_is_prefixed_and_cleaned(con):
    c, cap = con
    c.warn("a\x1b[2Jb")
    assert cap.readouterr().out == "! warning: ab\n"


def test_error_goes_to_stderr_and_cancelled_is_not_an_error(con):
    c, cap = con
    c.error("unknown app 'x'")
    c.error("cancelled")
    out = cap.readouterr()
    assert out.out == "" and out.err == "error: unknown app 'x'\ncancelled\n"


def test_colour_only_on_a_terminal_without_no_color(monkeypatch):
    class Tty:
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert console_mod.color_enabled(Tty())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not console_mod.color_enabled(Tty())
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert not console_mod.color_enabled(Tty())


def test_permission_lines_and_changes():
    old = manifest.Permissions(audio=True, dirs=("~/Music",))
    new = manifest.Permissions(audio=True, network=True, dirs=("~/Docs",), display="xwayland")
    assert permission_lines(old) == [("grants", "audio"), ("display", "wayland"), ("dirs", "~/Music")]
    arrow = console_mod.ARROW
    assert permission_changes(old, new) == [("network", f"no {arrow} yes"), ("display", f"wayland {arrow} xwayland"),
                                             ("dirs", "+ ~/Docs"), ("dirs", "- ~/Music")]


def test_json_is_one_ascii_line(con):
    c, cap = con
    c.json({"a": "x\x1b[2Jé", "b": [1, None]})
    out = cap.readouterr().out
    assert out.count("\n") == 1 and out.isascii() and "\x1b" not in out
    import json
    assert json.loads(out) == {"a": "x\x1b[2Jé", "b": [1, None]}


def test_note_and_item(con):
    c, cap = con
    c.note("x")
    c.item("y")
    assert cap.readouterr().out.splitlines() == ["note: x", f"  {console_mod.BULLET} y"]


class FakeTty:
    def isatty(self):
        return True


def test_wrapped_only_on_a_terminal_and_never_inside_a_word(monkeypatch, capsys):
    monkeypatch.setattr(console_mod.shutil, "get_terminal_size", lambda: type("S", (), {"columns": 40})())
    text = "word " * 30 + "https://example.org/" + "x" * 80
    assert console_mod.wrapped(text, hang=4, stream=object.__new__(type("P", (), {"isatty": lambda s: False}))) == [text]
    lines = console_mod.wrapped(text, hang=4, stream=FakeTty())
    assert len(lines) > 3 and all(line.startswith("    ") for line in lines[1:])
    assert all(len(line) <= 59 for line in lines if "xxxx" not in line)  # the 60-column floor
    assert any("https://example.org/" + "x" * 80 in line for line in lines)  # a long word stays whole
    assert " ".join(l.strip() for l in lines).split() == text.split()
