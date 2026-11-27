# 10. Wayfire, Cage and Weston: no security context, privileged globals on the only socket

| | |
|---|---|
| Targets | Wayfire: `github.com/WayfireWM/wayfire`; Cage: `github.com/cage-kiosk/cage`; Weston: `gitlab.freedesktop.org/wayland/weston` |
| Measured | Wayfire 0.9.0, 0.10.0, 0.10.1; Cage 0.2.0, 0.2.1, 0.3.1; Weston 14.0.2, 15.0.1 |
| Class | feature request (implement `wp_security_context_v1`), or documentation |
| Our severity | low (design choices; useful to know for sandboxes) |
| Suggested channel | Weston only, if at all (a public issue): Wayfire 0.11.0 has the protocol, and Cage's maintainer points to it |
| Review | pending (a candidate for not filing: ask the owner) |
| Filed | not filed |

## Issue text

**Title (each project):** Offer `wp_security_context_v1`, or document that the only socket is fully privileged

None of these compositors offers `wp_security_context_v1`. A sandbox therefore has to hand its app the compositor's one
socket, and that socket lists, measured on Debian 13, Ubuntu 26.04 and Fedora 45:

* Wayfire and Cage: `zwlr_screencopy_manager_v1`, `zwlr_export_dmabuf_manager_v1`, `zwlr_virtual_pointer_manager_v1`,
  `zwp_virtual_keyboard_manager_v1`, and (Wayfire) `zwlr_data_control_manager_v1`, `zwlr_foreign_toplevel_manager_v1`,
  `zwlr_layer_shell_v1`, `zwf_shell_manager_v2`; with real clients, Cage and Wayfire 0.10 allowed capture, and both
  allowed typing and reading the clipboard without focus;
* Weston: `weston_capture_v1`, `zwp_input_panel_v1`, `weston_desktop_shell` (not exercised by the probes).

Asking for the restricted-socket protocol, or a sentence in the documentation that the socket is not a sandbox boundary,
would let sandboxes decide without measuring.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 10` (debian, ubuntu, fedora).
* Saved results: `docs/compositor-assessment/results-*.json` (`wayfire`, `cage`, `weston`).

## Reviewer notes (not posted)

* Checked 2026-11-27: Wayfire merged `security-context-v1` in September 2025 (PR #2828, fixing #2151) and released it
  in 0.11.0 (2026-07-27; `plugins/protocols/security-context-v1.cpp` is in that tag, not in 0.10.1). The Wayfire part
  is obsolete: drop it, or only say that distributions on 0.9 and 0.10 lack the protocol. Cage: in cage#505 (May 2026)
  the maintainer wrote that Cage should not be needed to secure a Wayland socket and that `wp_security_context_v1`
  should be enough; a request is unlikely to be welcome. Weston: #206 ("A security context implementation for
  authenticating and/or authorizing clients") was closed on 2024-08-01; why was not read (the comments need a login).
* Cage is a kiosk compositor: a request there may not be welcome. Decide per project.
* The Weston globals were listed, not tried.
