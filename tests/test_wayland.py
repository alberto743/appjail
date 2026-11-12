# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import array
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest

from appjail import jail, runtimejail, wayland
from appjail.errors import RunError

from .helpers import build, integration


def event(obj, opcode, payload=b""):
    return struct.pack("II", obj, ((8 + len(payload)) << 16) | opcode) + payload


def global_event(name, iface, version=1):
    return event(wayland.REGISTRY_ID, 0, struct.pack("I", name) + wayland._string(iface) + struct.pack("I", version))


class FakeCompositor(threading.Thread):
    """Serves one connection: answers get_registry and sync, records fds and requests."""

    def __init__(self, path, interfaces, fail_commit=False):
        super().__init__(daemon=True)
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(str(path))
        self.srv.listen(4)
        self.interfaces, self.fail_commit = interfaces, fail_commit
        self.requests, self.fds = [], []

    def run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.serve(conn)

    def serve(self, conn):
        buf = b""
        while True:
            try:
                data, anc, _, _ = conn.recvmsg(4096, socket.CMSG_SPACE(16))
            except OSError:
                return
            if not data:
                return
            for level, kind, raw in anc:
                if kind == socket.SCM_RIGHTS:
                    fds = array.array("i")
                    fds.frombytes(raw[:len(raw) - len(raw) % 4])
                    self.fds += list(fds)
            buf += data
            while len(buf) >= 8:
                obj, word = struct.unpack("II", buf[:8])
                size = word >> 16
                if len(buf) < size:
                    break
                buf = buf[size:]
                op = word & 0xFFFF
                self.requests.append((obj, op))
                if obj == wayland.DISPLAY_ID and op == 1:
                    for i, iface in enumerate(self.interfaces):
                        conn.sendall(global_event(i + 1, iface))
                elif obj == wayland.DISPLAY_ID and op == 0:
                    if self.fail_commit:
                        msg = wayland._string("boom")
                        conn.sendall(event(wayland.DISPLAY_ID, 0, struct.pack("II", 5, 2) + msg))
                    conn.sendall(event(wayland.CALLBACK_ID, 0, struct.pack("I", 0)))


@pytest.fixture
def compositor(sandbox):
    path = sandbox / "wl"

    def start(interfaces, **kw):
        c = FakeCompositor(path, interfaces, **kw)
        c.start()
        env = {"XDG_RUNTIME_DIR": str(sandbox), "WAYLAND_DISPLAY": "wl"}
        return c, env
    return start


def advertised(host_env):
    """Interface names the compositor offers (a connection that only reads the registry)."""
    sock, _, found = wayland._connect(host_env)
    sock.close()
    return set(found)


def test_globals_are_listed(compositor):
    _c, env = compositor(["wl_compositor", "zwlr_screencopy_manager_v1"])
    assert advertised(env) == {"wl_compositor", "zwlr_screencopy_manager_v1"}


def test_no_protocol_means_no_restricted_socket(compositor):
    _c, env = compositor(["wl_compositor"])
    with wayland.RestrictedSocket(env) as path:
        assert path is None


def test_restricted_socket_is_registered_and_cleaned_up(compositor):
    c, env = compositor(["wl_compositor", wayland.MANAGER])
    with wayland.RestrictedSocket(env, app_id="demo") as path:
        assert Path(path).is_socket() and Path(path).parent.parent == Path(env["XDG_RUNTIME_DIR"])
        assert (wayland.MANAGER_ID, 1) in c.requests  # create_listener
        assert [op for obj, op in c.requests if obj == wayland.CONTEXT_ID] == [1, 2, 3, 4]
        directory = Path(path).parent
    assert not directory.exists()


def test_protocol_error_is_reported_and_leaves_nothing(compositor):
    _c, env = compositor([wayland.MANAGER], fail_commit=True)
    with pytest.raises(RunError, match="boom"), wayland.RestrictedSocket(env):
        pass
    assert not list(Path(env["XDG_RUNTIME_DIR"]).glob("appjail-wl-*"))


def test_missing_host_socket_is_an_error(sandbox):
    with pytest.raises(RunError, match="not found"):
        advertised({"XDG_RUNTIME_DIR": str(sandbox), "WAYLAND_DISPLAY": "nope"})


# -- what a socket lets a client do, read from its registry -------------------------------------------------


def test_interfaces_reads_the_registry_of_the_own_and_of_another_socket(compositor, sandbox):
    _c, env = compositor(["wl_compositor", "zwlr_screencopy_manager_v1"])
    assert wayland.interfaces(env) == {"wl_compositor", "zwlr_screencopy_manager_v1"}
    assert wayland.interfaces({}, path=sandbox / "wl") == {"wl_compositor", "zwlr_screencopy_manager_v1"}


