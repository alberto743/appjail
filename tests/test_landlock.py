# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Landlock scoping: an app with network_host shares the host's network namespace, and must not reach the abstract
unix sockets created outside its jail (the X server's first of all)."""

import os
import secrets
import socket
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from appjail import jail, landlock, manifest, runner, runtimejail, seccomp
from appjail.cli import Abort
from appjail.jail import RunError
from appjail.permargs import require_network_isolation

from .helpers import NO_RESTRICTION, build, install, integration


def extract(image, dest, fallback=False):
    (Path(dest) / "AppRun").parent.mkdir(parents=True)
    (Path(dest) / "AppRun").write_text("#!/bin/sh\n")
    return 1, 1


CONNECT = r'''#!/usr/bin/python3
import socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect("\0" + sys.argv[1]); print("connected")
except OSError as e:
    print("refused", e.errno)
'''

needs_landlock = pytest.mark.skipif(not landlock.available(), reason="needs Landlock ABI 6 (Linux 6.12 or later)")


def test_ruleset_sets_only_the_abstract_socket_scope():
    assert struct.unpack("=QQQ", landlock.RULESET_ATTR) == (0, 0, landlock.LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET)


@integration
def test_the_test_systems_offer_landlock_abi_6():
    """Debian 13 (6.12) and Ubuntu 26.04 have it; without it every network_host app would be refused."""
    assert landlock.abi() >= landlock.MIN_ABI


@integration
@needs_landlock
@pytest.mark.parametrize("restricted", [False, True])
def test_network_host_app_cannot_reach_an_outside_abstract_socket(sandbox, runtime, restricted):
    name = "appjail-test-" + secrets.token_hex(6)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind("\0" + name)
    listener.listen(1)
    kw = build(sandbox, runtime, network=True, network_host=True)
    (kw["root"] / "AppRun").write_text(CONNECT)
    (kw["root"] / "AppRun").chmod(0o755)
    kw["command"] = ["/app/AppRun", name]
    fd = seccomp.open_fd(False)
    try:
        argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd)]
        proc = jail.supervise(landlock.wrap(argv) if restricted else argv, timeout=30, pass_fds=(fd,))
    finally:
        os.close(fd)
        listener.close()
    # without the restriction the shared namespace lets it through: that is what the restriction is for
    assert proc.stdout.split()[0] == ("refused" if restricted else "connected"), proc.stderr


def test_network_host_is_refused_without_landlock(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(landlock, "available", lambda: False)
    install(sandbox, network=True, network_host=True)
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    with pytest.raises(RunError, match="Landlock"):
        runner.launch("app", host_env=env, extract=extract, say=lambda *_: None, runner=lambda argv: 0,
                      restricted=NO_RESTRICTION)
    with pytest.raises(Abort, match="Landlock"):
        require_network_isolation(manifest.Permissions(network=True, network_host=True))
    require_network_isolation(manifest.Permissions(audio=True))  # nothing else depends on it


@pytest.mark.parametrize("perms,wrapped", [({}, True), ({"network": True, "network_host": True}, True),
                                           ({"network": True}, False)])
def test_launch_puts_jails_outside_pasta_in_the_landlock_domain(sandbox, runtime, monkeypatch, perms, wrapped):
    """Behind pasta the private namespace already isolates abstract sockets (and pasta refuses no_new_privs)."""
    monkeypatch.setattr(landlock, "available", lambda: True)
    monkeypatch.setattr(jail, "find_pasta", lambda: "/usr/bin/pasta")
    install(sandbox, **perms)
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    seen = []
    runner.launch("app", host_env=env, extract=extract, say=lambda *_: None, runner=seen.append, restricted=NO_RESTRICTION)
    argv = seen[0]
    assert (argv[:3] == [sys.executable, "-I", landlock.__file__]) is wrapped
    assert argv[3 if wrapped else 0] == (jail.find_bwrap() if wrapped else "/usr/bin/pasta")


@integration
@needs_landlock
def test_the_wrapper_restricts_itself_then_runs_the_command():
    proc = subprocess.run(landlock.wrap(["/bin/sh", "-c", "grep -c . /proc/self/status >/dev/null && echo ran"]),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and proc.stdout.strip() == "ran", proc.stderr
    assert landlock.main(["landlock.py"]) == 2  # no command: usage, nothing run
