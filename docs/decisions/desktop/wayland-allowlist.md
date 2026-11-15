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
| `zwp_idle_inhibit_manager_v1` | Keeps the screen on or unlocked while the app's window is visible | Video players and presentations need it | A permission of its own for idle notification and inhibition |
| `wp_color_manager_v1` | The colour profile (ICC) of each output | A hardware fingerprint, like the make and model of `wl_output`, which every app gets | A permission of its own for the hardware description of the outputs |
| `kde_output_device_v2`, `kde_output_device_registry_v2` | The outputs with their EDID and serial numbers | The same: a hardware fingerprint, no control | The same |
| `gtk_shell1` | The window hints GTK sends (application id, startup notification, modal), and two things beyond the app's own window. **Any client can take the keyboard focus** from another app, with no token: `gtk_surface1.present(0)` (Mutter treats timestamp 0 as "now" and skips its focus-stealing check), or `gtk_shell1.notify_launch` followed by `gtk_surface1.request_focus` with the same id (the app makes the startup sequence itself). Measured on Mutter, Muffin and Cinnamon on Debian 13, Ubuntu 26.04 and Fedora 45 (`tests/compositors/focus_steal.py`): a window-only client had the focus, the other window had lost it; a client that sent nothing, or `present` with an old timestamp, did not take it. After the steal the app receives the keys the user types in what they took to be the other window. Second, `set_dbus_properties` gives GNOME Shell a bus name and object paths that it builds `org.gtk.Actions` and `org.gtk.Application` proxies to, on the host session bus (`shell-app.c`) | Every GNOME and Cinnamon 6.4 lists it and GTK clients bind it, so refusing it refuses them all. The focus is taken in the open (the window changes), the app gets nothing it did not already draw but the keys that follow, and an X11 application can do the same on a classic desktop. The proxies are calls the shell makes to a name it was given, read mostly and only to services that implement those interfaces | A filtering proxy that drops `present`, `request_focus` and `notify_launch` (the first job of the [deferred proxy](../deferred.md)), or a compositor that applies its focus-stealing check to these requests |

Other interfaces allowed after a decision, as they act only while the app has the focus or name a target without
capturing: `zwp_keyboard_shortcuts_inhibit_manager_v1`, `zwp_pointer_constraints_v1` (an app may keep the desktop's
shortcuts from reaching the compositor while it has the focus; whether a compositor keeps a way to take the shortcuts
back was not measured), and the capture-*source* managers (naming a screen or a window as a source; the copy manager,
privileged, is what captures).

Interfaces seen on Fedora 45 are privileged under "windows": `kde_lockscreen_overlay_v1` (a surface shown over the lock
screen) and `org_kde_plasma_activation_feedback` (it tells any client which app is being started, which is what refusing
the toplevel lists keeps from an app). Two more are privileged under "windows" since the reassessment of 2026-11-15,
because each makes the shell reach something the app names, and only KDE or Cinnamon 6.8 lists them (both are refused
for other reasons, so no user is refused by them today):

- `org_kde_kwin_appmenu_manager` lets the app name a D-Bus service and path that the shell then calls as a menu;
- `xapp_shell_v1` (Cinnamon 6.8) was allowed on the belief that Muffin only stores its hints. Its definition (Muffin
  6.8.1) says the icon may be "an absolute path to an icon file that the compositor and its desktop shell should use":
  the shell would open a file the app picks, and the app can write one in its own home.

**Options rejected.** A separate, weaker permission for unknown interfaces (`full_wayland` already means "more than
appjail vouches for"); measuring every compositor first (some are not packaged for the supported systems, and the
tables protect without measuring them); refusing `wp_drm_lease_device_v1` (it was proposed in the reassessment of
2026-11-15 and withdrawn: it puts every GNOME user on `full_wayland`, for a cost that is bounded and written down above).

**Consequences.** A compositor update that adds a harmless interface refuses apps until it is classified; the message
names it, and users are asked to report it. Classification is by name, not version: a new version of an allowed
interface is assumed to keep its scope. The check reads the registry once, when the app starts: a global the compositor
adds later is not seen. The protocol of every allowed interface was read, and the generated table says where.

**Revisit when** a commonly used compositor's new interface is reported, idle notification gets a permission of its own,
or a Wayland filtering proxy exists (it would turn every refusal here into enforcement: hide the global instead of
refusing the app).
