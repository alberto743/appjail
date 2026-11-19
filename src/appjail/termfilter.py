# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Keep what an app prints from acting on your terminal (docs/understand/acquisition/untrusted-text.md).

A terminal obeys control sequences: some set the clipboard or the window title, rewrite the screen, or make the
terminal type a reply into your input. An app that shares your terminal can send them. Unless it has `raw_terminal`,
and when its output goes to a terminal, the app gets no input and its output goes through a pipe: a thread reads it in
fixed-size pieces, removes every control sequence and control character, and writes the lines to your terminal.
Redirected output, and apps started from a menu or the window (not terminals), are left alone.
"""

import codecs
import os
import subprocess
import threading

from . import textsafe

CHUNK = 65536  # what one read takes
MAX_LINE = 65536  # a line without a newline is written out at this length, so memory stays bounded
JOIN_SECONDS = 3  # how long to wait for the pumps to drain once the app is gone

HINT = ("the app's terminal output was cleaned of control sequences; `appjail perms NAME --allow raw_terminal` "
        "(or `appjail run --raw NAME` for one run) gives it your terminal as it is")


def _is_terminal(stream):
    try:
        return stream is not None and stream.isatty()
    except (ValueError, OSError):  # a closed stream
        return False


def _same_terminal(a, b):
    try:
        return os.fstat(a.fileno()).st_rdev == os.fstat(b.fileno()).st_rdev
    except (ValueError, OSError, AttributeError):
        return False


def plan(raw, stdin, stdout, stderr):
    """The Terminal that cleans an app's output, or None when the app keeps the real streams.

    raw: the app may have your terminal as it is (`raw_terminal` or `run --raw`).
    """
    if raw or not (_is_terminal(stdout) or _is_terminal(stderr)):
        return None
    return Terminal(stdin, stdout, stderr)


class Terminal:
    """The streams of one app run and the threads that clean its output."""

    def __init__(self, stdin, stdout, stderr):
        out, err = _is_terminal(stdout), _is_terminal(stderr)
        self.merged = out and err and _same_terminal(stdout, stderr)  # one pipe keeps the order of what both print
        self.pipes = {"stdout": out, "stderr": err and not self.merged}
        self.sinks = {"stdout": stdout, "stderr": stderr}
        self.input_closed = _is_terminal(stdin)
        self.saw_escape = False
        self._threads = []
        self._read_ends = []

    def popen_kwargs(self):
        """The stdin, stdout and stderr arguments for subprocess.Popen."""
        kw = {}
        if self.input_closed:
            kw["stdin"] = subprocess.DEVNULL  # a terminal's replies to the app's questions would arrive as its input
        if self.pipes["stdout"]:
            kw["stdout"] = subprocess.PIPE
        if self.merged:
            kw["stderr"] = subprocess.STDOUT
        elif self.pipes["stderr"]:
            kw["stderr"] = subprocess.PIPE
        return kw

    def start(self, proc):
        """Begin cleaning the pipes of the started process."""
        for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            if pipe is not None:
                t = threading.Thread(target=self._pump, args=(pipe, self.sinks[name]), daemon=True)
                t.start()
                self._threads.append(t)
                self._read_ends.append(pipe)

    def finish(self):
        """Wait (a little) for what is left in the pipes to be written, then close them."""
        for t in self._threads:
            t.join(JOIN_SECONDS)
        for pipe in self._read_ends:
            pipe.close()

    def _pump(self, pipe, sink):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text = ""
        fd = pipe.fileno()
        while True:
            try:
                data = os.read(fd, CHUNK)
            except OSError:
                break
            if not data:
                break
            text += decoder.decode(data)
            if text.endswith("\r"):  # may be the first half of \r\n
                held, text = "\r", text[:-1]
            else:
                held = ""
            *lines, text = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            for line in lines:
                self._write(sink, line, "\n")
            while len(text) > MAX_LINE:
                self._write(sink, text[:MAX_LINE], "")
                text = text[MAX_LINE:]
            text += held
        text += decoder.decode(b"", final=True)
        if text:
            self._write(sink, text, "\n")

    def _write(self, sink, line, end):
        if textsafe.has_escape(line):
            self.saw_escape = True
        try:
            sink.write(textsafe.clean_output(line) + end)
            sink.flush()
        except (OSError, ValueError):  # the terminal went away: keep reading so the app is never blocked on a full pipe
            pass
