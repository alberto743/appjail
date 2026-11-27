# 10. Wayfire, Cage and Weston: no security context, privileged globals on the only socket

| | |
|---|---|
| Targets | Wayfire: `github.com/WayfireWM/wayfire`; Cage: `github.com/cage-kiosk/cage`; Weston: `gitlab.freedesktop.org/wayland/weston` |
| Measured | Wayfire 0.9.0, 0.10.0, 0.10.1; Cage 0.2.0, 0.2.1, 0.3.1; Weston 14.0.2, 15.0.1 |
| Class | feature request (implement `wp_security_context_v1`), or documentation |
| Our severity | low (design choices; useful to know for sandboxes) |
| Suggested channel | public issues |
| Review | pending (a candidate for not filing: ask the owner) |
| Filed | not filed |

## Issue text

**Title (each project):** Offer `wp_security_context_v1`, or document that the only socket is fully privileged

None of these compositors offers `wp_security_context_v1`. A sandbox therefore has to hand its app the compositor's one
socket, and that socket lists, measured on Debian 13, Ubuntu 26.04 and Fedora 45:

*  Wayfire and Cage: `zwlr_screencopy_manager_v1`, `zwlr_export_dmabuf_manager_v1`, `zwlr_virtual_pointer_manager_v1`,
  `zwp_virtual_keyboard_manager_v1`, and (Wayfire) `zwlr_data_control_manager_v1`, `zwlr_foreign_toplevel_manager_v1`,
  `zwlr_layer_shell_v1`, `zwf_shell_manager_v2`; with real clients, Cage and Wayfire 0.10 allowed capture, and both
  allowed typing and reading the clipboard without focus;
*  Weston: `weston_capture_v1`, `zwp_input_panel_v1`, `weston_desktop_shell` (not exercised by the probes).

Asking for the restricted-socket protocol, or a sentence in the documentation that the socket is not a sandbox boundary,
would let sandboxes decide without measuring.

## Evidence and reproduction in the repository

*  `upstream-reports/reproduce.sh 10` (debian, ubuntu, fedora).
*  Saved results: `docs/compositor-assessment/results-*.json` (`wayfire`, `cage`, `weston`).

## Reviewer notes (not posted)

*  Cage is a kiosk compositor: a request there may not be welcome. Decide per project.
*  The Weston globals were listed, not tried.
