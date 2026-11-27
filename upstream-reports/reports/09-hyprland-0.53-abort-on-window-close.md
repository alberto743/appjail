# 09. Hyprland 0.53.3 aborts when a window closes

| | |
|---|---|
| Target | Hyprland: `github.com/hyprwm/Hyprland` |
| Measured | Hyprland 0.53.3 (Ubuntu 26.04); 0.55.2 did not crash in these runs |
| Class | crash (any client can end the session by closing a window) |
| Our severity | low to medium; intermittent |
| Suggested channel | public issue, after checking whether 0.55 fixed it |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** 0.53.3: SIGABRT in `CWindow::unmapWindow` when a window closes (headless)

Hyprland 0.53.3 (`AQ_BACKENDS=headless`) aborts when a client's window closes, depending on what is left on the screen:
the abort is in `CWindow::unmapWindow`, while looking for the next window to focus (`CReservedArea`). The compositor is
gone, so the next client fails to connect. It happens in a minority of runs: the test opens two small windows in turn
(one copies, one pastes) and closes them; some runs finish, some end the compositor.

0.55.2 did not crash in the same runs. Is this a known 0.53 bug and was it fixed by a specific change?

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 09` (ubuntu): runs `clipboard.py --only hyprland` up to three times and reports
  whether the compositor stopped answering.
* Reproduction rate: the crash is intermittent; the saved Ubuntu results record one run where the second direction was
  untestable because of it.

## Reviewer notes (not posted)

* The backtrace was read during the original survey; it was not saved. Before filing, capture one (`coredumpctl` or the
  compositor log) and attach it.
* If three tries do not crash, the script says so: run it again, or increase the tries.
