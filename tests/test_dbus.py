# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from appjail import dbusproxy, grants, jail, manifest, runner
from appjail.jail import RunError
from appjail.manifest import ManifestError, Permissions

from .helpers import NO_RESTRICTION, build, integration, needs_proxy, pairs

NAMES = ("org.freedesktop.Notifications", "org.mpris.MediaPlayer2.*", "org.kde.StatusNotifierWatcher")


# -- name validation ----------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES + ("org.example.App", "org.example.App.*"))
def test_ordinary_names_are_accepted(name):
    assert grants.check_dbus_name(name) == name


@pytest.mark.parametrize("name", [
    "org.freedesktop.DBus", "org.freedesktop.systemd1", "org.freedesktop.Flatpak", "org.gnome.Shell",
    "org.freedesktop.portal.Desktop", "org.freedesktop.impl.portal.PermissionStore",
    "org.freedesktop.*", "org.gnome.*", "org.*", "org.freedesktop.portal.*",
])
def test_names_that_hand_over_the_host_are_refused(name):
    with pytest.raises(ManifestError):
        grants.check_dbus_name(name)


def test_blocked_names_are_refused_when_loading_a_manifest():
    text = manifest.dumps(manifest.Manifest("a", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                                            permissions=Permissions(dbus_filter=("org.example.A",))))
    with pytest.raises(ManifestError):
        manifest.loads(text.replace("org.example.A", "org.freedesktop.systemd1"))


OWN = ("org.mpris.MediaPlayer2.myplayer", "org.example.App", "org.example.App.*", "org.kde.StatusNotifierItem.*")


@pytest.mark.parametrize("name", OWN)
def test_ordinary_owned_names_are_accepted(name):
    assert grants.check_dbus_own(name) == name


@pytest.mark.parametrize("name", [
    "org.freedesktop.Notifications", "org.freedesktop.secrets", "org.gnome.Mutter.ScreenCast", "org.kde.KWin",
    "org.freedesktop.systemd1", "org.freedesktop.portal.Desktop", "org.kde.plasmashell", "org.freedesktop.*",
    "org.gnome.*", "org.kde.*", "org.freedesktop.DBus", "not a name",
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


def test_rules_see_nothing_and_talk_to_the_listed_names():
    r = dbusproxy.rules(Permissions(dbus_filter=NAMES))
    assert r[0] == "--filter" and r[1:] == [f"--talk={n}" for n in NAMES]


def test_rules_add_own_policy_and_a_bus_is_needed():
    perms = Permissions(dbus_filter=NAMES[:1], dbus_own=("org.mpris.MediaPlayer2.*",))
    assert dbusproxy.rules(perms) == ["--filter", f"--talk={NAMES[0]}", "--own=org.mpris.MediaPlayer2.*"]
    assert dbusproxy.needed(Permissions(dbus_own=("org.example.A",)))


def test_dbus_own_without_proxy_socket_is_refused(sandbox, runtime):
    with pytest.raises(RunError, match="filtered bus socket"):
        jail.runtime_args(**build(sandbox, runtime, dbus_own=("org.example.A",)))


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
    assert tail[-2:] == ["--filter", "--talk=org.freedesktop.Notifications"]


def test_app_jail_gets_only_the_filtered_socket(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime, dbus_filter=NAMES[:1]), dbus_socket="/x/bus")
    assert ("/x/bus", f"/run/user/{os.getuid()}/bus") in pairs(args, "--ro-bind")
    env = dict(pairs(args, "--setenv"))
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path=/run/user/{os.getuid()}/bus"


def test_no_bus_without_dbus_filter(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime))
    assert "DBUS_SESSION_BUS_ADDRESS" not in dict(pairs(args, "--setenv"))


def test_filtered_manifest_without_proxy_socket_is_refused(sandbox, runtime):
    with pytest.raises(RunError, match="filtered bus socket"):
        jail.runtime_args(**build(sandbox, runtime, dbus_filter=NAMES[:1]))


def test_portals_stay_refused(sandbox, runtime):
    with pytest.raises(RunError, match="portals"):
        jail.runtime_args(**build(sandbox, runtime, portals=True), dbus_socket="/x/bus")


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
                         restricted=NO_RESTRICTION)
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
        proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw, dbus_socket=sock)], timeout=60)
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
        proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw, dbus_socket=sock)], timeout=60)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["owned"] == "ok" and r["wild"] == "ok"
    assert "AccessDenied" in r["other"] or "not allowed" in r["other"].lower() or "Error" in r["other"]
    assert r["other"] != "ok" and r["notif"] != "ok"
