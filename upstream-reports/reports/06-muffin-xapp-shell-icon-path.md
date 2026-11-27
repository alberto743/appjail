# 06. xapp_shell_v1: the icon may be an absolute path the shell opens

| | |
|---|---|
| Target | Muffin: `github.com/linuxmint/muffin` (and the consumers in Cinnamon) |
| Measured | Muffin 6.8.1 (source, Fedora 45); the global is listed by Cinnamon 6.8.0 |
| Class | hardening (the shell may open a file the client names) |
| Our severity | low |
| Suggested channel | public issue |
| Review | pending |
| Filed | not filed |

## Issue text

**Title:** `xapp_shell_v1.set_icon_name`: accept theme names, or say what is done with an absolute path

`protocol/xapp-shell.xml` says of `set_icon_name`: "Set a themed icon name, or an absolute path to an icon file, that
the compositor and its desktop shell should use for this window in titlebars, task lists and window switchers." The
compositor stores the string (`meta_window_set_icon_name`) and the shell loads it. A sandboxed client can write a file
in its own data directory (outside the sandbox that is a real path on the host) and name it, which makes the shell
decode a file the client wrote; a client in a sandbox that cannot reach `/home` still chooses which path the shell
opens.

The X11 hint `_NET_WM_XAPP_ICON_NAME` has the same property, so this is not new, but the Wayland protocol is new.

Suggested change: accept only theme names on Wayland, or load an absolute path only from places the shell trusts, and
say in the protocol text which it is.

## Evidence and reproduction in the repository

* `upstream-reports/reproduce.sh 06` (fedora): downloads the Muffin 6.8.1 source RPM in the guest, extracts
  `xapp-shell.xml` as text, prints the request text, and checks the sentence about the absolute path. Source only; the
  shell's side was not read to the end.

## Reviewer notes (not posted)

* What the shell does with the path (which loader, which size limits) was not read or tried: do not claim a
  vulnerability.
* In appjail the interface is refused to apps without `full_wayland` for this reason (privileged, "windows").
