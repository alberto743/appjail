# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `accessibility` permission: the accessibility bus behind its own xdg-dbus-proxy (docs/decisions/desktop/a11y-bus.md)."""

import json
import os
import shutil
import socket
import subprocess
from dataclasses import replace

import pytest

from appjail import dbusproxy, grants, jail, manifest, permargs, runner, runtimejail
from appjail.errors import RunError
from appjail.manifest import ManifestError, Permissions

from .helpers import COMPOSITOR, build, integration, needs_proxy, pairs

# -- the permission in the manifest and on the command line -------------------------------


def _manifest(**perms):
    return manifest.Manifest("a", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                             permissions=Permissions(**perms))


def test_the_permission_is_off_by_default_and_round_trips():
    assert Permissions().accessibility is False
    assert "accessibility" not in manifest.dumps(_manifest())
    text = manifest.dumps(_manifest(accessibility=True))
    assert "accessibility = true" in text
    assert manifest.loads(text).permissions.accessibility is True


def test_a_non_boolean_value_is_refused():
    text = manifest.dumps(_manifest(accessibility=True)).replace("accessibility = true", 'accessibility = "yes"')
    with pytest.raises(ManifestError):
        manifest.loads(text)


def test_allow_accessibility_is_a_flag_and_shows_in_the_summary_and_the_changes():
    assert "accessibility" in permargs.PERMISSION_FLAGS
    new = replace(Permissions(), accessibility=True)
    assert permargs.granted_summary(new).startswith("grants: accessibility;")
    assert ("accessibility", "no → yes") in permargs.permission_changes(Permissions(), new)


def test_granting_it_says_what_it_gives():
    said = []

    class Console:
        def warn(self, text):
            said.append(text)
    permargs.warn_new_grants(Console(), Permissions(), replace(Permissions(), accessibility=True))
    assert len(said) == 1 and "assistive tools" in said[0] and "fake key events" in said[0]
    said.clear()
    permargs.warn_new_grants(Console(), replace(Permissions(), accessibility=True), replace(Permissions(), accessibility=True))
    assert said == []


def test_the_accessibility_names_stay_refused_and_the_message_points_to_the_permission():
    with pytest.raises(ManifestError, match="`accessibility` permission"):
        grants.check_dbus_name("org.freedesktop.a11y.Manager")
    with pytest.raises(ManifestError):
        grants.check_dbus_own("org.a11y.Bus")


# -- the proxy's rules ---------------------------------------------------------------------


def test_the_rules_let_an_app_register_and_nothing_that_reads_or_drives_others():
    rules = dbusproxy.A11Y_RULES
    assert rules[0] == "--filter"
    joined = " ".join(rules)
    assert "Socket.Embed@/org/a11y/atspi/accessible/root" in joined
    for refused in ("RegisterKeystrokeListener", "GenerateKeyboardEvent", "GenerateMouseEvent", "RegisterEvent",
                    "GetItems", "GetChildren", "BecomeMonitor", "--talk", "--own", "--see"):
        assert refused not in joined
    # every rule is for the registry's own name, and a call rule names the object path it is for
    assert all(r.startswith(("--call=org.a11y.atspi.Registry=", "--broadcast=org.a11y.atspi.Registry=")) and "@/org/a11y/" in r
               for r in rules[2:])


def test_the_proxy_runs_in_its_own_jail_without_network_or_home(tmp_path):
    args = dbusproxy._argv("/run/user/1/at-spi/bus", tmp_path, list(dbusproxy.A11Y_RULES), 7)
    assert "--unshare-all" in args and "--share-net" not in args and "--die-with-parent" in args
    assert ("/run/user/1/at-spi/bus", "/run/user/1/at-spi/bus") in pairs(args, "--ro-bind")
    tail = args[args.index("--") + 1:]
    assert tail[0] == dbusproxy.PROXY and tail[1:3] == ["unix:path=/run/user/1/at-spi/bus", f"{tmp_path}/bus"]
    assert tail[tail.index("--filter"):] == list(dbusproxy.A11Y_RULES)


# -- finding the accessibility bus ---------------------------------------------------------


@pytest.fixture
def bus_socket(tmp_path):
    path = tmp_path / "a11y"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(1)
    yield str(path)
    s.close()


def test_the_environment_address_is_used_when_there_is_one(bus_socket):
    assert dbusproxy.a11y_bus({"AT_SPI_BUS_ADDRESS": f"unix:path={bus_socket},guid=abc"}) == bus_socket


@pytest.mark.parametrize("address", ["unix:abstract=/tmp/x", "tcp:host=h,port=1", "unix:path=relative", "unix:path=/nonexistent/bus"])
def test_an_unusable_address_is_refused(address):
    with pytest.raises(RunError):
        dbusproxy.a11y_bus({"AT_SPI_BUS_ADDRESS": address})


def _fake_dbus_send(tmp_path, body):
    script = tmp_path / "dbus-send"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


