# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from appjail import dbusproxy, grants, jail, manifest, runner, runtimejail
from appjail.errors import RunError
from appjail.manifest import ManifestError, Permissions

from .helpers import COMPOSITOR, build, integration, needs_proxy, pairs

NAMES = ("org.freedesktop.Notifications", "org.mpris.MediaPlayer2.*", "org.kde.StatusNotifierWatcher")


# -- name validation ----------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES + ("org.a11y.Bus", "org.gnome.Mutterly", "org.cinnamon.Muffinx", "org.Cinnamonx", "org.cinnamon.Example", "org.kde.plasmashellx", "org.kde.JobViewServer","org.freedesktop.a11yx", "org.example.App", "org.example.App.*", "org.gtkmm.Example", "org.freedesktop.FileManager1"))
def test_ordinary_names_are_accepted(name):
    assert grants.check_dbus_name(name) == name


@pytest.mark.parametrize("name", [
    "org.freedesktop.DBus", "org.freedesktop.systemd1", "org.freedesktop.Flatpak", "org.gnome.Shell",
    "org.freedesktop.portal.Desktop", "org.freedesktop.impl.portal.PermissionStore",
    "org.freedesktop.*", "org.gnome.*", "org.*", "org.freedesktop.portal.*",
    "ca.desrt.dconf", "ca.desrt.*", "org.gtk.vfs.Daemon", "org.gtk.vfs.*",
    # the names a compositor's desktop answers to any client (docs/compositor-assessment)
    "org.gnome.Mutter.ScreenCast", "org.gnome.Mutter.RemoteDesktop", "org.gnome.Mutter.InputCapture",
    "org.gnome.Mutter.DisplayConfig", "org.gnome.Mutter.ServiceChannel", "org.gnome.Mutter.*",
    "org.freedesktop.a11y.Manager", "org.freedesktop.a11y.*", "org.gnome.ScreenSaver", "org.kde.kglobalaccel", "org.kde.keyboard",
    "org.cinnamon.Muffin.DisplayConfig", "org.cinnamon.Muffin.IdleMonitor", "org.cinnamon.Muffin.*",
    "org.Cinnamon", "org.Cinnamon.LookingGlass", "org.Cinnamon.AudioDeviceSelection", "org.Cinnamon.LookingGlass.*",
    "org.gnome.Shell.Screenshot", "org.kde.plasmashell", "org.kde.klipper",
])
def test_names_that_hand_over_the_host_are_refused(name):
    with pytest.raises(ManifestError):
        grants.check_dbus_name(name)


def test_blocked_names_are_refused_when_loading_a_manifest():
    text = manifest.dumps(manifest.Manifest("a", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                                            permissions=Permissions(dbus_filter=("org.example.A",))))
    with pytest.raises(ManifestError):
        manifest.loads(text.replace("org.example.A", "org.freedesktop.systemd1"))


OWN = ("org.mpris.MediaPlayer2.myplayer", "org.example.App", "org.example.App.*", "org.kde.StatusNotifierItem.*",
       "org.gtkmm.Example")


@pytest.mark.parametrize("name", OWN)
def test_ordinary_owned_names_are_accepted(name):
    assert grants.check_dbus_own(name) == name


@pytest.mark.parametrize("name", [
    "org.freedesktop.Notifications", "org.freedesktop.secrets", "org.gnome.Mutter.ScreenCast", "org.kde.KWin",
    "org.freedesktop.systemd1", "org.freedesktop.portal.Desktop", "org.kde.plasmashell", "org.freedesktop.*",
    "org.gnome.*", "org.kde.*", "org.freedesktop.DBus", "not a name",
    "org.gtk.Application", "org.gtk.*", "ca.desrt.dconf", "ca.desrt.Other",
])
def test_owning_desktop_services_is_refused(name):
    with pytest.raises(ManifestError):
        grants.check_dbus_own(name)


def test_dbus_own_round_trips_and_is_checked_when_loading():
    m = manifest.Manifest("a", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                          permissions=Permissions(dbus_own=("org.example.A",)))
    text = manifest.dumps(m)
    assert manifest.loads(text).permissions.dbus_own == ("org.example.A",)
    with pytest.raises(ManifestError, match="dbus_own"):
        manifest.loads(text.replace("org.example.A", "org.freedesktop.Notifications"))


