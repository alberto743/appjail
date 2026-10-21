# appjail

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
- Python 3.12 or newer (tested with 3.12, 3.13 and 3.14). appjail uses only the standard library.
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
or pip (pip downloads only the build backend, Hatchling):

```sh
git clone <repository-url> appjail
cd appjail
pipx install .          # or: pip install --user .
appjail --help
```

To try it without installing, run it from the clone: `PYTHONPATH=src python3 -m appjail --help`.
Update appjail with `git pull` after reading what changed, then reinstall.

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

`add` shows the repository owner, account age, stars and fork or archive status before it downloads anything, and
asks if several release assets match. By default an app gets audio and GPU access and nothing else.

### Permissions

```sh
appjail perms lagrange                              # show
appjail perms lagrange --allow network              # outbound network only (see below)
appjail perms lagrange --add-dir ~/Documents:rw     # a directory, read-only unless :rw
appjail perms lagrange --add-dbus org.example.Name  # talk to one session-bus name through a filtering proxy
appjail perms lagrange --allow portals              # desktop portals (file chooser, notifications, ...)
appjail run lagrange --file ~/report.pdf            # one file, for this run only
```

| Permission | Effect |
|---|---|
| `network` | Outbound internet through a private network namespace made by `pasta`. The app cannot reach services on your machine's localhost or its own addresses. Needs `passt`; without it the app is refused rather than put on the host network. |
| `network_host` | The host's own network, including localhost services. For apps that really need them. |
| `audio`, `gpu` | On by default; `--no-audio` and `--no-gpu` at `add` time, or `--deny` later. |
| `portals` | The safe set of desktop portals; privileged ones are listed per app with `--add-portal`. |
| `userns` | Nested user namespaces (Chromium and Electron sandboxes). Weakens isolation, off by default. |
| `dirs` | Directories mapped into the private home. Credentials, browser profiles, shell startup files and system trees are refused. |
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
appjail search editor     # candidates only; installing is always `appjail add owner/repo`
```

## Other commands

- `appjail history [app]`: every change to the manifests, from the local git repository. `appjail run` warns if a
  manifest was edited outside appjail.
- `appjail tools status|install NAME`: helper binaries whose URL, size and hash are pinned in appjail's source (`gh` for
  attestations, `dwarfs` for DwarFS-based AppImages).
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
- Stopping `appjail run` with SIGINT, SIGTERM or SIGHUP stops the whole jail, including `pasta`. If appjail itself is
  killed with SIGKILL, an app with `network` can keep running (stop it with `pkill` on its name).
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
[CLAUDE.md](CLAUDE.md) for the details. GitHub Actions runs the full suite and a REUSE compliance check on every push.

## License

[MPL-2.0](LICENSES/MPL-2.0.txt). The repository follows the [REUSE](https://reuse.software/) specification.
