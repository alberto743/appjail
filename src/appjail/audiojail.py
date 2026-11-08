# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A private PipeWire graph for one app's `audio` and `mic`.

Three daemons (pipewire, wireplumber, pipewire-pulse) run in their own jail: no network, no host files except their
runtime directory, a read-only configuration and the host's Pulse socket. The only nodes in their graph are tunnels to
the host's Pulse server: a sink always, a source only with `mic`. The app jail gets this graph's sockets and nothing of
the host's PipeWire, so it sees neither the host's devices, nor cameras, nor other apps' streams, and without `mic` it
has no microphone at all. The tunnels follow the host's default devices only at connection time (see DECISIONS.md).
"""

import collections
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import jail, textsafe
from .errors import JailError

RUNTIME = "/run/appaudio"
CONFIG = "/etc/appaudio"
HOST_PULSE = "/run/hostpulse/native"
TOOLS = ("pipewire", "wireplumber", "pipewire-pulse", "pw-dump")
SINK, SOURCE = "app-speaker", "app-mic"
DRIVERS = ("Dummy-Driver", "Freewheel-Driver")
READY_TIMEOUT = 15.0
DUMP_TIMEOUT = 4.0  # one look at the graph; a daemon that is not answering yet must not use up the whole start
SETTLE = 0.6  # WirePlumber's device monitors start a moment after it connects; look for strays after that
WIREPLUMBER_CONF = ("wireplumber.profiles = { main = { hardware.audio = disabled, hardware.video-capture = disabled, "
                    "hardware.bluetooth = disabled } }\n")
# WirePlumber connects to PipeWire once and, if the socket is not there yet, stays up without a connection for good (found on a
# loaded Ubuntu 26.04 guest: "Failed to connect to PipeWire" 0.4 ms before the socket appeared). So the others start only once
# PipeWire answers.
DAEMONS = "pipewire & until pw-dump >/dev/null 2>&1; do sleep 0.05; done; wireplumber & pipewire-pulse & wait"


class AudioUnavailable(Exception):
    """The private graph cannot be used; the message says why (the caller falls back to the host's Pulse socket)."""


def _in_jail_system(path):
    """Whether a tool at this path is visible inside a helper jail, which sees only the system directories."""
    real = os.path.realpath(path)
    return any(real == d or real.startswith(d + "/") for d in jail.SYSTEM_DIRS)


def availability(host_pulse_socket, which=shutil.which, module_dirs=None):
    """(True, "") when the private graph can be tried, else (False, reason)."""
    for tool in TOOLS:
        path = which(tool)
        if not path:
            return False, f"{tool} is not installed"
        if not _in_jail_system(path):
            return False, f"{tool} is not under /usr, where the audio jail can see it"
    if module_dirs is None:
        module_dirs = [*Path("/usr/lib").glob("*/pipewire-0.3"), Path("/usr/lib/pipewire-0.3")]
    if not any((Path(d) / "libpipewire-module-pulse-tunnel.so").exists() for d in module_dirs):
        return False, "PipeWire's pulse-tunnel module is missing"
    if not (host_pulse_socket and Path(host_pulse_socket).is_socket()):
        return False, "the host has no Pulse socket (pipewire-pulse or PulseAudio is not running)"
    return True, ""


def pipewire_conf(mic):
    """The private daemon's configuration: tunnels to the host's Pulse server, a source only with `mic`."""
    def tunnel(mode, name, klass):
        return (f'  {{ name = libpipewire-module-pulse-tunnel args = {{ tunnel.mode = {mode} pulse.server.address = "unix:{HOST_PULSE}" '
                f'node.name = {name} stream.props = {{ media.class = {klass} }} }} }}\n')
    return "context.modules = [\n" + tunnel("sink", SINK, "Audio/Sink") + (tunnel("source", SOURCE, "Audio/Source") if mic else "") + "]\n"


def hostname_for(name):
    """The jail's hostname, which the tunnel puts in its stream's name ("Tunnel for USER@HOSTNAME") on the host."""
    host = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:63].strip("-")
    return host or "app"


def daemon_args(runtime_dir, config_dir, passwd_file, host_pulse_socket, command, hostname="app"):
    """bwrap arguments (without the bwrap path) that run command with the private daemons' view of the system."""
    return (jail.common_args() + ["--hostname", hostname]
            + ["--bind", str(runtime_dir), RUNTIME, "--ro-bind", str(config_dir), CONFIG, "--ro-bind", str(passwd_file), "/etc/passwd",
               "--ro-bind", str(host_pulse_socket), HOST_PULSE,
               "--setenv", "XDG_RUNTIME_DIR", RUNTIME, "--setenv", "XDG_CONFIG_HOME", CONFIG,
               "--remount-ro", "/", "--"] + list(command))


def graph_nodes(dump):
    """The node names in a pw-dump listing, and whether WirePlumber's client is there. ([], False) for anything unreadable."""
    try:
        objects = json.loads(dump)
        names = [o["info"]["props"].get("node.name") for o in objects if str(o.get("type", "")).endswith("Node")]
        wp = any(str(o.get("type", "")).endswith("Client") and o["info"]["props"].get("application.name") == "WirePlumber" for o in objects)
    except (ValueError, KeyError, TypeError, AttributeError):
        return [], False
    return [n for n in names if isinstance(n, str)], wp