# -- argument building (pure) ---------------------------------------------------------------


def test_rules_see_nothing_and_talk_to_unknown_names():
    r = dbusproxy.rules(Permissions(dbus_filter=("org.example.A", "org.example.Family.*")))
    assert r == ["--filter", "--talk=org.example.A", "--talk=org.example.Family.*"]


def test_known_services_are_confined_to_their_own_objects():
    r = dbusproxy.rules(Permissions(dbus_filter=("org.freedesktop.Notifications",)))
    assert "--talk=org.freedesktop.Notifications" not in r
    assert "--call=org.freedesktop.Notifications=org.freedesktop.Notifications.*@/org/freedesktop/Notifications" in r
    assert "--call=org.freedesktop.Notifications=org.freedesktop.DBus.Properties.*@/org/freedesktop/Notifications" in r
    assert ("--broadcast=org.freedesktop.Notifications=org.freedesktop.Notifications.*@/org/freedesktop/Notifications"
            in r)
    assert all(a.startswith(("--filter", "--call=org.freedesktop.Notifications=", "--broadcast=org.freedesktop.Notifications="))
               and a.endswith(("--filter", "@/org/freedesktop/Notifications")) for a in r)


@pytest.mark.parametrize(("name", "path"), [("org.mpris.MediaPlayer2.*", "/org/mpris/MediaPlayer2"),
                                            ("org.mpris.MediaPlayer2.vlc", "/org/mpris/MediaPlayer2"),
                                            ("org.freedesktop.secrets", "/org/freedesktop/secrets/*"),
                                            ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher"),
                                            ("org.gtk.Notifications", "/org/gtk/Notifications")])
def test_every_confined_rule_names_the_service_path(name, path):
    r = dbusproxy.name_rules(name)
    assert r and all(a.startswith((f"--call={name}=", f"--broadcast={name}=")) and a.endswith("@" + path) for a in r)
    assert dbusproxy.talk_names(Permissions(dbus_filter=(name,))) == []


def test_rules_add_own_policy_and_a_bus_is_needed():
    perms = Permissions(dbus_filter=("org.example.A",), dbus_own=("org.mpris.MediaPlayer2.*",))
    assert dbusproxy.rules(perms) == ["--filter", "--talk=org.example.A", "--own=org.mpris.MediaPlayer2.*"]
    assert dbusproxy.needed(Permissions(dbus_own=("org.example.A",)))


SHELL_OWNERS = {"org.freedesktop.DBus": "org.freedesktop.DBus", ":1.9": ":1.9", "org.Cinnamon": ":1.5", "org.gnome.Panel": ":1.5",
                "org.freedesktop.Notifications": ":1.5", "org.example.Family.one": ":1.5", "org.example.Alone": ":1.9"}


def test_a_talk_name_sharing_the_owner_of_a_refused_one_is_found():
    assert dbusproxy.shared_owners(["org.gnome.Panel"], SHELL_OWNERS) == [("org.gnome.Panel", "org.gnome.Panel", "org.Cinnamon")]
    assert dbusproxy.shared_owners(["org.example.Family.*"], SHELL_OWNERS) == [
        ("org.example.Family.*", "org.example.Family.one", "org.Cinnamon")]
    assert dbusproxy.shared_owners(["org.example.Alone", "org.example.Missing"], SHELL_OWNERS) == []


def test_owner_check_refuses_shared_talk_names_and_skips_confined_ones():
    owners = lambda bus, wanted: {n: o for n, o in SHELL_OWNERS.items() if wanted(n)}
    with pytest.raises(RunError, match="org.gnome.Panel is owned by the same process as org.Cinnamon"):
        dbusproxy.check_owners(Permissions(dbus_filter=("org.gnome.Panel",)), "/bus", owners)
    dbusproxy.check_owners(Permissions(dbus_filter=("org.freedesktop.Notifications", "org.example.Alone")), "/bus", owners)
    dbusproxy.check_owners(Permissions(dbus_filter=("org.freedesktop.Notifications",)), "/bus",
                           lambda bus, wanted: pytest.fail("no talk name, so the bus is not asked"))


