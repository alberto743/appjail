# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Fake xdg-desktop-portal FileChooser backend for tests (guest only: needs python3-dbus and python3-gi).

Usage: fake_backend.py LOGFILE CHOSEN_FILE
Owns org.freedesktop.impl.portal.desktop.fake, appends the app_id of every OpenFile call to LOGFILE
and answers with CHOSEN_FILE as the user's choice.
"""

import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

NAME = "org.freedesktop.impl.portal.desktop.fake"
PATH = "/org/freedesktop/portal/desktop"


class FileChooser(dbus.service.Object):
    def __init__(self, bus, log, chosen):
        super().__init__(bus, PATH)
        self.log, self.chosen = log, chosen

    @dbus.service.method("org.freedesktop.impl.portal.FileChooser", in_signature="osssa{sv}", out_signature="ua{sv}")
    def OpenFile(self, handle, app_id, parent_window, title, options):
        with open(self.log, "a") as f:
            f.write(f"{app_id}\n")
        return dbus.UInt32(0), {"uris": dbus.Array([f"file://{self.chosen}"], signature="s")}


HELD = []


def main(log, chosen):
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    HELD.append(dbus.service.BusName(NAME, bus))  # the name is owned while this object is alive
    FileChooser(bus, log, chosen)
    print("ready", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main(*sys.argv[1:3])
