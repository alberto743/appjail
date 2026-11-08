# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Which audio path an app gets for its `audio` and `mic` permissions.

`pulse` binds the host's Pulse socket, which always includes microphone capture. `pipewire` is a private PipeWire graph
(audiojail.py) that exposes only playback, and the microphone when `mic` is granted. When the graph cannot be used, an app
with `mic` falls back to the Pulse socket and one without gets no audio, and a warning says so.

The host's Pulse socket is never bound when the server behind it is PulseAudio itself: a client of PulseAudio can make it load
a library of the client's choosing (`module-ladspa-sink` with an absolute path), which runs the client's code in the server,
outside the jail (reproduced on PulseAudio 17.0). PipeWire's Pulse server does not implement that.
"""

import os
import socket
import time
from pathlib import Path

from . import audiojail

PULSE, PIPEWIRE = "pulse", "pipewire"
PULSEAUDIO = "pulseaudio"  # the process name of PulseAudio proper
UNSAFE_SERVER = ("the host's Pulse server is PulseAudio, which a client can make load its own code, outside the jail "
                 "(PipeWire's Pulse server cannot be made to)")


def host_pulse(host_env):
    """The host's Pulse socket, or None."""
    rt = host_env.get("XDG_RUNTIME_DIR")
    path = Path(rt) / "pulse" / "native" if rt else None
    return str(path) if path and path.is_socket() else None


def _holders(inode, proc):
    """The names of the processes that hold the socket with this inode, except systemd (which holds a socket-activated one)."""
    names = set()
    for fds in Path(proc).glob("[0-9]*/fd"):
        try:
            if any(os.readlink(fd) == f"socket:[{inode}]" for fd in fds.iterdir()):
                names.add((fds.parent / "comm").read_text().strip())
        except OSError:
            continue
    return names - {"systemd"}


def host_server(path, proc="/proc", unix_table="/proc/net/unix", wait=3.0):
    """The process name of the server behind a unix socket (`pulseaudio`, `pipewire-pulse`, ...), or None when it cannot be told.

    Found through the inode of the listening socket, since a socket-activated server's peer credentials are systemd's. When only
    systemd holds it, a connection starts the server and the answer is awaited for `wait` seconds."""
    real = os.path.realpath(path)
    try:
        rows = [line.split() for line in Path(unix_table).read_text().splitlines()[1:]]
    except OSError:
        return None
    inodes = [r[6] for r in rows if len(r) >= 8 and os.path.realpath(r[7]) == real and r[5] == "01"]
    if not inodes:
        return None
    names = _holders(inodes[0], proc)
    if not names:  # socket activation: ask for the server to be started, then look again
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(wait)
            try:
                s.connect(str(path))
            except OSError:
                return None
            deadline = time.monotonic() + wait
            while not names and time.monotonic() < deadline:
                time.sleep(0.1)
                names = _holders(inodes[0], proc)
    return PULSEAUDIO if PULSEAUDIO in names else (min(names) if names else None)


def usable_pulse(host_env, server=host_server):
    """(socket, "") when an app may be given the host's Pulse socket, else (None, why): there is none, or it is PulseAudio's."""
    path = host_pulse(host_env)
    if path and server(path) == PULSEAUDIO:
        return None, UNSAFE_SERVER
    return path, ""


def fallback(perms, reason, has_pulse, refused=""):
    """(backend, note) for an app that asked for `pipewire` when the private graph cannot be used.

    The host's Pulse socket always includes capture, so only an app granted `mic` may have it. An app without `mic` gets no
    audio rather than a microphone it was not given.
    """
    why = f"audio_mode pipewire is not available ({reason})"
    if not perms.mic:
        return None, (f"{why}: this app gets no audio, because the host's Pulse socket would also open the microphone, which it "
                      "was not granted" + (f" (and {refused})" if refused else ""))
    if refused:
        return None, f"{why} and {refused}: this app gets no audio"
    if not has_pulse:
        return None, f"{why} and the host has no Pulse socket either: this app gets no audio"
    return PULSE, f"{why}: this app gets the host's Pulse socket, which also lets it record from the microphone"


def resolve(perms, host_env, availability=None, server=host_server):
    """(backend, note): the backend to try (None without audio, or when none may be used), and a warning when it is not what was asked."""
    if not perms.audio:
        return None, None
    pulse, refused = usable_pulse(host_env, server)
    if perms.audio_mode == PULSE:
        if refused:
            return None, f"audio_mode pulse is refused: {refused}. This app gets no audio; use audio_mode pipewire"
        return PULSE, None
    ok, reason = (availability or audiojail.availability)(host_pulse(host_env))
    if ok:
        return PIPEWIRE, None
    return fallback(perms, reason, pulse is not None, refused)