def test_dbus_own_without_proxy_socket_is_refused(sandbox, runtime):
    with pytest.raises(RunError, match="filtered bus socket"):
        runtimejail.runtime_args(**build(sandbox, runtime, dbus_own=("org.example.A",)))


@pytest.mark.parametrize("env,expected", [
    ({"DBUS_SESSION_BUS_ADDRESS": "unix:path={rt}/b"}, "{rt}/b"),
    ({"DBUS_SESSION_BUS_ADDRESS": "unix:path={rt}/b,guid=abc"}, "{rt}/b"),
    ({}, "{rt}/bus"),
])
def test_host_bus_address(runtime, env, expected):
    import socket
    socks = []
    try:
        for n in ("b", "bus"):
            s = socket.socket(socket.AF_UNIX)
            socks.append(s)
            s.bind(str(runtime / n))
            s.listen(1)
        env = {k: v.format(rt=runtime) for k, v in env.items()} | {"XDG_RUNTIME_DIR": str(runtime)}
        assert dbusproxy.host_bus(env) == expected.format(rt=runtime)
    finally:
        for s in socks:
            s.close()


@pytest.mark.parametrize("addr", ["unix:abstract=/tmp/x", "tcp:host=h,port=1", "unix:path=relative", "unix:path=/nonexistent/bus"])
def test_unsupported_or_missing_bus_is_refused(runtime, addr):
    with pytest.raises(RunError):
        dbusproxy.host_bus({"XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": addr})


def test_proxy_runs_in_its_own_jail_without_network_or_home(tmp_path):
    args = dbusproxy.proxy_args("/run/user/1/bus", tmp_path, Permissions(dbus_filter=NAMES[:1]), 7)
    assert "--unshare-all" in args and "--share-net" not in args and "--die-with-parent" in args
    assert ("/run/user/1/bus", "/run/user/1/bus") in pairs(args, "--ro-bind")
    assert args[args.index("--") + 1] == dbusproxy.PROXY
    tail = args[args.index("--") + 1:]
    assert tail[1:3] == ["unix:path=/run/user/1/bus", f"{tmp_path}/bus"] and "--fd=7" in tail
    assert tail[tail.index("--filter"):] == dbusproxy.rules(Permissions(dbus_filter=NAMES[:1]))


def test_app_jail_gets_only_the_filtered_socket(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime, dbus_filter=NAMES[:1]), dbus_socket="/x/bus")
    assert ("/x/bus", f"/run/user/{os.getuid()}/bus") in pairs(args, "--ro-bind")
    env = dict(pairs(args, "--setenv"))
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path=/run/user/{os.getuid()}/bus"


def test_no_bus_without_dbus_filter(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime))
    assert "DBUS_SESSION_BUS_ADDRESS" not in dict(pairs(args, "--setenv"))


def test_filtered_manifest_without_proxy_socket_is_refused(sandbox, runtime):
    with pytest.raises(RunError, match="filtered bus socket"):
        runtimejail.runtime_args(**build(sandbox, runtime, dbus_filter=NAMES[:1]))


def test_portals_stay_refused(sandbox, runtime):
    with pytest.raises(RunError, match="portals"):
        runtimejail.runtime_args(**build(sandbox, runtime, portals=True), dbus_socket="/x/bus")


def test_proxy_failure_is_reported_and_cleaned_up(runtime, monkeypatch):
    import socket
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(runtime / "bus"))
    s.listen(1)
    monkeypatch.setattr(dbusproxy, "PROXY", "/bin/false")
    with (pytest.raises(RunError, match="did not start"),
          dbusproxy.Proxy(Permissions(dbus_filter=NAMES[:1]), {"XDG_RUNTIME_DIR": str(runtime)})):
        pass
    assert [p.name for p in runtime.iterdir() if p.name.startswith("appjail-")] == []


