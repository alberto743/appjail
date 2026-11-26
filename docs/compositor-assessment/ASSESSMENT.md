# Compositor security assessment

Status: measurements complete for Debian 13, Ubuntu 26.04 and Fedora 45. Decided: option A below (the rule reads the
registry of the socket the app will get), KWin is refused by default, and the D-Bus names that hand over the desktop are
refused as a family. The implementation follows in `src/appjail/wayland.py`, `grants.py` and `dbusproxy.py`; this
document keeps the evidence. A granted D-Bus name used to reach every interface of the connection that owns it, which
defeated the refused names on GNOME Shell, Cinnamon and Plasma's shell; appjail now confines known services and refuses
the other grants that share a refused name's owner (see "One granted name reaches its whole connection").

## Why this exists

appjail's Wayland rule assumed that a compositor without `wp_security_context_v1` cannot restrict an app's socket and
that the full socket is dangerous, so `run` refuses a windowed app there unless it has the permission `full_wayland`.
That rule was built on a claim, repeated in the README and in DESIGN.md, that GNOME's Mutter implements the protocol
from version 46. **It does not** (measured on Mutter 48.7 and 50.1). Mutter protects privileged operations another way,
through D-Bus, so the rule as merged refuses every windowed app on a stock GNOME session while protecting little there.
This assessment replaces the claim with measurements and sets out what a correct rule has to rest on.

## Method

`tests/compositors/probe.py` runs, unchanged, in a guest per distribution (`GUEST=debian-compositors`,
`GUEST=ubuntu-compositors`, `GUEST=fedora-compositors`, see `tests/vm/guest.sh`; the packages are in
`tests/vm/packages-compositors.txt`). For every compositor it starts the compositor headless (Muffin and the Cinnamon
shell, which have no headless backend, as a window of a private Xvfb) in a private runtime directory and on a private
session bus, and records:

* **Wayland registry** on the compositor's own socket, read with appjail's own protocol code and, as a second reader,
  with `wayland-info` (the two agreed for every compositor); whether `wp_security_context_manager_v1` is offered; and,
  when it is, the registry on the restricted socket that `wayland.RestrictedSocket` creates for an app.
* **What a client can really do** (advertised is not usable), with real tools, on each socket: capture the screen
  (`grim`), read another client's clipboard (`wl-copy` by a victim, `wl-paste` by the client), type (`wtype`).
* **D-Bus:** every interface of the bus names the compositor owns (`busctl`); side-effect-free calls made as an ordinary
  client; for GNOME, what Mutter's service channel hands out (via GLib); and what appjail's own D-Bus name policy
  (`grants.check_dbus_name`) does with each name.

Where a desktop keeps its privileged operations on D-Bus, a second tool shows what an ordinary client of the bus gets
through them, end to end: `mutter_dbus.py` (Mutter, GNOME Shell) and `cinnamon_dbus.py` (Cinnamon). How to assess a
compositor that is not here yet, step by step, and what went wrong on the way:
[the method](../develop/assessing-compositors.md).

Raw results: `results-*.json` (probe.py), `rule-a-*.json` (rule_a.py), `clipboard-*.json` (clipboard.py),
`mutter-dbus-*.json`, `cinnamon-dbus-*.json` and `shared-connection-*.json` (shared_connection.py), one file per
distribution, in this directory. Every table between `generated` markers is written by
`tests/compositors/report.py --write` from those files and checked against them by `tests/test_assessment.py`; edit the
results or the tool, not the table. The guests ran identical code. Nothing here comes from a third party. The survey
(`results-*.json`) was taken before the decisions: its `appjail_policy_*` fields and its privileged counts describe
appjail's D-Bus name policy and rule as they then were, not as they are now.

## Results: the Wayland socket

Cell format is capture / clipboard / typing, `yes` meaning a client succeeded.

<!-- generated:wayland -->
| Compositor | Distribution | Version | Security context | Privileged interfaces on the full socket | Full socket: capture / clipboard / typing | Restricted socket: capture / clipboard / typing | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | no | 6 | yes/yes/yes | - |  |
| cage | fedora 45 | 0.3.1-2.fc45 | no | 7 | yes/yes/yes | - |  |
| cage | ubuntu 26.04 | 0.2.1-1 | no | 6 | yes/yes/yes | - |  |
| cinnamon | debian 13 | 6.4.10-2+deb13u1 | no | 1 | no/no/no | - |  |
| cinnamon | fedora 45 | 6.8.0-1.fc45 | no | 3 | no/yes/no | - |  |
| cinnamon | ubuntu 26.04 | 6.4.13-2ubuntu0.2 | no | 1 | no/no/no | - |  |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | no | 1 | no/no/no | - |  |
| gnome-shell | fedora 45 | 51.1-1.fc45 | no | 1 | no/no/no | - |  |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | no | 1 | no/no/no | - |  |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | yes | 20 | no/yes/yes | no/no/no |  |
| hyprland | fedora 45 | - | - | - | - | - | not installed |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | yes | 17 | - | - | ConnectionRefusedError: [Errno 111] Connection refused |
| kwin | debian 13 | 4:6.3.6-1 | yes | 5 | no/yes/no | no/yes/no |  |
| kwin | fedora 45 | 6.8.2-3.fc45 | yes | 15 | no/yes/no | no/yes/no |  |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | yes | 5 | no/yes/no | no/yes/no |  |
| labwc | debian 13 | 0.8.3-1 | yes | 14 | yes/yes/yes | no/no/no |  |
| labwc | fedora 45 | 0.20.2-2.fc45 | yes | 18 | yes/yes/yes | no/no/no |  |
| labwc | ubuntu 26.04 | 0.9.3-1 | yes | 17 | yes/yes/yes | no/no/no |  |
| muffin | debian 13 | 6.4.1-1 | no | 1 | no/no/no | - |  |
| muffin | fedora 45 | 6.8.1-1.fc45 | - | - | - | - | not installed |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | no | 1 | no/no/no | - |  |
| mutter | debian 13 | 48.7-0+deb13u1 | no | 1 | no/no/no | - |  |
| mutter | fedora 45 | 51.1-1.fc45 | no | 1 | no/no/no | - |  |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | no | 1 | no/no/no | - |  |
| plasmashell | debian 13 | 4:6.3.6-2 | yes | 9 | no/yes/no | no/yes/no |  |
| plasmashell | fedora 45 | 6.8.2-1.fc45 | yes | 15 | no/yes/no | no/yes/no |  |
| plasmashell | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | yes | 10 | no/yes/no | no/yes/no |  |
| sway | debian 13 | 1.10.1-2 | yes | 14 | yes/yes/yes | no/no/no |  |
| sway | fedora 45 | 1.12-2.fc45 | yes | 20 | yes/yes/yes | no/no/no |  |
| sway | ubuntu 26.04 | 1.11-3 | yes | 17 | yes/yes/yes | no/no/no |  |
| wayfire | debian 13 | 0.9.0-5 | no | 12 | no/yes/yes | - |  |
| wayfire | fedora 45 | 0.10.1-2.fc45 | no | 13 | yes/yes/yes | - |  |
| wayfire | ubuntu 26.04 | 0.10.0-1 | no | 13 | yes/yes/yes | - |  |
| weston | debian 13 | 14.0.2-1 | no | 3 | no/no/no | - |  |
| weston | fedora 45 | 15.0.1-3.fc45 | no | 3 | no/no/no | - |  |
| weston | ubuntu 26.04 | 14.0.2-5 | no | 3 | no/no/no | - |  |
<!-- /generated -->