def test_the_session_bus_is_asked_when_the_environment_has_no_address(runtime, tmp_path, bus_socket, monkeypatch):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(runtime / "bus"))
    s.listen(1)
    monkeypatch.setattr(dbusproxy, "DBUS_SEND", _fake_dbus_send(
        tmp_path, f'case "$*" in *org.a11y.Bus*GetAddress*) echo "method return"; echo \'   string "unix:path={bus_socket},guid=1"\';; *) exit 1;; esac\n'))
    try:
        assert dbusproxy.a11y_bus({"XDG_RUNTIME_DIR": str(runtime)}) == bus_socket
    finally:
        s.close()


def test_no_accessibility_bus_is_an_error_that_names_the_package(runtime, tmp_path, monkeypatch):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(runtime / "bus"))
    s.listen(1)
    monkeypatch.setattr(dbusproxy, "DBUS_SEND", _fake_dbus_send(
        tmp_path, 'echo "Error org.freedesktop.DBus.Error.ServiceUnknown: The name org.a11y.Bus was not provided" >&2; exit 1\n'))
    try:
        with pytest.raises(RunError, match="at-spi2-core"):
            dbusproxy.a11y_bus({"XDG_RUNTIME_DIR": str(runtime)})
    finally:
        s.close()


def test_a_missing_proxy_program_is_reported(runtime, monkeypatch):
    monkeypatch.setattr(dbusproxy, "PROXY", "/nonexistent/xdg-dbus-proxy")
    with pytest.raises(RunError, match="accessibility needs xdg-dbus-proxy"), dbusproxy.A11yProxy({"XDG_RUNTIME_DIR": str(runtime)}):
        pass


def test_a_proxy_that_does_not_start_is_reported_and_cleaned_up(runtime, bus_socket, monkeypatch):
    monkeypatch.setattr(dbusproxy, "PROXY", "/bin/false")
    with (pytest.raises(RunError, match="did not start"),
          dbusproxy.A11yProxy({"XDG_RUNTIME_DIR": str(runtime)}, address=lambda env: bus_socket)):
        pass
    assert [p.name for p in runtime.iterdir() if p.name.startswith("appjail-")] == []


# -- the app's jail ------------------------------------------------------------------------


def test_the_app_gets_only_the_proxy_socket_and_the_variable_that_names_it(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime, accessibility=True), a11y_socket="/x/bus")
    assert ("/x/bus", f"/run/user/{os.getuid()}/at-spi-bus") in pairs(args, "--ro-bind")
    env = dict(pairs(args, "--setenv"))
    assert env["AT_SPI_BUS_ADDRESS"] == f"unix:path=/run/user/{os.getuid()}/at-spi-bus"
    assert "DBUS_SESSION_BUS_ADDRESS" not in env  # the session bus is a separate grant


def test_no_accessibility_bus_without_the_permission(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime))
    assert "AT_SPI_BUS_ADDRESS" not in dict(pairs(args, "--setenv"))
    assert not any("at-spi" in a for a in args)


def test_the_permission_without_a_proxy_socket_is_refused(sandbox, runtime):
    with pytest.raises(RunError, match="accessibility bus socket"):
        runtimejail.runtime_args(**build(sandbox, runtime, accessibility=True))


def _launch(sandbox, runtime, monkeypatch, accessibility):
    events = []

    class FakeA11y:
        def __init__(self, env):
            events.append("init")

        def __enter__(self):
            events.append("start")
            return "/fake/a11y"

        def __exit__(self, *a):
            events.append("stop")

    m = _manifest(accessibility=accessibility)
    kw = build(sandbox, runtime, accessibility=accessibility)
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env=kw["host_env"], a11y_proxy=FakeA11y, runner=lambda argv: events.append(argv) or 0,
                         **COMPOSITOR)
    return code, events


def test_launch_runs_the_app_inside_the_accessibility_proxy(sandbox, runtime, monkeypatch):
    code, events = _launch(sandbox, runtime, monkeypatch, True)
    assert code == 0 and events[:2] == ["init", "start"] and events[-1] == "stop"
    assert ("/fake/a11y", f"/run/user/{os.getuid()}/at-spi-bus") in pairs(events[2], "--ro-bind")


def test_launch_starts_no_proxy_without_the_permission(sandbox, runtime, monkeypatch):
    code, events = _launch(sandbox, runtime, monkeypatch, False)
    assert code == 0 and "init" not in events


# -- a real accessibility bus, a real proxy, a real jail (guest) ----------------------------

