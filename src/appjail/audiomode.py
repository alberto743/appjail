# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Which audio path an app gets for its `audio` and `mic` permissions.

`pulse` binds the host's Pulse socket, which always includes microphone capture. `pipewire` is a private PipeWire graph
(audiojail.py) that exposes only playback, and the microphone when `mic` is granted. When the graph cannot be used the
app falls back to the Pulse socket, and says so.
"""

from pathlib import Path

from . import audiojail

PULSE, PIPEWIRE = "pulse", "pipewire"


def host_pulse(host_env):
    """The host's Pulse socket, or None."""
    rt = host_env.get("XDG_RUNTIME_DIR")
    path = Path(rt) / "pulse" / "native" if rt else None
    return str(path) if path and path.is_socket() else None


def fallback_note(reason, has_pulse=True):
    """What to tell when `pipewire` was asked for and the Pulse socket is used instead."""
    if not has_pulse:
        return f"audio_mode pipewire is not available ({reason}) and the host has no Pulse socket either: this app gets no audio"
    return (f"audio_mode pipewire is not available ({reason}): this app gets the host's Pulse socket, "
            "which also lets it record from the microphone")


def resolve(perms, host_env, availability=None):
    """(backend, note): the backend to try (None without audio), and a warning when it is not what was asked."""
    if not perms.audio:
        return None, None
    pulse = host_pulse(host_env)
    if perms.audio_mode == PULSE:
        return PULSE, None
    ok, reason = (availability or audiojail.availability)(pulse)
    if ok:
        return PIPEWIRE, None
    return PULSE, fallback_note(reason, pulse is not None)