The Hyprland 0.53.3 row on Ubuntu comes from the first survey, whose probe connected too early; see point 6 below.

What the table shows:

1. **sway, labwc, Hyprland 0.55** (wlroots-style; sway 1.12 and labwc 0.20 on Fedora): the security context works. The
   restricted socket hides every privileged interface and none of the three capabilities works on it, while all work (or
   clipboard and typing do) on the ordinary socket. This is the model appjail was written for.
2. **KWin (6.3.6, 6.6.6 and 6.8.2)**: the protocol is offered. On 6.3.6 and 6.6.6 the restricted socket hides **only the
   protocol manager itself**: a client on it sees the same privileged-looking interfaces (`zwlr_data_control_manager_v1`
   or `ext_data_control_manager_v1`, `zwlr_layer_shell_v1`, `org_kde_plasma_shell`, `kde_output_management_v2`,
   keyboard-shortcuts inhibit) and **can read another client's clipboard**. On 6.8.2 (Fedora 45) it also hides
   data-control, fake input, the lock screen overlay, activation feedback, Plasma window management and screencast, but
   still lists the layer shell, the Plasma shell, output management, screen power, brightness, screen edges, virtual
   desktops and the lock keys; the clipboard read that still worked there used `wl-paste`'s fallback, a window with the
   keyboard focus, which is the ordinary path. KWin guards the rest by other means (it does not advertise screen capture
   or fake input to an unauthorised client).
3. **GNOME (Mutter and GNOME Shell, 48.7, 50.1 and 51.1)**: no security context, and no privileged capability on the
   socket: none of the three works, and the only privileged-looking global is keyboard-shortcuts inhibit.
4. **Wayfire, Cage**: no security context, and the full socket allows clipboard reads and typing (Cage and Wayfire 0.10
   and later also capture).
5. **Weston 14 and 15**: no security context; none of the three works. It advertises weston-specific interfaces
   (`weston_capture_v1`, `weston_desktop_shell`, `zwp_input_panel_v1`) that these tools do not exercise, so this is not
   a statement that weston is safe.
6. **Hyprland 0.53.3 (Ubuntu 26.04)**: the table above comes from the first survey, where connections to the restricted
   socket were refused. A later, repeated run (`rule-a-*.json`) connected every time, so the refusal was a startup
   timing problem of the probe, not of Hyprland. What the later runs show is worse for 0.53: its restricted socket still
   lists `zwlr_virtual_pointer_manager_v1`, `zwp_input_method_manager_v2` and `zwp_virtual_keyboard_manager_v1`, and
   `wtype` types through it. 0.55.2 (Debian backports) hides them.
7. **Muffin 6.4.1** (Cinnamon's compositor, a Mutter fork; measured later, 2026-11-13): no security context, and, like
   Mutter, no privileged capability on the socket (the only extra global is keyboard-shortcuts inhibit). It lists four
   older or GTK-private versions of ordinary protocols (`wl_shell`, `zxdg_shell_v6`,
   `gtk_primary_selection_device_manager`, `gtk_text_input_manager`), classed as allowed. Muffin crashes (a
   floating-point exception) when `wl-copy` or `wl-paste` connect, so any client can end the session; that is Muffin's
   bug, and it is why the probe reads D-Bus before running the clients. Its D-Bus name
   `org.cinnamon.Muffin.DisplayConfig` answers any client of the bus and offers `ApplyMonitorsConfig`, `ChangeBacklight`
   and `SetCrtcGamma`; `org.cinnamon.Muffin` is refused as a family, like `org.gnome.Mutter`. Measured standalone here;
   the Cinnamon shell on top of it is point 8.
8. **Cinnamon 6.4.10 and 6.4.13** (the shell, a Muffin plugin, `cinnamon --wayland --nested`; measured 2026-11-13): the
   same Wayland socket as Muffin (the same globals, the same crash on `wl-copy` and `wl-paste`), so the rule runs apps
   on it. The shell adds a dozen bus names on Muffin's connection, among them `org.Cinnamon`, whose `Eval` runs any
   JavaScript inside the shell for any client of the bus (GNOME Shell refuses that outside its unsafe mode), and
   `org.gnome.Shell.Screenshot`. What that gives is in the D-Bus section below.
9. **Plasma's shell, plasmashell 6.3.6 and 6.6.6** (`plasma-workspace`, measured 2026-11-13): a Wayland client of a
   virtual KWin, started with the activity manager it needs, so the Wayland socket is KWin's (point 2 and the rule's
   verdict for KWin apply: `rule_a.py` refuses it like KWin; the clipboard works on its restricted socket, rerun
   2026-11-15). On the bus, one plasmashell connection owns `org.kde.plasmashell`, `org.kde.klipper`,
   `org.freedesktop.Notifications`, `org.kde.JobViewServer`, `org.kde.kuiserver`, `com.canonical.Unity` and a
   `org.kde.StatusNotifierHost-PID` name. Two of its calls answer any client: the shell's
   `org.kde.PlasmaShell.evaluateScript` runs a desktop script (in a manual check, a script wrote a file into the user's
   configuration directory), and `org.kde.klipper.klipper.getClipboardContents` (and the history calls) returned text
   another client had copied. Both names are refused (decision D).
