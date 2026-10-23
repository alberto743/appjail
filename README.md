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
- **You name the source.** You give a GitHub `owner/repo`, or an AppImage file or URL yourself. That is the only
  place the app is fetched from, whatever an AppImage's embedded update information says.
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

**Apps that are not GitHub releases.** Give the AppImage itself:

```sh
appjail add --file ~/Downloads/Tool-x86_64.AppImage [--name tool] [--sha256 HEX]
appjail add --url https://example.org/dl/Tool-x86_64.AppImage [--name tool] [--sha256 HEX] [--max-size MIB]
appjail update tool --file ~/Downloads/Tool-new.AppImage       # an app added from a file
```

Nothing identifies who published such a file, so these apps are tier 5 (trust on first use) or tier 4 when you pass the
hash the publisher gives with `--sha256` (a mismatch aborts). A URL must be https and is downloaded in the jail (1 GiB
at most unless `--max-size`); redirects may go to any host, and a redirect through plain http asks for an extra
confirmation unless `--sha256` matches. `update` of a URL app asks the server first with a conditional request and a
few small range requests, and downloads the whole file only when something changed.

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
| 4 | A GitHub asset without a digest: trust on first use, anchored by the pinned owner account. For `--file`/`--url`: the hash you gave with `--sha256` matched. |
| 5 | `--file`/`--url` without a hash from outside: trust on first use of the bytes alone. |

Tier 2 (GPG signatures) is not implemented. Most AppImages will land on tier 3 to 5, which proves "unchanged" (and, for
GitHub, "from the same account"), not "safe". `update APP --sha256 HEX` earns tier 4 for a tier 5 app when the hash
matches, and a tier 4 URL or file app refuses new content that comes without one.

`appjail update` re-resolves the pinned repository, downloads the candidate in the jail, verifies it, and shows you the
version, the hashes, the tier and the release link. A release must be seen for the quarantine period before it can
be installed (`--quarantine DAYS`). For tier 4 apps appjail records the candidate's hash when it is first seen and refuses
the install if the content changed in the meantime. A change of repository owner or a drop in tier blocks the update.
`--channel stable|prerelease|pinned` chooses which releases an app follows.

What `update` prints per app: *up to date*; *waiting* (a candidate was seen and its quarantine has not ended: run `update`
again later, it needs no action); *blocked* (the owner changed, the evidence got weaker, or the content changed during
the quarantine: nothing was installed and the message says why); *declined* (you answered no); *pinned* (the app follows
no releases). The exit status is 1 if any app was blocked or failed. A URL app's candidate is kept on disk during
the quarantine and installed from there (`--verify` downloads it again first); a file app has no quarantine, you hold the bytes.

## Searching

`search` looks through **catalogs**: lists of apps with, where known, the project each one comes from. A hit
is only a suggestion; installing is always `appjail add owner/repo` (or `--url`), after you have checked
the owner. Catalogs are untrusted data: appjail parses them strictly, strips terminal escape sequences from every
text, and never runs anything from them.

```sh
appjail index update                  # refresh every catalog: fetch, show what changed, ask before accepting
appjail index status                  # the sources, their revisions and update times
appjail index rollback [NAME]         # back to the previous catalog of a source (default: am)
appjail index add mine --url https://example.org/apps.json    # another catalog (https; fetched in the jail)
appjail index add local --file ~/apps.json                    # or a local file
appjail index update mine             # refresh one source (--commit SHA is for am only)
appjail index remove mine
appjail search editor                 # all sources; with several, each hit shows its source in brackets
```

`search` shows 20 results; use `--limit N` or `--all` for more.

