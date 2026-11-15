# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Test client that runs INSIDE the app jail as AppRun: the Camera portal end to end.

Asks the portal whether there is a camera, opens the PipeWire remote it limits to camera nodes, and has GStreamer write one
frame from it as a PNG. Reports what happened as JSON.
"""

import json
import os
import struct
import subprocess

import dbus
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
props = dbus.Interface(portal, "org.freedesktop.DBus.Properties")
camera = dbus.Interface(portal, "org.freedesktop.portal.Camera")
out = {"present": bool(props.Get("org.freedesktop.portal.Camera", "IsCameraPresent"))}
try:
    camera.AccessCamera({"handle_token": "appjailtest"})  # the stored decision answers, no dialog
    fd = camera.OpenPipeWireRemote({}).take()
except dbus.DBusException as e:
    out["error"] = str(e)[:200]
else:
    png = "/home/app/frame.png"
    done = subprocess.run(["/usr/bin/gst-launch-1.0", "-q", "pipewiresrc", f"fd={fd}", "num-buffers=5", "!", "videoconvert", "!",
                           "pngenc", "snapshot=true", "!", "filesink", f"location={png}"],
                          pass_fds=(fd,), capture_output=True, text=True, timeout=40)
    out["gst"] = done.returncode
    if os.path.exists(png):
        with open(png, "rb") as f:
            data = f.read()
        out["png"] = len(data)
        out["size"] = struct.unpack(">II", data[16:24]) if data[:4] == b"\x89PNG" else None
    else:
        out["stderr"] = done.stderr[-300:]
print(json.dumps(out))