10. **Fedora 45** (Mutter and GNOME Shell 51.1, KWin and Plasma 6.8.2, Cinnamon 6.8.0, sway 1.12, labwc 0.20,
    Wayfire 0.10.1, Cage 0.3.1, Weston 15; measured 2026-11-14): the same results as the other two systems, with five
    differences. **New globals.** Six globals were in no list, which refuses the compositor that offers them. Allowed
    after reading their definitions: `ext_background_effect_manager_v1` (blur behind the client's own translucent
    surface), `xdg_session_manager_v1` (the client's own toplevels, restored through a session token the compositor
    makes) and `kde_output_device_registry_v2` (the list of outputs, as `kde_output_device_v2`, already allowed,
    describes them). `xapp_shell_v1` was first allowed too (Cinnamon: hints for the client's own window, an icon name or
    path and a progress value; Muffin stores the string without opening anything or answering the client, no consumer of
    it was found in Cinnamon 6.8's scripts and libraries, and an X11 client can set the same hint through
    `_NET_WM_XAPP_ICON_NAME`); its definition made it privileged (item 12). Privileged, under "windows":
    `kde_lockscreen_overlay_v1` (a surface shown over the lock screen) and `org_kde_plasma_activation_feedback`
    (read-only events naming every app that is being started, defined in `plasma-window-management.xml`). The verdicts,
    rerun live with the new lists: GNOME runs; Cinnamon, KWin and Plasma are refused, and none of these six globals
    decides that. **Cinnamon 6.8 offers `zwlr_layer_shell_v1`** (6.4 did not): a client of the same socket drew a solid
    surface on the desktop with `swaybg`, and a whole-screen capture held it (checked by hand, with a control run
    without the client). That is what keeps Cinnamon 6.8 refused. **Cinnamon 6.8 renamed its screenshot service** from
    `org.gnome.Shell.Screenshot` to `org.cinnamon.Screenshot`, which answers `Screenshot` from any client (the D-Bus
    section below), so that name and `org.cinnamon.ScreenSaver` are refused. **Muffin and Cinnamon survived `wl-copy`
    and `wl-paste`**, which ended them in 6.4. **KWin 6.8 hosts `org.kde.touchpad` on the connection that owns
    `org.kde.KWin`**, so granting it reaches KWin (the shared-connection section below). **Not measured:** Hyprland
    (Fedora does not package it) and standalone Muffin (Fedora's `muffin` ships no executable; only the shell is
    measured, which runs Muffin).
11. **Reassessment from scratch** (2026-11-15, all three distributions; Cinnamon, Muffin and Plasma's shell reinstalled
    in the Debian and Ubuntu guests, where the packages had gone). Every compositor was surveyed again with fresh
    processes (`probe.py`, `rule_a.py`, `clipboard.py`) and compared with the saved results: **no registry, verdict or
    clipboard result differed**, and the clipboard of Plasma's shell, which had not been run on Debian and Ubuntu, works
    in both directions on the restricted socket. The protocol XML shipped by Fedora 45 (`wayland-protocols`,
    `plasma-wayland-protocols`) was then read for every allowed global, and one was tried live. Findings:
    - **`wp_drm_lease_device_v1` sends an unprivileged DRM descriptor on bind.** On Mutter and GNOME Shell (Debian 13,
      Ubuntu 26.04, Fedora 45) a client with nothing but a window received an open `/dev/dri/renderD128`, the node the
      `gpu` permission binds; Hyprland 0.55 does the same on its own socket (`card0`, non-master) and hides the global
      on the restricted one. Refusing it would put every GNOME user on `full_wayland`, so it stays allowed as
      an **accepted limit** and is written down (decision page, `devices.md`, `SECURITY.md`); a filtering proxy would
      remove it (deferred).
    - **`org_kde_kwin_appmenu_manager`** lets the app name a D-Bus service that the shell then calls as a menu:
      privileged ("windows"). Only KDE lists it, and KWin is refused anyway.
    - **`org_kde_kwin_idle`** has `simulate_user_activity`, which resets the idle timer, as
      `zwp_idle_inhibit_manager_v1` (allowed) already does while a window is visible: kept, as an accepted limit with
      idle notification.
    - **`kde_output_device_v2`, its registry and `wp_color_manager_v1`** give EDID, serial numbers and the colour
      profile of the outputs, a hardware fingerprint without control: accepted limits.
    - The other allowed globals act on the client's own surfaces, behind a focus, a serial or a token, or describe
      outputs. `RATIONALE` in `wayland.py` records this for every one of them and where the protocol was read.
