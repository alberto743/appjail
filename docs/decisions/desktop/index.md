# Desktop access

Decisions about what an app may reach of your desktop: the display, the session bus and its portals, sound, devices,
the network, and the menu. How it works is explained in [Desktop access](../../understand/desktop/index.md).

| Decision | Covers |
|---|---|
| [The Wayland socket is judged by what it lists](wayland-registry.md) | the rule that refuses privileged Wayland interfaces, and KWin |
| [Unknown Wayland interfaces are refused](wayland-allowlist.md) | the allow list, and the interfaces allowed after a decision |
| [X11-only apps on GNOME: rootful Xwayland](xwayland-rootful.md) | a private X server in one window, with openbox |
| [D-Bus names that are always refused](dbus-refused.md) | the names that hand over the desktop |
| [One granted name reaches its whole connection](dbus-connection.md) | confined services and the owner check |
| [A Flatpak identity for the portals](portal-identity.md) | how the portals recognise an app |
| [A private audio graph per app](audio-graph.md) | `audio`, `mic`, `audio_mode` |
| [PulseAudio's socket is never given](pulseaudio.md) | module loading, and when apps get no sound |
| [Camera: the capture nodes only](camera.md) | which devices `camera` binds, and the portal route |
| [Network through pasta](network.md) | the private network namespace, and the LAN |
| [Menu entries are written by appjail](menu-entries.md) | the AppImage's own `.desktop` file, file types |
| [Icons rewritten, not decoded](icons.md) | the PNG sanitiser |
