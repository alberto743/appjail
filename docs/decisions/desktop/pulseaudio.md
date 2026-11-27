# PulseAudio's socket is never given

*Decision on [desktop access](index.md).*

**Context.** A Pulse client can ask the server to load modules. On PipeWire's Pulse server this creates null sinks,
loopbacks, TCP listeners and FIFOs at paths of the client's choosing (tested on PipeWire 1.4.2 and 1.6.2; loading a
library from a path is not implemented there). On PulseAudio itself, `module-ladspa-sink plugin=/path.so` makes the
server load a library of the client's choosing, so the client's code runs in the server, outside the jail: reproduced
on PulseAudio 17.0 with a library from the app's own home.

**Options.** Warn only; refuse `pulse` mode everywhere; refuse the socket when PulseAudio is behind it; and for a
server that cannot be identified, treat it as PipeWire's or refuse it too.

**Decision.** appjail never gives an app the socket of a PulseAudio server: in `pulse` mode, and in the fallback of the
private graph, the app gets no sound, with a message. `pulse` mode stays available on PipeWire hosts, where module
loading cannot run code; its remaining effects are stated where it is granted. The server is identified by the
process that holds the listening socket (found through the socket's inode, because a socket-activated server's peer
credentials name systemd). A server that cannot be identified is refused the same way, since it could be PulseAudio
(November 2026; it used to be treated as PipeWire's). A warning alone was rejected: it would describe an escape, not a
weaker promise.

**Consequences.** On a PulseAudio host, apps get sound only through the private graph, which tunnels to PulseAudio like
to any Pulse server and refuses module requests itself. Where the server cannot be identified, `pulse` mode and the
`mic` fallback give no sound, with a message that says why.

**Measured** (`tests/pulseserver/measure.py`, November 2026: `pipewire-pulse` on Debian 13, Ubuntu 26.04 and Fedora 45,
PulseAudio 17.0 on Debian 13):

| Situation | Identified | Before this decision | Now |
|---|---|---|---|
| server running | at once | as identified | as identified |
| socket-activated, not yet started | in about 0.11 s (`host_server` waits up to 3 s) | as identified | as identified |
| the same under load (eight busy processes per CPU and a disk writer, 4 CPUs) | in 0.11 to 0.19 s | as identified | as identified |
| a socket file left with no server | no | a dead socket, so no sound | no sound, with a message |
| appjail in another network namespace (`unshare -rn`, as in a container with its own network) | no: that namespace's socket table does not list the socket, which still connects | the socket given, PulseAudio's included | refused |
| a system-wide server, run as another user | no: its descriptors cannot be read (not measured) | the socket given | refused |

PulseAudio's `--system` mode does not turn off module loading by clients; its manual only recommends
`--disallow-module-loading` with it. So the last two rows could hand over a server that runs a client's code. A slow
start does not: no cold start came near the 3 s wait, under load included. An early run that restarted the server five
times within 10 s failed on systemd's start limit, not on the server; the script now waits between starts.