12. **The seven globals first marked unread** (2026-11-15, same day). Their definitions came from the source packages of
    the versions measured (Debian's and Ubuntu's source packages through `apt-get source`, Fedora's source RPM; text
    only, read, not built): Mutter 48.7, Muffin 6.4.1 and 6.8.1, KWin 6.3.6, Mesa 26.1.6, Hyprland 0.55.2,
    hyprland-protocols 0.7.1, and GNOME Shell 48.7 for who uses what. Results:
    - **`gtk_shell1`: any client can take the keyboard focus.** `gtk_surface1.present(timestamp)` calls
      `meta_window_activate_full`, whose focus-stealing check (`timestamp` before `last_user_time`) is skipped for the
      timestamp 0; and `gtk_shell1.notify_launch(id)` makes a startup sequence that `gtk_surface1.request_focus(id)`
      then redeems, with the current time. `tests/compositors/focus_steal.py` tried it with two bare windows
      (`focus_client.py`, a stdlib client), one focused last: **on Mutter, Muffin and Cinnamon on Debian 13,
      Ubuntu 26.04 and Fedora 45 the other window took the focus** (`present 0` on every one of them, the notify route
      on every one; GNOME Shell on Debian lost both windows to its overview on `present 0` and took the focus through
      the notify route; GNOME Shell on Fedora never gave the first window the focus: untestable). The control (nothing
      sent) and `present 1` did not take it. `set_dbus_properties` is stored on the window and GNOME Shell builds
      `org.gtk.Actions` and `org.gtk.Application` proxies to the bus name and paths the app gave (`shell-app.c`). Both
      are accepted limits: refusing `gtk_shell1` refuses all of GNOME and Cinnamon 6.4. Raw results: `focus-*.json`.
    - **`wl_drm`** (KWin, Plasma's shell, Hyprland): the device name (`/dev/dri/renderD128`), no descriptor.
      `authenticate` is answered and does nothing (Hyprland's code says so); `create_buffer` by flink name is refused by
      KWin ("not implemented") and Hyprland ("use prime instead"): tried live. Own buffers only.
    - **`hyprland_surface_manager_v1`**: opacity and visible region of the client's own surface (the XML and Hyprland's
      code).
    - **`frog_color_management_factory_v1`** (KWin): colour management of the client's own surface, and an event with
      the preferred metadata of its output.
    - **`gtk_primary_selection_device_manager`, `gtk_text_input_manager`** (Muffin): the selection is offered only to
      the client with the keyboard focus, text input follows the focus, as the `zwp_` versions.
    - **`xapp_shell_v1`** (Muffin 6.8.1): its icon can be "an absolute path to an icon file" that the shell uses, so the
      shell opens a file the app names: privileged ("windows"), not allowed as first decided. Only Cinnamon 6.8 lists
      it, and that is refused for the layer shell.

## Results: option A and the clipboard, tried live

`tests/compositors/rule_a.py` applies option A to every compositor: it picks the socket the app would get (the
restricted one when the compositor makes it, else its own), lists the privileged globals left on it, and starts a real
window client (`weston-simple-shm`) there. The privileged set is `wayland.PRIVILEGED`, which leaves out three globals
the survey also counts (`probe.EXTRA`) because they are harmless on their own:
`zwp_keyboard_shortcuts_inhibit_manager_v1` (apps use it while focused; it is also the only extra global GNOME shows)
and the two capture-*source* managers (they name a target; a copy manager is what captures). Raw data: `rule-a-*.json`.

<!-- generated:rule -->
| Compositor | Distribution | Version | Socket the app gets | Privileged interfaces left on it | Window client | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; input: zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_gamma_control_manager_v1, zwlr_output_manager_v1 | works | refuse |
| cage | fedora 45 | 0.3.1-2.fc45 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; input: zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_output_manager_v1 | works | refuse |
| cage | ubuntu 26.04 | 0.2.1-1 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; input: zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_gamma_control_manager_v1, zwlr_output_manager_v1 | works | refuse |
| cinnamon | debian 13 | 6.4.10-2+deb13u1 | full | nothing | works | run |
| cinnamon | fedora 45 | 6.8.0-1.fc45 | full | windows: xapp_shell_v1, zwlr_layer_shell_v1 | works | refuse |
| cinnamon | ubuntu 26.04 | 6.4.13-2ubuntu0.2 | full | nothing | works | run |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | full | nothing | works | run |
| gnome-shell | fedora 45 | 51.1-1.fc45 | full | nothing | works | run |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | full | nothing | works | run |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | restricted | nothing | works | run |
| hyprland | fedora 45 | - | - | - | - | not installed |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | restricted | input: zwlr_virtual_pointer_manager_v1, zwp_input_method_manager_v2, zwp_virtual_keyboard_manager_v1 | works | refuse |
| kwin | debian 13 | 4:6.3.6-1 | restricted | clipboard: zwlr_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| kwin | fedora 45 | 6.8.2-3.fc45 | restricted | desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_kwin_keystate, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | clipboard: ext_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_kwin_keystate, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| labwc | debian 13 | 0.8.3-1 | restricted | nothing | works | run |
| labwc | fedora 45 | 0.20.2-2.fc45 | restricted | nothing | works | run |
| labwc | ubuntu 26.04 | 0.9.3-1 | restricted | nothing | works | run |
| muffin | debian 13 | 6.4.1-1 | full | nothing | works | run |
| muffin | fedora 45 | 6.8.1-1.fc45 | - | - | - | not installed |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | full | nothing | works | run |
| mutter | debian 13 | 48.7-0+deb13u1 | full | nothing | works | run |
| mutter | fedora 45 | 51.1-1.fc45 | full | nothing | works | run |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | full | nothing | works | run |
| plasmashell | debian 13 | 4:6.3.6-2 | restricted | clipboard: zwlr_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| plasmashell | fedora 45 | 6.8.2-1.fc45 | restricted | desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_kwin_keystate, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| plasmashell | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | clipboard: ext_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_kwin_keystate, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_kwin_appmenu_manager, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| sway | debian 13 | 1.10.1-2 | restricted | nothing | works | run |
| sway | fedora 45 | 1.12-2.fc45 | restricted | nothing | works | run |
| sway | ubuntu 26.04 | 1.11-3 | restricted | nothing | works | run |
| wayfire | debian 13 | 0.9.0-5 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; clipboard: zwlr_data_control_manager_v1; input: zwf_shell_manager_v2, zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_layer_shell_v1, zwlr_output_manager_v1, zwlr_output_power_manager_v1 | works | refuse |
| wayfire | fedora 45 | 0.10.1-2.fc45 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; clipboard: zwlr_data_control_manager_v1; input: zwf_shell_manager_v2, zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: ext_session_lock_manager_v1, zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_layer_shell_v1, zwlr_output_manager_v1, zwlr_output_power_manager_v1 | works | refuse |
| wayfire | ubuntu 26.04 | 0.10.0-1 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; clipboard: zwlr_data_control_manager_v1; input: zwf_shell_manager_v2, zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: ext_session_lock_manager_v1, zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_layer_shell_v1, zwlr_output_manager_v1, zwlr_output_power_manager_v1 | works | refuse |
| weston | debian 13 | 14.0.2-1 | full | capture: weston_capture_v1; input: zwp_input_panel_v1; windows: weston_desktop_shell | works | refuse |
| weston | fedora 45 | 15.0.1-3.fc45 | full | capture: weston_capture_v1; input: zwp_input_panel_v1; windows: weston_desktop_shell | works | refuse |
| weston | ubuntu 26.04 | 14.0.2-5 | full | capture: weston_capture_v1; input: zwp_input_panel_v1; windows: weston_desktop_shell | works | refuse |
<!-- /generated -->

In short: sway, labwc, Hyprland 0.55 and GNOME run (nothing left on the socket); KWin, Wayfire, Cage, Weston,
Hyprland 0.53 and, on Fedora 45, Cinnamon are refused. Weston is refused although none of the three probes worked on it,
which is conservative. A window client ran on the chosen socket of every compositor, on every distribution.

`tests/compositors/clipboard.py` tests what an ordinary user does: copy in one window, paste in another, with real
keyboard focus, in both directions between a window outside and a window on the app's socket (`clipboard-*.json`). The
headless seats have no keyboard, so one is added: a persistent virtual keyboard (`wtype`) for the wlroots family, KWin's
own seat, the `org.gnome.Mutter.RemoteDesktop` API for Mutter and GNOME Shell (it needs a pointer click and a key to
focus a new window), and, for Weston, which has no input of its own, a nested run as a window of a headless sway.

<!-- generated:clipboard -->
| Compositor | Distribution | Version | Socket the app gets | Outside → app | App → outside |
| --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | full | ok | ok |
| cage | fedora 45 | 0.3.1-2.fc45 | full | ok | ok |
| cage | ubuntu 26.04 | 0.2.1-1 | full | ok | ok |
| cinnamon | debian 13 | 6.4.10-2+deb13u1 | full | ok | ok |
| cinnamon | fedora 45 | 6.8.0-1.fc45 | full | ok | ok |
| cinnamon | ubuntu 26.04 | 6.4.13-2ubuntu0.2 | full | ok | ok |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | full | ok | ok |
| gnome-shell | fedora 45 | 51.1-1.fc45 | full | untestable (a window never got keyboard focus) | untestable (a window never got keyboard focus) |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | full | ok | ok |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | restricted | ok | ok |
| hyprland | fedora 45 | - | - | - | not installed |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | restricted | ok | untestable (the compositor stopped answering: it crashed) |
| kwin | debian 13 | 4:6.3.6-1 | restricted | ok | ok |
| kwin | fedora 45 | 6.8.2-3.fc45 | restricted | ok | ok |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | ok | ok |
| labwc | debian 13 | 0.8.3-1 | restricted | ok | ok |
| labwc | fedora 45 | 0.20.2-2.fc45 | restricted | ok | ok |
| labwc | ubuntu 26.04 | 0.9.3-1 | restricted | ok | ok |
| muffin | debian 13 | 6.4.1-1 | full | ok | ok |
| muffin | fedora 45 | 6.8.1-1.fc45 | - | - | not installed |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | full | ok | ok |
| mutter | debian 13 | 48.7-0+deb13u1 | full | ok | ok |
| mutter | fedora 45 | 51.1-1.fc45 | full | ok | ok |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | full | ok | ok |
| plasmashell | debian 13 | 4:6.3.6-2 | restricted | ok | ok |
| plasmashell | fedora 45 | 6.8.2-1.fc45 | restricted | ok | ok |
| plasmashell | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | ok | ok |
| sway | debian 13 | 1.10.1-2 | restricted | ok | ok |
| sway | fedora 45 | 1.12-2.fc45 | restricted | ok | ok |
| sway | ubuntu 26.04 | 1.11-3 | restricted | ok | ok |
| wayfire | debian 13 | 0.9.0-5 | full | ok | ok |
| wayfire | fedora 45 | 0.10.1-2.fc45 | full | ok | ok |
| wayfire | ubuntu 26.04 | 0.10.0-1 | full | ok | ok |
| weston-nested | debian 13 | 14.0.2-1 | full | ok | ok |
| weston-nested | fedora 45 | 15.0.1-3.fc45 | full | ok | ok |
| weston-nested | ubuntu 26.04 | 14.0.2-5 | full | ok | ok |
<!-- /generated -->

`untestable` means a window never got keyboard focus, so nothing could be copied or pasted: it is not a failure of the
clipboard. On Hyprland 0.53.3 the cause is a crash, found on 2026-11-13: Hyprland aborts (SIGABRT, in
`CWindow::unmapWindow`, looking for the next window to focus, `CReservedArea`) when a window closes, depending on what
is left on the screen, so the next window has no compositor. Any client can therefore end a Hyprland 0.53.3 session by
closing a window; 0.55.2 did not crash in these runs. The outbound direction is the one that hits it in this test, so it
was `ok` only when an earlier run had not crashed it. `clipboard.py` now checks that the compositor still answers and
says when it crashed.

So ordinary copy and paste works wherever an app is allowed to run: the core clipboard (`wl_data_device`) needs focus
and is unaffected by hiding data-control. What the KWin refusal prevents is an app reading the clipboard without focus.

## Results: D-Bus

Calls made by an ordinary client on the compositor's session bus (side-effect free; a refused call says the compositor
itself checked the caller):

