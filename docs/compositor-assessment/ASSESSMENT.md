# Compositor security assessment

Status: measurements complete for Debian 13 and Ubuntu 26.04. Decided: option A below (the rule reads the registry of the
socket the app will get), KWin is refused by default, and the D-Bus names that hand over the desktop are refused as a family.
The implementation follows in `src/appjail/wayland.py` and `grants.py`; this document keeps the evidence.

## Why this exists

appjail's Wayland rule assumed that a compositor without `wp_security_context_v1` cannot restrict an app's socket and that the
full socket is dangerous, so `run` refuses a windowed app there unless it has the permission `full_wayland`. That rule was
built on a claim, repeated in the README and in DESIGN.md, that GNOME's Mutter implements the protocol from version 46. **It
does not** (measured on Mutter 48.7 and 50.1). Mutter protects privileged operations another way, through D-Bus, so the
rule as merged refuses every windowed app on a stock GNOME session while protecting little there. This assessment replaces
the claim with measurements and sets out what a correct rule has to rest on.

## Method

`tests/compositors/probe.py` runs, unchanged, in a guest per distribution (`GUEST=debian-compositors`,
`GUEST=ubuntu-compositors`, see `tests/vm/guest.sh`; the packages are in `tests/vm/packages-compositors.txt`). For every
compositor it starts the compositor headless (Muffin, which has no headless backend, as a window of a private Xvfb) in a
private runtime directory and on a private session bus, and records:

* **Wayland registry** on the compositor's own socket, read with appjail's own protocol code and, as a second reader, with
  `wayland-info` (the two agreed for every compositor); whether `wp_security_context_manager_v1` is offered; and, when it is,
  the registry on the restricted socket that `wayland.RestrictedSocket` creates for an app.
* **What a client can really do** (advertised is not usable), with real tools, on each socket: capture the screen (`grim`),
  read another client's clipboard (`wl-copy` by a victim, `wl-paste` by the client), type (`wtype`).
* **D-Bus:** every interface of the bus names the compositor owns (`busctl`); side-effect-free calls made as an ordinary
  client; for GNOME, what Mutter's service channel hands out (via GLib); and what appjail's own D-Bus name policy
  (`grants.check_dbus_name`) does with each name.

Raw results: `results-*.json` (probe.py), `rule-a-*.json` (rule_a.py) and `clipboard-*.json` (clipboard.py), one file per
distribution, in this directory. Every table between `generated` markers is written by `tests/compositors/report.py --write`
from those files and checked against them by `tests/test_assessment.py`; edit the results or the tool, not the table. Both
guests ran identical code. Nothing here comes from a third party. The survey (`results-*.json`) was taken before the
decisions: its `appjail_policy_*` fields and its privileged counts describe appjail's D-Bus name policy and rule as they
then were, not as they are now.

## Results: the Wayland socket

Cell format is capture / clipboard / typing, `yes` meaning a client succeeded.

<!-- generated:wayland -->
| Compositor | Distribution | Version | Security context | Privileged interfaces on the full socket | Full socket: capture / clipboard / typing | Restricted socket: capture / clipboard / typing | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | no | 6 | yes/yes/yes | - |  |
| cage | ubuntu 26.04 | 0.2.1-1 | no | 6 | yes/yes/yes | - |  |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | no | 1 | no/no/no | - |  |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | no | 1 | no/no/no | - |  |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | yes | 20 | no/yes/yes | no/no/no |  |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | yes | 17 | - | - | ConnectionRefusedError: [Errno 111] Connection refused |
| kwin | debian 13 | 4:6.3.6-1 | yes | 5 | no/yes/no | no/yes/no |  |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | yes | 5 | no/yes/no | no/yes/no |  |
| labwc | debian 13 | 0.8.3-1 | yes | 14 | yes/yes/yes | no/no/no |  |
| labwc | ubuntu 26.04 | 0.9.3-1 | yes | 17 | yes/yes/yes | no/no/no |  |
| muffin | debian 13 | 6.4.1-1 | no | 1 | no/no/no | - |  |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | no | 1 | no/no/no | - |  |
| mutter | debian 13 | 48.7-0+deb13u1 | no | 1 | no/no/no | - |  |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | no | 1 | no/no/no | - |  |
| sway | debian 13 | 1.10.1-2 | yes | 14 | yes/yes/yes | no/no/no |  |
| sway | ubuntu 26.04 | 1.11-3 | yes | 17 | yes/yes/yes | no/no/no |  |
| wayfire | debian 13 | 0.9.0-5 | no | 12 | no/yes/yes | - |  |
| wayfire | ubuntu 26.04 | 0.10.0-1 | no | 13 | yes/yes/yes | - |  |
| weston | debian 13 | 14.0.2-1 | no | 3 | no/no/no | - |  |
| weston | ubuntu 26.04 | 14.0.2-5 | no | 3 | no/no/no | - |  |
<!-- /generated -->