FAKE_REGISTRY = """#!/usr/bin/python3
import sys, dbus, dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
DBusGMainLoop(set_as_default=True)
bus = dbus.bus.BusConnection(sys.argv[1])
name = dbus.service.BusName("org.a11y.atspi.Registry", bus)
DEC = "org.a11y.atspi.DeviceEventController"


class Registry(dbus.service.Object):
    @dbus.service.method("org.a11y.atspi.Registry", out_signature="a(ss)")
    def GetRegisteredEvents(self):
        return []

    @dbus.service.method("org.a11y.atspi.Registry", in_signature="sass")
    def RegisterEvent(self, event, props, app):
        pass


class Controller(dbus.service.Object):
    @dbus.service.method(DEC, in_signature="oa(iisi)uu(bbb)", out_signature="b")
    def RegisterKeystrokeListener(self, listener, keys, mask, types, mode):
        return True

    @dbus.service.method(DEC, out_signature="a(souua(iisi)u(bbb))")
    def GetKeystrokeListeners(self):
        return []


class Root(dbus.service.Object):
    @dbus.service.method("org.a11y.atspi.Accessible", out_signature="a(so)")
    def GetChildren(self):
        return []

    @dbus.service.method("org.a11y.atspi.Socket", in_signature="(so)", out_signature="(so)")
    def Embed(self, plug):
        return ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")


objs = [Registry(bus, "/org/a11y/atspi/registry"), Controller(bus, "/org/a11y/atspi/registry/deviceeventcontroller"),
        Root(bus, "/org/a11y/atspi/accessible/root")]
print("ready", flush=True)
GLib.MainLoop().run()
"""

APP_PROBE = """#!/usr/bin/python3
import json, os, dbus, dbus.bus
conn = dbus.bus.BusConnection(os.environ["AT_SPI_BUS_ADDRESS"])
R = "org.a11y.atspi.Registry"
DEC = ("/org/a11y/atspi/registry/deviceeventcontroller", "org.a11y.atspi.DeviceEventController")
out = {}


def attempt(label, dest, path, iface, member, sig="", *args):
    try:
        conn.call_blocking(dest, path, iface, member, sig, args, timeout=5)
        out[label] = "ok"
    except dbus.DBusException as e:
        out[label] = e.get_dbus_name().rsplit(".", 1)[-1]


attempt("embed", R, "/org/a11y/atspi/accessible/root", "org.a11y.atspi.Socket", "Embed", "(so)", ("x", "/y"))
attempt("registered_events", R, "/org/a11y/atspi/registry", R, "GetRegisteredEvents")
attempt("listeners", R, *DEC, "GetKeystrokeListeners")
attempt("register_keys", R, *DEC, "RegisterKeystrokeListener", "oa(iisi)uu(bbb)", "/x", [], 0, 3, (False, False, True))
attempt("register_event", R, "/org/a11y/atspi/registry", R, "RegisterEvent", "sass", "object:", [], "")
attempt("children", R, "/org/a11y/atspi/accessible/root", "org.a11y.atspi.Accessible", "GetChildren")
try:
    conn.call_blocking("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                       "asu", ([], 0), timeout=5)
    out["monitor"] = "ok"
except dbus.DBusException as e:
    out["monitor"] = e.get_dbus_name().rsplit(".", 1)[-1]
out["session_bus"] = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
print(json.dumps(out))
"""

needs_python_dbus = pytest.mark.skipif(
    not shutil.which("python3") or subprocess.run(["python3", "-c", "import dbus, gi"]).returncode != 0,
    reason="needs python3-dbus and python3-gi (run provision.sh)")


@pytest.fixture
def a11y_bus_daemon(runtime, tmp_path):
    """A bus with a fake registry on it, standing in for the accessibility bus (which has no policy either)."""
    path = runtime / "at-spi-test"
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1", f"--address=unix:path={path}"],
                              stdout=subprocess.PIPE, text=True, env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime)})
    daemon.stdout.readline()
    script = tmp_path / "registry.py"
    script.write_text(FAKE_REGISTRY)
    registry = subprocess.Popen(["python3", str(script), f"unix:path={path}"], stdout=subprocess.PIPE, text=True,
                                env={"PATH": "/usr/bin:/bin"})
    assert registry.stdout.readline().strip() == "ready"
    yield str(path)
    registry.terminate()
    registry.wait()
    daemon.terminate()
    daemon.wait()


@integration
@needs_proxy
@needs_python_dbus
def test_an_app_registers_and_is_refused_everything_else_end_to_end(sandbox, runtime, a11y_bus_daemon):
    env = build(sandbox, runtime)["host_env"] | {"AT_SPI_BUS_ADDRESS": f"unix:path={a11y_bus_daemon}"}
    with dbusproxy.A11yProxy(env) as sock:
        kw = build(sandbox, runtime, accessibility=True)
        (kw["root"] / "AppRun").write_text(APP_PROBE)
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, a11y_socket=sock)], timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["embed"] == "ok" and got["registered_events"] == "ok" and got["listeners"] == "ok"
    for refused in ("register_keys", "register_event", "children", "monitor"):
        assert got[refused] == "AccessDenied", (refused, got)
    assert got["session_bus"] is None
    assert not os.path.exists(sock)  # the proxy stopped and its directory is gone
