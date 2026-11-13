# Audio

*Part of [Desktop access](index.md). Previous: [portals](portals.md). Next: [GPU and camera](devices.md).*

## What it is

Sound on current Linux desktops is handled by **PipeWire**, a media server that routes audio (and video) between
devices and applications as a *graph* of nodes and links. **WirePlumber** is its session manager: it finds devices,
decides defaults and links new streams. Most applications still speak the older **PulseAudio** protocol; PipeWire
serves it through `pipewire-pulse`, on the socket `$XDG_RUNTIME_DIR/pulse/native`. Some systems run PulseAudio itself
instead. Native PipeWire clients use `$XDG_RUNTIME_DIR/pipewire-0`.

## Why it matters

Neither socket can be shared safely with a jailed app:

- **The Pulse protocol has no notion of a restricted client.** A client that can play can also record the microphone
  and the sound of every other app, and it can ask the server to load modules: on PipeWire's Pulse server, null sinks,
  loopbacks, network listeners and named pipes at paths of its choosing; on PulseAudio itself, a module that loads a
  library from a path the client names, so the client's own code runs inside your audio server, outside any jail.
- **PipeWire restricts only clients it recognises as sandboxed**, which means Flatpak. A jailed client on `pipewire-0`
  would see every node: your devices, your cameras, other apps' streams and screen casts. Marking a second socket as
  restricted does not help with WirePlumber's default rules, which still let such a client record and link to a camera.

So a separate microphone permission could not be a real promise on the host's sockets.

## How appjail uses it

- **Two permissions.** `audio` is playback; `mic` is the microphone, and needs `audio`.
- **A private graph per app** (`audio_mode = pipewire`, the default). Before the app starts, appjail runs `pipewire`,
  WirePlumber and `pipewire-pulse` for that app alone, in a helper jail that has no sound, video or Bluetooth device and
  no `/sys` device tree, so no hardware can appear in it. The graph holds tunnels to your Pulse server: a speaker
  always, a microphone only with `mic`. The app gets this graph's two sockets and nothing of the host's, so both Pulse
  and native PipeWire clients work, and neither sees a device, a camera or another app. The graph's `pipewire-pulse`
  refuses to load modules, and after start-up the graph is checked to hold nothing but its own nodes. On your side, the
  app appears as one stream named after it.
- **`audio_mode = pulse`** gives the host's Pulse socket instead, which follows your desktop's device choices but
  always includes the microphone; `add` and `perms` say so. When the server behind that socket is PulseAudio itself, the
  socket is never given, since an app could make it load its own code: the app gets no sound, with a message.
- **Fallback.** When the private graph cannot run (a missing tool, no Pulse server to tunnel to, a graph that does not
  come up), an app with `mic` gets the host's Pulse socket with a warning, and an app without `mic` gets no sound, with
  a warning: silence is visible and harmless, a microphone opened without permission is not.

## Connections

- The same fact about PipeWire shapes the camera: [GPU and camera](devices.md).
- Decisions: [A private audio graph per app](../../decisions/desktop/audio-graph.md),
  [PulseAudio's socket is never given](../../decisions/desktop/pulseaudio.md).

## Limits

- The tunnels connect to the devices that are your defaults when the app starts. Making another device the default later
  adds links instead of moving them (sound on both, the microphone mixed from both); unplugging a device the app used
  stops its sound until the app restarts; the tunnels do not reconnect if your audio server restarts.
- About 36 MiB of memory and under a second of start-up per app.
- Apps that speak only native PipeWire need `pipewire` mode.
- Tested with virtual devices and PipeWire 1.4 and 1.6; not yet with a real headset.

## References

- [PipeWire documentation](https://docs.pipewire.org/): [access control](https://docs.pipewire.org/page_access.html),
  [the Pulse server](https://docs.pipewire.org/page_module_protocol_pulse.html),
  [the pulse-tunnel module](https://docs.pipewire.org/page_module_pulse_tunnel.html).
- [WirePlumber documentation](https://pipewire.pages.freedesktop.org/wireplumber/).
- PulseAudio, [Modules](https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/Modules/) (including the
  LADSPA sink, which loads a plugin library by path).
