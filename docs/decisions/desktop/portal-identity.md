# A Flatpak identity for the portals

*Decision on [desktop access](index.md).*

**Context.** XDG desktop portals let a sandboxed app open a file chooser, send a notification or request the camera
through dialogs the app does not control. xdg-desktop-portal identifies the caller by its sandbox: it reads
`/.flatpak-info` in the root of the calling process and a `bwrapinfo.json` in the runtime directory. Besides Flatpak it
understands only Snap and Linyaps. A client it does not recognise is treated as a host application, with nothing to
restrict.

**Options.** Use `org.freedesktop.host.portal.Registry`, which lets an app claim any application id that has a
`.desktop` file; write a Flatpak-style identity.

**Decision.** appjail writes the Flatpak-style identity, as a compatibility shim: nothing installs or depends on
Flatpak. The application id is `app.appjail.NAME`, escaped so that two names can never share an id. The identity file
is placed in the *proxy's* jail, because the proxy's connection is the peer the portal sees, never in the app's, so the
app can neither read nor forge it. The process id comes from bubblewrap's status pipe, and the app is held until the
file exists. `portals = true` allows a safe set of interfaces; the privileged ones (screenshots, screen casting, remote
desktop, camera, location, background, ...) must be named one by one; spawning on the host and installing launchers
are refused.

**Consequences.** The permission store and the Background portal treat the app as a Flatpak app (an autostart entry
would say `flatpak run`, which does nothing without Flatpak). `remove` deletes the app's document grants and its
remembered portal decisions, so a later app with the same name starts with none. Only the GTK backend has been
tested; the GNOME and KDE backends and their dialogs are still a manual check.