def test_registry_gives_the_versions_and_read_registry_reads_a_connection_handed_over(compositor, sandbox):
    _c, env = compositor(["wl_compositor", "zwlr_screencopy_manager_v1"])
    assert wayland.registry(env) == {"wl_compositor": 1, "zwlr_screencopy_manager_v1": 1}
    with socket.socket(socket.AF_UNIX) as sock:
        sock.connect(str(sandbox / "wl"))
        assert wayland.read_registry(sock) == {"wl_compositor": 1, "zwlr_screencopy_manager_v1": 1}


@pytest.fixture
def dead_socket(sandbox, monkeypatch):
    """A socket path that is bound but never listening (connections are refused), and the sleeps taken while waiting."""
    slept = []
    monkeypatch.setattr(wayland.time, "sleep", slept.append)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(sandbox / "dead"))
    yield sandbox / "dead", slept
    listener.close()


def test_a_socket_that_refuses_connections_is_waited_for_then_reported(dead_socket):
    path, slept = dead_socket
    with pytest.raises(ConnectionRefusedError):
        wayland.interfaces({}, path=path)
    assert len(slept) == wayland.CONNECT_ATTEMPTS - 1


def test_the_compositors_own_socket_is_not_waited_for(dead_socket):
    path, slept = dead_socket
    with pytest.raises(ConnectionRefusedError):
        wayland.interfaces({"XDG_RUNTIME_DIR": str(path.parent), "WAYLAND_DISPLAY": path.name})
    assert slept == []


def test_the_privileged_set_groups_by_capability_and_ignores_harmless_globals():
    names = {"wl_compositor", "zwp_keyboard_shortcuts_inhibit_manager_v1", "ext_output_image_capture_source_manager_v1",
             "zwlr_screencopy_manager_v1", "zwlr_data_control_manager_v1", "zwp_virtual_keyboard_manager_v1"}
    assert wayland.privileged(names) == {"capture": ["zwlr_screencopy_manager_v1"],
                                         "input": ["zwp_virtual_keyboard_manager_v1"],
                                         "clipboard": ["zwlr_data_control_manager_v1"]}
    assert wayland.privileged({"wl_compositor", "zwp_keyboard_shortcuts_inhibit_manager_v1"}) == {}
    assert "capture the screen" in wayland.describe({"capture": ["zwlr_screencopy_manager_v1"]})


def test_a_global_in_neither_list_is_unknown_and_named_last():
    found = wayland.privileged({"wl_compositor", "zcosmic_future_manager_v1", "zwlr_screencopy_manager_v1"})
    assert found == {"capture": ["zwlr_screencopy_manager_v1"], wayland.UNKNOWN: ["zcosmic_future_manager_v1"]}
    text = wayland.describe(found)
    assert text.index("zwlr_screencopy_manager_v1") < text.index("zcosmic_future_manager_v1")
    assert "not known to it" in text


def test_the_lists_do_not_overlap_and_every_kind_says_what_it_allows():
    assert not wayland.ALLOWED & set(wayland.PRIVILEGED_BY_NAME)
    assert set(wayland.CAPABILITY) == set(wayland.PRIVILEGED) | {wayland.UNKNOWN}


@pytest.mark.parametrize("name", ["ext_idle_notifier_v1", "wp_drm_lease_device_v1", "zwp_pointer_constraints_v1",
                                  "zwp_keyboard_shortcuts_inhibit_manager_v1", "ext_output_image_capture_source_manager_v1"])
def test_the_globals_allowed_after_a_decision_stay_allowed(name):
    """README.md, "Wayland compositors", names these; moving one means changing the docs and refusing compositors."""
    assert name in wayland.ALLOWED


