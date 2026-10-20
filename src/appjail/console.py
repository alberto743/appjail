# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Terminal I/O shared by the commands."""

from . import textsafe


class Abort(Exception):
    """The user declined, or the operation cannot continue; message is shown as is."""


class Console:
    """Terminal I/O. Every line goes through textsafe, so callers cannot leak escapes."""

    def out(self, line=""):
        print(textsafe.clean(line))

    def warn(self, line):
        print("WARNING: " + textsafe.clean(line))

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