def test_launch_wraps_the_run_in_the_proxy(sandbox, runtime, monkeypatch):
    events = []

    class FakeProxy:
        def __init__(self, perms, env):
            events.append("init")

        def __enter__(self):
            events.append("start")
            return "/fake/bus"

        def __exit__(self, *a):
            events.append("stop")

    m = manifest.Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                          permissions=Permissions(dbus_filter=NAMES[:1]))
    kw = build(sandbox, runtime, dbus_filter=NAMES[:1])
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    env = kw["host_env"]
    code = runner.launch("app", host_env=env, proxy=FakeProxy, runner=lambda argv: events.append(argv) or 0,
                         **COMPOSITOR)
    assert code == 0 and events[:2] == ["init", "start"] and events[-1] == "stop"
    assert ("/fake/bus", f"/run/user/{os.getuid()}/bus") in pairs(events[2], "--ro-bind")


# -- real bus, real proxy, real jail (guest) -----------------------------------------------

PROBE = """#!/usr/bin/python3
import json, os, subprocess
def call(dest, member):
    r = subprocess.run(["dbus-send", "--session", "--print-reply", "--reply-timeout=1500", "--dest=" + dest, "/x", member],
                       capture_output=True, text=True, timeout=30)
    return r.stderr
print(json.dumps({
    "addr": os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    "rt": sorted(os.listdir(os.environ["XDG_RUNTIME_DIR"])),
    "reload": call("org.freedesktop.DBus", "org.freedesktop.DBus.ReloadConfig"),
    "granted": call("org.example.Granted", "org.example.Granted.Ping"),
    "other": call("org.example.Other", "org.example.Other.Ping"),
}))
"""


@pytest.fixture
def session_bus(runtime):
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1",
                               f"--address=unix:path={runtime}/bus"], stdout=subprocess.PIPE, text=True,
                              env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime)})
    daemon.stdout.readline()
    yield runtime / "bus"
    daemon.terminate()
    daemon.wait()


@integration
@needs_proxy
def test_filtered_bus_end_to_end(sandbox, runtime, session_bus):
    perms = Permissions(dbus_filter=("org.example.Granted",))
    env = build(sandbox, runtime)["host_env"] | {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    with dbusproxy.Proxy(perms, env) as sock:
        kw = build(sandbox, runtime, dbus_filter=perms.dbus_filter)
        (kw["root"] / "AppRun").write_text(PROBE)
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, dbus_socket=sock)], timeout=60)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["addr"] == f"unix:path=/run/user/{os.getuid()}/bus"
    assert "bus" in r["rt"] and "wayland-0" in r["rt"]
    assert "AccessDenied" in r["reload"]  # bus control calls are filtered away
    # The granted name reaches the real bus, which says it has no such service; the proxy answers
    # for every other name without asking the bus.
    assert "was not provided by any .service files" in r["granted"]
    assert "ServiceUnknown" in r["other"] and ".service files" not in r["other"]
    assert not Path(sock).exists()  # proxy stopped and its directory removed


@integration
@needs_proxy
def test_proxy_dies_with_the_context(runtime, session_bus):
    env = {"XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    with dbusproxy.Proxy(Permissions(dbus_filter=("org.example.Granted",)), env) as sock:
        assert Path(sock).is_socket()
    assert not Path(sock).exists()
    assert [p for p in runtime.iterdir() if p.name.startswith("appjail-")] == []


OWN_PROBE = """#!/usr/bin/python3
import json, dbus, dbus.service
bus = dbus.SessionBus()
def own(name):
    try:
        dbus.service.BusName(name, bus, do_not_queue=True)
        return "ok"
    except Exception as e:
        return type(e).__name__ + ": " + str(e)[:120]
print(json.dumps({"owned": own("org.example.Owned"), "wild": own("org.example.Family.one"),
                  "other": own("org.example.Other"), "notif": own("org.freedesktop.Notifications")}))
"""


@integration
@needs_proxy
@pytest.mark.skipif(not shutil.which("python3") or subprocess.run(["python3", "-c", "import dbus"]).returncode != 0,
                    reason="needs python3-dbus (run provision.sh)")
def test_owning_a_granted_name_end_to_end(sandbox, runtime, session_bus):
    perms = Permissions(dbus_own=("org.example.Owned", "org.example.Family.*"))
    env = build(sandbox, runtime)["host_env"] | {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    with dbusproxy.Proxy(perms, env) as sock:
        kw = build(sandbox, runtime, dbus_own=perms.dbus_own)
        (kw["root"] / "AppRun").write_text(OWN_PROBE)
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, dbus_socket=sock)], timeout=60)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["owned"] == "ok" and r["wild"] == "ok"
    assert "AccessDenied" in r["other"] or "not allowed" in r["other"].lower() or "Error" in r["other"]
    assert r["other"] != "ok" and r["notif"] != "ok"


