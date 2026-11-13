# Portals

*Part of [Desktop access](index.md). Previous: [D-Bus and the filtering proxy](dbus.md). Next: [audio](audio.md).*

## What it is

**XDG desktop portals** are D-Bus interfaces through which a sandboxed app asks the desktop to do something on its
behalf, with you deciding. The app calls `org.freedesktop.portal.Desktop`; the portal service, `xdg-desktop-portal`,
passes the request to a *backend* for your desktop (GNOME, KDE, GTK, wlroots), which shows its own dialog. The best
known is the **file chooser**: the app asks for a file, you pick one in a dialog the app does not control, and the app
receives that file and nothing else, through the **document portal**, a small filesystem that exposes only the files
you chose. Other portals cover notifications, opening links in another app, printing, screenshots and screen casting,
the camera, the appearance settings and more. Decisions you take (allow the camera, a screen-cast source) are kept in a
**permission store**.

To know who is asking, `xdg-desktop-portal` identifies the calling process's sandbox: it understands Flatpak (a
`.flatpak-info` file in the root of the caller), Snap and Linyaps. A caller it does not recognise is a host
application, with nothing to restrict.

## Why it matters

Portals invert the usual question. Instead of "may this app read my Documents folder?", the app may ask for one
document, and the answer is your choice in the dialog. That is the only way to give an app a file it needs without
deciding in advance which folder it may see. But a portal can only restrict an app it recognises as sandboxed, and only
offer the dialogs its backend implements.

## How appjail uses it

- **`portals = true`** gives the app a **safe set** through the [filtering proxy](dbus.md): file chooser, notifications,
  settings, trash, printing, inhibiting sleep, network, proxy, power and memory status, the secret portal, real-time
  scheduling, and the document portal. Everything else on the portal's name is invisible.
- **Opt-in interfaces** that give more must be named one by one, with a warning: opening URIs in other apps, e-mail,
  screenshots, screen casting, remote desktop, global shortcuts, input capture, camera, location, account information,
  wallpaper, running in the background, USB devices. Spawning commands on the host and installing launchers are never
  available.
- **An identity the portal understands.** appjail writes a Flatpak-style identity for each running app: the file the
  portal reads, with the application id `app.appjail.NAME`, and the jail's process id taken from bubblewrap. The id is the portal's
  whole notion of who the app is, so two apps must never share one: in each dot-separated part of the name, `_` becomes
  `_u`, `-` becomes `_h`, an empty part becomes `_e`, and a part starting with a digit gets a leading `_` (`my-app` is
  `app.appjail.my_happ`, `7zip` is `app.appjail._7zip`). It goes
  into the *proxy's* jail, because the proxy's connection is what the portal sees as the caller, never into the app's,
  so the app can neither read nor forge it. Nothing depends on Flatpak; this is a compatibility shim.
- **The document portal** is started if needed, and only the app's own view of it is bound into the jail.
- **Taking back.** `appjail portals NAME` lists the files the app received and revokes them (`--revoke`,
  `--revoke-all`), through the portal itself, so the files disappear from the app's view at once. `remove` also deletes
  the app's remembered portal decisions, so a later app with the same name starts with none.

## Connections

- Portals travel on D-Bus, through the same proxy: [D-Bus and the filtering proxy](dbus.md).
- The Camera portal is how apps that use PipeWire reach a camera: [GPU and camera](devices.md).
- The Settings portal carries the dark-mode preference: [Appearance](../../guide/appearance.md).
- Decision: [A Flatpak identity for the portals](../../decisions/desktop/portal-identity.md).

## Limits

- The protection of each opt-in interface depends on the backend asking you. Only the GTK backend has been tested; the
  GNOME and KDE backends and their dialogs have not, and backends differ in what they implement.
- The permission store and the Background portal treat the app as a Flatpak app (an autostart entry would say
  `flatpak run`, which does nothing without Flatpak).
- The document portal needs FUSE.

## References

- [XDG Desktop Portal documentation](https://flatpak.github.io/xdg-desktop-portal/docs/), including
  [FileChooser](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.FileChooser.html),
  [Documents](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Documents.html) and
  [Settings](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Settings.html).
