# The accessibility bus: the evidence

Working notes, not a specification. The behaviour today is on [D-Bus and the filtering proxy](../understand/desktop/dbus.md),
and the decision drawn from these measurements, built as the `accessibility` permission, is
[An opt-in accessibility bus](../decisions/desktop/a11y-bus.md). Written
in November 2026 from experiments in the Debian 13 guest only. "Measured" means a script ran in the guest (they are in
`tests/a11y/`); "read" means source code or documentation only; "not done" means neither. Nothing here was run on the
maintainer's own machine, and Ubuntu and Fedora were not measured.

The question: `org.freedesktop.a11y` and the accessibility bus are refused, so a screen reader cannot see a jailed app.
Flatpak lets its apps reach the accessibility bus through a second filtering proxy. Could appjail do the same, and what
would it expose?

## Who needs it

The accessibility bus (AT-SPI) is how an application describes its window to other programs: every button, label and text
field, its role, name and state, and the events when they change. Anything that is not the application itself and wants
to understand or drive its window reads it. That is not only blind users with a screen reader (Orca):

- screen magnifiers that follow the keyboard focus or the caret;
- on-screen keyboards, which learn when a text field takes focus;
- switch and voice control, and eye trackers, which need the names of the controls to say which one to press;
- UI test and automation tools.

A window that is missing from the bus is a blank window to all of them. Toolkits publish an app's window on the bus on their
own; what the jail removes is the bus socket they publish it to.

## Environment

| | Debian 13 guest |
|---|---|
| AT-SPI (`at-spi2-core`) | 2.56.2 |
| `xdg-dbus-proxy` | 0.1.6 |
| bubblewrap | 0.12.0 |
| GTK 3 | 3.24.49 |
| PyQt6 | 6.9.0 |
| Compositor | headless weston 14.0.2 (no keyboard or seat) |
| Kernel | 6.12.118 |

The test apps are a GTK 3 window and a Qt 6 window with a push button (`tests/a11y/apps.py`), run in a jail built from
appjail's own read-only system view, with the accessibility bus (and only that) behind `xdg-dbus-proxy`, which runs in a
jail of its own like the session-bus proxy (`tests/a11y/harness.py`). The screen reader is a stand-in written with
`libatspi` (`tests/a11y/at.py`): no real Orca ran. There is no keyboard, so no real key press was tested. No AppImage was
downloaded.

## How an app finds the bus (read, then measured)

- **Read.** Flatpak's `flatpak_run_add_a11y_dbus_args` (`common/flatpak-run-dbus.c`) uses `AT_SPI_BUS_ADDRESS` if the host
  has it, and otherwise asks the session bus: `org.a11y.Bus.GetAddress`. It starts a second `xdg-dbus-proxy` on that
  address with `--filter --sloppy-names` and the rules below, binds its socket into the sandbox as
  `/run/flatpak/at-spi-bus` and sets `AT_SPI_BUS_ADDRESS` for the app. The app itself never calls `org.a11y.Bus`.
- **Measured.** The accessibility bus is a second `dbus-daemon` that `at-spi-bus-launcher` starts, on
  `$XDG_RUNTIME_DIR/at-spi/bus`. With the daemon stopped, `dbus-send` to `org.a11y.Bus` `GetAddress` on the session bus,
  from outside any jail, started the launcher and the bus and returned the address. appjail already runs `dbus-send` this
  way (`dbusproxy.bus_owners`).
- **Measured.** Both toolkits connected to that address with only `AT_SPI_BUS_ADDRESS` set in the jail and **no session bus
  at all**: the screen reader saw the GTK 3 window with its whole tree (frame, panel, buttons, labels) and the Qt 6 window
  with its button. Neither needed `QT_LINUX_ACCESSIBILITY_ALWAYS_ON`.
- **Measured.** The toolkits register whether or not a screen reader is running: with `org.a11y.Status` `IsEnabled` set to
  false, the GTK 3 app still called `Socket.Embed`. A grant therefore costs an app one more bus connection even for users
  who never start an assistive tool.

## What the accessibility bus protects (measured)

The bus has no policy of its own. `/usr/share/defaults/at-spi2/accessibility.conf` allows every client to send to every
destination, receive every message and own any name, and only the user may connect. Whoever can reach the socket is the
whole bus.

The same hostile client (`tests/a11y/probe.py`: it tries what an app could try) ran in the jail twice, with a second app
open and a stand-in screen reader that had registered a keystroke listener:

