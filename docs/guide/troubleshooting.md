# Troubleshooting

| Message or symptom | Cause and fix |
|---|---|
| bwrap fails with `Operation not permitted` or `setting up uid map: Permission denied` | Unprivileged user namespaces are blocked. On Ubuntu, AppArmor restricts them (`kernel.apparmor_restrict_unprivileged_userns`); relaxing that, or giving bubblewrap its own AppArmor profile, changes a protection of the whole system, so decide for yourself. See [namespaces](../understand/isolation/namespaces.md). |
| `no usable Wayland session` or `Wayland socket not found` | `run` needs a Wayland session (`WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`), which a plain ssh login does not have. A command-line app needs no window: `perms APP --display none`. |
| `Missing X server or $DISPLAY` (an Electron app that defaults to X11) | `perms APP --display xwayland`, or give the app its own switch for Wayland as a variable: `perms APP --set-env NAME=VALUE` ([environment variables](permissions.md#environment-variables)). |
| An X11-only app shows no window | `perms APP --display xwayland`, or on GNOME `--display xwayland-rootful` (needs `openbox`). |
| `run` refuses an app, naming privileged interfaces or interfaces "not known to it" | See [Wayland compositors](compositors.md). |
| `run` refuses an app, saying a `dbus_filter` entry "is owned by the same process as" a refused name | The granted name's process also serves a name that controls the desktop, and a grant reaches the whole process. Remove the entry: `perms APP --rm-dbus NAME`. Notifications, the secret service, media players and the tray watcher are confined and never refused this way. See [D-Bus and portals](dbus.md). |
| An app exits at once with status 0 and no window | Its launcher starts the real app in the background and exits. `perms APP --allow linger`, or the app's own wait option (`appjail run vscodium -- --wait`). |
| A terminal program (`htop`, an editor) shows nothing or text soup, or asks a question and gets no answer | appjail cleans an app's terminal output and gives it no input unless it may have your terminal: `run APP --raw`, or `perms APP --allow raw_terminal`. See [Permissions](permissions.md#apps-that-run-in-a-terminal). |
| `resource limits (memory_max, cpu_quota, tasks_max) need systemd-run and a systemd user session`, or `the resource limits could not be applied` | The limits need a login session with a systemd user manager. Log in through one, or remove the limits: `perms APP --memory-max infinity` (and `--cpu-quota`, `--tasks-max`). See [resource limits](../understand/isolation/resource-limits.md). |
| An app with a memory limit vanishes, and `run` returns 137 | It went over `memory_max` and the whole app was stopped. Raise the limit: `perms APP --memory-max 4G`. |
| `strace` or `gdb` in the jail fails with `Operation not permitted` | Tracing is refused unless the app has `devel`: `perms APP --allow devel` ([Permissions](permissions.md#tracing-and-debugging-an-app)). |
| `accessibility needs the accessibility bus` | The session has no accessibility bus: install `at-spi2-core` (and `dbus-bin`, or `dbus-tools` on Fedora). |
| `refused link: the link is not of a scheme this app handles` | Grant the scheme: `perms APP --add-scheme SCHEME`, then `appjail desktop APP` ([opening links](menu-entry.md#opening-links)). |
| `APP is not taking links (its queue is full)` | The running app is not handling the links it was sent. Wait, or close it and open the link again. |
| `linger needs python3 in /usr/bin` or `URL schemes need python3 in /usr/bin` | Install `python3` from your distribution: the supervisor runs inside the jail with the host's interpreter. |
| An app with `network` is refused, naming `passt` | Install `passt`. |
| `add`, `update` or `index` fails saying a step needs a private network and `passt` is missing | Install `passt`. Only if you cannot, `APPJAIL_ALLOW_HOST_NETWORK=1 appjail ...` lets that command's download jail share the host network, with a warning. |
| An app with `network_host` is refused, naming Landlock | The kernel lacks Landlock ABI 6 (Linux 6.12). Use `network` instead. |
| No sound | `perms APP --allow audio`. If a warning says the private audio graph is unavailable, install the PipeWire packages listed in [Getting started](getting-started.md). |
| `no asset in TAG matches 'PATTERN'` | The publisher renamed the release's files. Pick the right one from the list shown and run `update APP --pattern 'NEW-*-PATTERN.AppImage'` ([Updates](updates.md#when-the-release-file-was-renamed)). |
| `redirect to a private network address refused` | The server of a URL app or catalog redirected the download to a machine of your local network. If you expect that (an intranet mirror), add `--allow-private-redirects` to that command ([why](../decisions/acquisition/private-redirects.md)). |
| A file or folder on a USB drive cannot be granted or opened | Grant the drive's own mount point (`/media/USER/LABEL`, or `/run/media/USER/LABEL` with your own user name), not the directory above it, and not another user's drive. See [removable media](files.md#removable-media-usb-drives-sd-cards). |
| `GitHub API rate limit reached` | 60 requests an hour without a token. Set `GITHUB_TOKEN`. |
| `unsquashfs is not installed` | Install `squashfs-tools`. |
| A DwarFS-based AppImage | `appjail tools install dwarfs`. |
| `no local index; run appjail index update first` | `search` reads downloaded catalogs only: `appjail index update`. |
| An app cannot see a file or folder | Nothing outside its private home is visible by default: `perms APP --add-dir PATH`, or `run APP --file PATH` once. See [Files and folders](files.md). |
| A grant is refused as a sensitive path | It holds credentials, is too broad, or would let the app change things outside the jail. Grant a narrower path. See [Files and folders](files.md#what-cannot-be-granted). |
| An app looks different from your other apps | See [Appearance](appearance.md). |
| `the manifest of APP was changed outside appjail` | Something other than appjail edited `~/.config/appjail/apps/APP.toml`. Check `appjail history APP` and the directory's git log. |
| `APP is running; close it, then try again` | `remove`, `reset` and an update of the app wait until it is closed. With `linger`, every process of the app counts. |
| `another appjail command is working on APP` | Another command is adding, updating, extracting or removing that app, and did not finish within a minute (a large app can take longer to extract). Run the command again when it has finished. |
| `refusing to run`: the stored AppImage does not match the pinned sha256 | The file on disk was changed. Remove and add the app again from its source. |

## Reporting a problem

Before opening an issue, collect `appjail version`, your distribution and kernel, the bubblewrap version
(`bwrap --version`), your desktop and compositor with its version, and `appjail perms APP`. Remove your home path and
user name from what you paste. Security problems are reported privately: see the
[security policy](https://github.com/alberto743/appjail/blob/main/SECURITY.md).