The Hyprland 0.53.3 row on Ubuntu comes from the first survey, whose probe connected too early; see point 6 below.

What the table shows:

1. **sway, labwc, Hyprland 0.55** (wlroots-style): the security context works. The restricted socket hides every privileged
   interface and none of the three capabilities works on it, while all work (or clipboard and typing do) on the ordinary
   socket. This is the model appjail was written for.
2. **KWin (6.3.6 and 6.6.6)**: the protocol is offered, but the restricted socket hides **only the protocol manager itself**.
   A client on it sees the same privileged-looking interfaces (`zwlr_data_control_manager_v1`, `zwlr_layer_shell_v1`,
   `org_kde_plasma_shell`, `kde_output_management_v2`, keyboard-shortcuts inhibit) and **can read another client's clipboard**.
   KWin guards the rest by other means (it does not advertise screen capture or fake input to an unauthorised client).
3. **GNOME (Mutter and GNOME Shell, 48.7 and 50.1)**: no security context, and no privileged capability on the socket: none of
   the three works, and the only privileged-looking global is keyboard-shortcuts inhibit.
4. **Wayfire, Cage**: no security context, and the full socket allows clipboard reads and typing (Cage and Wayfire 0.10 also
   capture).
5. **Weston 14**: no security context; none of the three works. It advertises weston-specific interfaces
   (`weston_capture_v1`, `weston_desktop_shell`, `zwp_input_panel_v1`) that these tools do not exercise, so this is not a
   statement that weston is safe.
6. **Hyprland 0.53.3 (Ubuntu 26.04)**: the table above comes from the first survey, where connections to the restricted socket
   were refused. A later, repeated run (`rule-a-*.json`) connected every time, so the refusal was a startup timing problem of
   the probe, not of Hyprland. What the later runs show is worse for 0.53: its restricted socket still lists
   `zwlr_virtual_pointer_manager_v1`, `zwp_input_method_manager_v2` and `zwp_virtual_keyboard_manager_v1`, and `wtype` types
   through it. 0.55.2 (Debian backports) hides them.
