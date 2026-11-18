# Getting started

## Requirements

- Linux on x86-64 with unprivileged user namespaces. Supported: Debian 13, Ubuntu 26.04 and Fedora 45, or later.
- Python 3.12 or later. appjail uses only the standard library.
- A Wayland desktop for apps with a window. The host's X11 server is never shared; X11-only apps get a private one.

Install the system packages appjail uses. On Debian or Ubuntu:

```sh
sudo apt install bubblewrap squashfs-tools passt xdg-dbus-proxy xwayland openbox git \
    librsvg2-bin libgtk-3-bin desktop-file-utils dbus-bin libnotify-bin
```

On Fedora:

```sh
sudo dnf install bubblewrap squashfs-tools passt xdg-dbus-proxy xorg-x11-server-Xwayland openbox git \
    librsvg2-tools gtk-update-icon-cache desktop-file-utils dbus-tools libnotify
```

The table gives the Debian and Ubuntu names; where Fedora's differ they follow in parentheses.

| Package | Needed for |
|---|---|
| `bubblewrap` (0.10 or later) | every jail |
| `squashfs-tools` | extracting AppImages (`unsquashfs`) |
| `passt` | the `network` permission, and a private network for the download jails; without it apps with `network` are refused and so are the downloads (`APPJAIL_ALLOW_HOST_NETWORK=1` lets one command use the host network instead) |
| `xdg-dbus-proxy` | D-Bus grants and portals |
| `xwayland` (`xorg-x11-server-Xwayland`), `openbox` | X11-only apps (`openbox` for `xwayland-rootful`) |
| `git` | the manifest history |
| `librsvg2-bin` (`librsvg2-tools`), `libgtk-3-bin` (`gtk-update-icon-cache`), `desktop-file-utils` | menu icons from SVG, icon caches, file types |
| `dbus-bin` (`dbus-tools`), `libnotify-bin` (`libnotify`) | D-Bus owner checks and the document portal; error notices from the menu |
| `pipewire`, `pipewire-bin` (`pipewire-utils`), `wireplumber`, `pipewire-pulse` (`pipewire-pulseaudio`) | sound through the private audio graph (usually already installed) |
| `python3-tk` (`python3-tkinter`, optional) | the window, `appjail-gui` |

Linux 6.12 or later with Landlock is needed for the `network_host` permission; every supported system has it.

## Install

appjail is a Python package with no dependencies:

```sh
pipx install appjail        # or: pip install --user appjail
appjail --help
```

From a clone of the repository: `pipx install .`, or without installing, `PYTHONPATH=src python3 -m appjail --help`.
appjail never updates itself: upgrade with `pipx upgrade appjail` after reading what changed.

## A first app

```sh
appjail add skyjake/lagrange
```

`add` shows the repository and its owner (account age, stars, fork or archive status) and the release file with its
evidence, and asks before downloading anything. It then downloads the file in a jail, checks it, extracts it in another
jail and records the pins. What happened at each step is explained in [Acquisition](../understand/acquisition/index.md).

```sh
appjail run lagrange        # start it in its jail
appjail perms lagrange      # what it may do: only a window, for now
appjail perms lagrange --allow network   # lagrange is a browser: give it the internet
appjail list                # installed apps and their evidence tiers
appjail update              # check every app for a newer release
appjail remove lagrange     # delete it and its private home
```

## Next

- [Installing apps](installing.md): releases, tags, files and URLs.
- [Permissions](permissions.md): giving an app more than a window.
- [Updates](updates.md): what `update` shows and why a new release waits.
