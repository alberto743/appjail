# Menu entries are written by appjail

*Decision on [desktop access](index.md).*

**Context.** An AppImage carries a `.desktop` file. Its `Exec`, `TryExec`, `Actions` and `MimeType` keys are run or
acted on by the desktop, outside any jail; copying it into the menu would let the app decide what runs on a click.

**Decision.** appjail generates the menu entry itself. From the app's file it keeps only display text (name, comment,
categories, keywords), cleaned and capped, and adds " (appjail)" to the name so an app cannot pose as a host app. The
command is always `appjail run NAME`, or `appjail open NAME -- %F` when file types were chosen. File types are opt-in
and advertise-only: only types the app declares and that pass a filter can be picked (no URL handlers, no executables
or scripts, no installers), and appjail never makes an app the default for anything. Opening a file binds that one
file, read-only unless the entry was created with `--rw`; choosing the file is the consent. Only entries carrying
appjail's marker are ever replaced or deleted.

**Consequences.** No URL handlers, default applications or per-type actions. An entry for an app with `display = none`
is refused, since it would start invisibly.
