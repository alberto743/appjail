# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A stand-in for a screen reader, on the host's accessibility bus (guest only; needs gir1.2-atspi-2.0).

Usage: at.py tree NAME       the applications on the bus, and the accessible tree of those whose name contains NAME
       at.py events SECONDS  listens to object events and prints the kinds received
       at.py keys SECONDS    registers a keystroke listener and prints the key events it receives
"""

import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib


def dump(node, depth=0):
    if depth > 5:
        return
    print("  " * depth + f"{node.get_role_name()}: {node.get_name()!r}")
    for i in range(node.get_child_count()):
        if child := node.get_child_at_index(i):
            dump(child, depth + 1)


def tree(name):
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    apps = [desktop.get_child_at_index(i) for i in range(desktop.get_child_count())]
    print("apps:", [a.get_name() for a in apps if a])
    for app in apps:
        if app and name in (app.get_name() or ""):
            dump(app)


def listen(kind, seconds):
    got = []
    if kind == "events":
        listener = Atspi.EventListener.new(lambda event, *_: got.append(event.type))
        listener.register("object:state-changed")
        listener.register("object:property-change")
    else:
        listener = Atspi.DeviceListener.new(lambda event, *_: got.append((event.id, event.event_string)) or False, None)
        Atspi.register_keystroke_listener(listener, None, 0, 3, Atspi.KeyListenerSyncType.NOSYNC)

    def done():
        print(f"{kind} received:", sorted(set(map(str, got))) if kind == "events" else got, flush=True)
        sys.exit(0)
    GLib.timeout_add_seconds(seconds, done)
    GLib.MainLoop().run()


if __name__ == "__main__":
    if sys.argv[1] == "tree":
        tree(sys.argv[2])
    else:
        listen(sys.argv[1], int(sys.argv[2]))