| Attempt | Raw bus socket | Behind the proxy (Flatpak's rules) |
|---|---|---|
| list names; `GetRegisteredEvents`; `GetKeystrokeListeners` | answered | answered |
| `RegisterKeystrokeListener` (the whole keyboard, `global` mode) | accepted | `AccessDenied` |
| `GenerateKeyboardEvent` | accepted | `AccessDenied` |
| `NotifyListenersSync` / `Async` (a key event to the listeners) | answered | answered |
| `RegisterEvent` | accepted | `AccessDenied` |
| list the other apps (`GetChildren` on the registry root, child count) | answered | `AccessDenied` |
| `Cache.GetItems` | answered | `AccessDenied` |
| `eavesdrop=true` match | accepted | `AccessDenied` |
| `BecomeMonitor` (a monitor sees every message of the bus) | accepted | `AccessDenied` |
| `GetChildren` on every unique name on the bus | 1 of 3 answered (the registry) | 0 of 2 answered |
| signals that reached the client | all broadcasts | the registry's `EventListenerRegistered` and `EventListenerDeregistered` only |

On the raw bus the client registered a keystroke listener, read the desktop's application list and the other app's tree
(names of windows and controls), and became a monitor of every message. This is the reason the grant is refused today.

Through the proxy none of those worked, and the app still did what a toolkit needs: the stand-in screen reader read the
tree of the jailed app and received its `state-changed` and `property-change` events, for GTK 3 and for Qt 6.

## What still passes, and why (measured)

Flatpak's rules allow four calls that are not the app's own registration. Two matter:

- **`NotifyListenersSync` and `NotifyListenersAsync` deliver a key event to every keystroke listener.** The jailed client
  sent a made-up key ('a', code 38) and the stand-in's listener received it, once for each call. So an app can feed fake key
  events to a screen reader. It cannot read the user's keys, and cannot type into another window (`GenerateKeyboardEvent`
  was denied). These calls are, by their purpose, how a toolkit passes its own key presses to a screen reader: the documentation says the
  device event controller cannot watch the keyboard on Wayland (read), so only the app in focus can report keys. That use
  was not measured (no keyboard). Removing the calls would likely leave a screen reader without the keys typed in that app.
- **`GetRegisteredEvents` and `GetKeystrokeListeners` tell the app what assistive technology is listening.** The client read
  the stand-in's listener, its bus name and object path, and the event types it had registered. That discloses that a
  screen reader (or any key listener) is running, and its mode. Nothing says what it does with them.

A third, small one: with `--sloppy-names` the app can list the unique names of the other connections on the bus, so it can
count the apps and the assistive tools that are open. It cannot call them (all denied).

## Which rules a toolkit needs (measured)

The tree seen by the stand-in with one of Flatpak's rules removed, for each toolkit (`tests/a11y/run.sh`, section 4):

| Rule removed | GTK 3 | Qt 6 |
|---|---|---|
| none | tree complete | tree complete |
| `--sloppy-names` | unchanged | unchanged |
| `GetRegisteredEvents`, `GetKeystrokeListeners`, `GetDeviceEventListeners` | unchanged | unchanged |
| `NotifyListenersSync` and `Async` | unchanged | unchanged |
| `Socket.Unembed`, the two `EventListener*` broadcasts | unchanged | unchanged |
| **`Socket.Embed`** | **tree empty** | **tree empty** |

Only the app's registration, `Socket.Embed`, is needed for the window to appear. The other rules support what a *running*
assistive tool needs from the app (which events to send, its keys), which a button in a headless compositor does not
exercise: "unchanged" shows the window stays visible, not that every function of a screen reader survives. Not measured:
event filtering, because the events arrived in every variant; and key delivery, because there is no keyboard.

## The app's side channel (measured)

GTK 3 apps also open a socket of their own under `$XDG_RUNTIME_DIR/at-spi2-*/socket` so that a screen reader can talk to
them directly. In the jail that directory does not exist on the host, and the stand-in printed "Unable to open bus
connection" and then read the tree through the bus. The tree was complete, so nothing needs binding for it.

## What is not known

- **Real assistive technology.** No Orca, no magnifier, no on-screen keyboard; the stand-in uses the library they use.
  Orca's behaviour with the keys of a jailed app, and its use of `GetChildren`-style calls on other bus objects, is not
  measured.
- **Other toolkits.** GTK 4, Chromium and Electron (which find the bus themselves; Electron's AppImages are the main
  candidates) were not tried, and neither were an X11 or Xwayland app, which may find the bus through the X root window
  property `AT_SPI_BUS` before the environment.
- **Other distributions.** Ubuntu 26.04 and Fedora 45, and a session using `dbus-broker`.
- **A keyboard.** The compositor had no seat; key events from real hardware were not exercised.
- **Name rules.** Flatpak also adds per-app name rules (`flatpak_context_add_bus_filters`, and
  `<app>.Sandboxed.*` for sub-sandboxes). Apps that own a name on this bus were not tried.
- **The proxy's resource use.** One more `xdg-dbus-proxy` process and jail per running app, as for the session bus; not
  measured.

## Reproducing

In the Debian guest (`tests/vm/sync.sh`, then the files of `tests/a11y/` copied to `~/a11y`): `sh ~/a11y/run.sh`. The
packages are in `tests/vm/packages.txt` (`weston`, `gir1.2-gtk-3.0`, `gir1.2-atspi-2.0`, `python3-pyqt6`, `python3-dbus`).
It starts a headless weston, switches `IsEnabled` on and off, and prints the five sections above.

## References

- Flatpak, [`common/flatpak-run-dbus.c`](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-dbus.c)
  (`flatpak_run_add_a11y_dbus_args`), read in November 2026; and the options `--a11y-bus`, `--no-a11y-bus` and
  `--a11y-own-name` of [flatpak-run(1)](https://github.com/flatpak/flatpak/blob/main/doc/flatpak-run.xml).
- GNOME, [AT-SPI2 core developer documentation](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/): the
  [Registry](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.Registry.html),
  [Socket](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.Socket.html),
  [Cache](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.Cache.html) and
  [DeviceEventController](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.DeviceEventController.html)
  interfaces, and the [device event controller notes](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/de-controller.html).
- [xdg-dbus-proxy](https://github.com/flatpak/xdg-dbus-proxy) and its manual page (`--filter`, `--sloppy-names`, `--call`,
  `--broadcast`).