<!-- generated:dbus -->
| Compositor | Call, as an ordinary client | debian 13 | fedora 45 | ubuntu 26.04 |
| --- | --- | --- | --- | --- |
| cinnamon | `Cinnamon.Eval` | allowed | allowed | allowed |
| cinnamon | `Cinnamon.GetRunState` | allowed | allowed | allowed |
| cinnamon | `DisplayConfig.GetCurrentState` | allowed | allowed | allowed |
| cinnamon | `ScreenSaver.GetActive` | - | allowed | - |
| cinnamon | `Magnifier.isActive` | allowed | allowed | allowed |
| cinnamon | `Screenshot.SelectArea` | not called | - | not called |
| gnome-shell | `KeyboardMonitor.WatchKeyboard` | refused | refused | refused |
| gnome-shell | `DisplayConfig.GetCurrentState` | allowed | allowed | allowed |
| gnome-shell | `InputCapture.CreateSession` | allowed | allowed | allowed |
| gnome-shell | `RemoteDesktop.CreateSession` | allowed | allowed | allowed |
| gnome-shell | `ScreenCast.CreateSession` | allowed | allowed | allowed |
| gnome-shell | `ServiceChannel.OpenWaylandServiceConnection` | allowed | allowed | allowed |
| gnome-shell | `Shell.Eval` | refused | refused | refused |
| gnome-shell | `Introspect.GetWindows` | refused | - | refused |
| gnome-shell | `Screenshot.SelectArea` | refused | - | refused |
| kwin | `KeyboardMonitor.WatchKeyboard` | refused | refused | refused |
| kwin | `KGlobalAccel.allComponents` | allowed | allowed | allowed |
| kwin | `KWin.supportInformation` | allowed | allowed | allowed |
| kwin | `Scripting.isScriptLoaded` | allowed | allowed | allowed |
| muffin | `DisplayConfig.GetCurrentState` | allowed | - | allowed |
| mutter | `KeyboardMonitor.WatchKeyboard` | refused | refused | refused |
| mutter | `DisplayConfig.GetCurrentState` | allowed | allowed | allowed |
| mutter | `InputCapture.CreateSession` | allowed | allowed | allowed |
| mutter | `RemoteDesktop.CreateSession` | allowed | allowed | allowed |
| mutter | `ScreenCast.CreateSession` | allowed | allowed | allowed |
| mutter | `ServiceChannel.OpenWaylandServiceConnection` | allowed | allowed | allowed |
| plasmashell | `KeyboardMonitor.WatchKeyboard` | refused | refused | refused |
| plasmashell | `KGlobalAccel.allComponents` | allowed | allowed | allowed |
| plasmashell | `KWin.supportInformation` | allowed | allowed | allowed |
| plasmashell | `PlasmaShell.evaluateScript` | allowed | allowed | allowed |
| plasmashell | `klipper.getClipboardContents` | allowed | allowed | allowed |
| plasmashell | `Scripting.isScriptLoaded` | allowed | allowed | allowed |
<!-- /generated -->

