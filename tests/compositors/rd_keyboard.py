# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A keyboard for a headless Mutter or GNOME Shell, through its own D-Bus API (org.gnome.Mutter.RemoteDesktop), which any
client of the session bus may use (tests/compositors/clipboard.py). Prints `started`, then presses and releases the key `z`
for a line `key` read on stdin, and clicks the middle of the screen for a line `click`.
"""

import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

NAME, PATH = "org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop"
KEYSYM_Z = 0x7A

bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def call(path, interface, method, params=None, reply=None):
    return bus.call_sync(NAME, path, interface, method, params, reply, Gio.DBusCallFlags.NONE, 8000, None)


session = call(PATH, NAME, "CreateSession", None, GLib.VariantType("(o)")).unpack()[0]
call(session, NAME + ".Session", "Start")
print("started", flush=True)
BTN_LEFT = 0x110
for line in sys.stdin:
    if line.startswith("click"):  # a new window is not focused by itself: put the pointer in the middle of the screen and click
        for dx, dy in ((-5000.0, -5000.0), (512.0, 384.0)):
            call(session, NAME + ".Session", "NotifyPointerMotionRelative", GLib.Variant("(dd)", (dx, dy)))
        for pressed in (True, False):
            call(session, NAME + ".Session", "NotifyPointerButton", GLib.Variant("(ib)", (BTN_LEFT, pressed)))
            time.sleep(0.05)
        # fall through: a key right after the click, which is what hands focus to the window in Mutter
    for pressed in (True, False):
        call(session, NAME + ".Session", "NotifyKeyboardKeysym", GLib.Variant("(ub)", (KEYSYM_Z, pressed)))
        time.sleep(0.05)
