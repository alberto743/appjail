# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Does granting one bus name reach every interface of the connection that owns it? *-compositors guests only:

    python3 tests/compositors/shared_connection.py --out /tmp/shared-connection.json [--only gnome-shell,cinnamon]

A compositor's shell owns many names on one connection: harmless-looking ones (notifications, a keyring prompter) next to
the privileged ones appjail refuses. xdg-dbus-proxy started with `--filter --talk=NAME` filters by destination name, not by
object or interface. For every name the compositor's privileged connection owns that appjail's name policy allows, the
tool sends the privileged call of that connection (side-effect free: a session created and not started, or `Eval` of
`1+1`) through a proxy that grants only that name:

* `reached`: with `--talk=NAME`, the plain proxy rule (what appjail did before confining names);
* `appjail`: what appjail does now. Either its launch check refuses the grant (`dbusproxy.shared_owners`, fed with the
  owners this bus lists), or the proxy runs with appjail's own rules (`dbusproxy.rules`): the privileged call is sent to the
  name and to its owner's unique name, and, for a service with a known harmless call (`SERVICE_CALL`), that call too.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

from appjail import dbusproxy, grants
from appjail.manifest import Permissions
from appjail.valid import ManifestError

# (object path, interface, method, GVariant text of the arguments), by the refused name that marks the connection.
PRIVILEGED_CALL = {
    "org.gnome.Mutter.RemoteDesktop": ("/org/gnome/Mutter/RemoteDesktop", "org.gnome.Mutter.RemoteDesktop", "CreateSession", "()"),
    "org.Cinnamon": ("/org/Cinnamon", "org.Cinnamon", "Eval", "('1+1',)"),
}
# The service's own side-effect-free call, which a confined grant must still reach (removing a notification that does not
# exist changes nothing).
SERVICE_CALL = {
    "org.freedesktop.Notifications": ("/org/freedesktop/Notifications", "org.freedesktop.Notifications", "GetServerInformation", "()"),
    "org.gtk.Notifications": ("/org/gtk/Notifications", "org.gtk.Notifications", "RemoveNotification",
                              "('appjail.test', 'none')"),
}


def connections(session):
    """{well-known name: unique name of the connection that owns it}."""
    with contextlib.suppress(ValueError):
        return {e["name"]: e.get("connection") for e in json.loads(probe.busctl(session, "list", "--json=short").stdout)}
    return {}


def allowed(name):
    try:
        grants.check_dbus_name(name)
    except ManifestError:
        return False
    return True


def through_proxy(session, rules, calls):
    """Start xdg-dbus-proxy with `--filter` and `rules`, connect through it and send each (destination, call)."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    with tempfile.TemporaryDirectory(dir=session.rt) as tmp:
        sock = Path(tmp) / "bus"
        proxy = subprocess.Popen(["xdg-dbus-proxy", session.address, str(sock), "--filter", *rules],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(50):
                if sock.exists():
                    break
                time.sleep(0.1)
            flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
            conn = Gio.DBusConnection.new_for_address_sync(f"unix:path={sock}", flags, None, None)
            out = []
            for dest, (path, iface, method, args) in calls:
                try:
                    reply = conn.call_sync(dest, path, iface, method, GLib.Variant.parse(None, args, None, None), None,
                                           Gio.DBusCallFlags.NONE, 8000, None)
                    out.append({"reached": True, "answer": str(reply.unpack())[:120]})
                except GLib.Error as e:
                    out.append({"reached": False, "answer": e.message[:160]})
            return out
        finally:
            probe.stop(proxy)


def appjail_outcome(session, name, call, owner):
    """What appjail does with a grant of `name` on this bus: refuse it at launch, or confine it through the proxy."""
    perms = Permissions(dbus_filter=(name,))
    clash = dbusproxy.shared_owners(dbusproxy.talk_names(perms), connections(session))
    if clash:
        return {"outcome": "refused at launch", "shares_owner_with": clash[0][2]}
    calls = [(name, call), (owner, call)] + ([(name, SERVICE_CALL[name])] if name in SERVICE_CALL else [])
    got = through_proxy(session, dbusproxy.rules(perms)[1:], calls)
    result = {"outcome": "confined" if dbusproxy.confined(name) else "talk", "by_name": got[0], "by_unique_name": got[1]}
    if name in SERVICE_CALL:
        result["service_call"] = got[2]
    return result


def evaluate(key):
    packages, argv_for, extra = probe.COMPOSITORS[key]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        before = probe.sockets(session.rt)
        proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
        try:
            if probe.wait_for_display(proc, session.rt, before) is None:
                result["status"] = "did not start"
                return result
            time.sleep(4.0)  # the shells take their bus names after the socket appears
            result["status"] = "ok"
            names = probe.owned_by(session, proc.pid)
            result["names"] = names
            result["tries"] = {}
            owner = connections(session)
            for marker, call in PRIVILEGED_CALL.items():
                if marker not in names:
                    continue
                for name in names:
                    if allowed(name) and owner.get(name) == owner[marker]:
                        talk = through_proxy(session, [f"--talk={name}"], [(name, call)])[0]
                        result["tries"][name] = {"call": f"{call[1]}.{call[2]}", **talk,
                                                 "appjail": appjail_outcome(session, name, call, owner[name])}
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            probe.stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="gnome-shell,cinnamon")
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
