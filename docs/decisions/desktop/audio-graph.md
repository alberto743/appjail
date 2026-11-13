# A private audio graph per app

*Decision on [desktop access](index.md).*

**Context.** Sound on current desktops goes through PipeWire, which also serves the PulseAudio protocol. Neither path
can be shared safely with a jailed app:

- the Pulse protocol cannot restrict a client by device: a client that can play can also record the microphone and the
  sound other apps play, so a separate "microphone" permission would be a promise it cannot keep;
- PipeWire restricts only clients it recognises as Flatpak sandboxes. Two workarounds failed against PipeWire 1.4.2 and
  WirePlumber 0.5.8 with a test camera: a `.flatpak-info` in the app's jail (it would also make GLib and Electron
  believe they run under Flatpak), and a second socket marked restricted, whose clients WirePlumber's default rules
  still let record, link to the camera and receive its frames.

**Decision.** `audio` is playback and `mic` is the microphone, a separate permission. By default (`audio_mode =
pipewire`) each app gets a PipeWire graph of its own: `pipewire`, WirePlumber and `pipewire-pulse` run in a helper jail
with no sound, video or Bluetooth devices, and the graph holds only tunnels to your Pulse server: a speaker always, a
microphone only with `mic`. The app gets this graph's sockets and nothing of the host's, so it sees no device, no
camera and no other app's stream. The graph's `pipewire-pulse` refuses module loading, because a client could
otherwise load a tunnel to your microphone. After start-up, the graph is checked to contain nothing but its own nodes.
`audio_mode = pulse` gives the host's Pulse socket instead, which follows your desktop's device choices but cannot
withhold the microphone; `add` and `perms` say so.

**Fallback.** When the graph cannot be used (a missing tool or module, no Pulse server, a graph that does not come up),
an app with `mic` gets the host's Pulse socket with a warning, and an app without `mic` gets no sound, with a warning:
missing sound is visible and harmless, a silently open microphone is not.

**Start order.** PipeWire starts first; WirePlumber and `pipewire-pulse` start only once `pw-dump` gets an answer from
it. WirePlumber connects once: started in parallel, on a loaded machine it could try before the socket existed and stay
up without a connection, so the graph never completed. Found by reproducing an intermittent CI failure in the Ubuntu
guest under load (1 run in 15); with the order fixed, 60 loaded runs had no failure.

**Rejected.** A filtering proxy in front of the Pulse socket: blocking recording still let a client load modules and
mute the microphone, and a safe one needs an allow list of the whole protocol, parsed in Python. Rebuilding the tunnel
when devices change: `pw-cli` crashed unloading it, and restarting the daemons drops the app's connection.

**Consequences.** About 36 MiB and under a second per app. The tunnel connects to the devices that are the defaults when
the app starts: a later change of default adds a link instead of moving it, an unplugged device's sound stops until
the app restarts, and the tunnel does not reconnect after the host's audio server restarts.

**Revisit when** those limits hurt (a supervisor that rebuilds the tunnel), or the portals gain an audio interface.
