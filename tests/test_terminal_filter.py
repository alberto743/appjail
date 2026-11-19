# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What reaches the terminal from an app: cleaned unless the app has `raw_terminal` (termfilter.py, runner._run_app)."""

import os
import pty
import select
import sys
import time

import pytest

from appjail import cli, runner, runtimejail, termfilter
from appjail.manifest import Permissions

OSC52 = "\x1b]52;c;ZXZpbA==\x07"
APP = ("import sys\n"
       f"sys.stdout.write('hello\\n' + {OSC52!r} + 'clip\\n')\n"
       "sys.stdout.write('\\x1b]0;title\\x07\\x1b[2J\\x1b[c\\x1b[6nrewritten\\n')\n"
       "sys.stdout.write('a\\tb  c\\r\\nline\\r')\n"
       "sys.stderr.write('oops\\n')\n"
       "sys.stdout.flush()\n")


class Tty:
    """A pseudo-terminal: the slave side is a text stream that reports isatty(); the master is read by the test."""

    def __init__(self):
        self.master, slave = pty.openpty()
        self.stream = os.fdopen(slave, "w", buffering=1, encoding="utf-8", errors="replace")

    def text(self, wait=0.3):
        out = b""
        while select.select([self.master], [], [], wait)[0]:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            out += data
        return out.decode("utf-8", "replace").replace("\r\n", "\n")

    def close(self):
        self.stream.close()
        os.close(self.master)


@pytest.fixture
def tty():
    t = Tty()
    yield t
    t.close()


def run(code, terminal):
    return runner._run_app([sys.executable, "-c", code], terminal=terminal)


# -- when the output is cleaned --------------------------------------------------------


def test_nothing_is_done_for_redirected_output(tmp_path):
    with open(tmp_path / "out", "w") as f:
        assert termfilter.plan(False, sys.stdin, f, f) is None


def test_nothing_is_done_when_the_app_has_the_terminal():
    t = Tty()
    try:
        assert termfilter.plan(True, t.stream, t.stream, t.stream) is None
    finally:
        t.close()


def test_a_terminal_on_either_output_starts_the_filter(tty, tmp_path):
    with open(tmp_path / "f", "w") as f:
        assert termfilter.plan(False, f, tty.stream, f).pipes == {"stdout": True, "stderr": False}
        assert termfilter.plan(False, f, f, tty.stream).pipes == {"stdout": False, "stderr": True}


def test_one_terminal_for_both_outputs_uses_one_pipe(tty):
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    assert terminal.merged and terminal.popen_kwargs()["stderr"] == termfilter.subprocess.STDOUT
    assert terminal.popen_kwargs()["stdin"] == termfilter.subprocess.DEVNULL


def test_input_that_is_not_a_terminal_is_left_alone(tty, tmp_path):
    with open(tmp_path / "in", "w") as f:
        assert "stdin" not in termfilter.plan(False, f, tty.stream, tty.stream).popen_kwargs()


# -- what is written -------------------------------------------------------------------


def test_control_sequences_do_not_reach_the_terminal(tty):
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    assert run(APP, terminal) == 0
    shown = tty.text()
    assert "\x1b" not in shown and "\x07" not in shown
    for word in ("hello", "clip", "rewritten", "oops", "line"):
        assert word in shown
    assert "a\tb  c\n" in shown, "tabs and spaces are kept, and a carriage return ends the line"
    assert terminal.saw_escape


def test_the_filter_closes_the_apps_input_and_the_terminal_never_sees_a_query(tty):
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    code = "import sys\nsys.stdout.write('\\x1b[c\\x1b[6n'); sys.stdout.flush()\nprint(repr(sys.stdin.read()))"
    assert run(code, terminal) == 0
    assert tty.text().strip() == "''"


def test_the_exit_status_and_a_run_without_escapes_pass_through(tty):
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    assert run("import sys\nprint('plain')\nsys.exit(7)", terminal) == 7
    assert tty.text().strip() == "plain" and not terminal.saw_escape


def test_a_sequence_cut_in_two_by_the_line_limit_leaves_no_escape(tty, monkeypatch):
    monkeypatch.setattr(termfilter, "MAX_LINE", 10)
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    assert run("import sys\nsys.stdout.write('aaaaaaaa\\x1b[31mred\\x1b]52;c;QUJD\\x07tail')", terminal) == 0
    shown = tty.text()
    assert "\x1b" not in shown and "\x07" not in shown and "aaaaaaaa" in shown


def test_a_line_without_a_newline_is_written_in_pieces_not_kept_whole(tty, monkeypatch):
    monkeypatch.setattr(termfilter, "MAX_LINE", 1000)
    written = []
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    terminal.sinks = {"stdout": type("S", (), {"write": lambda self, s: written.append(len(s)), "flush": lambda self: None})(),
                      "stderr": None}
    assert run("import sys\nsys.stdout.write('x' * 200000)", terminal) == 0
    assert max(written) <= 1001 and sum(written) >= 200000


def test_multibyte_characters_split_between_reads_survive(tty, monkeypatch):
    monkeypatch.setattr(termfilter, "CHUNK", 1)
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)
    assert run("import sys\nsys.stdout.buffer.write('café ✓\\n'.encode())", terminal) == 0
    assert "café ✓" in tty.text()


def test_the_terminal_going_away_does_not_block_the_app(tty):
    terminal = termfilter.plan(False, tty.stream, tty.stream, tty.stream)

    class Gone:
        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

    terminal.sinks = {"stdout": Gone(), "stderr": Gone()}
    start = time.time()
    assert run("print('x' * 100000)\nprint('done')", terminal) == 0
    assert time.time() - start < 10


# -- the command line, the manifest and the environment ------------------------------------


def test_run_has_a_raw_option_that_is_off_by_default():
    parse = cli.build_parser().parse_args
    assert parse(["run", "app"]).raw is False and parse(["run", "app", "--raw"]).raw is True


@pytest.mark.parametrize("host, expected", [
    ({"TERM": "xterm-256color"}, "xterm-256color"), ({"TERM": "foot"}, "foot"), ({"TERM": "a b"}, None),
    ({"TERM": "x\x1b]52;c;AA==\x07"}, None), ({"TERM": ""}, None), ({}, None), ({"TERM": "-x"}, None)])
def test_term_is_passed_only_when_it_looks_like_a_terminal_name(host, expected):
    assert runtimejail._terminal_env(host, exists=lambda d: True).get("TERM") == expected


def test_terminfo_dirs_are_the_existing_ones_of_the_host_usr():
    assert runtimejail._terminal_env({}, exists=lambda d: d == "/usr/share/terminfo") == {"TERMINFO_DIRS": "/usr/share/terminfo"}
    assert runtimejail._terminal_env({}, exists=lambda d: False) == {}


def environment(tmp_path, perms, user_env=(), host_env=None):
    args = runtimejail.runtime_args(root=tmp_path, home=tmp_path, etc_dir=tmp_path, perms=perms, uid=1000, command=["/x"],
                                    host_env=host_env or {"TERM": "xterm-256color"}, user_env=user_env)
    return {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}


def test_the_app_gets_term_only_with_raw_terminal(tmp_path):
    assert "TERM" not in environment(tmp_path, Permissions(display="none"))
    assert environment(tmp_path, Permissions(display="none", raw_terminal=True))["TERM"] == "xterm-256color"


def test_the_apps_own_term_wins(tmp_path):
    env = environment(tmp_path, Permissions(display="none", raw_terminal=True), user_env=(("TERM", "linux"),))
    assert env["TERM"] == "linux"
