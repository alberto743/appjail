# 07. Muffin and Cinnamon 6.4 end when wl-copy or wl-paste connect

| | |
|---|---|
| Target | Muffin: `github.com/linuxmint/muffin` |
| Measured | Muffin 6.4.1 (Debian 13, Ubuntu 26.04) every time; Cinnamon 6.4.10 and 6.4.13 (the shell on it) in the saved surveys, intermittently on rerun; Cinnamon 6.8.0 survived |
| Class | crash (any client ends the session) |
| Our severity | low to medium |
| Suggested channel | public issue |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** Muffin 6.4.1 (Wayland): SIGFPE when `wl-copy` or `wl-paste` connect

Muffin 6.4.1 (Debian 13 and Ubuntu 26.04), and often the Cinnamon 6.4 shell on it, terminate with a floating-point
exception when `wl-copy` or `wl-paste` (wl-clipboard) connect to the compositor's Wayland socket; started headless, in a
private Xvfb (`xvfb-run`-style private Xvfb; `muffin --wayland --nested --no-x11`, and
`cinnamon --wayland --nested --no-x11 --sm-disable`). Any client can therefore end a Wayland session. Cinnamon 6.8.0
survived the same clients, so the cause may be fixed upstream; the question is which change fixed it, so that the 6.4
packages can take it.

The clients that were run in sequence are `grim`, `wtype`, `wl-copy --foreground` and `wl-paste`; the compositor stopped
answering while they ran (`survived_clients: false`). The probe records it; it does not isolate which of the four ends
it (the earlier survey named `wl-copy` and `wl-paste`).

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 07` (debian, ubuntu: 6.4 ends; fedora: 6.8 survives).
* Saved results: `docs/compositor-assessment/results-debian-13.json`, `results-ubuntu-26.04.json` (`survived_clients`).

## Reviewer notes (not posted)

* No core file or backtrace was kept. Before filing, reproduce once with `coredumpctl` or `gdb` in the guest and attach
  the backtrace.
* Which of the four clients ends it was not isolated in the saved run.
* Intermittent for the Cinnamon shell: the saved surveys and an Ubuntu rerun (6.4.13) ended it; a rerun on Debian
  (6.4.10) survived. Muffin 6.4.1 alone ended on both distributions every time recorded.
