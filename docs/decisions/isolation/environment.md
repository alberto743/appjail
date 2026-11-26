# Environment variables in the manifest

*Decision on [isolation](index.md).*

**Context.** The jail's environment is cleared and rebuilt from a fixed list, so nothing of the host's reaches an app.
Some apps need a variable to start: an unofficial package of an Electron app uses X11 by default and fails under
`display = "wayland"` (no `DISPLAY`) unless a variable of its own asks for Wayland. The only way was a file in the app's
private home, which `reset` deletes and `perms` does not show.

**Options.** A file in the private home, documented; a fix in each launcher; an `[env]` table in the manifest; an
`env` permission.

**Decision.** An optional top-level `[env]` table of names and string values, edited with `perms --set-env NAME=VALUE`
and `--unset-env NAME`, shown by `perms` and `list --long`, and recorded in the manifest's history. It is not a
permission: a variable grants no capability, so changing it asks no "this grants" warning (the usual confirmation
stays). Names are `[A-Z_][A-Z0-9_]*`, at most 64 characters; values are at most 1024 characters without control
characters (an empty value is allowed); at most 32 entries. The table is added last, and refused names are rejected when
written, when the manifest is read and again when the jail is built:

- every name appjail sets itself (`PATH`, `HOME`, the display, bus, audio and portal variables, the toolkit hints), so
  `display` and the permissions stay the only way to change them;
- common names that make the dynamic loader, an interpreter, a toolkit or the graphics stack load code from a path:
  `LD_*`, `PYTHON*`, `PERL*`, `RUBY*`, `LUA_*`, `GST_PLUGIN*`, `VK_*`, the GTK, GIO, Qt, Java, Node and EGL module
  variables (the full list is in the [policy lists](../../reference/policy.md#environment-variables)). Such a variable
  would run code in the jail that is not the verified AppImage (a library preloaded from a granted folder, say).

This second list catches a mistake, such as a variable copied from a forum; it is not a boundary and cannot be
complete. Only you write the manifest, and the app could set any of these for its own processes; what it loads still
runs in the same jail, with the same grants.

`update` never changes `[env]`, as it never changes the permissions: a release cannot change how the app is started.

**Consequences.** A manifest that sets a name added to the refused lists later no longer loads, and `perms` cannot
change it either: remove the line from `~/.config/appjail/apps/NAME.toml` by hand (the error names it). The manifest is
plain text under git, so tokens and passwords do not belong in it; `perms` says so when a variable is set. A variable
that is not in the refused lists can still change an app's behaviour (a proxy, a config path); it cannot widen the jail,
which is built outside the app.

**Revisit when** an app needs a refused name for a legitimate reason, or secrets for apps need a store of their own.
