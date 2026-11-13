# D-Bus and the filtering proxy

*Part of [Desktop access](index.md). Previous: [X11 and the private Xwayland](xwayland.md). Next: [portals](portals.md).*

## What it is

**D-Bus** is the message bus desktop programs use to talk to each other. Each login session has a **session bus**, a
daemon listening on a unix socket (`$XDG_RUNTIME_DIR/bus`); there is also a system bus for system services, which
appjail never exposes.

- A program that connects gets a **unique name** (`:1.42`) and may claim **well-known names** in reverse-DNS form
  (`org.freedesktop.Notifications`), which others use to find it. One connection can own many names.
- A service exposes **objects** at paths (`/org/freedesktop/Notifications`), each implementing **interfaces**: sets of
  methods, signals and properties.
- Clients send **method calls** to a name, object and interface, and receive **signals** they subscribe to. A service
  that is not running can be started on demand (*activation*).

The bus itself does almost no access control within a session: any program of yours may call any service of yours.
Each service decides on its own whether to trust its callers, and most trust anyone on the session bus.

## Why it matters

Giving an app the session bus gives it every service of your desktop: the notification daemon, but also the settings
database (where a custom shortcut is a command that runs on a key press), the shell, the screensaver, the services that
start programs and mount filesystems, and, on GNOME and Cinnamon, the interfaces for screen capture and remote input.
Measured on headless desktops, an ordinary client of the bus with no prompt could capture the whole screen and type into
another window on GNOME (through Mutter), run commands in the shell on Cinnamon (`org.Cinnamon.Eval`) and Plasma
(`evaluateScript`), and read the clipboard history on Plasma.

Filtering by name is not enough either: a call to a name reaches the *connection* that owns it, and through it every
object that connection serves. Desktop shells own ordinary names (notifications, the keyring prompter) on the same
connection as the privileged ones. Through a filter that allowed only `org.gtk.Notifications`, a client reached Mutter's
remote-desktop interface on GNOME Shell; through `org.freedesktop.Notifications`, Cinnamon's `Eval`.

## How appjail uses it

- **No bus by default.** Without D-Bus grants the jail has no bus socket and no bus address.
- **A filtering proxy.** With grants, `run` starts `xdg-dbus-proxy`, the filter Flatpak uses, in a jail of its own (no
  network, the read-only system, your bus socket and a private directory). The app gets only the proxy's socket, as
  `$XDG_RUNTIME_DIR/bus`; the real bus is never visible. Every name not granted is invisible, and every call the proxy
  does not allow is answered by the proxy with an error.
- **Confined services.** For known services (desktop notifications, `org.gtk.Notifications`, the Secret Service, MPRIS
  media players, the status-notifier watcher) the proxy allows only the interfaces their specifications define, on
  their own object path, plus properties, introspection and ping, and passes their signals. Whoever owns the name, the
  rest of that connection is unreachable.
- **The owner check.** Any other granted name reaches its whole connection. Before starting the proxy, `run` asks the bus
  who owns each granted name and each refused one, and refuses to start when one connection owns both, naming them. It
  fails closed when the owners cannot be read.
- **Refused names.** Names that hand over the desktop are refused when you grant them and when a manifest is loaded: the
  bus itself, systemd, the desktop shells and compositors, the session manager, `dconf`, GVfs, the accessibility bus,
  global shortcuts, the screensaver, the clipboard manager, the portals' own names. Wildcards need at least three name
  parts.
- **Owning names.** An app may own a name it is granted with `--dbus-own` (a media player, a single-instance name), never
  one in a desktop namespace (`org.freedesktop.`, `org.gnome.`, `org.kde.`, `org.gtk.`, ...), so it cannot impersonate a
  desktop service; tray-icon names are the exception.

## Connections

- The [portals](portals.md) also go through this proxy, with rules of their own.
- On GNOME and Cinnamon the refused names are what protect the screen and keyboard, since their
  [Wayland socket](wayland.md) offers no privileged interface to block.
- How to find and grant names: [D-Bus and portals](../../guide/dbus.md).
- Decisions: [D-Bus names that are always refused](../../decisions/desktop/dbus-refused.md),
  [One granted name reaches its whole connection](../../decisions/desktop/dbus-connection.md).

## Limits

- The owner check runs at start: a name that nobody owns then, or that changes owner while the app runs, is not checked
  again.
- A granted name that is not a confined service reaches everything its owner serves.
- Names with a process-id suffix (some tray icons) cannot be expressed: the proxy matches only a trailing `.*`.
- Only the notification services of headless GNOME Shell, Cinnamon and Plasma shells were called through the confined
  rules; real MPRIS players and tray icons are untested.

## References

- freedesktop.org, [D-Bus Specification](https://dbus.freedesktop.org/doc/dbus-specification.html) and
  [D-Bus Tutorial](https://dbus.freedesktop.org/doc/dbus-tutorial.html).
- [xdg-dbus-proxy](https://github.com/flatpak/xdg-dbus-proxy) and its manual page
  [xdg-dbus-proxy(1)](https://manpages.debian.org/trixie/xdg-dbus-proxy/xdg-dbus-proxy.1.en.html) (`--talk`, `--call`,
  `--broadcast`, `--own`).
- Specifications of the confined services: [Desktop Notifications](https://specifications.freedesktop.org/notification-spec/latest/),
  [Secret Service](https://specifications.freedesktop.org/secret-service-spec/latest/),
  [MPRIS](https://specifications.freedesktop.org/mpris-spec/latest/).
- Flatpak documentation, [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html) (D-Bus access).
