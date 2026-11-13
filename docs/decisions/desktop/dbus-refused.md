# D-Bus names that are always refused

*Decision on [desktop access](index.md).*

**Context.** An app has no session bus by default; a granted name is reached through a filtering proxy. Some names hand
over the desktop to any client of the bus, so granting them would undo the rest of the jail. GNOME and Cinnamon keep
screen capture and remote input on D-Bus rather than on Wayland, so on those desktops the bus names are what stands
between an app and the screen and keyboard. Measured on headless desktops (Debian 13 and Ubuntu 26.04):

- Mutter's `ScreenCast`, `RemoteDesktop` and `InputCapture` open a session for any client; a complete screen capture and
  typing into another client's window were shown as an ordinary client, with no prompt (Mutter and GNOME Shell 48.7,
  50.1);
- Cinnamon's `org.Cinnamon.Eval` runs any JavaScript in the shell for any client: it ran a command as the user and typed
  into another window; the shell also answers screenshot calls (Cinnamon 6.4.10, 6.4.13);
- Muffin's display configuration changes monitors, backlight and gamma for any client (Muffin 6.4.1);
- Plasma's `evaluateScript` runs a desktop script for any client, and klipper returns the clipboard and its history
  (plasmashell 6.3.6, 6.6.6);
- the settings database (`dconf`) can set custom keyboard shortcuts, which run commands; GVfs reaches mounts and host
  locations outside the jail's grants; the accessibility bus monitors the keyboard.

**Decision.** These names are refused when typed and when a manifest is loaded, with any wildcard that would cover
them: the bus itself, systemd, Flatpak, the portals' own names (portals have their own permission), GNOME Shell and
the session manager, Mutter, Muffin, Cinnamon, KWin, Plasma's shell and klipper, KDE's launchers, global shortcuts and
keyboard state, the screensaver, `dconf`, GVfs and accessibility. Wildcards with fewer than three name parts are
refused. Names in desktop namespaces (`org.freedesktop.`, `org.gnome.`, `org.kde.`, `org.gtk.`, ...) cannot be
*owned*, so an app cannot impersonate the notification daemon or the secret service; status-notifier names are the
exception. Names that give access to stored secrets are allowed with a warning. `org.freedesktop.FileManager1` is
not refused: it is needed to browse files when portals are used.

**Consequences.** Refusing by name protects only if every name of the privileged process is refused; see
[One granted name reaches its whole connection](dbus-connection.md). Not measured: the daemons of complete GNOME,
Cinnamon and Plasma sessions (screen lockers, KWallet, settings daemons).
