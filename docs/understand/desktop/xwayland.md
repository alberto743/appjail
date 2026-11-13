# X11 and the private Xwayland

*Part of [Desktop access](index.md). Previous: [Wayland](wayland.md). Next: [D-Bus and the filtering proxy](dbus.md).*

## What it is

**X11** is the display protocol Linux desktops used before Wayland, and many applications (older toolkits, Java/AWT,
games, scientific tools) still speak only X11. On a Wayland desktop they run on **Xwayland**, an X server that is itself
a Wayland client: it draws the X windows into Wayland surfaces. In *rootless* mode each X window becomes a separate
window on the desktop, which needs the compositor to act as the X *window manager*; in *rootful* mode Xwayland shows one
window holding a whole X screen.

## Why it matters

X11 has no isolation between clients. Any client connected to an X server can read the keys typed into every other
client's windows, capture their contents and send them synthetic input. On a Wayland desktop every X11 app of your
session shares the desktop's Xwayland, reached through `/tmp/.X11-unix/X0` or the abstract socket `@/tmp/.X11-unix/X0`.
Giving a jailed app that server would give it every other X11 app.

## How appjail uses it

- **The host's X server is never shared.** No X socket is bound into the jail, the `/tmp` that holds the X sockets is
  private, and the host's abstract X socket is out of reach (the jail's own network namespace, or Landlock with
  `network_host`).
- **A private Xwayland per app.** With `display = xwayland`, a short script inside the jail starts a rootless Xwayland
  as a client of the app's own Wayland socket (`-nolisten tcp`, the display number reported through a pipe), sets
  `DISPLAY` and starts the app. The app's environment selects X11 for its toolkits and has no `WAYLAND_DISPLAY`. The
  server lives and dies with the jail, and no other app can reach it.
- **Rootful for GNOME.** Mutter manages the windows only of the Xwayland it starts itself, so a private rootless server's
  windows are never shown there. `display = xwayland-rootful` starts Xwayland with one window of its own, of the size
  `display_size` (default 1280x800), and runs `openbox` inside the jail for stacking, focus, decorations and the cursor.
  The mode is chosen by you, never automatically.
- **The same Wayland rule.** Xwayland connects to the app's Wayland socket, so the [registry rule](wayland.md) applies
  to X11-only apps as it does to native ones.

## Connections

- [Landlock](../isolation/landlock.md) keeps an app with `network_host` off the host's abstract X socket while the
  private server, started inside the jail, stays reachable.
- Decision: [X11-only apps on GNOME: rootful Xwayland](../../decisions/desktop/xwayland-rootful.md).

## Limits

- In rootful mode the app's windows (dialogs, menus) live inside one host window.
- GPU acceleration through the private Xwayland, and clipboard and drag and drop through the rootful window, have not
  been verified.
- In rootless mode on a scaled screen, X11 apps can look blurry.
- Needs the `xwayland` package, and `openbox` for the rootful mode; `run` stops with a message when one is missing.

## References

- Debian manual page [Xwayland(1)](https://manpages.debian.org/trixie/xwayland/Xwayland.1.en.html) (`-rootless`,
  `-geometry`, `-displayfd`) and [openbox(1)](https://manpages.debian.org/trixie/openbox/openbox.1.en.html).
- X.Org Foundation, [Access control and authentication in X](https://www.x.org/wiki/Development/Documentation/Security/):
  ordinary clients can read other clients' windows and input.