def test_the_survey_tool_counts_what_the_rule_counts_and_names_what_it_adds():
    """tests/compositors/probe.py takes its list from wayland.PRIVILEGED; it adds only EXTRA, which the rule leaves out."""
    spec = importlib.util.spec_from_file_location("probe", Path(__file__).parent / "compositors" / "probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    extra = {n for names in probe.EXTRA.values() for n in names}
    assert not extra & set(wayland.PRIVILEGED_BY_NAME)
    names = set(wayland.PRIVILEGED_BY_NAME) | extra | {"wl_compositor"}
    assert {n for found in probe.classify(names).values() for n in found} == names - {"wl_compositor"}
    assert probe.classify({"wl_compositor", *extra}) == {"capture": sorted(probe.EXTRA["capture"]), "input": sorted(probe.EXTRA["input"])}
    assert wayland.privileged({"wl_compositor", *extra}) == {}
    assert probe.SECURITY_CONTEXT == wayland.MANAGER


ASSESSMENT = Path(__file__).resolve().parents[1] / "docs" / "compositor-assessment"


def measured():
    """(label, registry of the socket an app would get, what the live run of option A decided) for every compositor surveyed."""
    out = []
    for results in sorted(ASSESSMENT.glob("results-*.json")):
        survey = json.loads(results.read_text())
        decided = json.loads(results.with_name(results.name.replace("results-", "rule-a-")).read_text())
        for name, entry in survey["compositors"].items():
            w = entry.get("wayland")
            if entry["status"] != "ok" or not w:
                continue
            names = w.get("restricted") if w["security_context"] and w.get("restricted") is not None else w["full"]
            if w["security_context"] and w.get("restricted") is None:
                continue  # Hyprland 0.53 in the first survey: the restricted socket was not read (see rule-a-*.json)
            out.append((f"{survey['distro']['id']}-{survey['distro']['version']}-{name}", set(names), decided["compositors"][name]["verdict"]))
    return out


@pytest.mark.skipif(not ASSESSMENT.is_dir(), reason="the measurements are not in this tree")
@pytest.mark.parametrize(("label", "names", "decided"), measured(), ids=[m[0] for m in measured()])
def test_the_rule_matches_the_registries_measured_on_real_compositors(label, names, decided):
    """The registries are those of real compositors on Debian 13 and Ubuntu 26.04; `decided` is what option A decided when it
    was run live against them: GNOME, sway, labwc and Hyprland 0.55 run; KWin, Wayfire, Cage and Weston are refused."""
    assert bool(wayland.privileged(names)) == (decided == "refuse")


@pytest.mark.skipif(not ASSESSMENT.is_dir(), reason="the measurements are not in this tree")
def test_every_global_a_measured_compositor_lists_is_classified():
    """New measurements fail here until each new name is put in wayland.ALLOWED or wayland.PRIVILEGED; the full socket
    of every compositor is read too, not only the socket an app gets."""
    names = set()
    for results in ASSESSMENT.glob("results-*.json"):
        for entry in json.loads(results.read_text())["compositors"].values():
            w = entry.get("wayland") or {}
            names |= set(w.get("full") or ()) | set(w.get("restricted") or ())
    assert names, "no registry found in the saved results"
    assert wayland.privileged(names).get(wayland.UNKNOWN) is None


@integration
@pytest.mark.skipif(not shutil.which("sway") or not shutil.which("weston-simple-shm"), reason="sway or weston-simple-shm not installed")
def test_real_compositor_hides_privileged_protocols(sandbox):
    rt = Path(f"/run/user/{os.getuid()}")
    if not rt.is_dir():
        pytest.skip("no /run/user/<uid> in this session")
    (sandbox / "sway.conf").write_text("")
    before = set(rt.glob("wayland-*"))
    log = open(sandbox / "sway.log", "w")
    sway = subprocess.Popen(["sway", "-c", str(sandbox / "sway.conf")],
                            env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt), "WLR_BACKENDS": "headless",
                                 "WLR_LIBINPUT_NO_DEVICES": "1", "WLR_RENDERER": "pixman"}, stdout=log, stderr=log)
    try:
        name = None
        for _ in range(100):
            new = [p for p in rt.glob("wayland-*") if p not in before and not p.name.endswith(".lock")]
            if new:
                name = new[0].name
                break
            time.sleep(0.1)
        if name is None:
            pytest.skip("sway headless did not start: " + (sandbox / "sway.log").read_text()[-300:])
        time.sleep(0.5)
        env = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": name}
        host_globals = advertised(env)
        assert wayland.MANAGER in host_globals
        with wayland.RestrictedSocket(env, app_id="test") as path:
            restricted = advertised({"XDG_RUNTIME_DIR": str(Path(path).parent), "WAYLAND_DISPLAY": "wayland-0"})
            hidden = host_globals - restricted
            assert "wl_compositor" in restricted and wayland.MANAGER not in restricted
            assert "zwlr_screencopy_manager_v1" in host_globals and "zwlr_screencopy_manager_v1" in hidden
            assert "zwp_virtual_keyboard_manager_v1" in hidden
            kw = build(sandbox, rt, audio=False)
            kw["host_env"] = env
            (kw["root"] / "AppRun").write_text("#!/bin/sh\nexec /usr/bin/timeout 3 /usr/bin/weston-simple-shm\n")
            (kw["root"] / "AppRun").chmod(0o755)
            proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, wayland_socket=path)], timeout=30)
            assert proc.returncode == 124, proc.stderr  # still running at the timeout = it connected
        assert not Path(path).parent.exists()
    finally:
        sway.terminate()
        sway.wait(timeout=10)
        log.close()
