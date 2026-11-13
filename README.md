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

*How appjail compares with similar tools: see [Alternatives and related projects](#alternatives-and-related-projects).*

## Why

Package managers for AppImages typically download a release and run it with your full privileges. appjail
is built around the opposite assumptions:

- **Declarative manifests, no remote code.** An app is a small TOML file: source, pinned hash, permissions. Nothing
  fetched from the network is ever executed or sourced, and appjail has no self-update.
- **You name the source.** You give a GitHub `owner/repo`, or an AppImage file or URL. That is the only place the
  app is fetched from, whatever an AppImage's embedded update information says.
- **Downloads are jailed.** The download, the extraction and the verification tools run in throwaway sandboxes
  with only the access they need (a private network namespace for downloads, none for extraction).
- **Everything is denied by default.** An app starts with a private home and a restricted Wayland socket, nothing else.
  Audio, GPU, network, directories, D-Bus names, portals and the rest are explicit grants you can inspect and change.
- **Updates are reviewed.** A new release waits in quarantine (7 days by default), is shown to you as a diff, and
  is blocked outright if its evidence gets weaker or the repository changes owner.

## Requirements

- Linux on x86-64 with unprivileged user namespaces. Tested on Debian 13 and Ubuntu 26.04; older systems are
  not supported.
- Python 3.12 or newer (tested with 3.13 on Debian 13 and 3.14 on Ubuntu 26.04; 3.12 is the declared minimum and is
  not run by the tests). appjail uses only the standard library.
- Required: `bubblewrap` (0.10 or later) and `squashfs-tools` (`unsquashfs`). The downloads run the system's
  `/usr/bin/python3` inside their jail (whatever Python appjail itself was installed with), with the CA certificates of
  `/etc/ssl` (`ca-certificates`).
- Needed for specific features:
  - `passt` (the `pasta` command): apps with the `network` permission, which are refused without it. Also gives
    the download jails a private network namespace; without it they use the host network and print a warning.
  - `xdg-dbus-proxy`: D-Bus filtering and portals.
  - `xwayland`: X11-only apps, through a private rootless Xwayland. Compositors that manage the X windows themselves (sway, KDE) show them; GNOME's mutter does not.
  - `openbox`, together with `xwayland`: the `xwayland-rootful` display mode, which shows X11-only apps in one window that holds the whole X screen, with `openbox` as the window manager inside the jail; for GNOME. `--display-size WxH` sets the window size (default 1280x800).
  - `git`: the manifest history.
  - `dbus-bin` (`dbus-send`): starting the document portal and revoking its grants. `libnotify-bin` (`notify-send`): the error notice when a file opened from the menu fails.
  - `librsvg2-bin` (`rsvg-convert`): the menu icon of an app that ships only an SVG; without it the entry has no icon
    (`appjail desktop APP --show` says so). `libgtk-3-bin` (`gtk-update-icon-cache`) makes new icons appear in the
    menu at once; `desktop-file-utils` registers the file types.
  - Linux 6.12 or later with Landlock (both supported systems have it): apps with `network_host`, which are
    refused without it.
  - For `audio` in the default `pipewire` mode: `pipewire`, `wireplumber`, `pipewire-pulse` and `pw-dump` under `/usr`
    (Debian and Ubuntu: `pipewire`, `pipewire-bin`, `wireplumber`, `pipewire-pulse`), PipeWire's pulse-tunnel module, and
    the host's Pulse server (`pipewire-pulse` on PipeWire systems, or PulseAudio) to tunnel to. Without them (or if the graph
    does not come up) an app with `mic` gets the host's Pulse socket and one without gets no audio; with
    `audio_mode = pulse` the app gets the host's Pulse socket. When the host's Pulse server is PulseAudio itself, that socket
    is never given (an app can make PulseAudio load its own code), so there is no audio in those two cases. The host's PipeWire socket is never bound.
