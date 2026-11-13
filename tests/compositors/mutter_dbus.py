# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A complete capture and a complete keystroke through Mutter's own D-Bus API, made as an ordinary client of the session bus
(no portal, no prompt), on headless Mutter and GNOME Shell. *-compositors guests only:

    python3 tests/compositors/mutter_dbus.py --out /tmp/mutter-dbus.json [--only mutter,gnome-shell]

* keystroke: org.gnome.Mutter.RemoteDesktop opens a session, clicks the middle of the screen and presses keys; a GTK 4
  window of another client logs the keys it receives (`window` mode of this file).
* capture: org.gnome.Mutter.ScreenCast records the monitor; the frame is read from the PipeWire stream it announces with
  GStreamer (`pipewiresrc`), on a private PipeWire and WirePlumber in the same runtime directory, and its size and number of
  distinct colours are recorded (a GTK window with a coloured background is on the screen while it is taken).

These are the names `grants.DBUS_BLOCKED` refuses (`org.gnome.Mutter`); this shows what granting them would give.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

HERE = Path(__file__).resolve()
KEYS = "appjail"
SCREENCAST, REMOTE = "org.gnome.Mutter.ScreenCast", "org.gnome.Mutter.RemoteDesktop"


def window(out):
    """A GTK 4 window with a red background that logs `active` and `key:<name>` for every key it receives."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    def log(line):
        with open(out, "a") as f:
            f.write(line + "\n")

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app, title="victim", default_width=400, default_height=300)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: rgb(255, 0, 0); }", -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win.connect("notify::is-active", lambda w, _p: w.is_active() and log("active"))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, keyval, _code, _state: log("key:" + (Gdk.keyval_name(keyval) or "?")) or False)
        win.add_controller(keys)
        win.present()
        GLib.timeout_add_seconds(60, lambda: app.quit() or False)

    app = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", on_activate)
    return app.run([])


def attacker(mode, out):
    """The ordinary bus client: `type` or `capture`; writes a JSON line to `out`."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    def call(name, path, interface, method, params=None, reply=None):
        return bus.call_sync(name, path, interface, method, params, reply, Gio.DBusCallFlags.NONE, 8000, None)

    result = {}
    try:
        if mode == "type":
            path = "/org/gnome/Mutter/RemoteDesktop"
            session = call(REMOTE, path, REMOTE, "CreateSession", None, GLib.VariantType("(o)")).unpack()[0]
            iface = REMOTE + ".Session"
            call(REMOTE, session, iface, "Start")
            time.sleep(2.0)  # the seat takes a moment to show the new devices
            # GNOME Shell starts in the overview, which would take the click and the keys: Escape leaves it
            for pressed in (True, False):
                call(REMOTE, session, iface, "NotifyKeyboardKeysym", GLib.Variant("(ub)", (0xff1b, pressed)))
                time.sleep(0.05)
            time.sleep(1.0)
            for dx, dy in ((-5000.0, -5000.0), (512.0, 384.0)):
                call(REMOTE, session, iface, "NotifyPointerMotionRelative", GLib.Variant("(dd)", (dx, dy)))
            for pressed in (True, False):
                call(REMOTE, session, iface, "NotifyPointerButton", GLib.Variant("(ib)", (0x110, pressed)))
                time.sleep(0.05)
            # in Mutter a new window takes the focus at the first key after the click, which it does not deliver: a Shift
            for pressed in (True, False):
                call(REMOTE, session, iface, "NotifyKeyboardKeysym", GLib.Variant("(ub)", (0xffe1, pressed)))
                time.sleep(0.05)
            time.sleep(0.5)
            for char in KEYS:
                for pressed in (True, False):
                    call(REMOTE, session, iface, "NotifyKeyboardKeysym", GLib.Variant("(ub)", (ord(char), pressed)))
                    time.sleep(0.05)
            time.sleep(1.0)
            call(REMOTE, session, iface, "Stop")
            result["typed"] = KEYS
        else:
            state = call("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig",
                         "GetCurrentState").unpack()
            connector = state[1][0][0][0]
            session = call(SCREENCAST, "/org/gnome/Mutter/ScreenCast", SCREENCAST, "CreateSession",
                           GLib.Variant("(a{sv})", ({},)), GLib.VariantType("(o)")).unpack()[0]
            stream = call(SCREENCAST, session, SCREENCAST + ".Session", "RecordMonitor",
                          GLib.Variant("(sa{sv})", (connector, {})), GLib.VariantType("(o)")).unpack()[0]
            node = {}
            bus.signal_subscribe(SCREENCAST, SCREENCAST + ".Stream", "PipeWireStreamAdded", stream, None,
                                 Gio.DBusSignalFlags.NONE, lambda *a: node.setdefault("id", a[5].unpack()[0]))
            call(SCREENCAST, session, SCREENCAST + ".Session", "Start")
            loop, deadline = GLib.MainContext.default(), time.monotonic() + 10
            while "id" not in node and time.monotonic() < deadline:
                loop.iteration(False)
                time.sleep(0.05)
            result.update(connector=connector, node=node.get("id"))
            if "id" in node:
                raw = Path(out).with_suffix(".rgb")
                gst = subprocess.run(["gst-launch-1.0", "-q", "pipewiresrc", f"path={node['id']}", "num-buffers=1", "!",
                                      "videoconvert", "!", "video/x-raw,format=RGB", "!", "filesink", f"location={raw}"],
                                     capture_output=True, text=True, timeout=30)
                data = raw.read_bytes() if raw.exists() else b""
                pixels = {data[i:i + 3] for i in range(0, len(data) - 2, 3)}
                # the monitor is 1024x768 (probe.COMPOSITORS), so a whole frame is 1024 * 768 * 3 bytes
                result.update(gst_ok=gst.returncode == 0, gst_error=gst.stderr.strip()[-200:], bytes=len(data),
                              whole_frame=len(data) == 1024 * 768 * 3, colours=len(pixels), red=b"\xff\x00\x00" in pixels)
            call(SCREENCAST, session, SCREENCAST + ".Session", "Stop")
    except GLib.Error as e:
        result["error"] = e.message[:200]
    Path(out).write_text(json.dumps(result))
    return 0


