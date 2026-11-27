# 03. wp_drm_lease_device_v1 sends a DRM descriptor to every client

| | |
|---|---|
| Target | Mutter (GNOME): `gitlab.gnome.org/GNOME/mutter` |
| Measured | Mutter and GNOME Shell 48.7 (Debian 13), 50.1 (Ubuntu 26.04), 51.1 (Fedora 45); Hyprland 0.55.2 on its own socket |
| Class | hardening for sandboxes (a descriptor to a GPU device sent without being asked for) |
| Our severity | low (a non-master render-node descriptor; the same node any local process can open) |
| Suggested channel | public issue |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** Advertise `wp_drm_lease_device_v1` (and send the DRM fd) only when something can be leased

On Mutter 48.7, 50.1 and 51.1 every client that binds `wp_drm_lease_device_v1` receives, with the events that follow, an
open file descriptor for the render node (`/dev/dri/renderD128`), even in a session with nothing to lease. The protocol
says the descriptor is non-master and is meant to let the client pick the right device; it is sent to every client that
binds the global, whether or not a leasable connector exists.

A sandbox (Flatpak, bubblewrap-based tools) that keeps `/dev/dri` out of an app unless it is granted GPU access gets the
node anyway: the app receives it over the Wayland socket. The graphics stack already uses the node for rendering, so the
descriptor is not a new privilege on the machine, but it makes "no GPU permission" not mean "no GPU descriptor".

Suggested fix: advertise the global only while at least one non-desktop connector can be leased, and send the descriptor
when the client creates a lease request; or hide the global from clients that connect through a sandbox's
security-context socket.

Measured with a stdlib client that binds the global and prints the descriptors that arrive
(`tests/compositors/drm_fd.py`); KWin and sway do not list the global.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 03` (debian, ubuntu, fedora). Output: the node each compositor sent.
* Protocol: `wayland-protocols` `staging/drm-lease/drm-lease-v1.xml`, event `drm_fd`.

## Reviewer notes (not posted)

* The test sessions have no leasable connector; on a machine with a VR headset the global has a use. The proposal keeps
  that.
* Not tried: what ioctls a client can do on the descriptor (render nodes are meant for unprivileged use).
* Hyprland 0.55.2 sends `card0` (non-master) on its own socket but hides the global on the restricted one: not a
  defect.
