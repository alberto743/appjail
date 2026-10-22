<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/alberto743/appjail/main/assets/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/alberto743/appjail/main/assets/logo-light.svg" alt="appjail logo" width="128" height="128">
  </picture>
</p>

# appjail

[![PyPI](https://img.shields.io/pypi/v/appjail.svg)](https://pypi.org/project/appjail/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Falberto743%2Fappjail%2Fmain%2Fpyproject.toml)](pyproject.toml)
[![CI](https://github.com/alberto743/appjail/actions/workflows/ci.yml/badge.svg)](https://github.com/alberto743/appjail/actions/workflows/ci.yml)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](LICENSES/MPL-2.0.txt)
[![REUSE](https://github.com/alberto743/appjail/actions/workflows/reuse.yml/badge.svg)](https://github.com/alberto743/appjail/actions/workflows/reuse.yml)

A small command-line manager for [AppImages](https://appimage.org/) that runs every app inside a
[bubblewrap](https://github.com/containers/bubblewrap) sandbox. It works in user mode (no sudo), supports GUI apps
under Wayland, and treats the software you install as untrusted.

*appjail is young software: read the [limits](#limits) before relying on it.*

## Why

Package managers for AppImages typically download a release and run it with your full privileges. appjail
is built around the opposite assumptions:

- **Declarative manifests, no remote code.** An app is a small TOML file: source, pinned hash, permissions. Nothing
  fetched from the network is ever executed or sourced, and appjail has no self-update.
- **You name the source.** You give a GitHub `owner/repo`. That repository is the only place the app is fetched from,
  whatever an AppImage's embedded update information says.
- **Downloads are jailed.** The download, the extraction and the verification tools run in throwaway sandboxes
  with only the access they need (a private network namespace for downloads, none for extraction).
- **Everything is denied by default.** An app starts with a private home and a restricted Wayland socket. Network,
  directories, D-Bus names, portals and the rest are explicit grants you can inspect and change.
- **Updates are reviewed.** A new release waits in quarantine (7 days by default), is shown to you as a diff, and
  is blocked outright if its evidence gets weaker or the repository changes owner.

## Requirements

- Linux on x86-64 with unprivileged user namespaces. Tested on Debian 13 and Ubuntu 26.04; older systems are
  not supported.
- Python 3.12 or newer (tested with 3.13 on Debian 13 and 3.14 on Ubuntu 26.04; 3.12 is the declared minimum and is not
  run by the tests). appjail uses only the standard library.
- `bubblewrap` and `squashfs-tools` (`unsquashfs`) are required.
- Recommended: `passt` (the `pasta` command) for apps with network access, `xdg-dbus-proxy` for D-Bus filtering,
  `xwayland` for X11-only apps, `git` for the manifest history and the search index.
- A Wayland compositor for GUI apps. Apps that need X11 run on a private Xwayland inside their own sandbox; the host
  X11 socket is never shared.

On Debian or Ubuntu:

```sh
sudo apt install bubblewrap squashfs-tools passt xdg-dbus-proxy xwayland git
```

## Install

appjail is a Python package with no dependencies. Install it as a command with [pipx](https://pipx.pypa.io/)
or pip:

```sh
pipx install appjail    # or: pip install --user appjail
appjail --help
```

Or from a clone (pip downloads only the build backend, Hatchling):

```sh
git clone <repository-url> appjail
cd appjail
pipx install .          # or: pip install --user .
appjail --help
```

To try it without installing, run it from the clone: `PYTHONPATH=src python3 -m appjail --help`.
appjail never updates itself: upgrade with `pipx upgrade appjail` (or `git pull` and reinstall) after reading what changed.

Data lives in `~/.local/share/appjail` (images, extracted trees, private homes, staging) and `~/.config/appjail`
(manifests, tracked in a small local git repository). `APPJAIL_DATA_DIR` and `APPJAIL_CONFIG_DIR` override them.

## Quick start

```sh
appjail add skyjake/lagrange     # review the repository, pick the asset, download, pin, extract
appjail run lagrange             # run it in its sandbox
appjail list                     # installed apps, tiers and permissions
appjail update                   # check every app for a newer release
appjail remove lagrange          # delete the app and its private home
```

`add` also takes `--tag TAG` (a specific release instead of the latest), `--name`, `--prerelease`, and the permission
options below at install time (`--allow`, `--dir`, `--dbus`, `--dbus-own`, `--portal`, `--display xwayland`,
`--no-audio`, `--no-gpu`). `run` takes `--dir PATH[:ro|:rw]` and `--file PATH[:rw]` for one run only, and passes
everything after `--` to the app (`appjail run lagrange -- --help`). `remove` and `perms` ask for confirmation unless
given `--yes`.

`add` shows the repository owner, account age, stars and fork or archive status before it downloads anything, and
asks if several release assets match. By default an app gets audio and GPU access and nothing else.

### Permissions

```sh
appjail perms lagrange                              # show
appjail perms lagrange --allow network              # outbound network only (see below)
appjail perms lagrange --add-dir ~/Documents:rw     # a directory, read-only unless :rw
appjail perms lagrange --add-dbus org.example.Name  # talk to one session-bus name through a filtering proxy
appjail perms lagrange --add-dbus-own org.example.Name  # own a session-bus name (MPRIS player, single instance)
appjail perms lagrange --allow portals              # desktop portals (file chooser, notifications, ...)
appjail perms lagrange --deny network --rm-dir ~/Documents   # take grants back (also --rm-dbus, --rm-dbus-own, --rm-portal)
appjail portals lagrange                           # files it was granted through the file chooser
appjail portals lagrange --revoke-all               # take those grants back (also --revoke DOC_ID)
appjail run lagrange --file ~/report.pdf            # one file, for this run only
```

**Giving one file.** `run --file PATH` (add `:rw` to allow writing) makes just that file visible, not the rest of its
directory, and appends its path inside the sandbox to the app's arguments. It applies to that run only and is never
saved in the manifest; for a standing grant use a directory, or `portals` and the file chooser. Credentials, browser
profiles and the like are refused as for directories, and shell startup files are never writable. Apps that save by
writing a temporary file and renaming it fail on `:rw`.

| Permission | Effect |
|---|---|
| `network` | Outbound internet through a private network namespace made by `pasta`. The app cannot reach services on your machine's localhost or its own addresses. Needs `passt`; without it the app is refused rather than put on the host network. |
| `network_host` | The host's own network, including localhost services. For apps that really need them. |
| `audio`, `gpu` | On by default; `--no-audio` and `--no-gpu` at `add` time, or `--deny` later. |
| `portals` | The safe set of desktop portals; privileged ones are listed per app with `--add-portal`. |
| `userns` | Nested user namespaces (Chromium and Electron sandboxes). Weakens isolation, off by default. |
| `dirs` | Directories mapped into the private home. Credentials, browser profiles, shell startup files and system trees are refused. |
| `dbus`, `dbus_own` | Session-bus names the app may talk to or own, through `xdg-dbus-proxy`. Desktop namespaces are refused. |
| `display` | `wayland` (default) or `xwayland`. |

Every sandbox also drops all capabilities, has its own PID, IPC and UTS namespaces, a read-only system, a minimal
`/dev`, a generated `/etc/passwd`, and a seccomp filter. The extracted app tree is hashed and checked at every
launch.

## How trust works

Each app is pinned by hash and carries an *evidence tier* that `update` will never silently lower:

| Tier | Evidence |
|---|---|
| 1 | A verified GitHub build attestation (Sigstore), checked with a pinned `gh` that you install on request (`appjail tools install gh`). |
| 3 | The SHA-256 digest GitHub publishes for the release asset. |
| 4 | Trust on first use: appjail shows you the hash it computed. |

Tier 2 (GPG signatures) is not implemented. Most AppImages will land on tier 3 or 4, which proves "unchanged and from the
same account", not "safe".

`appjail update` re-resolves the pinned repository, downloads the candidate in the jail, verifies it, and shows you the
version, the hashes, the tier and the release link. A release must be seen for the quarantine period before it can
be installed (`--quarantine DAYS`). For tier 4 apps appjail records the candidate's hash when it is first seen and refuses
the install if the content changed in the meantime. A change of repository owner or a drop in tier blocks the update.
`--channel stable|prerelease|pinned` chooses which releases an app follows.

## Searching

appjail can search the [AM](https://github.com/ivan-hc/AM) application list as a source of suggestions. It reads that data
as plain text only and never runs anything from it.

```sh
appjail index update      # fetch the list in a jail, review the changes, pin it
appjail index rollback    # go back to the previous snapshot
appjail index status      # show the pinned snapshot
appjail search editor     # candidates only; installing is always `appjail add owner/repo`
```

`search` shows 20 results; use `--limit N` or `--all` for more.

## Other commands

- `appjail history [app] [--limit N]`: every change to the manifests, from the local git repository. `appjail run` warns if a
  manifest was edited outside appjail.
- `appjail tools status|install NAME`: helper binaries whose URL, size and hash are pinned in appjail's source (`gh` for
  attestations, `dwarfs` for DwarFS-based AppImages).
- `appjail desktop NAME [--mime TYPE]... [--mime-all] [--rw]` (also `add --desktop`): a menu entry that starts the app through
  appjail, generated by appjail (the AppImage's own `.desktop` is never used). File types are opt-in: only the ones you pick
  show under "Open with", and appjail never makes the app a default. Opening a file passes just that file to the app, read-only
  unless `--rw` (`appjail open NAME -- FILE...`). `--remove` and `--prune` delete entries; `remove` does it too.
- `appjail version` (or `--version`): the installed version. It comes from the git tag at build time (`0.1.2` on a release, `0.1.3.dev4+g1a2b3c4` four
  commits after it); it prints `unknown` when run from a source tree that is not installed.
- Set `GITHUB_TOKEN` to raise the GitHub API rate limit. It is only ever sent to `api.github.com`.

## Limits

- **Not audited, not a security boundary you should bet on yet.** bwrap and the Linux kernel do the isolation; appjail
  configures them conservatively but has had no external review.
- Only GitHub repositories are supported. Apps hosted elsewhere appear in `search` but cannot be added.
- A sandboxed app can still do whatever its grants allow. An app with `network` can reach other machines on your LAN.
- Granting a directory, a portal or a D-Bus name widens what a compromised app can do.
- x86-64 only. The GNOME and KDE portal backends have not been tested (the GTK backend and a real X11-only AppImage
  have, under headless weston; the portal dialogs themselves are not driven). Real internet IPv6 under `pasta` is
  untested; IPv6 forwarding is tested in a fake network.
- Stopping `appjail run` with SIGINT, SIGTERM or SIGHUP stops the whole jail, including `pasta`. If appjail is killed
  with SIGKILL, an app with `network` is stopped about a second later by a watcher inside its network namespace (a
  small empty directory `appjail-life-*` stays in the runtime directory).
- The audio permission includes the microphone.

The full design, the reasoning behind each choice and the verification notes are in [DESIGN.md](DESIGN.md).

## Development

The code is stdlib-only Python under `src/appjail/`; tests are plain `pytest`. Many tests start real sandboxes and need a Linux
machine with bubblewrap, `unsquashfs`, `pasta`, a headless Wayland compositor (`weston`) and the other packages in
`tests/vm/packages.txt`.

```sh
APPJAIL_INTEGRATION=1 python3 -m pytest
```

Without `APPJAIL_INTEGRATION=1` the tests that need real sandboxes are skipped. Tests that download from the network are
opt-in (`APPJAIL_E2E=1`, `APPJAIL_LIVE=1`). The project's own workflow runs the suite inside a disposable QEMU guest built
from `tests/vm/` so that downloads and sandboxed apps never run on the developer's machine; see
[CLAUDE.md](CLAUDE.md) for the details. GitHub Actions runs the full suite and a REUSE compliance check on every push, and a separate workflow runs every
opt-in suite (real downloads) on demand and weekly.

## License

[MPL-2.0](LICENSES/MPL-2.0.txt). The repository follows the [REUSE](https://reuse.software/) specification.
