# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `audio` permission against a real PipeWire: the app reaches Pulse, never PipeWire's own socket.

PipeWire restricts only clients it recognises as sandboxed (a .flatpak-info in their root), so a jailed client on
pipewire-0 is unrestricted: it sees every node, cameras included. A private PipeWire with a test video source (the
camera stand-in: the guest has no video device) shows both sides.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from appjail import jail, runtimejail, seccomp

from .helpers import build, integration, wait_for

CAMERA = "appjail-test-camera"
DROP_IN = f"""context.spa-libs = {{ videotestsrc = videotestsrc/libspa-videotestsrc }}
context.objects = [
  {{ factory = adapter args = {{ factory.name = videotestsrc node.name = {CAMERA} media.class = Video/Source }} }}
]
"""
CONNECT_PULSE = ("import os, socket; s = socket.socket(socket.AF_UNIX); "
                 "s.connect(os.environ['PULSE_SERVER'].removeprefix('unix:')); print('pulse ok')")


def node_names(dump):
    try:
        return [o["info"]["props"].get("node.name") for o in json.loads(dump) if o.get("type", "").endswith("Node")]
    except (ValueError, KeyError, TypeError):
        return []


@pytest.fixture
def pipewire():
    """A private PipeWire and pipewire-pulse; yields their runtime directory (which also holds a fake Wayland socket)."""
    if not all(shutil.which(b) for b in ("pipewire", "pipewire-pulse", "pw-dump")):
        pytest.skip("needs pipewire, pipewire-pulse and pw-dump (tests/vm/packages.txt)")
    base = Path(tempfile.mkdtemp(prefix="pw"))  # short: sun_path is limited
    rt, conf = base / "rt", base / "cfg" / "pipewire" / "pipewire.conf.d"
    rt.mkdir(mode=0o700)
    conf.mkdir(parents=True)
    (conf / "camera.conf").write_text(DROP_IN)
    wl = socket.socket(socket.AF_UNIX)
    wl.bind(str(rt / "wayland-test"))
    env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt), "XDG_CONFIG_HOME": str(base / "cfg"), "HOME": str(base)}
    procs = []
    try:
        procs.append(subprocess.Popen(["pipewire"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert wait_for(lambda: (rt / "pipewire-0").is_socket(), 10), "pipewire did not start"
        procs.append(subprocess.Popen(["pipewire-pulse"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert wait_for(lambda: (rt / "pulse" / "native").is_socket(), 10), "pipewire-pulse did not start"
        def camera_seen():
            dump = subprocess.run(["pw-dump"], env=env, capture_output=True, text=True, timeout=10).stdout
            return CAMERA in node_names(dump)
        assert wait_for(camera_seen, 10), "the test video source did not appear"
        yield rt
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)
        wl.close()
        shutil.rmtree(base, ignore_errors=True)


def in_audio_jail(sandbox, rt, command, extra_binds=()):
    """Run command in the app jail of an app with `audio` (extra_binds go in before the root is made read-only)."""
    kw = build(sandbox, rt, audio=True)
    kw["command"] = command
    fd = seccomp.open_fd(False)
    try:
        args = runtimejail.runtime_args(**kw, seccomp_fd=fd)
        i = args.index("--remount-ro")
        args[i:i] = list(extra_binds)
        return jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd,))
    finally:
        os.close(fd)


@integration
def test_audio_reaches_pulse_but_not_pipewire(sandbox, pipewire):
    assert "pulse ok" in in_audio_jail(sandbox, pipewire, ["/usr/bin/python3", "-c", CONNECT_PULSE]).stdout
    assert CAMERA not in node_names(in_audio_jail(sandbox, pipewire, ["/usr/bin/pw-dump"]).stdout)


@integration
def test_pipewire_socket_would_expose_the_camera(sandbox, pipewire):
    """The reason the socket is withheld (and proof the fixture works): a jailed client on pipewire-0 sees the camera."""
    rt = f"/run/user/{os.getuid()}"
    proc = in_audio_jail(sandbox, pipewire, ["/usr/bin/pw-dump"], ["--ro-bind", str(pipewire / "pipewire-0"), f"{rt}/pipewire-0"])
    assert CAMERA in node_names(proc.stdout)
