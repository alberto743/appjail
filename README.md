<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/alberto743/appjail/main/assets/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/alberto743/appjail/main/assets/logo-light.svg" alt="appjail logo" width="128" height="128">
  </picture>
</p>

# appjail

[![PyPI](https://img.shields.io/pypi/v/appjail.svg)](https://pypi.org/project/appjail/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Falberto743%2Fappjail%2Fmain%2Fpyproject.toml)](https://github.com/alberto743/appjail/blob/main/pyproject.toml)
[![CI](https://github.com/alberto743/appjail/actions/workflows/ci.yml/badge.svg)](https://github.com/alberto743/appjail/actions/workflows/ci.yml)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](https://github.com/alberto743/appjail/blob/main/LICENSES/MPL-2.0.txt)
[![REUSE](https://github.com/alberto743/appjail/actions/workflows/reuse.yml/badge.svg)](https://github.com/alberto743/appjail/actions/workflows/reuse.yml)

A small command-line manager for [AppImages](https://appimage.org/) that runs every app inside a
[bubblewrap](https://github.com/containers/bubblewrap) sandbox. It works in user mode (no sudo), supports GUI apps
on Wayland (and X11-only apps through a private Xwayland), and treats the software you install as untrusted.

*appjail is young software: read the [limits](#limits) before relying on it.*

**Documentation: <https://alberto743.github.io/appjail/>**

## Why

The usual way to use an AppImage is to download it and run it with your full privileges, and most tools that manage
AppImages do the same. appjail is built around the opposite assumptions:

- **Nothing from the network is executed.** An app is a small TOML manifest: source, pinned hash, permissions. appjail
  runs no install scripts and does not update itself.
- **You name the source.** A GitHub `owner/repo`, an AppImage URL or a file; nothing the software says can change it.
- **Downloads and extraction are jailed**, each step with only the access it needs.
- **Nothing is granted by default.** An app starts with a private home and a window; sound, GPU, network, folders,
  D-Bus names and portals are permissions you grant and can read back.
- **Updates are reviewed.** A new release waits in quarantine (7 days by default), is shown as a difference, and is
  blocked if its evidence gets weaker or the repository changes owner.

Why each of these, and how it works: [Understanding appjail](https://alberto743.github.io/appjail/understand/problem/).

## Requirements

Linux on x86-64 (Debian 13 or Ubuntu 26.04 or later), Python 3.12 or later, a Wayland desktop for apps with a window.
On Debian or Ubuntu:

```sh
sudo apt install bubblewrap squashfs-tools passt xdg-dbus-proxy xwayland openbox git \
    librsvg2-bin libgtk-3-bin desktop-file-utils dbus-bin libnotify-bin
```

What each package is for: [Getting started](https://alberto743.github.io/appjail/guide/getting-started/).

## Install

```sh
pipx install appjail        # or: pip install --user appjail
```

appjail has no Python dependencies and never updates itself: upgrade with `pipx upgrade appjail` after reading what
changed.

## Quick start

```sh
appjail add skyjake/lagrange     # review the repository, pick the asset, download, pin, extract
appjail run lagrange             # run it in its jail
appjail perms lagrange --allow network   # grant more than a window
appjail list                     # installed apps and their evidence tiers
appjail update                   # check every app for a newer release
appjail remove lagrange          # delete the app and its private home
```

`appjail-gui` opens a window with the same commands (needs `python3-tk`).

| Read | For |
|---|---|
| [Guide](https://alberto743.github.io/appjail/guide/getting-started/) | installing apps, permissions, files, D-Bus and portals, updates, search, troubleshooting |
| [Reference](https://alberto743.github.io/appjail/reference/commands/) | every command, option, permission and file |
| [Understanding appjail](https://alberto743.github.io/appjail/understand/problem/) | the threat model, the principles and every mechanism, with references |
| [Decisions](https://alberto743.github.io/appjail/decisions/) | why each choice was made, and related projects |
| [Development](https://alberto743.github.io/appjail/develop/architecture/) | the code, the tests and how to contribute |

## Limits

- **Not audited.** bubblewrap and the Linux kernel do the isolation; appjail configures them conservatively but has had
  no external review.
- **The Wayland socket is only as restricted as the compositor makes it.** appjail refuses an app whose socket offers
  privileged interfaces, unless you accept that per app; on KDE Plasma that is every app for now.
- **Evidence proves "unchanged", not "safe".** A publisher who ships malware from the start passes every check;
  containment is what limits it.
- **A grant widens what a compromised app can do.** An app with `network` reaches your LAN; a granted D-Bus name of an
  unknown service reaches everything its owner serves.
- Releases are resolved on GitHub only; x86-64 only.

The complete list is on each mechanism's page; see [The problem](https://alberto743.github.io/appjail/understand/problem/).
To report a vulnerability, see [SECURITY.md](https://github.com/alberto743/appjail/blob/main/SECURITY.md).

## License

[MPL-2.0](https://github.com/alberto743/appjail/blob/main/LICENSES/MPL-2.0.txt). The repository follows the
[REUSE](https://reuse.software/) specification.
