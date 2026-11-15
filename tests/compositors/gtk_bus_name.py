# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Does GNOME Shell call a D-Bus name that a client with only a window names in `gtk_surface1.set_dbus_properties`?

    python3 tests/compositors/gtk_bus_name.py --out /tmp/gtk-bus-name.json

GNOME Shell (headless, on a private session bus) shows a bare window (focus_client.py). A second client of the same bus owns
nothing and only has a unique name, which the window gives as the `unique_bus_name` of its gtk_surface1 together with object
paths. A bus monitor then says which calls the Shell sent to that name. A control run sets nothing. Guests only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clipboard
import focus_steal
import probe

HOLDER = """
import sys
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
print(bus.get_unique_name(), flush=True)
GLib.MainLoop().run()
"""


def evaluate(set_properties):
    packages, argv_for, extra = probe.COMPOSITORS["gnome-shell"]
    result = {"version": probe.package_version(*packages), "set_dbus_properties": set_properties}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        procs = []
        try:
            before = probe.sockets(session.rt)
            proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
            procs.append(proc)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            session.display = display
            time.sleep(5.0)  # the Shell takes its bus names and settles after the socket appears
            holder = subprocess.Popen(["python3", "-c", HOLDER], env=session.env(), text=True, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
            procs.append(holder)
            name = holder.stdout.readline().strip()
            result["unique_name"] = name
            monitor_out = session.rt / "monitor.log"
            with open(monitor_out, "w") as monitor_file:
                monitor = subprocess.Popen(["dbus-monitor", "--session", f"destination='{name}'"], env=session.env(),
                                           stdout=monitor_file, stderr=subprocess.DEVNULL, start_new_session=True)
            procs.append(monitor)
            time.sleep(1.0)
            kproc, _press = clipboard.remote_desktop_keyboard(session)
            procs.append(kproc)
            out = session.rt / "window.log"
            window = focus_steal.start(session, session.rt, display, out)
            procs.append(window)
            if not focus_steal.wait_for(session, out, "mapped", nudge=False):
                result["status"] = "the window did not map"
                return result
            if set_properties:
                focus_steal.command(window, f"dbus_props {name}")
            time.sleep(6.0)
            calls = [line for line in monitor_out.read_text(errors="replace").splitlines() if line.startswith("method call")]
            result["status"] = "ok"
            result["calls_to_the_name"] = calls
            result["called"] = bool(calls)
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            for proc in reversed(procs):
                probe.stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    data = {"distro": probe.distro(), "control": evaluate(False), "with_properties": evaluate(True)}
    print(json.dumps(data, indent=1))
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