- Optional: `python3-tk` for the window (`appjail-gui`, see [Graphical interface](#graphical-interface)).
- A Wayland compositor for GUI apps. The host X11 socket is never shared.

On Debian or Ubuntu:

```sh
sudo apt install bubblewrap squashfs-tools passt xdg-dbus-proxy xwayland openbox git librsvg2-bin libgtk-3-bin desktop-file-utils dbus-bin libnotify-bin
```

## Install

appjail is a Python package with no dependencies. Install it as a command with [pipx](https://pipx.pypa.io/)
or pip:

```sh
pipx install appjail    # or: pip install --user appjail
appjail --help
```

Or from a clone (pip downloads only the build backend, Hatchling and hatch-vcs):

```sh
git clone https://github.com/alberto743/appjail.git
cd appjail
pipx install .          # or: pip install --user .
```

To try it without installing, run it from the clone: `PYTHONPATH=src python3 -m appjail --help`. appjail never
updates itself: upgrade with `pipx upgrade appjail` (or `git pull` and reinstall) after reading what changed.
`appjail version` (or `--version`) prints the installed version, which comes from the git tag at build time (for example `1.2.3`
on a release, `1.2.4.dev4+g1a2b3c4` four commits after it) and is `unknown` when run from a source tree that is not
installed.

Data lives in `~/.local/share/appjail` (images, extracted trees, private homes, staging) and `~/.config/appjail`
(manifests, tracked in a small local git repository). `APPJAIL_DATA_DIR` and `APPJAIL_CONFIG_DIR` override them.

## Quick start

```sh
appjail add skyjake/lagrange     # review the repository, pick the asset, download, pin, extract
appjail run lagrange             # run it in its sandbox
appjail list                     # installed apps and tiers (-l: what each is granted, --json: for scripts)
appjail update                   # check every app for a newer release
appjail remove lagrange          # delete the app and its private home
```

Commands that change or delete something ask first (except `desktop --remove`/`--prune`, which only delete appjail's own
menu entries, and `index rollback`, which can be rolled back again); `remove`, `perms`, `portals` and `desktop` accept `--yes`.
`appjail COMMAND --help` lists every option.
`GITHUB_TOKEN`, if set, raises the GitHub API rate limit; it is only ever sent to `api.github.com`.

## Graphical interface

`appjail-gui` opens a window with the same commands and options: the installed apps (run, run with extra access
for one run, open a file, update, permissions, portals, history, menu entry, remove), adding an app, searching the
catalogs and the helper tools. It runs the CLI underneath, so it shows the same reviews and asks the same questions
in dialogs, with the same default answer: No, except when writing a menu entry you asked for. It needs the system package `python3-tk` (`sudo apt install python3-tk`)
and a display.

`appjail-gui --desktop` adds appjail to your application menu, with its icon; `appjail-gui --remove-desktop` takes it
out again. Only a menu entry created that way is ever replaced or deleted.

## Installing apps

**From a GitHub release.** `appjail add owner/repo` shows the repository owner, account age, stars and fork or archive
status before it downloads anything, and asks if several release assets match. By default an app gets a window
(a restricted Wayland socket) and nothing else: pass `--allow audio`, `--allow mic`, `--allow gpu` or `--allow camera` for those, and `--display none`
for an app that needs no window.

| Option | Effect |
|---|---|
| `--tag TAG` | A specific release instead of the latest; the app is then *pinned* and `update` leaves it alone. |
| `--prerelease` | Follow pre-releases. |
| `--name NAME` | The app's name (default: from the project). |
| `--allow`, `--dir`, `--dbus`, `--dbus-own`, `--portal`, `--display`, `--display-size`, `--audio-mode` | Permissions at install time (see [Permissions](#permissions)); the review warns about each risky one. |
| `--desktop [--mime TYPE] [--mime-all] [--rw]` | Also create a menu entry (see [Menu entry](#menu-entry-and-opening-files)). |

`run` passes everything after `--` to the app (`appjail run lagrange -- --help`).

**From a file or URL.** For apps that are not GitHub releases, give the AppImage itself:

```sh
appjail add --file ~/Downloads/Tool-x86_64.AppImage [--name tool] [--sha256 HEX]
appjail add --url https://example.org/dl/Tool-x86_64.AppImage [--name tool] [--sha256 HEX] [--max-size MIB]
appjail update tool --file ~/Downloads/Tool-new.AppImage       # an app added from a file
```

Nothing identifies who published such a file, so these apps are tier 5 (trust on first use), or tier 4 when you pass
the hash the publisher gives with `--sha256` (a mismatch aborts). A URL must be https and is downloaded in the jail
(1 GiB at most unless `--max-size`); redirects may go to any host, and a redirect through plain http asks for an extra
confirmation unless `--sha256` matches. `update` of a URL app asks the server first with a conditional request and a
few small range requests, and downloads the whole file only when something changed.

## Permissions

Everything is denied unless granted. Show or change an app's permissions with `perms`:

```sh
appjail perms lagrange                                   # show
appjail perms lagrange --allow network                   # outbound network only (see the table)
appjail perms lagrange --add-dir ~/Documents:rw          # a directory, read-only unless :rw
appjail perms lagrange --add-dbus org.example.Name       # talk to one session-bus name through a filtering proxy
appjail perms lagrange --add-dbus-own org.example.Name   # own a session-bus name (MPRIS player, single instance)
appjail perms lagrange --allow portals                   # desktop portals (file chooser, notifications, ...)
appjail perms lagrange --deny network --rm-dir ~/Documents   # take grants back (also --rm-dbus, --rm-dbus-own, --rm-portal)
appjail portals lagrange                                 # files it was granted through the file chooser
appjail portals lagrange --revoke-all                    # take those grants back (also --revoke DOC_ID)
```

| Permission | Effect |
|---|---|
| `network` | Outbound internet through a private network namespace made by `pasta`. The app cannot reach services on your machine's localhost or its own addresses. Needs `passt`; without it the app is refused rather than put on the host network. |
| `network_host` | The host's own network, including localhost services (`--allow network_host`, which implies `network`). For apps that really need them. Landlock (Linux 6.12 or later) keeps the app off the host's abstract unix sockets, such as the X server's; without it the permission is refused. |
| `audio` | Sound playback (`--allow audio`; `--deny` later). In the default `pipewire` mode the app gets a private audio graph that holds only a speaker tunnelled to your default output: it sees none of your devices, no camera and no other app's stream, and cannot record. In `pulse` mode it gets the host's Pulse socket, which also lets it record the microphone and the sound other apps play, and load modules into your audio server (rewire your audio, open a listener, create FIFOs in your name). Off by default. |
| `mic` | The microphone (`--allow mic`, which implies `audio`; `--deny mic` keeps playback): adds a microphone tunnelled to your default input to the private graph. In `pulse` mode, or when the private graph cannot start, it cannot be denied: the app gets the Pulse socket, which always includes capture, and appjail warns (an app without `mic` gets no audio then, see `audio_mode`). |
| `audio_mode` | `pipewire` (default) or `pulse` (`--audio-mode`; shown in the review once `audio` is granted). `pipewire` is the private graph described above and needs the tools listed under Requirements; if one is missing, or the graph does not come up, a warning says why and an app with `mic` falls back to the Pulse socket, while one without `mic` gets no audio (the Pulse socket would let it record). `pulse` is the host's Pulse socket, which follows the desktop's own device handling; it is refused (no audio, with a message) when that server is PulseAudio itself, since an app can make PulseAudio load its own code. The private graph has [limits](#limits) with changing devices. |
| `gpu` | `/dev/dri` (card and render nodes), `/dev/nvidia*` and read-only `/sys/devices` (`--allow gpu`). Needed for hardware-accelerated apps (Electron, Qt Quick, games); without it most apps fall back to slower software rendering. Off by default. |
| `camera` | The camera's V4L2 capture devices and their own `/sys` entries (`--allow camera`). Every capture device is visible to the app, and a camera plugged in after the app starts is not. Off by default. Apps that use PipeWire for the camera (browsers) need `--portal Camera` instead, with `portals`. |
| `portals` | The safe set of desktop portals; privileged ones are listed per app with `--add-portal`. |
| `userns` | Nested user namespaces (Chromium and Electron sandboxes). Weakens isolation, off by default. |
| `linger` | Keep the jail until every process in it has exited, not only the one that was started. For apps whose launcher starts the real app detached and exits (VSCodium). Grants nothing; off by default. |
| `full_wayland` | Let the app run although its Wayland socket lists privileged or unknown interfaces (`--allow full_wayland`). `run` reads the registry of the socket the app would get (the restricted one where the compositor makes it, else the compositor's own) and refuses a windowed app when it lists screen capture, input injection, data-control (reading the clipboard without focus), control of other windows or of the desktop, or an interface appjail does not know, naming them; see [Wayland compositors](#wayland-compositors). With the permission the app runs and `run` warns. A socket that lists none (GNOME's, sway's restricted one) never needs it. Off by default; an app with `display = none` never needs it. |
| `dirs` | Directories mapped into the private home (`--dir` / `--add-dir`). Credentials and the directories that contain them, key and password-database files, browser profiles, the whole home, the broad `~/.config`, `~/.local` and `~/.cache`, system trees, `/tmp` and `/var/tmp` (other programs' sockets live there) are refused, and so is write access to shell startup files and wherever else code would run outside the jail later (`~/.local/bin`, `~/.local/lib`, autostart, icon themes, thumbnailers, file-manager scripts, ...). |
| `dbus_filter`, `dbus_own` | Session-bus names the app may talk to (`--dbus`) or own (`--dbus-own`), through `xdg-dbus-proxy`. Names that control the desktop (the shell, the session, settings, screen capture, the bus itself) cannot be talked to, and no name in a desktop namespace (`org.freedesktop.`, `org.gnome.`, `org.kde.`, ...) can be owned. |
| `display` | `wayland` (default), `xwayland` or `xwayland-rootful` (`display_size`, default `1280x800`, sets its window), or `none`: no Wayland socket and no display variables, for command-line apps (no menu entry either). |

**Temporary grants.** `run APP --dir PATH[:ro|:rw]` and `run APP --file PATH[:ro|:rw]` grant access for that run only and
are never saved. `--file` makes just that one file visible, not the rest of its directory, and appends its path inside
the sandbox to the app's arguments. Credentials, browser profiles and the like are refused as for directories, and
shell startup files are never writable. Apps that save by writing a temporary file and renaming it fail on `:rw`. A file whose own name ends in
`:rw` or `:ro` needs its mode spelled out (`x:rw:ro`), and a directory with `:` in its name cannot be granted. For
a standing grant use a directory, or the portal file chooser.

Every sandbox also drops all capabilities, has its own PID, IPC and UTS namespaces, a read-only system, a minimal
`/dev`, a generated `/etc/passwd` and a seccomp filter. An app's sandbox outside `pasta`'s private network is also kept
off abstract unix sockets created outside it by Landlock, where the kernel has it. The extracted app tree is hashed and checked at every launch.

## Menu entry and opening files

`appjail desktop NAME [--mime TYPE]... [--mime-all] [--rw]` (also `add --desktop [--rw]`) creates a menu entry that starts the
app through appjail. appjail generates it itself; the AppImage's own `.desktop` is never used. File types are opt-in:
only the ones you pick show under "Open with", and appjail never makes the app a default. Opening a file passes just
that file to the app, read-only unless `--rw` (`appjail open NAME -- FILE...`). `desktop --remove` and `--prune` delete
entries; `remove` does it too. `desktop NAME --show` lists the registered file types, the ones the app offers and the ones
appjail refuses, and writes nothing (the Apps tab of the GUI has a "File types" button and a type list in "Menu entry…").

## Trust and updates

### Evidence tiers

Each app is pinned by hash and carries an *evidence tier* that `update` will never silently lower:

| Tier | Evidence |
|---|---|
| 1 | A verified GitHub build attestation (Sigstore), checked with a pinned `gh` that you install on request (`appjail tools install gh`). |
| 3 | The SHA-256 digest GitHub publishes for the release asset. |
| 4 | A GitHub asset without a digest: trust on first use, anchored by the pinned owner account. For `--file`/`--url`: the hash you gave with `--sha256` matched. |
| 5 | `--file`/`--url` without a hash from outside: trust on first use of the bytes alone. |

Tier 2 (GPG signatures) is not implemented. Most AppImages will land on tier 3 to 5, which proves "unchanged" (and, for
GitHub, "from the same account"), not "safe". `update APP --sha256 HEX` earns tier 4 for a tier 5 app when the hash
matches, and a tier 4 URL or file app refuses new content that comes without one.

### Updating

`appjail update [APP]` re-resolves the pinned repository, downloads the candidate in the jail, verifies it, and shows you
the version, the hashes, the tier and the release link. A release must be seen for the quarantine period before it can
be installed (`--quarantine DAYS`). For tier 4 apps appjail records the candidate's hash when it is first seen and refuses
the install if the content changed in the meantime. A change of repository owner or a drop in tier blocks the update.
`update APP --channel stable|prerelease|pinned` chooses which releases a GitHub app follows; a file or URL app has no
releases, so it is refused there.

What `update` prints per app:

- *up to date*;
- *waiting*: a candidate was seen and its quarantine has not ended; run `update` again later, no action needed;
- *blocked*: the owner changed, the evidence got weaker, or the content changed during the quarantine; nothing was
  installed and the message says why;
- *declined*: you answered no;
- *pinned*: the app follows no releases.

With several apps a closing table repeats each result (`current`, `updated`, `waiting`, `blocked`, `declined`, `pinned`,
`failed`, or `not checked` after a rate limit). `--prerelease` takes pre-releases into account for this one run. The exit
status is 1 if any app was blocked, failed or not checked. A URL app's candidate is kept on disk during the quarantine and
installed from there (`--verify` downloads it again first); a file app has no quarantine, you hold the bytes.

Every change to the manifests is committed to a local git repository (`appjail history [APP] [--limit N]` lists them), and
`appjail run` warns if a manifest was edited outside appjail.

## Searching

`search` looks through **catalogs**: lists of apps with, where known, the project each one comes from. A hit
is only a suggestion; installing is always `appjail add owner/repo` (or `--url`), after you have checked
the owner. Catalogs are untrusted data: appjail parses them strictly, strips terminal escape sequences from every
text, and never runs anything from them.

```sh
appjail index update                  # refresh every catalog: fetch, show what changed, ask before accepting
appjail index status                  # the sources, their revisions and update times
appjail index rollback [NAME]         # back to the previous catalog of a source (default: appjail-db)
appjail index add mine --url https://example.org/apps.json    # another catalog (https; fetched in the jail)
appjail index add local --file ~/apps.json                    # or a local file
appjail index update mine             # refresh one source (--commit SHA is for appjail-db only)
appjail index remove mine
appjail search editor                 # all sources; with several, each hit shows its source in brackets
```

`search` needs a catalog: run `appjail index update` once first. It shows 20 results; use `--limit N` or `--all` for
more. `search --json` and `index status --json` print one JSON document for scripts.

**Sources.** The built-in `appjail-db` source is the catalog of the sister project
[appjail-db](https://github.com/alberto743/appjail-db), rebuilt weekly from the [AM](https://github.com/ivan-hc/AM)
application list and the [AppImageHub](https://appimage.github.io) feed. `index update` asks the GitHub API for the latest commit of that repository, downloads its
`catalog.json` at that commit in a network-only jail and records the commit, so a catalog can be traced to an exact
state of appjail-db; `index update appjail-db --commit SHA` fetches a chosen commit instead. The catalog is not signed:
what protects you is HTTPS, the strict parser and the review below. Sources you add yourself provide a catalog directly. Every update shows the number of apps, the apps added and
removed, and every app whose repository changed, with a loud warning when the owner changed, and asks before it
replaces the catalog. One previous catalog is kept per source for `index rollback`; sources are stored in
`~/.local/share/appjail/index/`.

**Catalog format.** One UTF-8 JSON document, at most 16 MiB and 50,000 apps:

```json
{
  "format": "appjail-catalog",
  "version": 1,
  "origin": "https://example.org/my-apps",
  "revision": "2026-10-22",
  "apps": [
    {"name": "lagrange", "description": "A Gemini browser", "source": "github:skyjake/lagrange"},
    {"name": "tool-a", "source": "codeberg:user/tool-a"},
    {"name": "tool-b", "source": "gitlab:gitlab.example.org/group/sub/tool-b"},
    {"name": "tool-c", "source": "forgejo:git.example.net/user/tool-c"},
    {"name": "tool-d", "source": "url:https://example.com/dl/tool-d.AppImage"},
    {"name": "tool", "description": "Hosted elsewhere", "note": "resolve manually: https://example.org/tool"}
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | Always `"appjail-catalog"`. |
| `version` | yes | The integer `1`. A different version is refused. |
| `origin` | no | Where the catalog comes from, shown to you. Up to 300 characters. |
| `revision` | no | Anything that tells two states of the catalog apart (a commit, a date). Up to 300 characters. |
| `apps` | yes | A list of objects, with unique `name`s. |
| `apps[].name` | yes | The name to search for: letters, digits, `.`, `_`, `+`, `-`; starts with a letter or digit; up to 81 characters. |
| `apps[].description` | no | One line of text, up to 300 characters. |
| `apps[].source` | no | Where the app comes from, as `kind:target`: `github:owner/repo`, `gitlab:HOST/group/.../project`, `forgejo:HOST/owner/repo`, `codeberg:owner/repo` (shorthand for `forgejo:codeberg.org/...`), `url:https://...`. A forge host is always explicit (`gitlab:gitlab.com/...`), without port or credentials; a `url:` has no credentials. Anything else, including `file:` and a bare `owner/repo`, is refused: put other locations in `note`. |
| `apps[].note` | no | Why there is no usable `source`, or a flag such as a repackager. Up to 200 characters. |

Unknown keys are errors, so a catalog means the same thing to every version that accepts it. A catalog that breaks
a rule is refused as a whole and nothing changes; texts longer than their limit are cut, not refused. appjail writes the catalog it validated, not the downloaded bytes.
`search` offers `appjail add` for `github:` and `url:` sources only; GitLab and Forgejo sources are shown as information
until appjail can install from those forges. An app the two origins place in different repositories has no `source`; its note says
`resolve manually: ...` and names both, and you choose the repository at `appjail add`. An update that moves an app to another kind, host or owner is flagged as an
owner change.

## Command reference

| Command | What it does |
|---|---|
| `add owner/repo` | Install the latest release (or `--tag`, `--prerelease`) of a GitHub project. |
| `add --file PATH` / `add --url URL` | Install an AppImage you give yourself; `--sha256 HEX` confirms it (tier 4). |
| `run APP [-- ARGS]` | Run an app; `--dir PATH[:ro\|:rw]` and `--file PATH[:ro\|:rw]` grant access for this run only. |
| `list` | Installed apps, versions, sources, tiers and updates seen; `-l` adds what each is granted, `--json` is for scripts. |
| `update [APP]` | Check, quarantine and install new versions (see [Updating](#updating)). |
| `perms APP` | Show or change an app's permissions. |
| `portals APP` | List or revoke the files an app was granted through the file chooser. |
| `desktop APP` / `open APP -- FILE...` | Menu entry, and opening files with an app. |
| `remove APP` | Delete the app, its private home and menu entry, and take back its portal grants and remembered portal decisions. |
| `history [APP]` | Recorded changes to the manifests. |
| `search WORDS` | Suggestions from the catalogs. |
| `index add\|remove\|update\|rollback\|status` | Manage the catalogs `search` reads (the built-in appjail-db list and any you add). |
| `tools status\|install NAME` | Helper binaries whose URL, size and hash are pinned in appjail's source (`gh` for attestations, `dwarfs` for DwarFS-based AppImages). |
| `version` | The installed version. |
| `appjail-gui` (separate command) | The window; see [Graphical interface](#graphical-interface). |

## Troubleshooting

| Message or symptom | Cause and fix |
|---|---|
| bwrap fails with `Operation not permitted` or `setting up uid map: Permission denied` | Unprivileged user namespaces are blocked. On Ubuntu, AppArmor can restrict them (`kernel.apparmor_restrict_unprivileged_userns`); the project's CI relaxes it with `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. That changes a system-wide protection, so decide for yourself whether to do it, or give bubblewrap its own AppArmor profile. |
| An app exits after a few seconds with code 0 and no window | Its launcher starts the real app detached and exits, and the jail ends with it (VSCodium does this). `appjail perms APP --allow linger` keeps the jail until every process in it has exited; or pass the app's own wait option, e.g. `appjail run vscodium -- --wait`. |
| `no usable Wayland session` or `Wayland socket not found` | `run` needs a Wayland compositor and `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` in the environment (not available over a plain ssh login). Command-line apps need no window: `perms APP --display none` runs them without a Wayland session at all. Apps that only speak X11 use `perms APP --display xwayland` (needs `xwayland`), or `xwayland-rootful` (needs `xwayland` and `openbox`) when no window appears, as on GNOME. |
| `run` refuses an app, saying its Wayland socket lists privileged interfaces | The socket the app would get lets a client capture the screen, inject input, read the clipboard without focus or control other windows or the desktop (the message names which). Run it on a compositor whose socket lists none (GNOME, sway, labwc, Hyprland 0.55), or accept that with `appjail perms APP --allow full_wayland`. Copy and paste in the app's own window is not affected. |
| `run` refuses an app, saying its socket lists interfaces "not known to it" | The compositor offers an interface appjail has not classified (a compositor that was not measured, or a new version of one that was), so appjail cannot say what it allows. Accept it with `appjail perms APP --allow full_wayland`, and please report the interface name and the compositor version so it can be classified. |
| An app with `network` is refused, naming `passt` | Install `passt`; the app is never put on the host network silently. |
| An app with `network_host` is refused, naming Landlock | The kernel lacks Landlock ABI 6 (Linux 6.12 or later, with Landlock enabled). Use `network` instead, which keeps the app in a private network namespace. |
| `GitHub API rate limit reached` | Unauthenticated requests are limited to 60 per hour per address. Set `GITHUB_TOKEN`. |
| `unsquashfs is not installed` | Install `squashfs-tools`. `add` also offers to run the AppImage's own extractor in a jail with no network; `update` and `run` need `squashfs-tools`. |
| `no local index; run appjail index update first` | `search` reads downloaded catalogs only: run `appjail index update`. |
| DwarFS-based AppImage | `appjail tools install dwarfs` fetches the pinned helper. |
| An app cannot see a file or folder | Nothing outside its private home is visible by default: `appjail perms APP --add-dir PATH`, or `appjail run APP --file PATH` for one run. |

## Wayland compositors

What an app can reach through the Wayland socket depends on the compositor, so `run` does not go by the compositor's name or by
`wp_security_context_v1` alone: it reads the registry of the socket the app would get (the restricted socket where the
compositor makes one, else the compositor's own) and refuses a windowed app when that socket lists privileged interfaces
(screen capture, virtual input, data-control, control of other windows or of the desktop) or interfaces appjail does not
know, unless the app has `full_wayland`. The table is what
that gave on each compositor, started headless in a virtual machine (Debian 13 and Ubuntu 26.04, the same probes in both),
with real clients: capture (`grim`), another client's clipboard (`wl-paste`), typing (`wtype`), a window, and copy and paste
between windows with keyboard focus (GTK 4). The method, the raw results and the caveats are in
[docs/compositor-assessment](docs/compositor-assessment/ASSESSMENT.md); `tests/compositors/` repeats it.

| Compositor (tested versions) | The app's socket | Privileged interfaces left on it | Without `full_wayland` | Copy and paste with the app |
|---|---|---|---|---|
| GNOME: Mutter and GNOME Shell 48.7, 50.1 | the compositor's own (no `wp_security_context_v1`) | none | runs | works |
| Cinnamon's Muffin 6.4.1 (standalone, not a full Cinnamon session) | the compositor's own (no `wp_security_context_v1`) | none | runs | works |
| sway 1.10.1, 1.11 | restricted | none | runs | works |
| labwc 0.8.3, 0.9.3 | restricted | none | runs | works |
| Hyprland 0.55.2 | restricted | none | runs | works |
| Hyprland 0.53.3 | restricted | virtual pointer, virtual keyboard, input method (a client can type) | refused | works one way; the test crashes it (Hyprland 0.53.3 aborts when a window closes) |
| KDE: KWin 6.3.6, 6.6.6 | restricted | clipboard (data-control), layer shell, plasma shell, output management, desktop controls (screen power, brightness, virtual desktops, screen edges) | refused | works |
| Wayfire 0.9.0, 0.10.0 | the compositor's own | capture, clipboard, input, windows | refused | works |
| Cage 0.2.0, 0.2.1 | the compositor's own | capture, input, gamma and output | refused | works |
| Weston 14.0.2 | the compositor's own | weston capture, input panel, desktop shell | refused | works |

On KWin the restricted socket hides only the protocol manager, so another app's clipboard can be read without focus; that
is why KWin is refused, not copy and paste, which uses the core clipboard and needs focus. Plasma users therefore need
`full_wayland` for each app until KWin hides data-control on restricted sockets. Muffin crashes when some ordinary clients
connect (`wl-copy`, `wl-paste`), so on Cinnamon any app given a window can end the session; appjail cannot prevent that.
Compositors not measured (niri, river, COSMIC, Mir, Louvre, GameScope) are decided by their registry when the app starts.

appjail keeps two lists of interface names (`src/appjail/wayland.py`): the privileged ones, and the ones checked to act only
on the app's own windows, on input while it has the focus, or on its own buffers. An interface in neither list is
unknown and refused like a privileged one, since what it allows has not been checked. So a compositor that was not measured,
or an update that adds an interface, can refuse apps that ran before, until the interface is classified;
`full_wayland` is the way around that meanwhile. Some interfaces are allowed after a decision, because they reveal or
take a little but do not let the app act on other apps, and refusing them would refuse compositors that are otherwise fine:

| Interface | Listed by | What it gives the app | Why it is allowed |
|---|---|---|---|
| `ext_idle_notifier_v1`, `org_kde_kwin_idle` | sway, Hyprland 0.55 (and KWin, Wayfire, Cage) | whether the user is idle or active, at any time | a privacy signal, not control; refusing it would refuse sway and Hyprland |
| `wp_drm_lease_device_v1` | GNOME | the lease of a display the desktop does not use (a VR headset) | the desktop's own screens are not leased; refusing it would refuse GNOME |
| `zwp_pointer_constraints_v1`, `zwp_keyboard_shortcuts_inhibit_manager_v1` | most | locking the pointer, and receiving the desktop's shortcuts | only while the app has the focus (games, remote desktops); the user can switch away |
| `ext_output_image_capture_source_manager_v1`, `ext_foreign_toplevel_image_capture_source_manager_v1` | sway | naming a screen or window as a capture source | capturing needs the copy manager, which is privileged |

KWin's own controls (screen power, brightness, virtual desktops, screen edges, the lock keys) count as privileged, under
"desktop"; KWin is refused for data-control anyway.

GNOME and KDE keep their privileged operations on D-Bus (Mutter's ScreenCast, RemoteDesktop and InputCapture, KWin's scripting
and screenshots), which any client of a session bus can reach. An app has no bus by default, and appjail refuses to grant
the names `org.gnome.Mutter*`, `org.cinnamon.Muffin*`, `org.freedesktop.a11y*`, `org.gnome.ScreenSaver`, `org.gnome.Shell`, `org.kde.KWin`, `org.kde.kglobalaccel`
and `org.kde.keyboard`.

## Limits

- **Not audited, not a security boundary you should bet on yet.** bwrap and the Linux kernel do the isolation; appjail
  configures them conservatively but has had no external review.
- **The Wayland socket is only as restricted as the compositor makes it.** Compositors with `wp_security_context_v1` (sway,
  labwc, Hyprland 0.55) hide their privileged interfaces from the app's socket; KWin and Hyprland 0.53 do not hide all of them;
  GNOME has none on its own socket and keeps them on D-Bus. `run` reads the app's socket and refuses a windowed app that would
  get privileged interfaces, or interfaces appjail does not know, unless it has `full_wayland` (see
  [Wayland compositors](#wayland-compositors)). An app can still learn when the user is idle where the compositor offers
  that. Measured on headless compositors, not on real desktop sessions.
- Releases are resolved on GitHub only. Apps hosted elsewhere appear in `search` and can be added with `--url` or `--file`,
  but then nothing identifies the publisher (tier 5, or tier 4 with a matching `--sha256`). The cheap `update` check for
  URL apps detects a new version; a change confined to bytes it does not sample, with the same size and validators, is
  only seen by a full download.
- A sandboxed app can still do whatever its grants allow. An app with `network` can reach other machines on your LAN.
- Granting a directory, a portal or a D-Bus name widens what a compromised app can do.
- The private audio graph (`audio_mode = pipewire`) connects to the output and input that are your defaults when the app
  starts. If you later make a headset the default, the app plays on both and its microphone mixes both inputs; if you
  unplug a device the app was using, the sound stops for good (restart the app); nothing re-attaches by itself, and the
  tunnel does not reconnect after the host's audio server restarts. The app never sees which devices exist. `pulse`
  mode has none of this, but cannot deny the microphone. Apps that speak only native PipeWire work in `pipewire` mode
  only; the host's PipeWire socket is never shared (it would expose cameras and screen casts).
- Inside the jail only unix, internet and netlink sockets exist (no Bluetooth sockets, for example), and `io_uring`
  is unavailable; apps that depend on them fail or fall back.
- x86-64 only. The GNOME and KDE portal backends have not been tested (the GTK backend and a real X11-only AppImage
  have, under headless weston; the portal dialogs themselves are not driven). Real internet IPv6 under `pasta` is
  untested; IPv6 forwarding is tested in a fake network.
- `display = xwayland-rootful` shows the app in one window and worked on GNOME in a brief test; clipboard and drag-and-drop through
  that window, and GPU acceleration through Xwayland, have not been verified. Real desktop D-Bus services (notification
  daemon, MPRIS players) and tray icons that need a `-<pid>` bus name are untested too.
- Stopping `appjail run` with SIGINT, SIGTERM or SIGHUP stops the whole jail, including `pasta`. If appjail is killed
  with SIGKILL, an app with `network` is stopped about a second later by a watcher inside its network namespace; small
  `appjail-*` directories and files (sockets, a FIFO, the seccomp filter) stay in the runtime directory until logout.

To report a vulnerability, see [SECURITY.md](https://github.com/alberto743/appjail/blob/main/SECURITY.md).

The full design is in [DESIGN.md](https://github.com/alberto743/appjail/blob/main/DESIGN.md); the reasoning behind each choice, rejected alternatives and deferred
features are in [DECISIONS.md](https://github.com/alberto743/appjail/blob/main/DECISIONS.md).

## Alternatives and related projects

appjail covers one niche: AppImages from GitHub (or a file or URL you name), pinned by hash, each in its own
bubblewrap jail, with updates held in quarantine. Other tools cover other parts of this; if one fits you better, use it.
[DECISIONS.md](https://github.com/alberto743/appjail/blob/main/DECISIONS.md) says why some were not used as a base. Facts are as found on each project's page in
November 2026; check them before relying on them.

**Managing AppImages**

- [AM / AppMan](https://github.com/ivan-hc/AM): shell (GPL-3.0); thousands of install scripts for AppImages and other
  portable programs. It updates itself and fetches its scripts from `main`; sandboxing is an optional extra (`aisap`,
  `sas`). appjail's search catalog is derived from AM's list through [appjail-db](https://github.com/alberto743/appjail-db),
  but appjail never runs AM's scripts. AppMan is the same code installed without root.
- [Soar](https://github.com/pkgforge/soar): Rust (MIT); package manager for static binaries and AppImages from its own
  repositories, and for GitHub, GitLab, Codeberg and Forgejo releases; verifies checksums and signatures; delta updates;
  x86-64, aarch64, riscv64. Has some Landlock sandboxing; no update delay found.
- [AppManager](https://github.com/kem-a/AppManager) (kem-a): Vala/GTK (GPL-3.0); installs and manages AppImages and
  gives each app a private home and a bubblewrap sandbox with a D-Bus proxy. The closest in spirit; it is a desktop app,
  built around files you already have rather than pinned releases.
- [Gear Lever](https://github.com/mijorus/gearlever): Python/GTK (GPL-3.0, Flatpak); adds AppImages to the menu and
  updates them; a CLI since 3.0. No sandbox of its own that I found.
- [Zap](https://github.com/srevinsaju/zap): Go (MIT); installs from GitHub releases and URLs, delta-updates through the
  update information embedded in the AppImage. Last updated in June 2024; latest release December 2021.
- [Bread](https://github.com/pegvin/bread) and [appimage-cli-tool](https://github.com/AppImageCrafters/appimage-cli-tool):
  small CLIs to install, update and remove AppImages (Bread: from GitHub; optional sandbox, off by default). Last
  updated in 2024 and 2023.
- [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) and
  [appimaged](https://github.com/probonopd/go-appimage): desktop integration for AppImages you already have, no
  sandbox.
- [AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate): the AppImage project's delta updater, driven by
  the update information inside the AppImage. appjail ignores that information: you name the source.
- [awesome-appimage](https://github.com/AppImageCommunity/awesome-appimage) lists more tools;
  [Portable-Linux-Apps](https://github.com/Portable-Linux-Apps/Portable-Linux-Apps.github.io) is a browsable catalog of
  AppImages.

**Sandboxing**

- [Flatpak](https://flatpak.org/) and [Flathub](https://flathub.org/): the mature route when the app is on Flathub:
  runtimes, portals, signed remotes. appjail is for what is only released as an AppImage, and writes a `.flatpak-info`
  solely so xdg-desktop-portal recognises its sandbox.
- [simple-appimage-sandbox (sas)](https://github.com/Samueru-sama/simple-appimage-sandbox) (POSIX shell, GPL-3.0) and
  [aisap](https://github.com/mgord9518/aisap) (Go, with a Zig rewrite not yet usable; MIT; early development): bubblewrap wrappers for AppImages you
  already have. Neither fetches, pins or updates; sas leaves audio, D-Bus, network and display sockets on by default.
- [FlatImage](https://github.com/flatimage/flatimage) (Apache-2.0): a different format, a portable image sandboxed by
  default, not a manager of AppImages.
- [Bubblejail](https://github.com/igo95862/bubblejail) (Python, GPL-3.0-or-later): bubblewrap sandboxes for any desktop
  application, with profiles and a configuration GUI.
- [Firejail](https://github.com/netblue30/firejail) (C, GPL-2.0): SUID sandbox with 900+ profiles. appjail uses
  unprivileged bubblewrap instead.
- Building blocks: [bubblewrap](https://github.com/containers/bubblewrap) (LGPL-2.1; what appjail drives),
  [nsjail](https://github.com/google/nsjail) (Apache-2.0; process isolation for servers and untrusted code),
  [Landrun](https://github.com/Zouuup/landrun) (MIT; runs a command under Landlock). appjail uses one Landlock feature
  only.

**Installing release binaries (not AppImage-specific)**

- [eget](https://github.com/zyedidia/eget) (Go, MIT; checks a `.sha256` published next to the asset),
  [bin](https://github.com/marcosnils/bin) (Go, MIT), [ubi](https://github.com/houseabsolute/ubi) (Rust;
  `--min-age-days` skips very new releases) and [dra](https://github.com/devmatteini/dra) (Rust, MIT; can install
  AppImages): download the right asset of a release. No sandbox.

**Same name, unrelated**

- [AppJail](https://github.com/DtxdF/AppJail) (BSD-3-Clause; sh and C): a framework for FreeBSD jails. This project is
  not affiliated with it; it targets Linux AppImages and uses bubblewrap.

## Development

The code is stdlib-only Python under `src/appjail/`; tests are plain `pytest`. Many tests start real sandboxes and
need a Linux machine with bubblewrap, `unsquashfs`, `pasta`, a headless Wayland compositor (`weston`) and the other
packages in `tests/vm/packages.txt`.

```sh
APPJAIL_INTEGRATION=1 python3 -m pytest
```

Without `APPJAIL_INTEGRATION=1` the tests that need real sandboxes are skipped. Tests that download from the network are
opt-in (`APPJAIL_E2E=1`, `APPJAIL_LIVE=1`). The project's own workflow runs the suite inside a disposable QEMU guest
built from `tests/vm/` (`create.sh`, `start.sh`, `provision.sh`, `test.sh`) so that downloads and sandboxed apps never
run on the developer's machine. GitHub Actions runs the full suite, the packaging test, a check of every commit message
and a REUSE compliance check on pushes to `main` and on pull requests, and a separate workflow runs every opt-in suite
(real downloads) on demand and weekly. Enable the same commit-message check locally with
`git config core.hooksPath .githooks`.

## License

[MPL-2.0](https://github.com/alberto743/appjail/blob/main/LICENSES/MPL-2.0.txt). The repository follows the [REUSE](https://reuse.software/) specification.
