# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Stand-ins for a camera and a microphone in a private PipeWire stack of the tests.

PipeWire's own test sources (videotestsrc, audiotestsrc) come with Debian's and Ubuntu's `libspa-0.2-modules`; Fedora's
PipeWire does not ship them. Without them the camera is a null node that claims to be a Video/Source (the tests only look
for it in the graph) and the microphone is a pipe-tunnel source fed with a 440 Hz tone, which is what audiotestsrc plays.
"""

import os
import sys
from pathlib import Path

HAVE_SPA_TEST_SOURCES = any(list(Path("/usr").glob(f"{lib}/spa-0.2/videotestsrc/libspa-videotestsrc.so")) for lib in ("lib", "lib64", "lib/*"))

FEEDER = ("import math, struct, sys\n"
          "block = b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(4800))\n"
          "with open(sys.argv[1], 'wb', buffering=0) as pipe:\n"
          "    while True:\n"
          "        pipe.write(block)\n")


def camera(name, extra=""):
    """A PipeWire object that appears as a camera in the graph."""
    if HAVE_SPA_TEST_SOURCES:
        return (f"context.spa-libs = {{ videotestsrc = videotestsrc/libspa-videotestsrc }}\ncontext.objects = [ "
                f"{{ factory = adapter args = {{ factory.name = videotestsrc node.name = {name} media.class = Video/Source {extra} }} }} ]\n")
    return (f"context.objects = [ {{ factory = adapter args = {{ factory.name = support.null-audio-sink node.name = {name} "
            f"media.class = Video/Source {extra} }} }} ]\n")


def microphone(name, directory):
    """(configuration, feeder or None) of a source that plays a tone; the feeder is the process that has to run beside it."""
    if HAVE_SPA_TEST_SOURCES:
        return (f"context.spa-libs = {{ audiotestsrc = audiotestsrc/libspa-audiotestsrc }}\ncontext.objects = [ "
                f"{{ factory = adapter args = {{ factory.name = audiotestsrc node.name = {name} media.class = Audio/Source }} }} ]\n"), None
    fifo = Path(directory) / f"{name}.pcm"
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo, 0o600)
    conf = (f'context.modules = [ {{ name = libpipewire-module-pipe-tunnel args = {{ tunnel.mode = source pipe.filename = "{fifo}" '
            f"node.name = {name} audio.format = S16LE audio.rate = 48000 audio.channels = 1 audio.position = [ MONO ] "
            f"stream.props = {{ media.class = Audio/Source }} }} }} ]\n")
    return conf, [sys.executable, "-c", FEEDER, str(fifo)]