7. **Muffin 6.4.1** (Cinnamon's compositor, a Mutter fork; measured later, 2026-11-13): no security context, and, like Mutter,
   no privileged capability on the socket (the only extra global is keyboard-shortcuts inhibit). It lists four older or
   GTK-private versions of ordinary protocols (`wl_shell`, `zxdg_shell_v6`, `gtk_primary_selection_device_manager`,
   `gtk_text_input_manager`), classed as allowed. Muffin crashes (a floating-point exception) when `wl-copy` or `wl-paste`
   connect, so any client can end the session; that is Muffin's bug, and it is why the probe reads D-Bus before running the
   clients. Its D-Bus name `org.cinnamon.Muffin.DisplayConfig` answers any client of the bus and offers
   `ApplyMonitorsConfig`, `ChangeBacklight` and `SetCrtcGamma`; `org.cinnamon.Muffin` is refused as a family, like
   `org.gnome.Mutter`. Measured standalone, not inside a Cinnamon session (the `cinnamon` shell adds its own bus names,
   which were not measured).

## Results: option A and the clipboard, tried live

`tests/compositors/rule_a.py` applies option A to every compositor: it picks the socket the app would get (the restricted
one when the compositor makes it, else its own), lists the privileged globals left on it, and starts a real window client
(`weston-simple-shm`) there. The privileged set is `wayland.PRIVILEGED`, which leaves out three globals the survey also counts
(`probe.EXTRA`) because they are harmless on their own: `zwp_keyboard_shortcuts_inhibit_manager_v1` (apps use it while
focused; it is also the only extra global GNOME shows) and the two capture-*source* managers (they name a target; a copy
manager is what captures). Raw data: `rule-a-*.json`.

<!-- generated:rule -->
| Compositor | Distribution | Version | Socket the app gets | Privileged interfaces left on it | Window client | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; input: zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_gamma_control_manager_v1, zwlr_output_manager_v1 | works | refuse |
| cage | ubuntu 26.04 | 0.2.1-1 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; input: zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_gamma_control_manager_v1, zwlr_output_manager_v1 | works | refuse |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | full | nothing | works | run |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | full | nothing | works | run |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | restricted | nothing | works | run |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | restricted | input: zwlr_virtual_pointer_manager_v1, zwp_input_method_manager_v2, zwp_virtual_keyboard_manager_v1 | works | refuse |
| kwin | debian 13 | 4:6.3.6-1 | restricted | clipboard: zwlr_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | clipboard: ext_data_control_manager_v1; desktop: kde_external_brightness_v1, kde_screen_edge_manager_v1, org_kde_kwin_dpms_manager, org_kde_kwin_keystate, org_kde_plasma_virtual_desktop_management; windows: kde_output_management_v2, org_kde_plasma_shell, zwlr_layer_shell_v1 | works | refuse |
| labwc | debian 13 | 0.8.3-1 | restricted | nothing | works | run |
| labwc | ubuntu 26.04 | 0.9.3-1 | restricted | nothing | works | run |
| muffin | debian 13 | 6.4.1-1 | full | nothing | works | run |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | full | nothing | works | run |
| mutter | debian 13 | 48.7-0+deb13u1 | full | nothing | works | run |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | full | nothing | works | run |
| sway | debian 13 | 1.10.1-2 | restricted | nothing | works | run |
| sway | ubuntu 26.04 | 1.11-3 | restricted | nothing | works | run |
| wayfire | debian 13 | 0.9.0-5 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; clipboard: zwlr_data_control_manager_v1; input: zwf_shell_manager_v2, zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_layer_shell_v1, zwlr_output_manager_v1, zwlr_output_power_manager_v1 | works | refuse |
| wayfire | ubuntu 26.04 | 0.10.0-1 | full | capture: zwlr_export_dmabuf_manager_v1, zwlr_screencopy_manager_v1; clipboard: zwlr_data_control_manager_v1; input: zwf_shell_manager_v2, zwlr_virtual_pointer_manager_v1, zwp_virtual_keyboard_manager_v1; windows: ext_session_lock_manager_v1, zwlr_foreign_toplevel_manager_v1, zwlr_gamma_control_manager_v1, zwlr_layer_shell_v1, zwlr_output_manager_v1, zwlr_output_power_manager_v1 | works | refuse |
| weston | debian 13 | 14.0.2-1 | full | capture: weston_capture_v1; input: zwp_input_panel_v1; windows: weston_desktop_shell | works | refuse |
| weston | ubuntu 26.04 | 14.0.2-5 | full | capture: weston_capture_v1; input: zwp_input_panel_v1; windows: weston_desktop_shell | works | refuse |
<!-- /generated -->

In short: sway, labwc, Hyprland 0.55 and GNOME run (nothing left on the socket); KWin, Wayfire, Cage, Weston and Hyprland 0.53 are
refused. Weston is refused although none of the three probes worked on it, which is conservative. A window client ran on the
chosen socket of every compositor, on both distributions.

`tests/compositors/clipboard.py` tests what an ordinary user does: copy in one window, paste in another, with real keyboard
focus, in both directions between a window outside and a window on the app's socket (`clipboard-*.json`). The headless
seats have no keyboard, so one is added: a persistent virtual keyboard (`wtype`) for the wlroots family, KWin's own seat, the
`org.gnome.Mutter.RemoteDesktop` API for Mutter and GNOME Shell (it needs a pointer click and a key to focus a new window),
and, for Weston, which has no input of its own, a nested run as a window of a headless sway.

<!-- generated:clipboard -->
| Compositor | Distribution | Version | Socket the app gets | Outside → app | App → outside |
| --- | --- | --- | --- | --- | --- |
| cage | debian 13 | 0.2.0-2 | full | ok | ok |
| cage | ubuntu 26.04 | 0.2.1-1 | full | ok | ok |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | full | ok | ok |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | full | ok | ok |
| hyprland | debian 13 | 0.55.2+ds-1~bpo13+1 | restricted | ok | ok |
| hyprland | ubuntu 26.04 | 0.53.3+ds-4 | restricted | ok | untestable (a window never got keyboard focus) |
| kwin | debian 13 | 4:6.3.6-1 | restricted | ok | ok |
| kwin | ubuntu 26.04 | 4:6.6.6-0ubuntu0.1 | restricted | ok | ok |
| labwc | debian 13 | 0.8.3-1 | restricted | ok | ok |
| labwc | ubuntu 26.04 | 0.9.3-1 | restricted | ok | ok |
| muffin | debian 13 | 6.4.1-1 | full | ok | ok |
| muffin | ubuntu 26.04 | 6.4.1-1build1 | full | ok | ok |
| mutter | debian 13 | 48.7-0+deb13u1 | full | ok | ok |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | full | ok | ok |
| sway | debian 13 | 1.10.1-2 | restricted | ok | ok |
| sway | ubuntu 26.04 | 1.11-3 | restricted | ok | ok |
| wayfire | debian 13 | 0.9.0-5 | full | ok | ok |
| wayfire | ubuntu 26.04 | 0.10.0-1 | full | ok | ok |
| weston-nested | debian 13 | 14.0.2-1 | full | ok | ok |
| weston-nested | ubuntu 26.04 | 14.0.2-5 | full | ok | ok |
<!-- /generated -->

`untestable` means a window never got keyboard focus, so nothing could be copied or pasted: it is not a failure of the clipboard.
On Hyprland 0.53 the outbound direction was `ok` in some runs and `untestable` in others (cause unknown); the table shows the saved one.

So ordinary copy and paste works wherever an app is allowed to run: the core clipboard (`wl_data_device`) needs focus and
is unaffected by hiding data-control. What the KWin refusal prevents is an app reading the clipboard without focus.

## Results: D-Bus

Calls made by an ordinary client on the compositor's session bus (side-effect free; a refused call says the compositor itself
checked the caller):

