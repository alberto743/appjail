# Permissions

A new app gets a private home, a read-only view of the system and a window, nothing else
([why](../understand/principles.md#6-nothing-is-granted-by-default)). Everything beyond that is a permission recorded in
the app's manifest. This page shows how to read and change them; the [permission reference](../reference/permissions.md)
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

## Tracing and debugging an app

Inside the jail `ptrace` is refused, so `strace` and `gdb` cannot trace the app. Grant `devel` while you diagnose it:

```sh
appjail perms NAME --allow devel
appjail run NAME --raw -- ...                # a debugger that asks questions also needs your terminal
```

With it the app can trace its own processes, and run them at fixed addresses (`gdb` asks for that). It cannot reach
processes outside its jail, and the filter still applies to whatever it traces. What a debugger can attach to depends on
your system: with `kernel.yama.ptrace_scope` at 1 (Ubuntu) it can attach only to its own descendants, so `strace CMD`
and `gdb PROG` work and `strace -p PID` on an unrelated process does not. `perf` is not supported: it needs a sysctl
the jail cannot change and the host's `/sys`. Revoke it when you are done (`--deny devel`). See [debugging](../decisions/isolation/debugging.md).

## Apps that run in a terminal

When an app's output goes to your terminal, appjail gives the app no input and removes the control sequences from what
it prints: some of them set your clipboard or window title, rewrite the screen or make the terminal type into your input.
A command-line tool that only prints keeps working (without colours, and its output may come late). A tool that asks
questions, or a full-screen program such as `htop`, needs your terminal as it is:

```sh
appjail run htop --raw                       # this run only
appjail perms htop --allow raw_terminal      # every run; it also gets your TERM so the program can draw
```

Grant it only to an app you trust. After a run that had sequences removed, appjail says so and names these two ways.
Apps started from the menu or the window are not affected. See [untrusted
text](../understand/acquisition/untrusted-text.md#limits) for what is and is not cleaned.

## Grant for one run only

```sh
appjail run lagrange --dir ~/Downloads          # this folder, this run, read-only
appjail run lagrange --file ~/notes.gmi:rw      # this file only, read-write; its path is passed to the app
```

Nothing given to `run` is saved. Opening a file from the app's menu entry works the same way as `--file`.

## Environment variables

An app runs with a cleared environment, so a variable your shell sets does not reach it. Some apps need one to start
(an Electron launcher that picks Wayland only when asked, for example). Set it in the manifest:

```sh
appjail perms NAME --set-env CLAUDE_USE_WAYLAND=1
appjail perms NAME --unset-env CLAUDE_USE_WAYLAND
```

It is not a permission and grants nothing, and it survives `update` and `reset`. The manifest is plain text kept in git,
so keep tokens and passwords out of it. Names appjail sets itself (`HOME`, `DISPLAY`, the toolkit hints) and common
names that load code (`LD_PRELOAD`, `PYTHONPATH`, `GTK_MODULES`, ...) are refused: see the [policy
lists](../reference/policy.md#environment-variables).

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
