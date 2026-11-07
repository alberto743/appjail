# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Which audio path an app gets for its `audio` and `mic` permissions.

`pulse` binds the host's Pulse socket, which always includes microphone capture. `pipewire` is a private PipeWire graph
that exposes only playback, and the microphone when `mic` is granted. The private graph is not built yet, so for now a
`pipewire` request resolves to the Pulse socket and says so.
"""

PULSE, PIPEWIRE = "pulse", "pipewire"


def resolve(perms):
    """(backend, note) for these permissions: the backend actually used, and a warning to show when it is not what was asked."""
    if not perms.audio:
        return None, None
    if perms.audio_mode == PULSE:
        return PULSE, None
    return PULSE, ("audio_mode pipewire is not available yet: this app gets the host's Pulse socket, "
                   "which also lets it record from the microphone")
