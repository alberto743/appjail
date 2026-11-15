# Environment variables in the manifest

*Decision on [isolation](index.md).*

**Context.** The jail's environment is cleared and rebuilt from a fixed list, so nothing of the host's reaches an app.
Some apps need a variable to start: an unofficial Claude Desktop package uses X11 by default and fails under
`display = "wayland"` (no `DISPLAY`) unless `CLAUDE_USE_WAYLAND=1` is set. The only way was a file in the app's private
home, which `reset` deletes and `perms` does not show.

**Options.** A file in the private home, documented; a fix in each launcher; an `[env]` table in the manifest; an
`env` permission.

**Decision.** An optional top-level `[env]` table of names and string values, edited with `perms --set-env NAME=VALUE`
and `--unset-env NAME`, shown by `perms` and `list --long`, and recorded in the manifest's history. It is not a
permission: a variable grants no capability, so changing it asks no "this grants" warning (the usual confirmation stays).
Names are `[A-Z_][A-Z0-9_]*`, at most 64 characters; values are at most 1024 characters without control characters; at
most 32 entries. The table is added last, and refused names are rejected when written, when the manifest is read and
again when the jail is built:

- every name appjail sets itself (`PATH`, `HOME`, the display, bus, audio and portal variables, the toolkit hints), so
  `display` and the permissions stay the only way to change them;
- names that make a program load code of the caller's choosing: `LD_*`, `PYTHON*`, `PERL5*`, `BASH_ENV`, `ENV`,
  `NODE_OPTIONS`. They would run code in the jail that is not the verified AppImage (a library preloaded from a granted
  folder, say), so the pinned hash would no longer describe what runs.

`update` never changes `[env]`, as it never changes the permissions: a release cannot change how the app is started.

**Consequences.** The manifest is plain text under git, so tokens and passwords do not belong in it; `perms` says so
when a variable is set. A variable that is not in the refused lists can still change an app's behaviour (a proxy, a
config path); it cannot widen the jail, which is built outside the app.

**Revisit when** an app needs a refused name for a legitimate reason, or secrets for apps need a store of their own.
