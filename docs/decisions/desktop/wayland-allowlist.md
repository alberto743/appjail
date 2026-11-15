# Unknown Wayland interfaces are refused

*Decision on [desktop access](index.md).*

**Context.** A list of privileged interfaces alone lets through a dangerous interface nobody has classified yet: on a
compositor that was not measured (niri, river, COSMIC), or in a new version of one that was. A list that refuses
too much is no better: GNOME, the desktop most users run, lists a few globals that are not harmless to the letter, and an
app that needs `full_wayland` on every common desktop is not in a jail at all.

**Decision.** appjail keeps two tables (`wayland.py`): the privileged interfaces, by kind, and `RATIONALE`, the
interfaces allowed with the reason for each. An interface in neither is *unknown* and refused like a privileged one,
named in the message, unless the app has `full_wayland`. The test suite fails when a saved registry from the
measurements holds an unclassified name, and when an allowed name has no reason.

A global is classified by what it gives the app, never by whether refusing it would refuse a common desktop. Three
questions, in this order:

1. **Can it act on, or observe, other apps, the screen, input in general or the user's activity, beyond the app's own
   focus?** Then it is privileged and the app is refused without `full_wayland`.
2. **Does it hand over a host resource that a permission gates, or reach a service the app could not otherwise reach?**
   Then it is allowed only as an *accepted limit*: the cost is bounded, it is written down here and on
   [the Wayland page](../../understand/desktop/wayland.md), and the entry says what ends the exception.
3. **Otherwise** it acts on the app's own surfaces, buffers or settings, on input while the app has the focus, behind a
   token that another client or the compositor handed over, or it only describes the hardware. It is allowed, with the
   reason and where its protocol was read in [the generated table](../../reference/policy.md#wayland-interfaces).

The rule works in both directions: it keeps harmless globals from refusing sound compositors, and it stops a global
from being allowed because a compositor lists it.

## The accepted limits

| Interface | What it gives | Why it is allowed | What would end the exception |
|---|---|---|---|
| `wp_drm_lease_device_v1` | A DRM file descriptor, sent when the global is bound. Measured on Mutter and GNOME Shell (Debian 13, Ubuntu 26.04, Fedora 45): a render node, `/dev/dri/renderD128`, which an app without `gpu` cannot open itself. It is unprivileged (non-master: it controls no display) and is the node `gpu` binds. Leasing a display needs an output the desktop does not use (a VR headset) | A window-only app on GNOME gets the GPU driver's attack surface, not data or control of anything. Refusing it refuses all of GNOME | A filtering proxy that hides the global (see [deferred](../deferred.md)), or a compositor that does not send the descriptor |
| `ext_idle_notifier_v1` | Whether the user is idle | A privacy signal; no request acts on anything. Refusing it refuses sway and Hyprland | A permission of its own for idle notification |
| `org_kde_kwin_idle` | The same, and `simulate_user_activity`, which resets the idle timer | An idle inhibitor (`zwp_idle_inhibit_manager_v1`, allowed) already keeps the screen from blanking or locking while the app's window is visible; this does it without the window. KWin is refused for other reasons today | KWin hides the other privileged globals on restricted sockets: then reconsider this one |
| `zwp_idle_inhibit_manager_v1` | Keeps the screen on or unlocked while the app's window is visible | Video players and presentations need it | |
| `wp_color_manager_v1` | The colour profile (ICC) of each output | A hardware fingerprint, like the make and model of `wl_output`, which every app gets | |
| `kde_output_device_v2`, `kde_output_device_registry_v2` | The outputs with their EDID and serial numbers | The same: a hardware fingerprint, no control | |

Other interfaces allowed after a decision, as they act only while the app has the focus or name a target without
capturing: `zwp_keyboard_shortcuts_inhibit_manager_v1`, `zwp_pointer_constraints_v1` (an app may keep the desktop's
shortcuts from reaching the compositor while it has the focus; whether a compositor keeps a way to take the shortcuts back was not measured), and the
capture-*source* managers (naming a screen or a window as a source; the copy manager, privileged, is what captures).

`xapp_shell_v1` (Cinnamon 6.8) is allowed too: it sets an icon name or path and a progress value on the client's own window,
Muffin stores the string without opening it or answering, and an X11 client can set the same hint already. Its consumers are
not known; if one that opens the path turns up, the entry goes back. Interfaces seen on Fedora 45 are privileged under
"windows": `kde_lockscreen_overlay_v1` (a surface shown over the lock screen) and `org_kde_plasma_activation_feedback` (it
tells any client which app is being started, which is what refusing the toplevel lists keeps from an app).
`org_kde_kwin_appmenu_manager` is privileged under "windows" (2026-11-15 reassessment): it lets the app name a D-Bus service
and path that the shell then calls as a menu, which reaches a service the app cannot reach itself. Only KDE lists it, and
KWin is refused for other reasons, so no user is refused by it today.

**Options rejected.** A separate, weaker permission for unknown interfaces (`full_wayland` already means "more than
appjail vouches for"); measuring every compositor first (some are not packaged for the supported systems, and the
tables protect without measuring them); refusing `wp_drm_lease_device_v1` (it was proposed in the reassessment of
2026-11-15 and withdrawn: it puts every GNOME user on `full_wayland`, for a cost that is bounded and written down above).

**Consequences.** A compositor update that adds a harmless interface refuses apps until it is classified; the message
names it, and users are asked to report it. Classification is by name, not version: a new version of an allowed
interface is assumed to keep its scope. The check reads the registry once, when the app starts: a global the compositor
adds later is not seen. The rationale table marks which protocols were read; `unread` entries are known only from the
compositors that list them.

**Revisit when** a commonly used compositor's new interface is reported, idle notification gets a permission of its own,
or a Wayland filtering proxy exists (it would turn every refusal here into enforcement: hide the global instead of
refusing the app).