* **GNOME**: Mutter's own `ScreenCast`, `RemoteDesktop` and `InputCapture` accept `CreateSession` from any client, and
  so do `DisplayConfig` and `ServiceChannel`. GNOME Shell checks the caller for the other privileged APIs (`Screenshot`,
  `Introspect.GetWindows`; the accessibility `KeyboardMonitor` is refused too). So Mutter does not tell an ordinary
  client from a portal: it relies on who can reach those names, i.e. on the sandbox's bus filter and on the consent
  dialog in the portal. The service channel (`OpenWaylandServiceConnection`) hands any client a Wayland connection; its
  registry holds exactly one global more than the ordinary socket, `mutter_x11_interop`, and no capture or input
  protocol (client types 1 to 3).
* **KDE**: KWin answers scripting, `supportInformation` (a system report) and `KGlobalAccel.allComponents` to any
  client; `KeyboardMonitor` is refused.
* **appjail's name policy, when surveyed** (the `appjail_policy_*` fields of `results-*.json`) allowed
  `org.gnome.Mutter.*` (every one of the names above), `org.freedesktop.a11y.Manager`, `org.kde.keyboard` and
  `org.kde.kglobalaccel`, and refused `org.gnome.Shell*` and `org.kde.KWin*`. That was the gap: a user who granted
  `org.gnome.Mutter.ScreenCast` or `org.gnome.Mutter.RemoteDesktop` gave the app the ability to capture the screen and
  type into other apps with no prompt (shown below). It is closed: decision D below refuses all of these names, and an
  app has no bus at all by default.

**A complete capture and keystroke** (`tests/compositors/mutter_dbus.py`, measured later, 2026-11-13; raw data
`mutter-dbus-*.json`): an ordinary client of the bus opens a `RemoteDesktop` session, clicks and types into the window
of another client (a GTK 4 window that logs the keys it receives), and opens a `ScreenCast` session on the monitor,
whose PipeWire stream it reads with GStreamer (a private PipeWire and WirePlumber in the compositor's runtime
directory). The frame holds the other client's red window. No portal and no prompt are involved. GNOME Shell starts in
its overview, which takes the first click and keys; the tool presses Escape first and tries the typing up to three
times. Eighteen runs (three on each of the six versions) all succeeded; one GNOME Shell 48.7 run needed a second try.

<!-- generated:mutter_dbus -->
| Compositor | Distribution | Version | RemoteDesktop: keys typed into another client's window | ScreenCast: a whole frame of the screen |
| --- | --- | --- | --- | --- |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | yes (`appjail`) | yes (786432 pixels, 2159 colours) |
| gnome-shell | fedora 45 | 51.1-1.fc45 | yes (`appjail`) | yes (786432 pixels, 25621 colours) |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | yes (`appjail`) | yes (786432 pixels, 499 colours) |
| mutter | debian 13 | 48.7-0+deb13u1 | yes (`appjail`) | yes (786432 pixels, 427 colours) |
| mutter | fedora 45 | 51.1-1.fc45 | yes (`appjail`) | yes (786432 pixels, 404 colours) |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | yes (`appjail`) | yes (786432 pixels, 411 colours) |
<!-- /generated -->

**Cinnamon** (`tests/compositors/cinnamon_dbus.py`, 2026-11-13; raw data `cinnamon-dbus-*.json`). Cinnamon has no
ScreenCast or RemoteDesktop of its own; it does not need them. `org.Cinnamon.Eval` runs the JavaScript it is sent inside
the shell, with the shell's privileges and every GObject library the shell has, and returns the result, to any client of
the bus. As an ordinary client, the tool:

* runs a command as the user (the script calls `GLib.spawn_command_line_async`, which creates a file);
* types into another client's window (the script activates the window and types with a virtual keyboard of the shell's
  own input stack; nested in Xvfb this is the X11 backend's virtual device, in a real session it would be the native
  one);
* takes a picture of the whole screen with `Screenshot` of the name Cinnamon owns for it (`org.gnome.Shell.Screenshot`
  in 6.4, `org.cinnamon.Screenshot` in 6.8), which it answers for any client; the picture is the size of the shell's
  stage and holds the other client's red window;
* calls `SelectArea` of the same name, after which Cinnamon is gone (a GTK error: in this nested setup the shell has no
  display for the selection; in a real session it may show the selection instead). probe.py skips this call on Cinnamon
  for that reason.

Three runs on each distribution, all with the same result (on Fedora the first run, on a guest just started, typed
nothing: the window had not taken the focus; the five after it did). `org.Cinnamon` also has `induceSegfault`,
`RestartCinnamon` and `ShowEndSessionDialog`, which were not called. Granting `org.Cinnamon` would therefore hand over
the user's account, so `org.Cinnamon` is refused as a family (decision D); `org.gnome.Shell.Screenshot` already was,
under `org.gnome.Shell`, and `org.cinnamon.Screenshot` and `org.cinnamon.ScreenSaver` (`Lock`, `Quit`, `SetActive`) are
refused since Fedora 45.