**Sources.** The built-in `am` source is the [AM](https://github.com/ivan-hc/AM) application list: `index update` fetches
its repository in a network-only jail (only the list and the install scripts, no hooks or submodules), reads
each script as text to find the `SITE=` line, and keeps the result as a catalog. The scripts themselves are not
kept. Sources you add yourself provide a catalog directly. Every update shows the number of apps, the apps added and
removed, and every app whose repository changed, with a loud warning when the owner changed, and asks before it
replaces the catalog. One previous catalog is kept per source for `index rollback`.

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
| `apps[].source` | no | Where the app comes from, as `kind:target`: `github:owner/repo`, `gitlab:HOST/group/.../project`, `forgejo:HOST/owner/repo`, `codeberg:owner/repo` (shorthand for `forgejo:codeberg.org/...`), `url:https://...`. The host is always explicit (`gitlab:gitlab.com/...`), without port or credentials. Anything else, including `file:` and a bare `owner/repo`, is refused: put other locations in `note`. |
| `apps[].note` | no | Why there is no usable `source`, or a flag such as a repackager. Up to 200 characters. |

`search` offers `appjail add` for `github:` and `url:` sources only; GitLab and Forgejo sources are shown as information until appjail can install from those forges. An update that moves an app to another kind, host or owner is flagged as an owner change.

Unknown keys are errors, so a catalog means the same thing to every version that accepts it. A catalog that breaks
a rule is refused as a whole and nothing changes. appjail writes the catalog it validated, not the downloaded bytes.
Sources are listed in `~/.local/share/appjail/index/`.

## Command reference

| Command | What it does |
|---|---|
| `add owner/repo` | Install the latest release (or `--tag`, `--prerelease`) of a GitHub project. |
| `add --file PATH` / `add --url URL` | Install an AppImage you give yourself; `--sha256 HEX` confirms it (tier 4). |
| `run APP [-- ARGS]` | Run an app; `--dir PATH[:ro\|:rw]` and `--file PATH[:rw]` grant access for this run only. |
| `list` | Installed apps, versions, sources, tiers, permissions and updates seen. |
| `update [APP]` | Check, quarantine and install new versions (see "How trust works"). |
| `perms APP` | Show or change an app's permissions. |
| `portals APP` | List or revoke the files an app was granted through the file chooser. |
| `desktop APP` / `open APP -- FILE...` | Menu entry, and opening files with an app. |
| `remove APP` | Delete the app and its private home. |
| `history [APP]` | Recorded changes to the manifests. |
| `search WORDS` | Suggestions from the catalogs. |
| `index add\|remove\|update\|rollback\|status` | Manage the catalogs `search` reads (the built-in AM list and any you add). |
| `tools status\|install NAME` | Pinned helper binaries (`gh`, `dwarfs`). |
| `version` | The installed version. |

`appjail COMMAND --help` lists every option.

## Other commands

- `appjail history [app] [--limit N]`: every change to the manifests, from the local git repository. `appjail run` warns if a
  manifest was edited outside appjail.
- `appjail tools status|install NAME`: helper binaries whose URL, size and hash are pinned in appjail's source (`gh` for
  attestations, `dwarfs` for DwarFS-based AppImages).
- `appjail desktop NAME [--mime TYPE]... [--mime-all] [--rw]` (also `add --desktop`): a menu entry that starts the app through
  appjail, generated by appjail (the AppImage's own `.desktop` is never used). File types are opt-in: only the ones you pick
  show under "Open with", and appjail never makes the app a default. Opening a file passes just that file to the app, read-only
  unless `--rw` (`appjail open NAME -- FILE...`). `--remove` and `--prune` delete entries; `remove` does it too.
- `appjail version` (or `--version`): the installed version. It comes from the git tag at build time (`0.2.0` on a release, `0.2.1.dev4+g1a2b3c4` four
  commits after it); it prints `unknown` when run from a source tree that is not installed.
- Set `GITHUB_TOKEN` to raise the GitHub API rate limit. It is only ever sent to `api.github.com`.

## Troubleshooting

| Message or symptom | Cause and fix |
|---|---|
| bwrap fails with `Operation not permitted` or `setting up uid map: Permission denied` | Unprivileged user namespaces are blocked. On Ubuntu, AppArmor can restrict them (`kernel.apparmor_restrict_unprivileged_userns`); the project's CI relaxes it with `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. That changes a system-wide protection, so decide for yourself whether to do it, or give bubblewrap its own AppArmor profile. |
| `no usable Wayland session` or `Wayland socket not found` | `run` needs a Wayland compositor and `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` in the environment (not available over a plain ssh login). Apps that only speak X11 use `perms APP --display xwayland` (needs `xwayland`). |
| An app with `network` is refused, naming `passt` | Install `passt`; the app is never put on the host network silently. |
| `GitHub API rate limit reached` | Unauthenticated requests are limited to 60 per hour per address. Set `GITHUB_TOKEN`; it is only sent to `api.github.com`. |
| `unsquashfs is not installed` | Install `squashfs-tools`, or accept the offer to run the AppImage's own extractor in a jail with no network. |
| DwarFS-based AppImage | `appjail tools install dwarfs` fetches the pinned helper. |
| An app cannot see a file or folder | Nothing outside its private home is visible by default: `appjail perms APP --add-dir PATH`, or `appjail run APP --file PATH` for one run. |

## Limits

- **Not audited, not a security boundary you should bet on yet.** bwrap and the Linux kernel do the isolation; appjail
  configures them conservatively but has had no external review.
- Releases are resolved on GitHub only. Apps hosted elsewhere appear in `search` and can be added with `--url` or `--file`,
  but then nothing identifies the publisher (tier 5). The cheap `update` check for URL apps detects a new version; a
  change confined to bytes it does not sample, with the same size and validators, is only seen by a full download.
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
opt-in (`APPJAIL_E2E=1`, `APPJAIL_LIVE=1`). The project's own workflow runs the suite inside a disposable QEMU guest
built from `tests/vm/` (`create.sh`, `start.sh`, `provision.sh`, `test.sh`) so that downloads and sandboxed apps never
run on the developer's machine. GitHub Actions runs the full suite and a REUSE compliance check on every push, and a
separate workflow runs every opt-in suite (real downloads) on demand and weekly.

## License

[MPL-2.0](LICENSES/MPL-2.0.txt). The repository follows the [REUSE](https://reuse.software/) specification.