def attack(session, mode):
    """Run the ordinary bus client of this file in `mode` and return its result."""
    out = session.rt / f"{mode}.json"
    out.unlink(missing_ok=True)
    probe.run(["python3", str(HERE), mode, str(out)], env=session.env(), timeout=90)
    return json.loads(out.read_text()) if out.exists() else {"error": "no result"}


def evaluate(key):
    packages, argv_for, extra = probe.COMPOSITORS[key]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    procs = []
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        try:
            env = session.env(extra)
            for daemon in (["pipewire"], ["wireplumber"]):  # the screencast's PipeWire, private to this runtime directory
                procs.append(subprocess.Popen(daemon, env=env, stdout=logfile, stderr=logfile, start_new_session=True))
            time.sleep(1.5)
            before = probe.sockets(session.rt)
            proc = subprocess.Popen(argv_for(session), env=env, stdout=logfile, stderr=logfile, start_new_session=True)
            procs.append(proc)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            result["status"] = "ok"
            wenv = session.env({"WAYLAND_DISPLAY": display, "GDK_BACKEND": "wayland"})
            log = session.rt / "victim.log"
            procs.append(subprocess.Popen(["python3", str(HERE), "window", str(log)], env=wenv, stdout=logfile, stderr=logfile,
                                          start_new_session=True))
            time.sleep(8.0)  # GNOME Shell plays its start-up animation into the overview first
            # GNOME Shell sometimes stays in the overview, which takes the click and the keys: try up to three times
            for attempt in range(1, 4):
                result["type"] = attack(session, "type")
                received = log.read_text().split() if log.exists() else []
                result["type"].update(attempts=attempt, victim_log=received,
                                      received="".join(line[4:] for line in received if len(line) == 5 and line.startswith("key:")))
                result["type"]["ok"] = KEYS in result["type"]["received"]
                if result["type"]["ok"]:
                    break
            result["capture"] = capture = attack(session, "capture")
            capture["ok"] = bool(capture.get("gst_ok") and capture.get("whole_frame") and capture.get("red"))
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            for p in reversed(procs):
                probe.stop(p)
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "window":
        return window(argv[1])
    if argv and argv[0] in ("type", "capture"):
        return attacker(argv[0], argv[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="mutter,gnome-shell")
    args = parser.parse_args(argv)
    data = {"distro": probe.distro(), "compositors": {}}
    for key in args.only.split(","):
        print(f"== {key}", flush=True)
        data["compositors"][key] = evaluate(key)
        print(json.dumps(data["compositors"][key]), flush=True)
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