def unexpected(nodes, mic):
    """The nodes that should not be in the private graph."""
    allowed = {*DRIVERS, SINK, *([SOURCE] if mic else [])}
    return sorted(set(nodes) - allowed)


class PrivateAudio:
    """The running private graph: `with PrivateAudio(...) as audio:` then audio.pipewire_socket and audio.pulse_socket.

    Raises AudioUnavailable when the daemons do not come up, or when the graph holds anything it should not.
    """

    def __init__(self, name, mic, host_pulse_socket, host_runtime_dir, uid, gid, timeout=READY_TIMEOUT):
        self.name, self.mic, self.host_pulse, self.uid, self.gid, self.timeout = name, mic, str(host_pulse_socket), uid, gid, timeout
        self.base = Path(tempfile.mkdtemp(prefix="appjail-audio-", dir=host_runtime_dir))  # private (0700) and short: sun_path is limited
        self.runtime = self.base / "rt"
        self.proc = None
        self.last_error = ""
        self.log = collections.deque(maxlen=30)  # the last lines the daemons wrote: memory only, bounded

    @property
    def pipewire_socket(self):
        return self.runtime / "pipewire-0"

    @property
    def pulse_socket(self):
        return self.runtime / "pulse" / "native"

    def __enter__(self):
        try:
            self._start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def _write_config(self):
        config = self.base / "cfg"
        for sub, text in (("pipewire/pipewire.conf.d", pipewire_conf(self.mic)), ("wireplumber/wireplumber.conf.d", WIREPLUMBER_CONF)):
            (config / sub).mkdir(parents=True)
            (config / sub / "appjail.conf").write_text(text)
        passwd = self.base / "passwd"
        passwd.write_text(f"app:x:{self.uid}:{self.gid}::/tmp:/usr/sbin/nologin\n")
        self.runtime.mkdir(mode=0o700)
        return config, passwd

    def _jail_argv(self, command, config, passwd):
        return [jail.find_bwrap(), *daemon_args(self.runtime, config, passwd, self.host_pulse, command, hostname_for(self.name))]

    def _dump(self, config, passwd):
        """The listing of the graph, or None when it could not be had (not answering yet, or too slow): never an exception."""
        try:
            proc = jail.supervise(self._jail_argv(["/usr/bin/pw-dump"], config, passwd), timeout=DUMP_TIMEOUT, keep=1 << 20)  # whole JSON
        except JailError as e:
            self.last_error = textsafe.clean(str(e), 160)
            return None
        self.last_error = textsafe.clean(proc.stderr.strip().splitlines()[-1], 160) if proc.returncode and proc.stderr.strip() else ""
        return proc.stdout if proc.returncode == 0 else None

    def _collect(self, stream):
        for line in stream:
            self.log.append(line.rstrip())

    def _said(self):
        """What the daemons last wrote, for the message that says why the graph is unusable."""
        lines = [line for line in list(self.log) if line.strip()][-3:]
        return f"; the daemons said: {textsafe.clean(' | '.join(lines), 300)}" if lines else ""

    def _start(self):
        config, passwd = self._write_config()
        self.proc = subprocess.Popen(self._jail_argv(["/bin/sh", "-c", DAEMONS], config, passwd), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
        threading.Thread(target=self._collect, args=(self.proc.stdout,), daemon=True).start()
        wanted = {SINK, *([SOURCE] if self.mic else [])}
        self._wait_until_up(config, passwd, wanted)
        time.sleep(SETTLE)
        nodes = self._look_again(config, passwd, wanted)
        if stray := unexpected(nodes, self.mic):
            raise AudioUnavailable("the private audio graph holds nodes it should not: " + textsafe.clean(", ".join(stray), 200))

    def _wait_until_up(self, config, passwd, wanted):
        """Return when both sockets exist, WirePlumber is connected and the wanted nodes are there."""
        deadline = time.monotonic() + self.timeout
        nodes, wp = [], False
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AudioUnavailable("the private audio daemons exited" + self._said())
            if self.pipewire_socket.is_socket() and self.pulse_socket.is_socket():
                text = self._dump(config, passwd)
                if text is not None:
                    nodes, wp = graph_nodes(text)
                    if wanted <= set(nodes) and wp:
                        return
            time.sleep(0.2)
        seen = textsafe.clean(", ".join(sorted(set(nodes))) or "nothing", 200)
        detail = f"nodes seen: {seen}; WirePlumber {'connected' if wp else 'not connected'}"
        if self.last_error:
            detail += f"; pw-dump said: {self.last_error}"
        raise AudioUnavailable(f"the private audio graph did not come up in time ({detail}{self._said()})")

    def _look_again(self, config, passwd, wanted):
        """The nodes seen after the settle: an unreadable look is not a clean one, so it is repeated and then fails."""
        for _ in range(3):
            text = self._dump(config, passwd)
            nodes = graph_nodes(text)[0] if text is not None else []
            if wanted <= set(nodes):
                return nodes
        raise AudioUnavailable("the private audio graph could not be checked" + (f" ({self.last_error})" if self.last_error else "") + self._said())

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        shutil.rmtree(self.base, ignore_errors=True)