# -- one process owning a refused name and ordinary ones, as a desktop shell does (guest) ----------

FAKE_SHELL = """#!/usr/bin/python3
import sys, dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
names = [dbus.service.BusName(n, bus) for n in sys.argv[1:]]

class Obj(dbus.service.Object):
    def __init__(self, path, iface):
        super().__init__(bus, path)
        self.iface = iface

    @dbus.service.method("org.Cinnamon", in_signature="s", out_signature="s")
    def Eval(self, code):
        return "ran"

    @dbus.service.method("org.freedesktop.Notifications", out_signature="ssss")
    def GetServerInformation(self):
        return ("fake", "test", "1", "1.2")

    @dbus.service.method("org.freedesktop.Notifications", in_signature="u")
    def CloseNotification(self, nid):
        self.NotificationClosed(nid, 3)

    @dbus.service.signal("org.freedesktop.Notifications", signature="uu")
    def NotificationClosed(self, nid, reason):
        pass

    @dbus.service.method("org.freedesktop.Secret.Service", out_signature="s")
    def ServiceProbe(self):
        return "service"

    @dbus.service.method("org.freedesktop.Secret.Collection", out_signature="s")
    def CollectionProbe(self):
        return "collection"

    @dbus.service.method("org.mpris.MediaPlayer2.Player", out_signature="s")
    def Probe(self):
        return "player"

    @dbus.service.method("org.example.Plain", out_signature="s")
    def Ping(self):
        return "pong"

objs = [Obj(p, None) for p in ("/org/Cinnamon", "/org/freedesktop/Notifications", "/org/freedesktop/secrets",
                                "/org/freedesktop/secrets/collection/login", "/org/example/Plain",
                                "/org/mpris/MediaPlayer2")]
print(bus.get_unique_name(), flush=True)
GLib.MainLoop().run()
"""

CLIENT = """#!/usr/bin/python3
import json, sys, dbus, dbus.mainloop.glib
from gi.repository import GLib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.bus.BusConnection(sys.argv[1])
unique = sys.argv[2]
def call(dest, path, iface, member, *args):
    try:
        return str(bus.call_blocking(dest, path, iface, member, "u" if args else "", args, timeout=5))
    except dbus.DBusException as e:
        return "error: " + (e.get_dbus_name() or "")
got = []
bus.add_signal_receiver(lambda *a: got.append(int(a[0])), "NotificationClosed", "org.freedesktop.Notifications")
out = {}
out["listed"] = sorted(str(n) for n in bus.list_names() if not str(n).startswith(":"))
for label, dest in (("name", sys.argv[3]), ("unique", unique)):
    out[label] = {
        "eval": call(dest, "/org/Cinnamon", "org.Cinnamon", "Eval"),
        "notify_info": call(dest, "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "GetServerInformation"),
        "notify_close": call(dest, "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "CloseNotification", dbus.UInt32(7)),
        "notify_wrong_path": call(dest, "/org/Cinnamon", "org.freedesktop.Notifications", "GetServerInformation"),
        "secret_service": call(dest, "/org/freedesktop/secrets", "org.freedesktop.Secret.Service", "ServiceProbe"),
        "secret_collection": call(dest, "/org/freedesktop/secrets/collection/login", "org.freedesktop.Secret.Collection", "CollectionProbe"),
        "plain": call(dest, "/org/example/Plain", "org.example.Plain", "Ping"),
        "mpris_player": call(dest, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Probe"),
    }
loop = GLib.MainLoop()
GLib.timeout_add(1500, loop.quit)
loop.run()
out["signals"] = got
print(json.dumps(out))
"""

