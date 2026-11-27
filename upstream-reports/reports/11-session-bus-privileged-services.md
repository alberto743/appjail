# 11. Session-bus services that run code, read the clipboard or capture the screen for any client

| | |
|---|---|
| Targets | Cinnamon (`org.Cinnamon.Eval`, `org.cinnamon.Screenshot`, `org.cinnamon.ScreenSaver`, `org.cinnamon.Muffin.DisplayConfig`); KDE Plasma (`org.kde.PlasmaShell.evaluateScript`, `org.kde.klipper getClipboardContents`); Mutter (`org.gnome.Mutter.RemoteDesktop`, `ScreenCast`, `InputCapture`) |
| Measured | Cinnamon 6.4.10, 6.4.13, 6.8.0; Plasma 6.3.6, 6.6.6, 6.8.2; Mutter and GNOME Shell 48.7, 50.1, 51.1 |
| Class | design question: services that are privileged for any client of the session bus |
| Our severity | informational (these are same-user services; it matters when a sandbox lets an app reach a bus name) |
| Suggested channel | a documentation or hardening discussion, only if you want to open it; likely "works as intended" |
| Review | pending (a candidate for not filing) |
| Filed | not filed |

## Issue text

**Title:** Document which session-bus services act with the shell's privileges for any caller

An ordinary client of the session bus, with no check of the caller, could, measured on private buses:

*  `org.Cinnamon.Eval`: run JavaScript in the shell; a command was started as the user, keys were typed into another
  client's window, and a screenshot of the whole screen was taken with `org.gnome.Shell.Screenshot` (6.4) or
  `org.cinnamon.Screenshot` (6.8) (`tests/compositors/cinnamon_dbus.py`);
*  `org.kde.PlasmaShell.evaluateScript`: run a desktop script (in a manual check one wrote a file in the user's
  configuration directory); `org.kde.klipper getClipboardContents`: read the text another client copied;
*  `org.gnome.Mutter.RemoteDesktop` and `ScreenCast` `CreateSession`: a session was created, keys were typed into
  another client's window and a whole frame was captured, with no consent dialog (GNOME Shell refuses `Shell.Eval` and
  `Screenshot`, and checks other APIs) (`tests/compositors/mutter_dbus.py`).

For software outside a sandbox these are the same user's own services, and portals depend on Mutter's behaviour. They
matter for sandboxes that give an app a bus name: the sandbox has to know which names are equivalent to "the whole
session". A short list in the documentation of each desktop (or a caller check on the services that are not meant for
apps) would help.

## Evidence and reproduction in the repository

*  `upstream-reports/reproduce.sh 11` (debian, ubuntu, fedora): the calls that answered an ordinary client.
*  End-to-end tools: `tests/compositors/mutter_dbus.py`, `cinnamon_dbus.py`; saved `mutter-dbus-*.json`,
  `cinnamon-dbus-*.json`.

## Reviewer notes (not posted)

*  Probably intended behaviour for unsandboxed same-user software; filing it as a bug would be wrong. Consider not
  filing.
*  KWin's `org.kde.touchpad` name sits on KWin's own connection, so a granted `org.kde.touchpad` reaches KWin: that is a
  sandbox concern (appjail confines it), not a KDE defect, and is not in these reports.