<!-- generated:dbus -->
| Compositor | Call, as an ordinary client | debian 13 | ubuntu 26.04 |
| --- | --- | --- | --- |
| gnome-shell | `KeyboardMonitor.WatchKeyboard` | refused | refused |
| gnome-shell | `DisplayConfig.GetCurrentState` | allowed | allowed |
| gnome-shell | `InputCapture.CreateSession` | allowed | allowed |
| gnome-shell | `RemoteDesktop.CreateSession` | allowed | allowed |
| gnome-shell | `ScreenCast.CreateSession` | allowed | allowed |
| gnome-shell | `ServiceChannel.OpenWaylandServiceConnection` | allowed | allowed |
| gnome-shell | `Shell.Eval` | allowed | allowed |
| gnome-shell | `Introspect.GetWindows` | refused | refused |
| gnome-shell | `Screenshot.SelectArea` | refused | refused |
| kwin | `KeyboardMonitor.WatchKeyboard` | refused | refused |
| kwin | `KGlobalAccel.allComponents` | allowed | allowed |
| kwin | `KWin.supportInformation` | allowed | allowed |
| kwin | `Scripting.isScriptLoaded` | allowed | allowed |
| muffin | `DisplayConfig.GetCurrentState` | allowed | allowed |
| mutter | `KeyboardMonitor.WatchKeyboard` | refused | refused |
| mutter | `DisplayConfig.GetCurrentState` | allowed | allowed |
| mutter | `InputCapture.CreateSession` | allowed | allowed |
| mutter | `RemoteDesktop.CreateSession` | allowed | allowed |
| mutter | `ScreenCast.CreateSession` | allowed | allowed |
| mutter | `ServiceChannel.OpenWaylandServiceConnection` | allowed | allowed |
<!-- /generated -->

