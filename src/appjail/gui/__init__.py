# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Optional tkinter front end (`appjail-gui`). Every action runs the same CLI command the terminal would."""

import sys


def main():
    try:
        import tkinter  # a system package on Debian and Ubuntu
    except ImportError:
        print("appjail-gui needs tkinter: install the system package python3-tk", file=sys.stderr)
        return 1
    from .app import main as run

    try:
        return run()
    except tkinter.TclError as e:  # no display
        print(f"appjail-gui: {e}", file=sys.stderr)
        return 1
