# 07. Muffin and Cinnamon 6.4 end when wl-copy or wl-paste connect

| | |
|---|---|
| Target | Muffin: `github.com/linuxmint/muffin` (the 6.4 branch, which Debian 13 and Ubuntu 26.04 ship) |
| Measured | Muffin 6.4.1 (Debian 13, Ubuntu 26.04) nearly every time (on 2026-11-27, 5 runs of 6); Cinnamon 6.4.10 and 6.4.13 (the shell on it) intermittently; Cinnamon 6.8.3 survived; backtraces of both on Debian 13 (2026-11-27) |
| Class | crash (any client ends the session) |
| Our severity | low to medium |
| Suggested channel | public issue (Linux Mint publishes no security policy) |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** Muffin 6.4.1 (Wayland): SIGFPE in `wl_shell_surface_role_configure` (division by a zero scale)

Muffin 6.4.1 (Debian 13 and Ubuntu 26.04), and the Cinnamon 6.4 shell on it, terminate with SIGFPE when `wl-copy` or
`wl-paste` (wl-clipboard) connect to the compositor's Wayland socket; started headless, in a private Xvfb
(`muffin --wayland --nested --no-x11`, and `cinnamon --wayland --nested --no-x11 --sm-disable`). Any client can
therefore end a Wayland session.

The backtrace (Debian 13, `muffin 6.4.1-1`, symbols from debuginfod) is the same for Muffin and for Cinnamon:

```
Program terminated with signal SIGFPE, Arithmetic exception.
#0  wl_shell_surface_role_configure (shell_surface=..., configuration=...) at /usr/include/wayland-server-protocol.h:3443
#1  meta_window_wayland_configure (wl_window=..., configuration=...) at ../src/wayland/meta-window-wayland.c:175
#2  surface_state_changed (window=...) at ../src/wayland/meta-window-wayland.c:200
...
#12 meta_window_appears_focused_changed (window=...) at ../src/core/window.c:5645
#13 meta_window_set_focused_internal (window=..., focused=1) at ../src/core/window.c:5796
#14 meta_display_update_focus_window (display=..., window=...) at ../src/core/display.c:1492
#15 meta_display_set_input_focus (display=..., window=..., ...) at ../src/core/display.c:1547
#16 meta_window_focus (window=..., timestamp=23319) at ../src/core/window.c:5255
#17 meta_window_show (window=...) at ../src/core/window.c:2678
...
#20 idle_calc_showing (data=...) at ../src/core/window.c:1942
```

The faulting instruction is `idiv %ecx`, and the configuration is
`{serial = 1, has_size = 1, width = 0, height = 0, scale = 0, ...}`. When a `wl_shell` window is shown and takes the
focus before any configure was sent, `surface_state_changed()` builds a configuration from `last_sent_width`,
`last_sent_height` and `last_sent_geometry_scale`, which are still 0, and `wl_shell_surface_role_configure()`
(`src/wayland/meta-wayland-wl-shell.c`) sends `configuration->width / configuration->scale`.

Cinnamon 6.8.3 survives the same clients: Muffin's master branch no longer has `meta-wayland-wl-shell.c`. The 6.4
packages still do. A guard there (skip the configure, or treat a scale of 0 as 1, when nothing was sent yet) would let
distributions on 6.4 take the fix.

### Reproduce

Headless, in a private Xvfb: start `muffin --wayland --nested --no-x11`, then run `wl-copy --foreground text` and
`wl-paste` against its socket. The automated version is `tests/compositors/probe.py --only muffin` in the repository
named below (it also runs `grim` and `wtype`).

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 07` (debian, ubuntu: 6.4 ends; fedora: 6.8 survives).
* Saved results: `docs/compositor-assessment/results-debian-13.json`, `results-ubuntu-26.04.json` (`survived_clients`).
* Backtraces: taken on 2026-11-27 in `debian-compositors` with `systemd-coredump` and `gdb` (debuginfod.debian.net),
  `coredumpctl debug PID`; `frame 0`, `x/i $pc` and `p *configuration` give the division and its operands.
* Source read: Muffin 6.4.1 `src/wayland/meta-window-wayland.c` (`surface_state_changed`),
  `src/wayland/meta-wayland-wl-shell.c` (`wl_shell_surface_role_configure`); on master the second file is gone.

## Reviewer notes (not posted)

* Duplicates checked 2026-11-27: none in Muffin's tracker (searched wl-copy, SIGFPE). Channel: as report 05.
* Which client triggers it: of the four the probe runs, only `wl-copy` and `wl-paste` create a surface (`grim` and
  `wtype` make none), so it is one of them; this is deduced, not isolated by a run with one client. The first survey
  named them too.
* In the Debian run of 2026-11-27 the probe recorded the Cinnamon shell as surviving, yet a core of the shell with the
  same backtrace was written in that run (two seconds after Muffin's): it probably ended after the probe's check, so
  "intermittent" may describe when it ends rather than whether. Not verified further.
* Muffin 6.4.1 alone ended on both distributions every time until 2026-11-27, when it survived one run of five on
  Ubuntu: say "nearly every time", not "every time".