* **GNOME**: Mutter's own `ScreenCast`, `RemoteDesktop` and `InputCapture` accept `CreateSession` from any client, and so do
  `DisplayConfig` and `ServiceChannel`. GNOME Shell checks the caller for the other privileged APIs (`Screenshot`,
  `Introspect.GetWindows`; the accessibility `KeyboardMonitor` is refused too). So Mutter does not tell an ordinary client from
  a portal: it relies on who can reach those names, i.e. on the sandbox's bus filter and on the consent dialog in the portal.
  The service channel (`OpenWaylandServiceConnection`) hands any client a Wayland connection; its registry holds exactly one
  global more than the ordinary socket, `mutter_x11_interop`, and no capture or input protocol (client types 1 to 3).
* **KDE**: KWin answers scripting, `supportInformation` (a system report) and `KGlobalAccel.allComponents` to any client;
  `KeyboardMonitor` is refused.
* **appjail's name policy, when surveyed** (the `appjail_policy_*` fields of `results-*.json`) allowed `org.gnome.Mutter.*`
  (every one of the names above), `org.freedesktop.a11y.Manager`, `org.kde.keyboard` and `org.kde.kglobalaccel`, and refused
  `org.gnome.Shell*` and `org.kde.KWin*`. That was the gap: a user who granted `org.gnome.Mutter.ScreenCast` or
  `org.gnome.Mutter.RemoteDesktop` gave the app the ability to capture the screen and type into other apps with no prompt
  (shown below). It is closed: decision D below refuses all of these names, and an app has no bus at all by default.

