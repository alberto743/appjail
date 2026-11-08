# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A host whose Pulse server is PulseAudio itself (GUEST=debian-pulse; everywhere else these tests skip).

PulseAudio lets a client make it load a library of the client's choosing (`module-ladspa-sink` with an absolute path), which
runs the client's code in the server, outside the jail. PipeWire's Pulse server does not implement that. So appjail never
gives an app the socket of a PulseAudio server (`audio_mode = pulse` and the fallback), and the default private graph, whose
`pipewire-pulse` refuses module loading, is safe on such a host.
"""

import os
import shutil
import subprocess

import pytest

from appjail import audiojail, audiomode, jail, runtimejail, seccomp
from appjail.manifest import Permissions

from .helpers import build, integration

LIBRARY = r"""
#include <stdio.h>
#include <unistd.h>
__attribute__((constructor)) static void init(void) {
    FILE *f = fopen(MARKER, "a");
    if (f) { fprintf(f, "loaded into pid %d", getpid()); fclose(f); }
}
"""


@pytest.fixture
def host():
    """(environment, Pulse socket) of a host running PulseAudio proper, else a skip."""
    for tool in ("pactl", "gcc"):
        if not shutil.which(tool):
            pytest.skip(f"needs {tool}")
    env = {"XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""), "LANG": "C.UTF-8"}
    socket_path = audiomode.host_pulse(env)
    if not socket_path or audiomode.host_server(socket_path) != audiomode.PULSEAUDIO:
        pytest.skip("the host's Pulse server is not PulseAudio (tests/vm/create.sh, GUEST=debian-pulse)")
    return env, socket_path


@pytest.fixture
def library(tmp_path):
    """A shared library whose constructor leaves a marker naming the process that loaded it."""
    marker = tmp_path / "marker"
    src = tmp_path / "evil.c"
    src.write_text(LIBRARY)
    out = tmp_path / "evil.so"
    subprocess.run(["gcc", "-shared", "-fPIC", f'-DMARKER="{marker}"', "-o", str(out), str(src)], check=True)
    return out, marker


def pactl(*args):
    r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


@integration
def test_pulseaudio_loads_a_library_a_client_names(host, library):
    """The reason for the refusal below: if this stops being true, the refusal can be reconsidered."""
    so, marker = library
    pactl("load-module", "module-ladspa-sink", f"plugin={so}", "label=probe", "sink_name=probe")
    assert marker.exists() and "loaded into pid" in marker.read_text()


@integration
def test_pulse_mode_and_the_fallback_get_no_socket_from_pulseaudio(host):
    env, _ = host
    backend, note = audiomode.resolve(Permissions(audio=True, audio_mode="pulse"), env)
    assert backend is None and "refused" in note and "PulseAudio" in note
    for mic in (False, True):
        backend, note = audiomode.resolve(Permissions(audio=True, mic=mic), env, availability=lambda s: (False, "no graph"))
        assert backend is None and "PulseAudio" in note


@integration
def test_the_private_graph_on_a_pulseaudio_host_refuses_what_pulseaudio_would_load(host, library, tmp_path):
    env, socket_path = host
    so, marker = library
    ok, why = audiojail.availability(socket_path)
    if not ok:
        pytest.skip(why)
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    shutil.copy(so, sandbox / "evil.so")
    with audiojail.PrivateAudio("probe", False, socket_path, env["XDG_RUNTIME_DIR"], os.getuid(), os.getgid()) as audio:
        kw = build(sandbox, env["XDG_RUNTIME_DIR"], audio=True, display="none")
        kw["host_env"] = env
        (sandbox / "home" / "evil.so").write_bytes(so.read_bytes())

        def in_jail(command):
            kw["command"] = command
            fd = seccomp.open_fd(False)
            try:
                args = runtimejail.runtime_args(**kw, audio_sockets=(audio.pipewire_socket, audio.pulse_socket), seccomp_fd=fd)
                return jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd,), keep=1 << 20)
            finally:
                os.close(fd)

        sources = in_jail(["/usr/bin/pactl", "list", "short", "sources"]).stdout
        assert "app-speaker" in sources and "host-mic" not in sources  # the app's own tunnel, none of the host's devices
        for module in ("module-ladspa-sink plugin=/home/app/evil.so label=probe", f"module-tunnel-source server=unix:{audiojail.HOST_PULSE}"):
            load = in_jail(["/usr/bin/pactl", "load-module", *module.split()])
            assert load.returncode != 0, load.stdout
    assert not marker.exists()
