# Troubleshooting

| Message or symptom | Cause and fix |
|---|---|
| bwrap fails with `Operation not permitted` or `setting up uid map: Permission denied` | Unprivileged user namespaces are blocked. On Ubuntu, AppArmor restricts them (`kernel.apparmor_restrict_unprivileged_userns`); relaxing that, or giving bubblewrap its own AppArmor profile, changes a protection of the whole system, so decide for yourself. See [namespaces](../understand/isolation/namespaces.md). |
| `no usable Wayland session` or `Wayland socket not found` | `run` needs a Wayland session (`WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`), which a plain ssh login does not have. A command-line app needs no window: `perms APP --display none`. |
| An X11-only app shows no window | `perms APP --display xwayland`, or on GNOME `--display xwayland-rootful` (needs `openbox`). |
| `run` refuses an app, naming privileged interfaces or interfaces "not known to it" | See [Wayland compositors](compositors.md). |
| `run` refuses an app, saying a `dbus_filter` entry "is owned by the same process as" a refused name | The granted name's process also serves a name that controls the desktop, and a grant reaches the whole process. Remove the entry: `perms APP --rm-dbus NAME`. Notifications, the secret service, media players and the tray watcher are confined and never refused this way. See [D-Bus and portals](dbus.md). |
| An app exits at once with status 0 and no window | Its launcher starts the real app in the background and exits. `perms APP --allow linger`, or the app's own wait option (`appjail run vscodium -- --wait`). |
| An app with `network` is refused, naming `passt` | Install `passt`. |
| An app with `network_host` is refused, naming Landlock | The kernel lacks Landlock ABI 6 (Linux 6.12). Use `network` instead. |
| No sound | `perms APP --allow audio`. If a warning says the private audio graph is unavailable, install the PipeWire packages listed in [Getting started](getting-started.md). |
| `no asset in TAG matches 'PATTERN'` | The publisher renamed the release's files. Pick the right one from the list shown and run `update APP --pattern 'NEW-*-PATTERN.AppImage'` ([Updates](updates.md#when-the-release-file-was-renamed)). |
| `redirect to a private network address refused` | The server of a URL app or catalog redirected the download to a machine of your local network. If you expect that (an intranet mirror), add `--allow-private-redirects` to that command ([why](../decisions/acquisition/private-redirects.md)). |
| A file or folder on a USB drive cannot be granted or opened | Your system mounts drives under `/run/media`, which is refused. See [removable media](files.md#removable-media-usb-drives-sd-cards). |
| `GitHub API rate limit reached` | 60 requests an hour without a token. Set `GITHUB_TOKEN`. |
| `unsquashfs is not installed` | Install `squashfs-tools`. |
| A DwarFS-based AppImage | `appjail tools install dwarfs`. |
| `no local index; run appjail index update first` | `search` reads downloaded catalogs only: `appjail index update`. |
| An app cannot see a file or folder | Nothing outside its private home is visible by default: `perms APP --add-dir PATH`, or `run APP --file PATH` once. See [Files and folders](files.md). |
| A grant is refused as a sensitive path | It holds credentials, is too broad, or would let the app change things outside the jail. Grant a narrower path. See [Files and folders](files.md#what-cannot-be-granted). |
| An app looks different from your other apps | See [Appearance](appearance.md). |
| `the manifest of APP was changed outside appjail` | Something other than appjail edited `~/.config/appjail/apps/APP.toml`. Check `appjail history APP` and the directory's git log. |
| `refusing to run`: the stored AppImage does not match the pinned sha256 | The file on disk was changed. Remove and add the app again from its source. |

## Reporting a problem

Before opening an issue, collect `appjail version`, your distribution and kernel, the bubblewrap version
(`bwrap --version`), your desktop and compositor with its version, and `appjail perms APP`. Remove your home path and
user name from what you paste. Security problems are reported privately: see the
[security policy](https://github.com/alberto743/appjail/blob/main/SECURITY.md).
