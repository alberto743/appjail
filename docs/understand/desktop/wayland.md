# Wayland

*Part of [Desktop access](index.md). Next: [X11 and the private Xwayland](xwayland.md).*

## What it is

**Wayland** is the display protocol of current Linux desktops. A program that shows windows is a *client*; the
*compositor* (Mutter in GNOME, KWin in KDE, sway, Hyprland, and others) owns the screen, combines the clients' windows
and routes input to them. Clients connect to the compositor through a unix socket, usually
`$XDG_RUNTIME_DIR/wayland-0`.

Everything a client can do is offered as an **interface**. When a client connects, the compositor lists its interfaces
in a *registry* of *globals* (`wl_compositor` to create surfaces, `xdg_wm_base` to make them windows, `wl_seat` for
input, and so on); the client binds the ones it wants. The core protocol is isolating by design: a client sees only its
own surfaces, receives input only while it has the focus, and reads the clipboard only when the user pastes into it.
Desktop tools that need more (screenshot tools, on-screen keyboards, clipboard managers, panels and docks) use
**privileged protocols** that a compositor may or may not offer to every client.

The protocol `wp_security_context_v1` lets a sandbox engine ask the compositor for a separate, *restricted* socket for
one app, tagged with the engine's name and the app's id; the compositor decides what to hide on it.

## Why it matters

What a jailed app can do through its window depends entirely on which interfaces its socket lists. On a compositor that
offers privileged protocols to every client, an app with nothing but a window can:

| Kind | Examples | Gives a client |
|---|---|---|
| capture | `zwlr_screencopy_manager_v1`, `ext_image_copy_capture_manager_v1` | the contents of the whole screen |
| input | `zwp_virtual_keyboard_manager_v1`, `zwlr_virtual_pointer_manager_v1`, input methods | typing and clicking into other apps |
| clipboard | `ext_data_control_manager_v1`, `zwlr_data_control_manager_v1` | reading and replacing the clipboard without having the focus |
| windows | foreign toplevel management, layer shell, output management, session lock | seeing and controlling other windows, the screen layout, the lock screen |
| desktop | KWin's screen power, brightness, virtual desktops, screen edges, lock keys | changing the desktop itself |

Compositors differ widely. Measured on Debian 13 and Ubuntu 26.04 (headless, with real clients trying each capability):
sway, labwc and Hyprland 0.55 hide all of these on the restricted socket; KWin's restricted socket still lists
data-control, and a client read another client's clipboard through it; GNOME and Cinnamon have no restricted socket, but
their own socket lists none of these, because they keep capture and remote input on D-Bus; Wayfire, Cage and Weston
offer them on the only socket they have.

## How appjail uses it

- **The socket.** Where the compositor offers `wp_security_context_v1`, `run` creates a restricted socket for the app
  (tagged `appjail` and the app's name) and gives it that one; otherwise the compositor's own. Either way the app sees
  it as `$XDG_RUNTIME_DIR/wayland-0`, and nothing else of the runtime directory except what other grants bind. appjail
  speaks the few Wayland messages this needs itself, in Python.
- **The registry rule.** Before starting anything, `run` reads the registry of the socket the app will get. If it lists
  a privileged interface, or one appjail has not classified, the app is refused, with the names of the interfaces and
  what they would allow. The permission `full_wayland` accepts that risk for one app: it then runs, with a warning.
- **Two lists.** `wayland.py` holds the privileged interfaces by kind and the interfaces checked to act only on the
  app's own windows, on input while it has the focus, or on its own buffers. Anything in neither list is *unknown* and
  treated as privileged. A few interfaces are allowed after a decision, because they reveal little and refusing them
  would refuse otherwise sound compositors (idle notification, leasing a display the desktop does not use, pointer
  locking and shortcut inhibition while focused).
- **Apps without a window** (`display = none`) get no socket, no display variables, and no check; they also run
  without a Wayland session, over `ssh` for instance.

| Compositor (measured versions) | Without `full_wayland` |
|---|---|
| GNOME 48.7, 50.1 · Cinnamon 6.4 · sway 1.10, 1.11 · labwc 0.8, 0.9 · Hyprland 0.55 | runs |
| KWin 6.3, 6.6 · Hyprland 0.53 · Wayfire · Cage · Weston | refused |

Ordinary copy and paste works everywhere: it uses the core clipboard, which needs keyboard focus.

## Connections

- On GNOME and Cinnamon the privileged operations are on D-Bus instead, so the [D-Bus name policy](dbus.md) is part of
  the display defence.
- X11-only apps run on a private Xwayland that is itself a client of this socket, so the rule covers them too:
  [X11 and the private Xwayland](xwayland.md).
- How a compositor is measured: [Assessing a compositor](../../assessing-compositors.md).
- Decisions: [The Wayland socket is judged by what it lists](../../decisions/desktop/wayland-registry.md),
  [Unknown Wayland interfaces are refused](../../decisions/desktop/wayland-allowlist.md).

## Limits

- KWin is refused until it hides data-control on restricted sockets; Plasma users need `full_wayland` per app.
- The classification is by interface name, not version.
- An app can learn when you are idle where the compositor offers idle notification.
- The measurements are of headless compositors, not of complete desktop sessions. A compositor update that adds an
  interface refuses apps until it is classified; the message names it, and a report is welcome.
- Muffin, and so Cinnamon, crashes when some ordinary clients use the clipboard; any app with a window can end a Cinnamon
  Wayland session, and appjail cannot prevent it.

## References

- Wayland project, [Wayland architecture](https://wayland.freedesktop.org/architecture.html) and
  [the Wayland protocol](https://wayland.freedesktop.org/docs/html/ch04.html).
- [wayland-protocols](https://gitlab.freedesktop.org/wayland/wayland-protocols), and the
  [Wayland Explorer](https://wayland.app/protocols/): for example
  [security-context-v1](https://wayland.app/protocols/security-context-v1),
  [wlr-screencopy](https://wayland.app/protocols/wlr-screencopy-unstable-v1),
  [ext-data-control](https://wayland.app/protocols/ext-data-control-v1),
  [virtual-keyboard](https://wayland.app/protocols/virtual-keyboard-unstable-v1),
  [foreign-toplevel management](https://wayland.app/protocols/wlr-foreign-toplevel-management-unstable-v1),
  [layer-shell](https://wayland.app/protocols/wlr-layer-shell-unstable-v1).
- appjail's own measurements: [compositor assessment](https://github.com/alberto743/appjail/blob/main/docs/compositor-assessment/ASSESSMENT.md).