**A complete capture and keystroke** (`tests/compositors/mutter_dbus.py`, measured later, 2026-11-13; raw data
`mutter-dbus-*.json`): an ordinary client of the bus opens a `RemoteDesktop` session, clicks and types into the window of
another client (a GTK 4 window that logs the keys it receives), and opens a `ScreenCast` session on the monitor, whose PipeWire
stream it reads with GStreamer (a private PipeWire and WirePlumber in the compositor's runtime directory). The frame holds
the other client's red window. No portal and no prompt are involved. GNOME Shell starts in its overview, which takes the
first click and keys; the tool presses Escape first and tries the typing up to three times. Twelve runs (three on each of
the four versions) all succeeded; one GNOME Shell 48.7 run needed a second try.

<!-- generated:mutter_dbus -->
| Compositor | Distribution | Version | RemoteDesktop: keys typed into another client's window | ScreenCast: a whole frame of the screen |
| --- | --- | --- | --- | --- |
| gnome-shell | debian 13 | 48.7-0+deb13u2 | yes (`appjail`) | yes (786432 pixels, 2159 colours) |
| gnome-shell | ubuntu 26.04 | 50.1-0ubuntu1.5 | yes (`appjail`) | yes (786432 pixels, 499 colours) |
| mutter | debian 13 | 48.7-0+deb13u1 | yes (`appjail`) | yes (786432 pixels, 427 colours) |
| mutter | ubuntu 26.04 | 50.1-0ubuntu2.5 | yes (`appjail`) | yes (786432 pixels, 411 colours) |
<!-- /generated -->

## What it means for the security model

The question appjail has to answer is "can an app with default permissions capture the screen, snoop or inject input, read
another app's clipboard or take over the desktop?". The compositors answer it in different ways:

| Model | Compositors | What keeps an app out | What appjail has to do |
|---|---|---|---|
| Restricted socket | sway, labwc, Hyprland (0.55) | the compositor hides privileged globals from clients of a security context | use the restricted socket (done) |
| Mixed | KWin | the restricted socket hides almost nothing; KWin gates sensitive interfaces by authorisation, but data-control (clipboard) stays visible | use the restricted socket and decide whether the clipboard exposure is acceptable |
| Nothing privileged on Wayland; D-Bus instead | GNOME | the socket has no privileged global; the privileged APIs are on D-Bus and are only as protected as the bus | keep the app off those bus names (filter, denylist), keep portals consent-based |
| Nothing restricts it | Wayfire, Cage (and any compositor without the protocol that offers wlroots-style interfaces) | nothing | refuse, or accept knowingly (`full_wayland`) |

So the security-context test ("does the compositor offer the protocol") is neither necessary (GNOME is safe on the socket
without it) nor sufficient (KWin offers it and still shows the clipboard). The property that matters is **what the socket the
app will get actually lets a client do**, plus, for GNOME and KDE, **which bus names a user may grant**.

## Options considered and decision

**A. Decide from the registry of the socket the app will get.** Chosen. After choosing the socket, `run` refuses a windowed
app when the registry lists a privileged global (capture, virtual input, input method, data-control, foreign-toplevel, layer
shell, session lock, output management, gamma, ...) and names them; `full_wayland` overrides the refusal. It matched the
measurements of all 18 compositor and distribution runs. Weakness: a denylist of interface names misses interfaces not on it
(the inverse, allowing only known-harmless globals, would refuse compositors on their own extras).

**B. Warn only without the protocol.** Rejected: Wayfire and Cage let an app capture, type and read the clipboard, and a
terminal warning is not a decision.

**C. A table of compositors.** Rejected: right for the nine measured, stale with every release, silent on the rest; A reads
the registry anyway.

**D. Close the D-Bus gaps.** Done alongside A: `org.gnome.Mutter` and, after Muffin was measured, `org.cinnamon.Muffin`
(every name of each family), `org.freedesktop.a11y`,
`org.gnome.ScreenSaver`, `org.kde.kglobalaccel` and `org.kde.keyboard` are refused. Under A a GNOME app has no privileged
global on its socket, so these bus names are what keep it from capturing, injecting input or locking the screen.

**KWin.** Its restricted socket hides only the protocol manager, so data-control stays visible and a client reads another
client's clipboard. Accepting that for KWin alone would give the same capability as `full_wayland` without asking, so KWin is
refused like any other compositor with a privileged global, and the message says what is exposed.

**Hyprland 0.53.** Refused by A without a special case (see above).

**Unmeasured compositors** (niri, river, COSMIC) are decided by their registry at run time, and a global appjail does not
know refuses the app (`wayland.ALLOWED`).

## Limits of this measurement

* Headless compositors in virtual machines with default configuration; no real session, no logged-in desktop, no extensions,
  no portal backends, no consent dialogs. A real GNOME or Plasma session may add services.
* Capture was tried with `grim`, which speaks only the wlroots and ext-image-copy-capture protocols: a compositor with its own
  (KWin's screencast, Hyprland's toplevel export) is not covered, and "no" means "not demonstrated with this tool".
* The unfocused clipboard read was tried through data-control (`wl-clipboard`), which GNOME does not offer. Focused copy and
  paste was tested on all compositors with GTK 4 windows (see above), but with an added virtual input device, in headless
  compositors; a real session adds clipboard managers and extensions that were not tried.
* One client per capability, on a quiet compositor. Xwayland, GPU, camera and audio were not part of this.
* Only the versions the two distributions package (and Hyprland from Debian backports). niri, river, COSMIC and Miriway are
  not packaged in either, so they were not measured here. Muffin was measured standalone and nested in Xvfb, not as the
  compositor of a Cinnamon session.
* Hyprland needed a particular environment to start in the VM, and its 0.53 result may be a bug fixed later.

## Reproducing

On a machine with qemu/KVM (see `CLAUDE.md`, Testing environment), for each of `debian` and `ubuntu`:

    GUEST=<distro>-compositors tests/vm/create.sh      # reuses the base image; the first creation of that image downloads it
    GUEST=<distro>-compositors tests/vm/start.sh
    GUEST=<distro>-compositors tests/vm/ssh.sh 'cloud-init status --wait'
    GUEST=<distro>-compositors tests/vm/provision.sh   # installs the compositors (several hundred packages) and reboots
    GUEST=<distro>-compositors tests/vm/sync.sh
    GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/probe.py --out /tmp/results.json'
    # option A and the focused clipboard, each with its own results file:
    GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/rule_a.py --out /tmp/rule-a.json'
    GUEST=<distro>-compositors tests/vm/ssh.sh 'cd ~/appjail && python3 tests/compositors/clipboard.py --out /tmp/clipboard.json'
