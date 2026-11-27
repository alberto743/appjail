# 04. KWin: the security-context socket still lists privileged globals

| | |
|---|---|
| Target | KWin and Plasma: `bugs.kde.org` (products kwin, plasmashell); verify the security contact at filing time |
| Measured | KWin 6.3.6 (Debian 13), 6.6.6 (Ubuntu 26.04), 6.8.2 (Fedora 45); Plasma's shell on the same |
| Class | hardening of `wp_security_context_v1` sockets; with 6.3 and 6.6 a clipboard read without focus |
| Our severity | medium on 6.3 and 6.6 (another client's clipboard read), low to medium on 6.8 (desktop-control globals) |
| Suggested channel | security contact first for the clipboard read (verify KDE's policy); the rest as a public bug |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** The restricted socket from `wp_security_context_v1` hides almost nothing; data-control (6.3, 6.6), layer
shell and shell control (all)

A sandbox engine that asks KWin for a restricted socket (`wp_security_context_v1`) gets a socket whose registry differs
from the compositor's own only by the manager itself (KWin 6.3.6 and 6.6.6), or by seven globals (6.8.2:
`ext_data_control_manager_v1`, `kde_lockscreen_overlay_v1`, `org_kde_kwin_fake_input`,
`org_kde_plasma_activation_feedback`, `org_kde_plasma_window_management`, `zkde_screencast_unstable_v1` and the
manager). What stays listed on the restricted socket:

* 6.3.6 and 6.6.6: `zwlr_data_control_manager_v1` (6.3.6) or `ext_data_control_manager_v1` (6.6.6). A client on the
  restricted socket, with no window and no focus, read the text another client had copied (`wl-copy` on the compositor's
  socket, `wl-paste` on the restricted one);
* all three: `zwlr_layer_shell_v1`, `org_kde_plasma_shell`, `kde_output_management_v2`, `org_kde_kwin_dpms_manager`,
  `kde_external_brightness_v1`, `kde_screen_edge_manager_v1`, `org_kde_plasma_virtual_desktop_management`
  (`org_kde_kwin_keystate` on 6.6 and 6.8).

Question: is the restricted socket meant to be a sandbox boundary, as the protocol describes it? If yes, these globals
should not be offered on it, as sway, labwc and Hyprland 0.55 do. KWin 6.8 shows the filter exists; extending it to the
layer shell, the Plasma shell and output management would make the socket usable by sandboxes without a per-compositor
exception.

Smaller points, from the protocol XML in `plasma-wayland-protocols` (not tried live):

* `org_kde_kwin_appmenu_manager.create(...).set_address(service, path)` makes the shell call a D-Bus service the client
  names;
* `org_kde_kwin_idle_timeout.simulate_user_activity` resets the idle timer without a window;
* `kde_output_device_v2` sends EDID, serial number and EISA id of every output.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 04` (debian, ubuntu, fedora): the privileged globals left on the restricted socket,
  and whether the clipboard read worked.
* Saved results: `docs/compositor-assessment/results-*.json` (`kwin`, `plasmashell`; `hidden_by_restriction`),
  `rule-a-*.json`.
* Source: KWin 6.3.6 (`src/wayland/protocols`), `plasma-wayland-protocols` XML (Fedora 45).

## Reviewer notes (not posted)

* On 6.8.2 the probe still read the clipboard on the restricted socket: that used `wl-paste`'s fallback (a window with
  focus), the ordinary path; it is not a bypass.
* Headless KWin (`kwin_wayland --virtual`) without a full Plasma session; `plasmashell` was started beside it.
* Related, not a KDE defect: the D-Bus findings in report 11 (`org.kde.PlasmaShell`, klipper).