needs_python_dbus = pytest.mark.skipif(
    not shutil.which("python3") or subprocess.run(["python3", "-c", "import dbus, gi"]).returncode != 0,
    reason="needs python3-dbus and python3-gi (run provision.sh)")


@pytest.fixture
def fake_shell(runtime, session_bus, tmp_path):
    """A process that owns org.Cinnamon (refused) next to ordinary names, on the private session bus."""
    script = tmp_path / "shell.py"
    script.write_text(FAKE_SHELL)
    env = {"PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    proc = subprocess.Popen(["python3", str(script), "org.Cinnamon", "org.freedesktop.Notifications", "org.freedesktop.secrets",
                             "org.example.Plain", "org.mpris.MediaPlayer2.fake"], stdout=subprocess.PIPE, text=True, env=env)
    unique = proc.stdout.readline().strip()
    yield unique
    proc.terminate()
    proc.wait()


def through(runtime, session_bus, tmp_path, unique, name, dest=None):
    env = {"XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    client = tmp_path / "client.py"
    client.write_text(CLIENT)
    with dbusproxy.Proxy(Permissions(dbus_filter=(name,)), env) as sock:
        r = subprocess.run(["python3", str(client), f"unix:path={sock}", unique, dest or name], capture_output=True, text=True,
                           timeout=60, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@integration
@needs_proxy
@needs_python_dbus
def test_a_confined_name_reaches_only_its_own_objects(runtime, session_bus, tmp_path, fake_shell):
    r = through(runtime, session_bus, tmp_path, fake_shell, "org.freedesktop.Notifications")
    for label in ("name", "unique"):  # the rules hold whether the app names the service or its owner's unique name
        got = r[label]
        assert "fake" in got["notify_info"] and got["notify_close"] == "None", label
        for denied in ("eval", "notify_wrong_path", "secret_service", "secret_collection", "plain"):
            assert got[denied] == "error: org.freedesktop.DBus.Error.AccessDenied", (label, denied)
    assert r["signals"] == [7, 7]  # the service's own signals still reach the app


@integration
@needs_proxy
@needs_python_dbus
def test_secrets_reach_their_subtree_only(runtime, session_bus, tmp_path, fake_shell):
    r = through(runtime, session_bus, tmp_path, fake_shell, "org.freedesktop.secrets")
    for label in ("name", "unique"):
        got = r[label]
        assert got["secret_service"] == "service" and got["secret_collection"] == "collection", label
        for denied in ("eval", "notify_info", "plain"):
            assert got[denied] == "error: org.freedesktop.DBus.Error.AccessDenied", (label, denied)
    assert r["signals"] == []


@integration
@needs_proxy
@needs_python_dbus
def test_a_talk_name_of_a_refused_owner_is_refused_at_launch(runtime, session_bus, fake_shell):
    env = {"XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    with (pytest.raises(RunError, match="org.example.Plain is owned by the same process as org.Cinnamon"),
          dbusproxy.Proxy(Permissions(dbus_filter=("org.example.Plain",)), env)):
        pass
    assert [p for p in runtime.iterdir() if p.name.startswith("appjail-")] == []


@integration
@needs_proxy
@needs_python_dbus
def test_an_mpris_wildcard_reaches_the_players_only(runtime, session_bus, tmp_path, fake_shell):
    r = through(runtime, session_bus, tmp_path, fake_shell, "org.mpris.MediaPlayer2.*", dest="org.mpris.MediaPlayer2.fake")
    assert "org.mpris.MediaPlayer2.fake" in r["listed"]  # a controller finds the players by listing the names
    assert not {"org.Cinnamon", "org.example.Plain", "org.freedesktop.secrets"} & set(r["listed"])
    for label in ("name", "unique"):
        got = r[label]
        assert got["mpris_player"] == "player", label
        for denied in ("eval", "notify_info", "secret_service", "plain"):
            assert got[denied] == "error: org.freedesktop.DBus.Error.AccessDenied", (label, denied)
