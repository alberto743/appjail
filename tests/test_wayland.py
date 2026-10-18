# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import array
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

from bjail import jail, wayland
from bjail.jail import RunError

from .test_runner import build, integration, sandbox  # noqa: F401


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
                payload, buf = buf[8:size], buf[size:]
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


def test_globals_are_listed(compositor):
    c, env = compositor(["wl_compositor", "zwlr_screencopy_manager_v1"])
    assert wayland.advertised(env) == {"wl_compositor", "zwlr_screencopy_manager_v1"}


def test_no_protocol_means_no_restricted_socket(compositor):
    c, env = compositor(["wl_compositor"])
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
    c, env = compositor([wayland.MANAGER], fail_commit=True)
    with pytest.raises(RunError, match="boom"):
        with wayland.RestrictedSocket(env):
            pass
    assert not list(Path(env["XDG_RUNTIME_DIR"]).glob("bjail-wl-*"))


def test_missing_host_socket_is_an_error(sandbox):
    with pytest.raises(RunError, match="not found"):
        wayland.advertised({"XDG_RUNTIME_DIR": str(sandbox), "WAYLAND_DISPLAY": "nope"})


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
        host_globals = wayland.advertised(env)
        assert wayland.MANAGER in host_globals
        with wayland.RestrictedSocket(env, app_id="test") as path:
            restricted = wayland.advertised({"XDG_RUNTIME_DIR": str(Path(path).parent), "WAYLAND_DISPLAY": "wayland-0"})
            hidden = host_globals - restricted
            assert "wl_compositor" in restricted and wayland.MANAGER not in restricted
            assert "zwlr_screencopy_manager_v1" in host_globals and "zwlr_screencopy_manager_v1" in hidden
            assert "zwp_virtual_keyboard_manager_v1" in hidden
            kw = build(sandbox, rt, audio=False)
            kw["host_env"] = env
            (kw["root"] / "AppRun").write_text("#!/bin/sh\nexec /usr/bin/timeout 3 /usr/bin/weston-simple-shm\n")
            (kw["root"] / "AppRun").chmod(0o755)
            proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw, wayland_socket=path)], timeout=30)
            assert proc.returncode == 124, proc.stderr  # still running at the timeout = it connected
        assert not Path(path).parent.exists()
    finally:
        sway.terminate()
        sway.wait(timeout=10)
        log.close()
