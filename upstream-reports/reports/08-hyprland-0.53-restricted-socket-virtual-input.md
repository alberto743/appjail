# 08. Hyprland 0.53.3: the security-context socket lists virtual input

| | |
|---|---|
| Target | Hyprland: `github.com/hyprwm/Hyprland` (and the distribution packages of 0.53) |
| Measured | Hyprland 0.53.3 (Ubuntu 26.04: `0.53.3+ds-4`); 0.55.2 (Debian 13 backports) hides them |
| Class | restricted socket not restricted; a client on it typed into another client's window |
| Our severity | medium for 0.53 users who rely on the security context; fixed in 0.55 as far as measured |
| Suggested channel | the Ubuntu Security Team (a private Launchpad bug on `hyprland`, or `security@ubuntu.com`); upstream supports only its latest release |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** 0.53.3: the restricted socket from `wp_security_context_v1` lists `zwlr_virtual_pointer_manager_v1`,
`zwp_virtual_keyboard_manager_v1` and `zwp_input_method_manager_v2`

On Hyprland 0.53.3 (Ubuntu 26.04) the socket that `wp_security_context_v1.create_listener` gives a sandbox lists the
virtual pointer, the virtual keyboard and the input-method manager; `wtype`, run as a client of the restricted socket,
typed into another client's window. On Hyprland 0.55.2 (Debian 13 backports) the restricted socket lists none of them,
and `wtype` fails ("Compositor does not support the virtual keyboard protocol").

Is this a known bug of 0.53 that was fixed, and in which change? Distributions that ship 0.53 (Ubuntu 26.04) would need
it, and the security-context documentation could say which release hides what.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 08 -g ubuntu` (0.53.3: the three globals, typing works) and `-g debian` (0.55.2:
  nothing left, typing fails).
* Saved results: `docs/compositor-assessment/rule-a-ubuntu-26.04.json` and `rule-a-debian-13.json` (`hyprland`).

## Reviewer notes (not posted)

* Channel and duplicates checked 2026-11-27: Hyprland's `SECURITY.md` supports only the latest release (0.57.2,
  2026-11-09) and takes security reports by mail or chat to its maintainer; users can no longer open issues (a
  Discussion instead). The fix is upstream already, so the party that can act is Ubuntu, which ships 0.53.3 in 26.04
  (`ubuntu.com/security/disclosure-policy`: a private Launchpad bug or `security@ubuntu.com`). Address the issue text
  to Ubuntu (take the fix into 0.53); the question of which upstream change fixed it can go to a Hyprland Discussion.
  No issue on 0.53's restricted socket (searched security context; #4432 and #7180 are about screencopy).
* The first survey of the Ubuntu run could not connect to the restricted socket (a timing problem of the probe, not of
  Hyprland); the later rule runs always connected.
* Fedora does not package Hyprland.
