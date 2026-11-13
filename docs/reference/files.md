# Files and environment

## Where appjail keeps its files

Nothing is written outside these two trees, except the menu entries and icons you ask for.

| Path | Holds |
|---|---|
| `~/.config/appjail/apps/NAME.toml` | the manifests |
| `~/.config/appjail/.git` | the manifest history |
| `~/.local/share/appjail/apps/NAME/app.AppImage` | the pinned AppImage |
| `~/.local/share/appjail/apps/NAME/root/` | the extracted tree, with `root.sha256` and `root.tree.sha256` beside it |
| `~/.local/share/appjail/apps/NAME/home/` | the app's private home, `/home/app` in the jail |
| `~/.local/share/appjail/apps/NAME/etc/` | the generated `passwd` and `group` of the jail |
| `~/.local/share/appjail/apps/NAME/pending.json` | a candidate in quarantine (and `pending.AppImage` for URL apps) |
| `~/.local/share/appjail/tools/` | the pinned helper tools |
| `~/.local/share/appjail/index/` | the catalog sources, with the current and previous catalog of each |
| `~/.local/share/appjail/staging/` | temporary directories, removed when the step ends |
| `${XDG_DATA_HOME:-~/.local/share}/applications/appjail-NAME.desktop` | an app's menu entry |
| `${XDG_DATA_HOME:-~/.local/share}/icons/hicolor/*/apps/appjail-NAME.png` | its icon |
| `$XDG_RUNTIME_DIR/appjail-*`, `$XDG_RUNTIME_DIR/.flatpak/INSTANCE` | sockets and portal identity files of running apps, removed when they end |

## Environment variables appjail reads

| Variable | Effect |
|---|---|
| `APPJAIL_DATA_DIR` | replaces `~/.local/share/appjail` |
| `APPJAIL_CONFIG_DIR` | replaces `~/.config/appjail` |
| `GITHUB_TOKEN` | raises the GitHub API rate limit; sent only to `api.github.com` |
| `NO_COLOR` | no colour in the output (also when `TERM=dumb` or not on a terminal) |
| `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY` | where the Wayland socket and the audio sockets are |
| `DBUS_SESSION_BUS_ADDRESS` | the session bus (only `unix:path=` addresses; otherwise `$XDG_RUNTIME_DIR/bus`) |
| `XDG_DATA_HOME`, `XDG_CONFIG_HOME` | where menu entries and icons go, and where `mimeapps.list` is read |
| `LANG` | passed to the app; `TZ` too when set |

No other variable of yours reaches an app: the jail's environment is cleared and rebuilt from a fixed list.
