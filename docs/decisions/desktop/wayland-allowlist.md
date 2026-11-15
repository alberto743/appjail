# Unknown Wayland interfaces are refused

*Decision on [desktop access](index.md).*

**Context.** A list of privileged interfaces alone lets through a dangerous interface nobody has classified yet: on a
compositor that was not measured (niri, river, COSMIC), or in a new version of one that was.

**Decision.** appjail keeps two lists (`wayland.py`): the privileged interfaces, and the interfaces checked to act only
on the app's own windows, on input while it has focus, or on its own buffers. An interface in neither list is
*unknown* and refused like a privileged one, named in the message, unless the app has `full_wayland`. The test suite
fails when a saved registry from the measurements holds an unclassified name.

A few interfaces are **allowed after a decision**, because they reveal or take a little but do not let the app act on
other apps, and refusing them would refuse compositors that are otherwise fine:

| Interface | What it gives | Why allowed |
|---|---|---|
| `ext_idle_notifier_v1`, `org_kde_kwin_idle` | whether the user is idle | a privacy signal, not control; refusing it would refuse sway and Hyprland |
| `wp_drm_lease_device_v1` | leasing a display the desktop does not use (a VR headset) | the desktop's own screens are not leased; refusing it would refuse GNOME |
| pointer constraints, shortcut inhibition | locking the pointer, receiving the desktop's shortcuts | only while the app has focus |
| capture-source managers | naming a screen or window as a capture source | capturing still needs the privileged copy manager |
| `ext_background_effect_manager_v1` | blur behind the app's own translucent surface | acts on the app's own surfaces; refusing it would refuse GNOME, KWin and Plasma on Fedora 45 |
| `xdg_session_manager_v1` | the app's own toplevels, saved and restored through a token the compositor makes | acts on the app's own windows; the session replaced by a second client needs its unguessable token |
| `kde_output_device_registry_v2` | the list of outputs | describes outputs, as `kde_output_device_v2`, already allowed, does; it has no request that changes anything |

Two interfaces seen on Fedora 45 stay refused until they are checked: `xapp_shell_v1` (Cinnamon 6.8; a window's icon may be
an absolute path, which the shell opens outside the jail, the kind of host-side decoding that makes appearance folders
read-only) and `org_kde_plasma_activation_feedback` (Plasma 6.8; its definition was not found). `kde_lockscreen_overlay_v1`
(a surface shown over the lock screen) is privileged, with the other window and lock-screen interfaces.

**Options rejected.** A separate, weaker permission for unknown interfaces (`full_wayland` already means "more than
appjail vouches for"); measuring every compositor first (some are not packaged for the supported systems, and the allow
list protects without measuring them).

**Consequences.** A compositor update that adds a harmless interface refuses apps until it is classified; the message
names it, and users are asked to report it. Classification is by name, not version: a new version of an allowed
interface is assumed to keep its scope.

**Revisit when** a commonly used compositor's new interface is reported, or idle notification gets a permission of its
own.
