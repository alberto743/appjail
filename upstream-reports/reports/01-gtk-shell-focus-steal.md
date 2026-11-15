# 01. gtk_shell1: any client can take the keyboard focus

| | |
|---|---|
| Targets | Mutter (GNOME): `gitlab.gnome.org/GNOME/mutter`; Muffin and Cinnamon (Linux Mint): `github.com/linuxmint/muffin` |
| Measured | Mutter 48.7 (Debian 13), 50.1 (Ubuntu 26.04), 51.1 (Fedora 45); Muffin 6.4.1; Cinnamon 6.4.10, 6.4.13, 6.8.0 |
| Class | focus-stealing prevention bypass; the app then receives the keys the user types |
| Our severity | medium (user-visible, but it needs a client with a window; no data is read, only the keys typed after the steal) |
| Suggested channel | Mutter: a confidential issue first (verify the project's security policy); Muffin: a public issue (it copies Mutter's code) |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** gtk_shell1: a client can take the keyboard focus with `gtk_surface1.present(0)` or `notify_launch` + `request_focus`

A Wayland client that has only a mapped window can take the keyboard focus from another client, with no activation token
and no user input, through the private `gtk_shell1` protocol:

1. `gtk_surface1.present(0)`: `gtk_surface_present()` (`src/wayland/meta-wayland-gtk-shell.c`) calls
   `meta_window_activate_full (window, timestamp, META_CLIENT_TYPE_APPLICATION, NULL)`. The focus-stealing check in
   `meta_window_activate_full()` (`src/core/window.c`) is `if (timestamp != 0 && XSERVER_TIME_IS_BEFORE (timestamp,
   display->last_user_time))`, so the timestamp 0 skips it and the window is focused.
2. `gtk_shell1.notify_launch(id)` followed by `gtk_surface1.request_focus(id)`: `notify_launch` creates a startup sequence
   for any id the client picks, stamped with the current time; `request_focus` looks the id up, and activates the window with
   that timestamp.

A client that sends nothing, or `present` with an old timestamp (1), does not take the focus. After the steal, the client
receives the keys the user types in what they took to be the other window.

Measured with two bare windows (a stdlib client that speaks the wire protocol; no GTK needed), the second one mapped last and
focused: after the request, the first window has `wl_keyboard.enter` and the second `leave`. Mutter 48.7, 50.1, 51.1,
Muffin 6.4.1 and Cinnamon 6.4.10, 6.4.13, 6.8.0 behave the same way. (GNOME Shell 48.7 in a headless session showed its
overview on `present 0` and took the focus through the notify route.)

Suggested fix: treat a timestamp of 0 in `present` as "no user time" (set the demands-attention state instead of focusing), and
do not let a startup sequence made by `notify_launch` carry activation rights; or require the same conditions as for
`xdg_activation_v1`.

Found while measuring Wayland compositors for a sandbox; the reproducer below needs no sandbox.

### Reproduce (any Wayland session with a keyboard)

```sh
# two windows; the second one has the focus
python3 focus_client.py /tmp/a.log < <(sleep 60) &      # thief
python3 focus_client.py /tmp/b.log < <(sleep 60) &      # victim, mapped last
# then give the thief a command on its stdin: "present 0"  (or: "notify X;request_focus X")
# /tmp/a.log gets "keyboard-enter" and /tmp/b.log "keyboard-leave"
```

`focus_client.py` is `tests/compositors/focus_client.py` of the repository named below. The automated version
(`tests/compositors/focus_steal.py`) maps a new victim for each step and includes the control.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 01` (guests: debian, ubuntu, fedora): fresh compositor processes, the control and every step.
* Saved results: `docs/compositor-assessment/focus-debian-13.json`, `focus-ubuntu-26.04.json`, `focus-fedora-45.json`.
* Source read: Mutter 48.7 `src/wayland/meta-wayland-gtk-shell.c` (`gtk_surface_present`, `gtk_surface_request_focus`,
  `gtk_shell_notify_launch`), `src/core/window.c` (`meta_window_activate_full`); Muffin 6.4.1 has the same file.

## Reviewer notes (not posted)

* Debian 13 GNOME Shell: `present 0` left neither window focused (the overview took it); the notify route stole. Fedora GNOME Shell: the first window never got focus (untestable). Mutter alone is clean on all three.
* The real-session effect depends on what the user types while it happens; the headless keyboard comes from Mutter's RemoteDesktop API.
* The existing public commits already describe this finding (`ASSESSMENT.md` item 12, the Wayland allowlist decision). File soon.
