# PulseAudio's socket is never given

*Decision on [desktop access](index.md).*

**Context.** A Pulse client can ask the server to load modules. On PipeWire's Pulse server this creates null sinks,
loopbacks, TCP listeners and FIFOs at paths of the client's choosing (tested on PipeWire 1.4.2 and 1.6.2; loading a
library from a path is not implemented there). On PulseAudio itself, `module-ladspa-sink plugin=/path.so` makes the
server load a library of the client's choosing, so the client's code runs in the server, outside the jail: reproduced
on PulseAudio 17.0 with a library from the app's own home.

**Options.** Warn only; refuse `pulse` mode everywhere; refuse the socket when PulseAudio is behind it.

**Decision.** appjail never gives an app the socket of a PulseAudio server: in `pulse` mode, and in the fallback of the
private graph, the app gets no sound, with a message. `pulse` mode stays available on PipeWire hosts, where module
loading cannot run code; its remaining effects are stated where it is granted. The server is identified by the
process that holds the listening socket (found through the socket's inode, because a socket-activated server's peer
credentials name systemd). A warning alone was rejected: it would describe an escape, not a weaker promise.

**Consequences.** On a PulseAudio host, apps get sound only through the private graph, which tunnels to PulseAudio like
to any Pulse server and refuses module requests itself. A server that cannot be identified is treated as PipeWire's,
with the warning: that is the weak point of this check.
