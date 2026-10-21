# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Test client that runs INSIDE the app jail as AppRun, against a real desktop backend (xdg-desktop-portal-gtk).

Only non-interactive calls: Settings (answered by the backend from GSettings) and the start of a FileChooser request
(the backend opens a dialog nobody answers; the portal still returns the request handle at once).
"""

import json

import dbus

bus = dbus.SessionBus()
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
out = {}
try:
    settings = dbus.Interface(portal, "org.freedesktop.portal.Settings")
    out["read_all"] = sorted(str(k) for k in settings.ReadAll(["org.freedesktop.appearance"]))
    out["color_scheme"] = int(settings.ReadOne("org.freedesktop.appearance", "color-scheme"))
except dbus.DBusException as e:
    out["settings_error"] = str(e)[:200]
try:
    chooser = dbus.Interface(portal, "org.freedesktop.portal.FileChooser")
    out["request"] = str(chooser.OpenFile("", "Pick", {"handle_token": "appjailreal"}))
except dbus.DBusException as e:
    out["open_error"] = str(e)[:200]
print(json.dumps(out))
