# Permission reference

Every permission an app can have. The manifest key is in the `[permissions]` table of
`~/.config/appjail/apps/NAME.toml`; a key that is missing means denied. "Warns" means `add` and `perms` print a warning
when the permission is given. For how to use them, see the [guide](../guide/permissions.md).

## Switches

Granted with `--allow NAME` (at `add` or with `perms`) and taken back with `--deny NAME`.

| Key | Default | Gives the app | Needs | Warns |
|---|---|---|---|---|
| `network` | off | outbound internet through a private network namespace made by `pasta`; not your machine's loopback services or its own addresses; other hosts of the LAN are reachable | `passt`; refused without it | yes |
| `network_host` | off | your own network namespace: loopback services included. `--allow network_host` implies `network`; `--deny network` clears it | `network`; Landlock ABI 6 (Linux 6.12); refused without it | yes |
| `audio` | off | sound playback, as `audio_mode` says; `--deny audio` also takes `mic` | the private-graph tools for `pipewire` mode, else see `audio_mode` | in `pulse` mode |
| `mic` | off | the microphone; `--allow mic` implies `audio` | `audio` | yes |
| `gpu` | off | `/dev/dri` (card and render nodes), `/dev/nvidia*`, read-only `/sys/dev/char` and `/sys/devices`, the Vulkan and GLVND data | | no |
| `camera` | off | every V4L2 video-capture node present at start, and for each its own `/sys` entry | | yes |
| `portals` | off | the safe set of desktop portals through the filtering D-Bus proxy, and the document portal | `xdg-dbus-proxy`, xdg-desktop-portal | yes |
| `userns` | off | nested user namespaces and the mount API inside the jail ([namespaces](../understand/isolation/namespaces.md#nested-user-namespaces)) | | yes |
| `linger` | off | nothing; the jail lasts until every process in it has exited ([process lifetime](../understand/isolation/lifetime.md)) | | no |
| `full_wayland` | off | running although the app's Wayland socket lists privileged interfaces, or interfaces appjail does not know | | yes |

## Values

| Key | Values | Default | Set with |
|---|---|---|---|
| `display` | `wayland`, `xwayland`, `xwayland-rootful`, `none` | `wayland` | `--display` |
| `display_size` | `WxH`, each side 320 to 8192 (for `xwayland-rootful`) | `1280x800` | `--display-size` |
| `audio_mode` | `pipewire` (a private audio graph per app), `pulse` (the host's Pulse socket, which always includes capture) | `pipewire` | `--audio-mode` |

## Lists

| Key | Entries | Add / remove | Install option |
|---|---|---|---|
| `dirs` | absolute or `~/` paths, `:ro` (default) or `:rw` | `--add-dir`, `--rm-dir` | `--dir` |
| `dbus_filter` | session-bus names the app may talk to; a trailing `.*` covers the names below | `--add-dbus`, `--rm-dbus` | `--dbus` |
| `dbus_own` | session-bus names the app may own | `--add-dbus-own`, `--rm-dbus-own` | `--dbus-own` |
| `portal_interfaces` | opt-in portal interfaces, with `portals` | `--add-portal`, `--rm-portal` | `--portal` |

Directory entries are checked against the [paths that can never be granted](../guide/files.md#what-cannot-be-granted)
when they are given and again, on the folder really opened, at every start.

## For one run

| Option of `run` | Effect |
|---|---|
| `--dir PATH[:ro\|:rw]` | a folder for this run only |
| `--file PATH[:ro\|:rw]` | one regular file for this run only; its path in the jail is added to the app's arguments |

## Always, whatever the manifest says

Every app jail has its own mount, PID, user, UTS, IPC and cgroup namespaces, no capabilities, a cleared environment, a
read-only system, a private home, empty `/tmp` and `/run`, the seccomp filter, and where the kernel supports it a
Landlock scope against abstract sockets created outside the jail
([Isolation](../understand/isolation/index.md)).

## Example

```toml
[permissions]
network = true
audio = true
gpu = false
portals = false
userns = false
mic = true
display = "xwayland"
dirs = ["~/Documents/notes", "~/Pictures:rw"]
dbus_filter = ["org.freedesktop.Notifications"]
```
