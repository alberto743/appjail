#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Fail if a commit message carries a session link, a local path or a personal e-mail.

The same rule as .githooks/commit-msg, for CI: `commit_hygiene.py [REV-RANGE]`
checks every commit reachable from the range (default: HEAD).
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = ROOT / ".githooks" / "forbidden-patterns"
MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def load_patterns(path=PATTERNS):
    lines = path.read_text().splitlines()
    return [re.compile(line, re.IGNORECASE | re.MULTILINE) for line in lines if line and not line.startswith("#")]


def problems(message, patterns):
    """What is wrong with one commit message, as short strings; empty if nothing."""
    found = [m.group(0) for p in patterns for m in [p.search(message)] if m]
    found += [mail for mail in MAIL.findall(message) if "noreply" not in mail.lower()]
    return found


def main(argv):
    rev = argv[1] if len(argv) > 1 else "HEAD"
    log = subprocess.run(["git", "log", "--format=%H%x00%B%x01", rev], check=True, capture_output=True, text=True).stdout
    patterns = load_patterns()
    bad = 0
    for record in log.split("\x01"):
        sha, _, message = record.strip("\n").partition("\x00")
        if not sha:
            continue
        found = problems(message, patterns)
        if found:
            bad += 1
            print(f"{sha[:12]}: {', '.join(found)}")
    if bad:
        print(f"{bad} commit message(s) carry a session link, a local path or a personal e-mail", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
