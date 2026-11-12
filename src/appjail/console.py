# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Terminal I/O shared by the commands."""

import json
import os
import shutil
import sys
import textwrap

from . import textsafe


class Abort(Exception):
    """The user declined, or the operation cannot continue; message is shown as is."""


INDENTED_LABEL = 13  # label width of the indented blocks of update and desktop (two spaces, then up to 11)


def color_enabled(stream):
    """Colour only on a terminal, and never when NO_COLOR is set or the terminal is dumb."""
    return (stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM", "") != "dumb")


BULLET = "•"
ARROW = "→"
ARROW_NB = ARROW + "\u00a0"  # arrow glued to the value after it: wrapping never leaves it alone at a line end


def wrapped(text, hang=0, stream=None):
    """text as lines that fit a terminal, continuation lines indented by hang. Only on a terminal: a pipe or a log
    keeps one line per message. Words are never cut (a long URL or path stays whole)."""
    stream = stream or sys.stdout
    if not stream.isatty():
        return [text]
    width = max(60, shutil.get_terminal_size().columns - 1)
    body = text.lstrip(" ")  # the indent is passed on its own: textwrap drops it when the first word alone is too long
    return textwrap.wrap(body, width, initial_indent=text[:len(text) - len(body)], subsequent_indent=" " * hang,
                         break_long_words=False, break_on_hyphens=False) or [text]


def error_text(line):
    """`error: ` before a message, except for a plain cancellation, which is not an error."""
    line = textsafe.clean(line)
    return line if line.startswith("cancelled") else "error: " + line


class Console:
    """Terminal I/O. Every line goes through textsafe, so callers cannot leak escapes.

    Layout helpers (kv, item, note) are built on out(), so a console that replaces out() keeps working. Colour is
    added after cleaning, only for the fixed prefixes, never for text that came from outside.
    """

    def out(self, line="", max_len=2000):
        print(textsafe.clean(line, max_len))

    def kv(self, label, value, width=11):
        """`Label      value`, the label padded to width; a long value wraps under itself."""
        for line in wrapped(textsafe.clean(f"{label:<{width}} {value}"), hang=width + 1):
            self.out(line)

    def item(self, text, indent=2):
        """A bullet line."""
        for line in wrapped(textsafe.clean(f"{' ' * indent}{BULLET} {text}"), hang=indent + 2):
            self.out(line)

    def table(self, headers, rows, max_width=40):
        """Rows aligned under their headers. Cells are cleaned and cut to max_width; a column with no content is dropped."""
        rows = [[textsafe.clean(c, max_width) for c in row] for row in rows]
        keep = [i for i, h in enumerate(headers) if h and any(r[i] for r in rows)]
        widths = {i: max([len(headers[i]), *(len(r[i]) for r in rows)]) for i in keep}
        for line in [list(headers), *rows]:
            self.out("  ".join(line[i].ljust(widths[i]) for i in keep).rstrip())

    def json(self, data):
        """One JSON document on stdout. ASCII only (non-ASCII is escaped), so no terminal control can pass through; never
        cut, since a cut document is no longer JSON."""
        self.out(json.dumps(data, ensure_ascii=True), max_len=None)

    def note(self, line):
        for text in wrapped(textsafe.clean("note: " + line), hang=2):
            self.out(text)

    def warn(self, line):
        prefix = "! warning:"
        if color_enabled(sys.stdout):
            prefix = f"\x1b[33m{prefix}\x1b[0m"
        lines = wrapped("! warning: " + textsafe.clean(line), hang=2)
        lines[0] = lines[0].replace("! warning:", prefix, 1)
        print("\n".join(lines))

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
