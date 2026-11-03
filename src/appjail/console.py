# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Terminal I/O shared by the commands."""

import json
import os
import sys

from . import textsafe


class Abort(Exception):
    """The user declined, or the operation cannot continue; message is shown as is."""


INDENTED_LABEL = 13  # label width of the indented blocks of update and desktop (two spaces, then up to 11)


def color_enabled(stream):
    """Colour only on a terminal, and never when NO_COLOR is set or the terminal is dumb."""
    return (stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM", "") != "dumb")


def bullet():
    """The list marker: a bullet where the terminal can show it, `-` otherwise."""
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "•" if enc.startswith("utf") and os.environ.get("TERM", "") != "dumb" else "-"


def arrow():
    return "→" if bullet() == "•" else "->"


def error_text(line):
    """`error: ` before a message, except for a plain cancellation, which is not an error."""
    line = textsafe.clean(line)
    return line if line.startswith("cancelled") else "error: " + line


class Console:
    """Terminal I/O. Every line goes through textsafe, so callers cannot leak escapes.

    Layout helpers (kv, item, note) are built on out(), so a console that replaces out() keeps working. Colour is
    added after cleaning, only for the fixed prefixes, never for text that came from outside.
    """

    def out(self, line=""):
        print(textsafe.clean(line))

    def kv(self, label, value, width=11):
        """`Label      value`, the label padded to width."""
        self.out(f"{label:<{width}} {value}")

    def item(self, text, indent=2):
        """A bullet line."""
        self.out(f"{' ' * indent}{bullet()} {text}")

    def table(self, headers, rows, max_width=40):
        """Rows aligned under their headers. Cells are cleaned and cut to max_width; a column with no content is dropped."""
        rows = [[textsafe.clean(c, max_width) for c in row] for row in rows]
        keep = [i for i, h in enumerate(headers) if h and any(r[i] for r in rows)]
        widths = {i: max(len(headers[i]), *(len(r[i]) for r in rows)) for i in keep}
        for line in [list(headers), *rows]:
            self.out("  ".join(line[i].ljust(widths[i]) for i in keep).rstrip())

    def json(self, data):
        """One JSON document on stdout. ASCII only (non-ASCII is escaped), so no terminal control can pass through."""
        self.out(json.dumps(data, ensure_ascii=True))

    def note(self, line):
        self.out("note: " + line)

    def warn(self, line):
        prefix = "! warning:"
        if color_enabled(sys.stdout):
            prefix = f"\x1b[33m{prefix}\x1b[0m"
        print(f"{prefix} {textsafe.clean(line)}")

    def error(self, line):
        """Errors go to stderr, so a pipe or a script sees only the results."""
        text = error_text(line)
        if text.startswith("error: ") and color_enabled(sys.stderr):
            text = "\x1b[31merror:\x1b[0m" + text[len("error:"):]
        print(text, file=sys.stderr)

    def ask(self, prompt):
        try:
            return input(prompt).strip()
        except EOFError:
            raise Abort("no input available") from None

    def confirm(self, prompt, default=False):
        answer = self.ask(f"{prompt} [{'Y/n' if default else 'y/N'}] ").lower()
        return default if not answer else answer in ("y", "yes")

    def choose(self, prompt, options):
        for i, o in enumerate(options, 1):
            self.out(f"  {i}. {o}")
        answer = self.ask(f"{prompt} [1-{len(options)}, empty to cancel] ")
        if not answer:
            raise Abort("cancelled")
        if not answer.isdigit() or not 1 <= int(answer) <= len(options):
            raise Abort("invalid choice")
        return int(answer) - 1


def human_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
