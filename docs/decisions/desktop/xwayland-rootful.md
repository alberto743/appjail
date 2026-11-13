# X11-only apps on GNOME: rootful Xwayland

*Decision on [desktop access](index.md).*

**Context.** X11 has no isolation between clients: any client of an X server can read the others' keystrokes and
windows. appjail therefore never gives an app the session's X server, and runs X11-only apps on a private Xwayland
started inside the jail as a client of the app's own Wayland socket. A *rootless* Xwayland shows each X window as a
window of the desktop, but needs the compositor to act as the X window manager, which Mutter does only for the Xwayland
it starts itself. On GNOME the private rootless server's windows are mapped and never shown (found with `xeyes` and
Java applications).

**Options.** Bind the session's X socket, as Flatpak does (every X client could then read the others, and it would need
a per-app cookie and a Landlock exception); a nested kiosk compositor such as `cage` (one more dependency with GPU and
input quirks for the same result); Xpra (a client on the host and two moving parts); a *rootful* Xwayland with a small
window manager inside the jail.

**Decision.** A separate display mode, `xwayland-rootful`: Xwayland without `-rootless` makes one window of its own that
holds the whole X screen (sized by `display_size`), and `openbox` inside the jail provides stacking, focus, decorations
and the cursor. It is chosen by the user, never automatically, so the manifest says what the app gets; the rootless
mode stays for compositors that show its windows (sway, KDE). `openbox` was preferred to `matchbox` for its familiar
behaviour with several windows.

**Consequences.** The app's windows (dialogs, menus) live inside one host window. Tested briefly on GNOME; clipboard,
drag and drop and GPU acceleration through that window are not yet verified. Native Wayland remains the better route
for toolkits that have it (for Java, `-Dawt.toolkit.name=WLToolkit` where the JDK supports it).
