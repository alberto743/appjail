# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Test client that runs INSIDE the app jail as AppRun (uses the host's python3-dbus through /usr).

Calls FileChooser.OpenFile through the filtered bus, waits for the Response signal, reads the chosen
file through the document-portal mount, and reports what it could and could not do as JSON.
"""

import json
import os

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
out = {"flatpak_info": os.path.exists("/.flatpak-info"), "env_bus": os.environ.get("DBUS_SESSION_BUS_ADDRESS")}
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
loop = GLib.MainLoop()


def on_response(code, results):
    out["response"] = int(code)
    out["uris"] = [str(u) for u in results.get("uris", [])]
    loop.quit()


bus.add_signal_receiver(on_response, "Response", "org.freedesktop.portal.Request")
try:
    portal.OpenFile("", "Pick", {"handle_token": "appjailtest"}, dbus_interface="org.freedesktop.portal.FileChooser")
except dbus.DBusException as e:
    out["open_error"] = str(e)
else:
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()
if out.get("uris"):
    path = out["uris"][0].replace("file://", "")
    out["doc_path"] = path
    try:
        with open(path) as f:
            out["content"] = f.read()
    except OSError as e:
        out["read_error"] = str(e)

def probe(dest, path, iface, member, signature="", args=()):
    try:
        bus.call_blocking(dest, path, iface, member, signature, args, timeout=5)
        return "allowed"
    except dbus.DBusException as e:
        return e.get_dbus_name() + ": " + str(e)[:100]


DESKTOP = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
out["OpenURI"] = probe(*DESKTOP, "org.freedesktop.portal.OpenURI", "OpenURI", "ssa{sv}", ("", "https://example.org", {}))
out["Flatpak"] = probe("org.freedesktop.portal.Flatpak", "/org/freedesktop/portal/Flatpak",
                       "org.freedesktop.DBus.Properties", "GetAll", "s", ("org.freedesktop.portal.Flatpak",))
out["host_control"] = probe("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ReloadConfig")
print(json.dumps(out))
