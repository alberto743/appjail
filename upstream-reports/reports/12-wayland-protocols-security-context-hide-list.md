# 12. wayland-protocols: say what a security-context socket must hide

| | |
|---|---|
| Target | `gitlab.freedesktop.org/wayland/wayland-protocols` (`staging/security-context`) |
| Measured | 12 compositors on Debian 13, Ubuntu 26.04, Fedora 45 |
| Class | clarification / proposal for the protocol text |
| Our severity | n/a |
| Suggested channel | a public issue or a merge request with the proposed text |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** security-context-v1: state what a compositor must not offer on a restricted socket

`security-context-v1` says that the compositor "may" restrict the client's access to privileged protocols. Compositors
that offer it differ widely in practice. On the restricted socket the manager gives, measured on Debian 13, Ubuntu 26.04
and Fedora 45:

| Compositor | What is left on the restricted socket |
|---|---|
| sway 1.10 to 1.12, labwc 0.8 to 0.20, Hyprland 0.55 | no privileged global |
| KWin 6.3, 6.6 | everything but the manager (data-control, layer shell, Plasma shell, output management) |
| KWin 6.8 | the layer shell, the Plasma shell, output management, screen power and brightness |
| Hyprland 0.53 | virtual pointer, virtual keyboard, input-method manager |

A sandbox engine therefore has to read the registry of the socket and judge each global itself. Two requests:

1. State in the protocol which kinds of globals a restricted socket must not offer: screen capture, virtual input,
   input methods, data-control, foreign-toplevel and window management, layer shell, session lock, output management,
   and, with them, how a compositor can tell (a flag in the XML, or a registry file).
2. Say whether a client of a restricted socket may be sent a file descriptor for a DRM device (see report 03:
   `wp_drm_lease_device_v1`).

I can write the merge request if the direction is welcome.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 12` (debian, ubuntu, fedora): runs the rule on every compositor and prints which hide
  everything and which leave some.
* The per-compositor tables: `docs/compositor-assessment/ASSESSMENT.md`.

## Reviewer notes (not posted)

* This depends on reports 04 and 08 being understood first; it can be filed with or after them.
