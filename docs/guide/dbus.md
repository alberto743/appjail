# D-Bus and portals

Desktop apps talk to the rest of the desktop over D-Bus, the session's message bus: to show a notification, put an icon
in the tray, react to media keys, store a password in the keyring, or make sure only one copy runs. An app in a jail has
no bus at all, so these features are missing until you grant them. This page shows how to find what an app needs and
how to grant as little as possible.

## Start with the portals

Many common needs are covered by the desktop portals, which ask *you* through the desktop's own dialogs rather than
letting the app act directly:

```sh
appjail perms NAME --allow portals
```

This gives the safe set: the file chooser, notifications, the appearance settings (dark mode), the trash, printing,
inhibiting sleep, network and power status, proxy settings, and the secret portal. Apps built for Flatpak use these
automatically. Some portals are more powerful and must be named one by one:

```sh
appjail perms NAME --add-portal OpenURI       # open links and files in other apps
appjail perms NAME --add-portal Camera        # the camera, for apps that use PipeWire (browsers)
appjail perms NAME --add-portal ScreenCast    # share the screen or a window, after asking you
```

The others are `Email`, `Screenshot`, `RemoteDesktop`, `GlobalShortcuts`, `InputCapture`, `Location`, `Account`,
`Wallpaper`, `Background` and `Usb`; `add` and `perms` warn for each. Two are never available: spawning commands on the
host and installing launchers.

Files an app received through the file chooser stay available to it until you take them back:

```sh
appjail portals NAME                 # what it was given
appjail portals NAME --revoke-all    # take everything back (or --revoke DOC_ID)
```

## Granting a bus name

When an app needs a service the portals do not cover, grant that service's bus name. The app then gets a bus through a
filtering proxy that shows it that name and nothing else:

```sh
appjail perms NAME --add-dbus org.freedesktop.Notifications     # talk to a service
appjail perms NAME --add-dbus-own org.mpris.MediaPlayer2.myapp  # own a name (a media player, a single-instance app)
appjail perms NAME --rm-dbus org.freedesktop.Notifications      # take it back
```

A trailing `.*` covers the names below a prefix (`org.mpris.MediaPlayer2.*`), with at least three parts before it.

| The app wants to | Grant |
|---|---|
| show notifications | `--allow portals`, or `--add-dbus org.freedesktop.Notifications` |
| be controlled by media keys and the desktop's media widget | `--add-dbus-own org.mpris.MediaPlayer2.APPNAME` |
| control other media players | `--add-dbus 'org.mpris.MediaPlayer2.*'` |
| store passwords in the keyring | `--allow portals` (secret portal), or `--add-dbus org.freedesktop.secrets` (warns: it reaches every stored secret the keyring unlocks) |
| show a tray icon | `--add-dbus org.kde.StatusNotifierWatcher`, and an item name to own (see the limits below) |
| run as a single instance | `--add-dbus-own` the name the app uses for itself, often its application id |

Notifications, the secret service, media players and the tray watcher are *confined*: the proxy lets the app reach only
the interfaces their specifications define, on their own object. Any other granted name reaches everything the process
behind it serves; if that process also serves a name appjail refuses (a desktop shell typically does), the app is
refused at start with a message that names both
([why](../decisions/desktop/dbus-connection.md)).

## Finding the names an app needs

- **The app's own messages.** Run it from a terminal (`appjail run NAME`) and look for D-Bus errors such as
  `The name org.example.Service was not provided by any .service files` or `ServiceUnknown`: they name the service.
- **The app's Flatpak manifest**, if it is on Flathub: the `--talk-name=` and `--own-name=` lines of its `finish-args`
  are the names its developers found necessary. They are a starting point, not a list to copy whole: a Flatpak app
  that also uses portals usually needs fewer.
- **Watching the bus** on your side while the app runs: `busctl --user monitor NAME` (or `dbus-monitor --session`)
  shows the calls that pass through the proxy to a granted service. Calls the proxy refuses never reach the bus.

Grant one name at a time, and keep only what makes a visible difference.

## What cannot be granted

Names that would hand over the desktop are refused, with a message, whatever you ask: the bus itself, systemd, the
desktop shells (GNOME Shell, Mutter, Cinnamon, Muffin, KWin, Plasma's shell), the session manager, the settings
database (`dconf`), GVfs, the accessibility bus, global shortcuts, the screensaver, the clipboard manager, and the
portals' own names (use `--allow portals`). On GNOME and Cinnamon these names are what keeps an app from capturing the
screen and typing into other windows ([why](../decisions/desktop/dbus-refused.md)). An app cannot *own* a name in a
desktop namespace (`org.freedesktop.`, `org.gnome.`, `org.kde.`, `org.gtk.`, ...), so it cannot impersonate the
notification daemon or the keyring; tray-icon names are the exception.

## Limits

- Tray icons whose item name carries the app's process id (`org.kde.StatusNotifierItem-1234-1`) cannot be expressed:
  the proxy matches only a trailing `.*`.
- The owner check runs when the app starts. A name that nobody owns then, or that changes owner while the app runs, is
  not checked again.
- The portal dialogs depend on your desktop's portal backend. appjail is tested with the GTK backend; the GNOME and KDE
  backends have not been tested yet.
