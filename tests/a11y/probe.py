# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A hostile client of the accessibility bus (guest only; needs python3-dbus), run inside the jail by harness.py.

It tries what an app could do with the bus: look at the other applications, listen to keys, send keys, monitor the bus.
Prints one line per attempt, then the signals it receives for LISTEN seconds (default 6). Behind the proxy only the
calls of Flatpak's rules may pass; on the raw bus every one does.
"""

import os
import sys

import dbus
import dbus.bus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

ADDRESS = os.environ["AT_SPI_BUS_ADDRESS"]
REGISTRY = "org.a11y.atspi.Registry"
DEC = ("/org/a11y/atspi/registry/deviceeventcontroller", "org.a11y.atspi.DeviceEventController")
BUS = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
KEY_EVENT = dbus.Struct((dbus.UInt32(1), dbus.Int32(38), dbus.Int16(0), dbus.Int16(0), dbus.Int32(0), "a", True),
                        signature="uinnisb")


def attempt(conn, label, dest, path, iface, member, sig="", *args):
    try:
        reply = conn.call_blocking(dest, path, iface, member, sig, args, timeout=3)
        print(f"{label:34} OK {str(reply)[:70]}")
    except dbus.DBusException as e:
        print(f"{label:34} {e.get_dbus_name().rsplit('.', 1)[-1]}")


def main():
    conn = dbus.bus.BusConnection(ADDRESS)
    attempt(conn, "ListNames", *BUS, "ListNames")
    attempt(conn, "Registry.GetRegisteredEvents", REGISTRY, "/org/a11y/atspi/registry", REGISTRY, "GetRegisteredEvents")
    attempt(conn, "DEC.GetKeystrokeListeners", REGISTRY, *DEC, "GetKeystrokeListeners")
    attempt(conn, "DEC.RegisterKeystrokeListener", REGISTRY, *DEC, "RegisterKeystrokeListener", "oa(iisi)uu(bbb)",
            "/x/listener", [], 0, 3, (False, False, True))
    attempt(conn, "DEC.GenerateKeyboardEvent", REGISTRY, *DEC, "GenerateKeyboardEvent", "isu", 38, "a", 1)
    attempt(conn, "DEC.NotifyListenersSync", REGISTRY, *DEC, "NotifyListenersSync", "(uinnisb)", KEY_EVENT)
    attempt(conn, "DEC.NotifyListenersAsync", REGISTRY, *DEC, "NotifyListenersAsync", "(uinnisb)", KEY_EVENT)
    attempt(conn, "Registry.RegisterEvent", REGISTRY, "/org/a11y/atspi/registry", REGISTRY, "RegisterEvent", "sass",
            "object:", [], "")
    attempt(conn, "Desktop.GetChildren", REGISTRY, "/org/a11y/atspi/accessible/root", "org.a11y.atspi.Accessible",
            "GetChildren")
    attempt(conn, "Cache.GetItems", REGISTRY, "/org/a11y/atspi/cache", "org.a11y.atspi.Cache", "GetItems")
    attempt(conn, "Desktop.ChildCount", REGISTRY, "/org/a11y/atspi/accessible/root", "org.freedesktop.DBus.Properties",
            "Get", "ss", "org.a11y.atspi.Accessible", "ChildCount")
    try:
        conn.add_match_string("eavesdrop=true,type='signal'")
        print(f"{'AddMatch eavesdrop':34} accepted")
    except dbus.DBusException as e:
        print(f"{'AddMatch eavesdrop':34} {e.get_dbus_name().rsplit('.', 1)[-1]}")
    names = conn.call_blocking(*BUS, "ListNames", "", (), timeout=3)
    others = [n for n in names if n.startswith(":")]
    reached = 0
    for name in others:
        try:
            conn.call_blocking(name, "/org/a11y/atspi/accessible/root", "org.a11y.atspi.Accessible", "GetChildren", "", (),
                               timeout=2)
            reached += 1
        except dbus.DBusException:
            pass
    print(f"{'GetChildren on unique names':34} {reached} of {len(others)} answered")
    # Which signals reach a client, and whether the bus will make a connection a monitor of every message.
    seen, monitored = set(), []
    main_conn = dbus.bus.BusConnection(ADDRESS, mainloop=DBusGMainLoop())
    main_conn.add_match_string("type='signal'")
    main_conn.add_message_filter(lambda c, m: seen.add(f"{m.get_interface()}.{m.get_member()}"))
    monitor = dbus.bus.BusConnection(ADDRESS, mainloop=DBusGMainLoop())
    try:
        monitor.call_blocking(*BUS[:2], "org.freedesktop.DBus.Monitoring", "BecomeMonitor", "asu", ([], 0), timeout=3)
        monitor.add_message_filter(lambda c, m: monitored.append(f"{m.get_interface()}.{m.get_member()}"))
        print(f"{'BecomeMonitor':34} OK")
    except dbus.DBusException as e:
        print(f"{'BecomeMonitor':34} {e.get_dbus_name().rsplit('.', 1)[-1]}")
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(int(os.environ.get("LISTEN", "6")), loop.quit)
    loop.run()
    print("signals received:", sorted(seen - {"org.freedesktop.DBus.NameAcquired"}))
    print("messages seen by the monitor:", len(monitored))


if __name__ == "__main__":
    sys.exit(main())
