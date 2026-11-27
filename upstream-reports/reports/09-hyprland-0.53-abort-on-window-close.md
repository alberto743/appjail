# 09. Hyprland 0.53.3 aborts when a window closes

| | |
|---|---|
| Target | Ubuntu's `hyprland` package (26.04 ships 0.53.3); fixed upstream in 0.54.0 and 0.55.0 |
| Measured | Hyprland 0.53.3 (Ubuntu 26.04, `0.53.3+ds-4`); 0.55.2 did not crash in these runs; backtrace on 2026-11-27 |
| Class | crash (any client can end the session by closing a window) |
| Our severity | low to medium; intermittent |
| Suggested channel | a public Launchpad bug on Ubuntu's `hyprland` (upstream treats crashes as non-security and supports only its latest release) |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** hyprland 0.53.3: SIGABRT from an assertion in `CReservedArea` when a window closes; fixed upstream

Hyprland 0.53.3 as packaged in Ubuntu 26.04 (`0.53.3+ds-4`, `AQ_BACKENDS=headless`) aborts when a client disconnects
and its window is unmapped, depending on what is left on the screen. The compositor is gone, so the session ends. It
happens in a minority of runs: a test opens two small windows in turn (one copies, one pastes) and closes them.

Backtrace (systemd-coredump, symbols from debuginfod.ubuntu.com where available):

```
Program terminated with signal SIGABRT, Aborted.
#4  raise () from libc.so.6
#5  Desktop::CReservedArea::CReservedArea(Hyprutils::Math::CBox const&, Hyprutils::Math::CBox const&) ()
#6  Desktop::View::CWindow::getWindowIdealBoundingBoxIgnoreReserved() ()
#7  CWorkspace::getTopLeftWindow() ()
#8  IHyprLayout::getNextWindowCandidate(Hyprutils::Memory::CSharedPointer<Desktop::View::CWindow>) ()
#9  Desktop::View::CWindow::unmapWindow() ()
...
#17 CWLSurfaceResource::destroy() ()
...
#23 wl_client_destroy (client=...) at ../src/wayland-server.c:1014
```

In 0.53.3 that constructor (`src/desktop/reserved/ReservedArea.cpp`) asserts that both boxes are non-empty and that
the child lies inside the parent; an empty or misplaced box aborts the compositor. Upstream changed it in two commits,
neither in 0.53.3:

* `339661229d` "desktop/reserved: fix a possible reserved crash" (hyprwm/Hyprland#13207), in 0.54.0;
* `83d3babd4e` "desktop/reserved: do not crash on invalid box init" (hyprwm/Hyprland#13880), in 0.55.0: an empty box
  gives an empty reserved area and a misplaced one is logged instead of asserted (the code of 0.57.2; the diff of
  #13207 was not read).

0.55.2 did not crash in the same runs. Please consider taking the two commits into the 0.53 package.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 09` (ubuntu): runs `clipboard.py --only hyprland` up to three times and reports
  whether the compositor stopped answering. On 2026-11-27 it crashed on the first try.
* Backtrace: taken on 2026-11-27 in `ubuntu-compositors` with `systemd-coredump` and `gdb`, `coredumpctl debug PID`.
* Source read: Hyprland v0.53.3 and v0.57.2 `src/desktop/reserved/ReservedArea.cpp`; the commits that touched it, and
  which tags contain them (GitHub's compare of each tag with each commit).

## Reviewer notes (not posted)

* Channel and duplicates checked 2026-11-27: Hyprland's `SECURITY.md` lists crashes as not security issues and
  supports only the latest release (0.57.2); users can no longer open issues. Related upstream, not the same crash:
  #15096 (the dwindle layout while unmapping, 0.55.2, closed and sent to Discussions) and #14223 (a popup during
  `CWindow::unmapWindow`, 0.54.3).
* Hyprland's own frames have no line numbers (no debug symbols for it came from debuginfod), and no crash report or log
  was kept, so which of the three assertions failed is not known. That the two commits fix this crash is inferred from
  the frame and the code, not tested by building 0.53.3 with them.
* If three tries do not crash, the script says so: run it again, or increase the tries.
