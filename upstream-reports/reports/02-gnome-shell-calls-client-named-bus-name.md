# 02. GNOME Shell calls the D-Bus name a window gives in set_dbus_properties

| | |
|---|---|
| Target | GNOME Shell: `gitlab.gnome.org/GNOME/gnome-shell` (and Mutter, which stores the properties) |
| Measured | GNOME Shell 48.7 (Debian 13), 50.1 (Ubuntu 26.04), 51.1 (Fedora 45) |
| Class | confused deputy: the Shell sends calls to a name and path chosen by a Wayland client |
| Our severity | low (read-only calls observed, to services that implement the interfaces) |
| Suggested channel | public issue |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** `gtk_surface1.set_dbus_properties`: the Shell calls any bus name a client names

A Wayland client with a window can send
`gtk_surface1.set_dbus_properties (application_id, app_menu_path, menubar_path, window_object_path, application_object_path, unique_bus_name)`.
Mutter stores the values on the `MetaWindow` (`meta_window_set_gtk_dbus_properties`) and GNOME Shell uses them as given:
`shell_app_update_window_actions()` and `shell_app_add_window()` (`src/shell-app.c`) create a `GDBusActionGroup` for
`unique_bus_name` and the object path, and `shell_app_ensure_busy_watch()` an `org.gtk.Application` proxy.

Measured on a private session bus, with a second client of the bus that owns nothing: the window gives that client's
unique name, and the Shell sends it, with no user action,

```
method call sender=<shell> -> destination=<that name> path=/org/example/application; interface=org.gtk.Actions; member=DescribeAll
method call sender=<shell> -> destination=<that name> path=/org/example/application; interface=org.freedesktop.DBus.Properties; member=GetAll
```

A control run that sets nothing sends no such call. Nothing checks that the name belongs to the client that sent the
request, so a client can make the Shell query (and subscribe to the changes of) the objects of any service it can name,
for example a unique name it guessed. The calls are reads; whether any service answers `DescribeAll` in a harmful way
was not tried.

Suggested fix: accept `unique_bus_name` only if the bus connection's process is the client's
(`GetConnectionUnixProcessID` equals the `wl_client`'s pid), or ignore the properties of clients that are in a sandbox.

### Reproduce

The window is the stdlib client `tests/compositors/focus_client.py` with the command `dbus_props NAME`; the automated
version is `tests/compositors/gtk_bus_name.py`: GNOME Shell on a private bus, a holder of a unique name, `dbus-monitor`
on that name.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 02` (debian, ubuntu, fedora): prints the calls the Shell sent to the name, and the
  control.
* Source read: GNOME Shell 48.7 `src/shell-app.c` (lines of `shell_app_update_window_actions`,
  `shell_app_ensure_busy_watch`, `_shell_app_add_window`), Mutter 48.7 `src/wayland/meta-wayland-gtk-shell.c`
  (`gtk_surface_set_dbus_properties`).

## Reviewer notes (not posted)

* Duplicates checked 2026-11-27: GNOME Shell's tracker has none for `set_dbus_properties` or `unique_bus_name` (#714
  is about app instances). Its README sends bugs to the issue tracker.
* Only the calls made without user action were observed (DescribeAll, GetAll). Calls on user action (activating a
  window action) were not tried.
* The same pattern exists for KDE's appmenu protocol (report 04, source only).
