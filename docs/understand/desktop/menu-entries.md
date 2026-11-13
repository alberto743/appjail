# Menu entries and opening files

*Part of [Desktop access](index.md). Previous: [network](network.md).*

## What it is

Desktops build their application menu from **desktop entries**, `.desktop` files in `~/.local/share/applications` and
the system directories. An entry names the app, its icon, its categories, the command to run (`Exec`), additional
actions, and the file types (`MimeType`) it can open, which makes it appear under "Open with" in file managers. Icons
come from **icon themes**, image files the desktop shell and file manager load themselves.

An AppImage usually carries its own desktop entry and icon.

## Why it matters

A desktop entry is executed by the desktop, outside any jail: its `Exec`, `TryExec` and actions are commands, and its
file types decide what it is offered to open. Copying the AppImage's own entry into your menu would let the app choose
what runs when you click it. Its icon is decoded by the desktop's image loaders, also outside any jail, and crafted
images are a known way to attack such loaders. An app registered as the default for a type would receive files you never
meant to give it.

## How appjail uses it

- **Generated, never copied.** `appjail desktop NAME` (or `add --desktop`) writes the entry itself. From the AppImage's
  file it takes only display text (name, comment, generic name, categories, keywords), cleaned and capped, and adds
  " (appjail)" to the name so an app cannot pose as a host app. The command is always `appjail run NAME`. Only files
  carrying appjail's marker are ever replaced or deleted.
- **File types are opt-in.** Nothing is registered unless you pick types the app declares, and only types that pass a
  filter can be picked: no URL handlers, executables, scripts or installers, at most 32. appjail never makes an app the
  default for anything; with types, the entry runs `appjail open NAME -- FILE...`.
- **Opening binds one file.** `appjail open` grants each file alone for that run, read-only unless the entry was created
  with `--rw`, with the same path checks as any grant. Choosing the file in the file manager is the consent, as in the
  portal's file chooser.
- **Icons are rewritten.** A PNG icon is rebuilt by appjail's own code without decoding a pixel: its structure checked,
  its data inflated to exactly the size its header states, and only the essential chunks written. An SVG icon is first
  rendered to PNG by `rsvg-convert` in a jail without network, then rebuilt the same way.

## Connections

- Opening a file uses the same grant code as `run --file`: [the filesystem view](../isolation/filesystem.md).
- Text from the AppImage goes through the same cleaner as everything else: [untrusted text](../acquisition/untrusted-text.md).
- Decisions: [Menu entries are written by appjail](../../decisions/desktop/menu-entries.md),
  [Icons rewritten, not decoded](../../decisions/desktop/icons.md).

## Limits

- No URL handlers, default applications or per-type actions.
- A loader bug triggered by the pixel values of a well-formed image is not removed by the rewrite.
- An app with `display = none` gets no entry, since it would start invisibly.

## References

- freedesktop.org, [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/),
  [Icon Theme Specification](https://specifications.freedesktop.org/icon-theme-spec/latest/),
  [Shared MIME-info Database](https://specifications.freedesktop.org/shared-mime-info-spec/latest/).
- W3C, [Portable Network Graphics (PNG) Specification](https://www.w3.org/TR/png-3/).
