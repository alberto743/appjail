# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Optional tkinter front end (`appjail-gui`). Every action runs the same CLI command the terminal would."""

import argparse
import importlib.util
import sys
from importlib import resources

from .. import desktop


def _desktop_entry(args):
    """--desktop / --remove-desktop: the menu entry (and icon) of appjail-gui itself. Needs no display."""
    try:
        if args.remove_desktop:
            print("Removed the menu entry of appjail-gui." if desktop.remove_gui() else "No menu entry of appjail-gui to remove.")
            return 0
        svg = resources.files(__package__).joinpath("appjail.svg").read_bytes()
        print(f"Menu entry : {desktop.install_gui(svg)}")
        print(f"Icon       : {desktop.gui_icon_path()}")
    except (desktop.DesktopError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if importlib.util.find_spec("tkinter") is None:
        print("note: tkinter is missing; install the system package python3-tk before using the entry", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="appjail-gui", description="Graphical front end of appjail")
    entry = parser.add_mutually_exclusive_group()
    entry.add_argument("--desktop", action="store_true", help="create or refresh the menu entry (with its icon) that starts appjail-gui, then exit")
    entry.add_argument("--remove-desktop", action="store_true", help="delete that menu entry and icon, then exit")
    args = parser.parse_args(argv)
    if args.desktop or args.remove_desktop:
        return _desktop_entry(args)
    try:
        import tkinter
    except ImportError:
        print("appjail-gui needs tkinter: install the system package python3-tk", file=sys.stderr)
        return 1
    from .app import main as run

    try:
        return run()
    except tkinter.TclError as e:  # no display
        print(f"appjail-gui: {e}", file=sys.stderr)
        return 1