<!-- generated:cinnamon_dbus -->
| Distribution | Version | Eval: a command run as the user | Eval: keys typed into another client's window | Screenshot: the whole screen | SelectArea: Cinnamon still running afterwards |
| --- | --- | --- | --- | --- | --- |
| debian 13 | 6.4.10-2+deb13u1 | yes | yes (`appjail`) | yes (800x600, the other client's window in it) | no |
| fedora 45 | 6.8.0-1.fc45 | yes | yes (`appjail`) | yes (800x600, the other client's window in it) | no |
| ubuntu 26.04 | 6.4.13-2ubuntu0.2 | yes | yes (`appjail`) | yes (800x600, the other client's window in it) | no |
<!-- /generated -->

### One granted name reaches its whole connection

A desktop shell owns many names on **one** bus connection: next to the privileged names appjail refuses, it owns
ordinary ones a user may well grant (notifications, the keyring prompter, a mount-operation handler). xdg-dbus-proxy,
started as appjail starts it (`--filter --talk=NAME`), filters by the destination name of a call, not by its object or
interface, and a call to any name of a connection reaches every object of it. `tests/compositors/shared_connection.py`
(2026-11-13; raw data `shared-connection-*.json`) starts the proxy with one allowed name at a time, connects through it
as an app would, and sends the connection's privileged call to that allowed name:
`org.gnome.Mutter.RemoteDesktop.CreateSession` on GNOME Shell (the session that types into other windows, above),
`org.Cinnamon.Eval` of `1+1` on Cinnamon (the call that runs commands, above), `org.kde.PlasmaShell.evaluateScript` of
`print(1 + 1)` on plasmashell (point 9). On Fedora 45 KWin 6.8 lists a row too: `org.kde.touchpad` lives on its
connection, and the call to `org.kde.kwin.Scripting` reached KWin through it. Mutter and Muffin alone list no row: every
name of their privileged connection is refused.

The "reached with `--talk`" columns are the hole: every allowed name of both shells reached the privileged call. The
"appjail" columns are what `run` does now with the same grant (decision D):

* **Confined:** a name of a known service (`dbusproxy.CONFINED`: notifications, `org.gtk.Notifications`, the secret
  service, MPRIS, the status-notifier watcher) gets `--call` and `--broadcast` rules limited to its specified interfaces
  and object path instead of `--talk`. The privileged call was refused by the proxy whether it was addressed to the name
  or to its owner's unique name, and the service's own call still worked (`GetServerInformation`, `RemoveNotification`).
* **Refused at launch:** any other granted name gets `--talk`, so `run` first asks the bus who owns it and stops when
  that owner also owns a refused name. The check sees the owners at launch only: a name that nobody owns yet, or that
  changes owner while the app runs, is not caught ([D-Bus and the filtering proxy](../understand/desktop/dbus.md),
  Limits).

<!-- generated:shared_connection -->
| Compositor | Granted name (allowed) | Call sent to it | reached with `--talk`, debian 13 | appjail, debian 13 | reached with `--talk`, fedora 45 | appjail, fedora 45 | reached with `--talk`, ubuntu 26.04 | appjail, ubuntu 26.04 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cinnamon | `org.freedesktop.Notifications` | `Cinnamon.Eval` | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works |
| cinnamon | `org.gnome.Caribou.Keyboard` | `Cinnamon.Eval` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| cinnamon | `org.gnome.Magnifier` | `Cinnamon.Eval` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| cinnamon | `org.gnome.Panel` | `Cinnamon.Eval` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| cinnamon | `org.gnome.keyring.SystemPrompter` | `Cinnamon.Eval` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| cinnamon | `org.gtk.MountOperationHandler` | `Cinnamon.Eval` | - | - | yes | refused at launch | - | - |
| cinnamon | `org.x.StatusIconMonitor.cinnamon_0` | `Cinnamon.Eval` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| gnome-shell | `org.gnome.keyring.SystemPrompter` | `RemoteDesktop.CreateSession` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| gnome-shell | `org.gtk.MountOperationHandler` | `RemoteDesktop.CreateSession` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| gnome-shell | `org.gtk.Notifications` | `RemoteDesktop.CreateSession` | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works |
| kwin | `org.kde.touchpad` | `Scripting.isScriptLoaded` | - | - | yes | refused at launch | - | - |
| plasmashell | `com.canonical.Unity` | `PlasmaShell.evaluateScript` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| plasmashell | `org.freedesktop.Notifications` | `PlasmaShell.evaluateScript` | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works | yes | confined: privileged call blocked, the service's own call works |
| plasmashell | `org.kde.JobViewServer` | `PlasmaShell.evaluateScript` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| plasmashell | `org.kde.StatusNotifierHost-PID` | `PlasmaShell.evaluateScript` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| plasmashell | `org.kde.kuiserver` | `PlasmaShell.evaluateScript` | yes | refused at launch | yes | refused at launch | yes | refused at launch |
| plasmashell | `org.kde.touchpad` | `Scripting.isScriptLoaded` | - | - | yes | refused at launch | - | - |
<!-- /generated -->

Every one reached the compositor. So on GNOME Shell, granting `org.gtk.Notifications` (where GTK applications send their
notifications), `org.gnome.keyring.SystemPrompter` or `org.gtk.MountOperationHandler` gives an app Mutter's remote
desktop; on Cinnamon, granting `org.freedesktop.Notifications` (the example of a `dbus_filter` entry in DESIGN.md) or
any other name of the shell gives it `Eval`, that is, the user's account. Mutter and Muffin on their own own no allowed
name on that connection, so nothing reached there; KWin 6.8's `org.kde.touchpad` was refused at launch like the others.
In a real GNOME session the shell may own `org.freedesktop.Notifications` too; the headless shell did not, so that is
not measured. This is a hole in appjail's D-Bus grants, not in the compositors; the possible fixes are in
[One granted name reaches its whole connection](../decisions/desktop/dbus-connection.md).

## What it means for the security model

The question appjail has to answer is "can an app with default permissions capture the screen, snoop or inject input,
read another app's clipboard or take over the desktop?". The compositors answer it in different ways:

| Model | Compositors | What keeps an app out | What appjail has to do |
|---|---|---|---|
| Restricted socket | sway, labwc, Hyprland (0.55) | the compositor hides privileged globals from clients of a security context | use the restricted socket (done) |
| Mixed | KWin | the restricted socket hides little; KWin gates sensitive interfaces by authorisation, but data-control (clipboard, before 6.8), the layer shell, the Plasma shell and output management stay visible | refuse (decided: the registry rule below) |
| Nothing privileged on Wayland; D-Bus instead | GNOME, Cinnamon | the socket has no privileged global; the privileged APIs are on D-Bus and are only as protected as the bus | keep the app off those bus names (filter, denylist), keep portals consent-based |
| Nothing restricts it | Wayfire, Cage (and any compositor without the protocol that offers wlroots-style interfaces) | nothing | refuse, or accept knowingly (`full_wayland`) |

So the security-context test ("does the compositor offer the protocol") is neither necessary (GNOME is safe on the
socket without it) nor sufficient (KWin offers it and still shows the clipboard). The property that matters is **what
the socket the app will get actually lets a client do**, plus, for GNOME and KDE, **which bus names a user may grant**.

## Options considered and decision

**A. Decide from the registry of the socket the app will get.** Chosen. After choosing the socket, `run` refuses a
windowed app when the registry lists a privileged global (capture, virtual input, input method, data-control,
foreign-toplevel, layer shell, session lock, output management, gamma, ...) and names them; `full_wayland` overrides the
refusal. It matched the measurements of every compositor and distribution run. It began as a denylist of interface
names, which misses interfaces not on it; it is now an allowlist: every allowed global has a reason, and an unknown one
is refused like a privileged one ([the allowlist](../decisions/desktop/wayland-allowlist.md)).

**B. Warn only without the protocol.** Rejected: Wayfire and Cage let an app capture, type and read the clipboard, and a
terminal warning is not a decision.

**C. A table of compositors.** Rejected: right for the twelve measured, stale with every release, silent on the rest; A
reads the registry anyway.

**D. Close the D-Bus gaps.** Done alongside A: `org.gnome.Mutter` and, after Muffin and Cinnamon were measured,
`org.cinnamon.Muffin` and `org.Cinnamon` (every name of each family), and after Cinnamon 6.8 `org.cinnamon.Screenshot`
and `org.cinnamon.ScreenSaver`, `org.freedesktop.a11y`, `org.gnome.ScreenSaver`, `org.kde.kglobalaccel` and
`org.kde.keyboard` are refused, and after plasmashell was measured `org.kde.plasmashell` and `org.kde.klipper`. Under A
a GNOME or Cinnamon app has no privileged global on its socket, so these bus names are what keep it from capturing,
injecting input, running commands through the shell or locking the screen. Refusing names is not enough where an allowed
name shares the connection of a refused one (GNOME Shell, Cinnamon; found 2026-11-13, see "One granted name reaches its
whole connection"), so the proxy confines the grants of known services to their own objects, and `run` refuses any other
grant whose owner also owns a refused name.

**KWin.** Its restricted socket (6.3 and 6.6) hides only the protocol manager, so data-control stays visible and a
client reads another client's clipboard; 6.8 hides data-control but keeps the layer shell and shell control. Accepting
that for KWin alone would give the same capability as `full_wayland` without asking, so KWin is refused like any other
compositor with a privileged global, and the message says what is exposed.

**Hyprland 0.53.** Refused by A without a special case (see above).

**Unmeasured compositors** (niri, river, COSMIC) are decided by their registry at run time, and a global appjail does
not know refuses the app (`wayland.RATIONALE`, `wayland.PRIVILEGED`).

## Limits of this measurement

* Headless compositors in virtual machines with default configuration; no real session, no logged-in desktop, no
  extensions, no portal backends, no consent dialogs. A real GNOME or Plasma session may add services.
* Capture was tried with `grim`, which speaks only the wlroots and ext-image-copy-capture protocols: a compositor with
  its own (KWin's screencast, Hyprland's toplevel export) is not covered, and "no" means "not demonstrated with this
  tool".
* The unfocused clipboard read was tried through data-control (`wl-clipboard`), which GNOME does not offer. Focused copy
  and paste was tested on all compositors with GTK 4 windows (see above), but with an added virtual input device, in
  headless compositors; a real session adds clipboard managers and extensions that were not tried.
* One client per capability, on a quiet compositor. Xwayland, GPU, camera and audio were not part of this.
* Only the versions the three distributions package (and Hyprland from Debian backports). niri, river, COSMIC and
  Miriway are not packaged in any of them, so they were not measured here. Packaged but left out by decision
  (2026-11-13): Mir's demo shells (`mir-demos`), phoc (Phosh), gnome-kiosk, gamescope (Ubuntu only) and
  kylin-wayland-compositor (Ubuntu only).
* Muffin and Cinnamon were measured nested in Xvfb, without `cinnamon-session` and the daemons a real Cinnamon session
  starts (the settings daemon); those names were not measured. In that
  setup the shell's virtual keyboard is the X11 backend's.
* The layer-shell check on Cinnamon 6.8 (a `swaybg` surface in a screenshot) was done by hand, not by a saved tool.
* plasmashell was measured beside a virtual KWin with only the activity manager, without `plasma_session`, kded and the
  other daemons of a real Plasma session (the status-notifier watcher, KWallet, the screen locker); their names were not
  measured, and the end-to-end use of `evaluateScript` was checked by hand, not by a saved tool.
* Hyprland needed a particular environment to start in the VM, and its 0.53 result may be a bug fixed later.

## Reproducing

On a machine with qemu/KVM (see `CLAUDE.md`, Testing environment), for each of `debian`, `ubuntu` and `fedora`:

```sh
GUEST=<distro>-compositors tests/vm/create.sh      # reuses the base image; the first creation of that image downloads it
GUEST=<distro>-compositors tests/vm/start.sh
GUEST=<distro>-compositors tests/vm/ssh.sh 'sudo cloud-init status --wait'
GUEST=<distro>-compositors tests/vm/provision.sh   # installs the compositors (several hundred packages) and reboots
GUEST=<distro>-compositors tests/vm/sync.sh
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/probe.py --out /tmp/results.json'
# option A and the focused clipboard, each with its own results file:
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/rule_a.py --out /tmp/rule-a.json'
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/clipboard.py --out /tmp/clipboard.json'
# the desktops' D-Bus, end to end, and what one granted name reaches through appjail's proxy:
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/mutter_dbus.py --out /tmp/mutter-dbus.json'
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/cinnamon_dbus.py --out /tmp/cinnamon-dbus.json'
GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/shared_connection.py --only gnome-shell,mutter,cinnamon,kwin,muffin,plasmashell --out /tmp/shared-connection.json'
```

Copy each file to `docs/compositor-assessment/<prefix>-<distro>-<version>.json` and run
`python3 tests/compositors/report.py --write` in a guest. Adding one compositor to existing results, and everything
learned on the way: [the method](../develop/assessing-compositors.md).
