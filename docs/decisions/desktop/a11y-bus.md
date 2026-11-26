# An opt-in accessibility bus

*Decision on [desktop access](index.md). Decided in November 2026 by the maintainer after the study below, and built as the `accessibility` permission.*

**Context.** `org.freedesktop.a11y` and the accessibility bus are refused ([D-Bus names that are always refused](dbus-refused.md)),
so a jailed app is invisible to a screen reader, a magnifier that follows the focus, an on-screen keyboard, switch or voice
control and UI automation. Flatpak gives its apps the accessibility bus through a second `xdg-dbus-proxy`. The
[measurements](../../develop/a11y-evidence.md) (Debian 13, then Ubuntu 26.04 and Fedora 45 with the same result; a GTK 3
and a Qt 6 window, a stand-in screen reader) found:

- The accessibility bus has no policy: whoever reaches its socket can list every app and read its controls, register as
  the keyboard listener, send key events and monitor every message. Binding the socket, or letting the session-bus proxy
  pass `org.a11y.Bus`, would give an app all of that.
- Behind a second proxy with Flatpak's rules none of it worked, and both toolkits were still seen by the screen reader with
  their whole tree and their events. The app needs no session bus: it finds the bus through `AT_SPI_BUS_ADDRESS`, which
  appjail sets from an address it reads itself (`org.a11y.Bus.GetAddress`, as `dbusproxy.bus_owners` already calls the
  bus), starting the accessibility bus if it is not running.
- Two things still pass, and they are the price of the feature: an app can send fake key events to a screen reader
  (`NotifyListeners*`), and can see that an assistive tool is listening (`GetRegisteredEvents`, `GetKeystrokeListeners`).
  It cannot read keys, type into another window, or see other apps.
- The toolkits register on the bus even when no assistive tool is running.

**Decision.** A permission, off by default (principle 6): `accessibility = true`, granted with `--allow accessibility`:

1. `run` reads the accessibility bus address, starts a second `xdg-dbus-proxy` on it in a jail of its own, with Flatpak's rules
   (registration, the registry's two broadcasts, and the four device-event calls), and gives the app only its socket, as
   `AT_SPI_BUS_ADDRESS`. The session bus stays as the manifest says: without `dbus_filter` the app has none.
2. It fails closed, like every grant (principle 4): without `xdg-dbus-proxy`, or when the address cannot be read, the app
   does not start with a message, never with the bus unfiltered.
3. `perms` shows it, and granting it says in plain words what it gives: the app's window is readable by assistive tools,
   the app can tell whether one is running, and can send fake key events to it (principle 7). It is not a warning at every
   start.
4. The names `org.freedesktop.a11y` and `org.a11y.*` stay refused as `dbus_filter` and `dbus_own` entries: the permission
   is the only way in.

**Alternatives.**

- *Keep refusing it.* The status quo. A jailed app is unusable for people who need an assistive tool, which is a cost the
  project does not measure today.
- *Pass the raw accessibility bus.* Rejected: measured above, it hands over every app's window contents and the keyboard
  listener.
- *Allow `org.a11y.Bus` through the session proxy.* Rejected: it only returns the address of the raw bus; the app would
  have to be given that bus too.
- *Fewer rules than Flatpak.* Registration alone (`Socket.Embed`) was enough for both windows to appear, and removing
  `NotifyListeners*` would remove the fake-key path. It would likely also remove the keys a screen reader receives from the
  app (not measured: no keyboard). Worth testing with a real Orca before choosing it; the permission keeps Flatpak's set, which
  is what real assistive tools have been used with. `tests/test_a11y.py` checks the rules against a real proxy and a real
jail: registration passes, a key listener, an event registration, the desktop's children and monitoring are refused.
- *Enable it only when a screen reader runs* (`org.a11y.Status` `IsEnabled`). An app started before the reader would never
  register and would need restarting; Flatpak always provides the bus. The permission gives it whenever it is
  set.

**Consequences.** One more proxy process per running app that has the permission. The behaviour is on
[D-Bus and the filtering proxy](../../understand/desktop/dbus.md#the-accessibility-bus) and the permission in the
[reference](../../reference/permissions.md); the accessibility names stay refused as D-Bus names, and the refusal
message points to the permission. Not measured yet: Chromium, Electron, GTK 4 and X11 apps, and a real
Orca with a real keyboard ([what is not known](../../develop/a11y-evidence.md#what-is-not-known)). A trial with Orca on a
real desktop is a manual check.
