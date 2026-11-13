# Permissions

A new app gets a private home, a read-only view of the system and a window, nothing else
([why](../understand/principles.md#6-nothing-is-granted-by-default)). Everything beyond that is a permission recorded
in the app's manifest. This page shows how to read and change them; the [permission reference](../reference/permissions.md)
lists every one.

## See what an app may do

```sh
appjail perms lagrange          # the permissions of one app
appjail list -l                 # every app, with what it is granted
```

## Grant and take back

`perms` shows the permissions before and after the change and asks before saving:

```sh
appjail perms lagrange --allow network          # outbound internet, not your machine's own services
appjail perms lagrange --allow audio            # sound playback (add --allow mic for the microphone)
appjail perms lagrange --allow gpu              # hardware-accelerated graphics
appjail perms lagrange --add-dir ~/Documents/notes      # a folder, read-only
appjail perms lagrange --add-dir ~/Pictures:rw          # a folder, read-write
appjail perms lagrange --deny network --rm-dir ~/Pictures   # take grants back
```

The same options can be given when the app is installed (`appjail add owner/repo --allow audio --dir ~/Music`); the
installation review then lists them with the others.

Permissions take effect at the next start of the app. Several can be combined in one command.

## Grant for one run only

```sh
appjail run lagrange --dir ~/Downloads          # this folder, this run, read-only
appjail run lagrange --file ~/notes.gmi:rw      # this file only, read-write; its path is passed to the app
```

Nothing given to `run` is saved. Opening a file from the app's menu entry works the same way as `--file`.

## Warnings and refusals

Some grants widen what an app can reach more than others; `add` and `perms` print a warning for each when you give it
(for example `userns`, `network_host`, a D-Bus name that holds secrets, an opt-in portal). The warning is shown once,
when you decide; it is not repeated at every start.

Some grants are refused whatever you ask, with a message that says why: folders that hold credentials or are too broad
([which ones](files.md#what-cannot-be-granted)), D-Bus names that control the desktop, `network` on a system without
`pasta`, `network_host` on a kernel without Landlock. The way forward is always a narrower grant, or installing the
missing tool.

## Choosing permissions for an app

Start with nothing and add what the app visibly lacks:

| Symptom | Permission |
|---|---|
| no sound | `--allow audio` |
| it cannot record | `--allow mic` |
| slow rendering, or no hardware 3D | `--allow gpu` |
| "no network" or a connection error | `--allow network` |
| it cannot see a file or folder | `--add-dir PATH`, or `run APP --file PATH` once |
| an X11-only app shows no window | `--display xwayland` (or `xwayland-rootful` on GNOME) |
| an Electron or Chromium app fails setting up its sandbox | `--allow userns` |
| it exits at once with status 0 and no window | `--allow linger` |
| a command-line tool that needs no window | `--display none` |
| no notifications, tray icon or media keys | [D-Bus and portals](dbus.md) |
| a light theme on a dark desktop, a different cursor or missing fonts | [Appearance](appearance.md) |
