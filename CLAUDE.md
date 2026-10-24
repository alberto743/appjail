# appjail: instructions for Claude

Read `DESIGN.md` first: it specifies the behaviour. `DECISIONS.md` records rejected alternatives and deferred features, with the reasons. Do not deviate from the principles in `DESIGN.md` without asking.

## Project
A Python (stdlib only) AppImage manager: GitHub, URL and file installs with pinned and verified downloads, bwrap jails, quarantined updates, a derived catalog index (the built-in catalog is built by the sister project `../appjail-db`; `catalog.py` here defines the format and appjail-db keeps a copy). The version comes from the git tag (`[tool.hatch.version]`); pushing a `vX.Y.Z` tag runs `release.yml` and `pypi.yml` after the CI gate. Commits stay local until the user asks to push.

## Open items
Planned code work is marked as such; everything else needs a decision or an app/session the user approves.
- Manual checks on the user's machine: the GNOME and KDE portal backends; IPv6 on a real internet route.
- Decision pending: arm64 support (`DECISIONS.md`).
- Deferred by the user (`DECISIONS.md`): the GPG tier, resolvers for other forges, an allowlisting proxy for the LAN.
- Planned (code): the `camera` device permission (`/dev/video*`, `/dev/media*`); the remaining low audit findings: a symlinked tree root in the `--appimage-extract` fallback, more D-Bus names to refuse (dconf, gvfs, terminals), symlinks in files being opened, unbounded output buffering in `jail.supervise`, app-name validation in `run` and `update`, the `:rw` suffix in `--file` names.
- When GitHub moves `ubuntu-latest` to 26.04 (November 2026): switch the workflows and check CI.

## Docs
- `README.md`: user-facing entry point (what it is, requirements, usage, trust model, limits). Keep it short and in step with the CLI, the permission table and the limits, in the same commit.
- `DESIGN.md`: current behaviour, present tense, no dates, no development history. `DECISIONS.md`: why, and what is deferred.
- When code, decisions or the environment change, update the affected documents and the tests/scripts in the same commit.

## Code layout (src layout, `src/appjail/`)
- `cli.py` is only the parser and the command table (`COMMANDS`), and re-exports what tests import. Add new commands as `cmd_<name>.py`.
- Commands: `cmd_add.py` (also the install steps `update` shares), `cmd_addimage.py` (`add --file/--url`), `cmd_update.py`, `cmd_updateimage.py` (`update` of url/file apps), `cmd_apps.py` (tools, history, list, remove, perms), `cmd_portals.py`, `cmd_index.py` (search, index commands), `cmd_desktop.py`, `cmd_open.py`.
- Shared: `imagesrc.py` (url/file helpers), `grants.py` (what may be granted: D-Bus names, portal interfaces, directories), `valid.py` (value checks, `ManifestError`), `manifest.py` (schema, strict parser, writer), `store.py` (paths, `atomic_write` for every temp-and-rename write), `console.py` (Abort, Console), `permargs.py` (permission options), `services.py` (what `update` does to the outside world, replaceable in tests), `textsafe.py` (neutralises untrusted text).
- Install and update: `github.py` (release resolver, head commit), `snappy.py` (bounded decompressor of attestation bundles), `attest.py` (attestation check with the pinned `gh`), `appimage.py` (inspection, jailed extraction, tree validation), `fetcher.py` (downloader run inside the network-only jail), `tools.py` (pinned helper binaries), `updater.py` (policy, quarantine clock, pending state), `history.py` (manifest history in a local git repo).
- Running: `runner.py` (verify, prepare, launch), `runtimejail.py` (bwrap arguments of the app jail), `linger.py` (the `linger` supervisor), `jail.py` (download, extraction, manifest-history git and pasta jails), `wayland.py`, `seccomp.py`, `landlock.py` (abstract-socket scope), `dbusproxy.py`, `portal.py`, `desktop.py`.
- Index: `catalog.py` (format), `indexstore.py` (sources, snapshots; the built-in source is the sister project appjail-db), `index.py` (search).
- `gui/` is the optional tkinter front end (`appjail-gui`): `argv.py` (form state to CLI argv, no tkinter), `console.py` (`GuiConsole`, the prompt bridge, no tkinter), `worker.py` (threads and detached children), `apps.py` (installed apps as data), `dialogs.py`, `app.py` (window). It runs the CLI; it never reimplements a command or adds `--yes`. Tests: `test_gui_*.py` (the smoke test needs `python3-tk` and `xvfb`, otherwise skips).
- `__main__.py` is the entry point.

## Testing environment
- Never use the host for execution, except to edit files, run git in this directory and run qemu itself. Everything else runs in the qemu-kvm guest: unit and integration tests, the `appjail` command, network access (GitHub API probes included), downloads, extraction and bwrap. Never install test tools on the host.
- Host requirements (Debian 13): qemu with KVM, `qemu-img`, `cloud-localds`, `genisoimage`, OVMF, and read-write access to `/dev/kvm`. Install nothing else without asking.
- The guest needs a headless Wayland compositor (weston), user namespaces, bubblewrap, `unsquashfs`, `xdg-dbus-proxy`, `dbus-bin`, `passt`, `xwayland`, portals, PipeWire with pipewire-pulse and a kernel with DRM drivers; the list is `tests/vm/packages.txt` (one commented line per package). Change requirements there, never ad hoc in the guest.
- Ask before creating or downloading a guest image (a binary download). The VM is reproducible from tracked files; `vm/` (image, disk, ssh key, console log) is gitignored and may be deleted and rebuilt. Keep images, disks and scripts under this directory or the scratchpad, never in the user's home.
- VM scripts (`tests/vm/`):
  1. `create.sh` downloads the Debian 13 genericcloud image (~340 MB, verified against `SHA512SUMS`), creates the overlay disk, ssh key and cloud-init seed (`--force` rebuilds overlay and seed; the seed only runs on a fresh overlay).
  2. `start.sh` boots it (ssh on 127.0.0.1:2222, user `tester`, passwordless sudo inside the guest only; virtio NIC and virtio-gpu; the default NIC leaves the guest without DNS). Wait with `ssh.sh 'cloud-init status --wait'`.
  3. `provision.sh` brings the running guest to the expected state (packages, regular kernel for `/dev/dri`, `tester` in `video` and `render`, reboot if the kernel changed); idempotent, rerun after editing `packages.txt`.
  4. `sync.sh` copies the project to `~/appjail` in the guest; `ssh.sh CMD` runs commands; `test.sh` syncs and runs the suite; `down.sh` stops the guest.
  - Resume: `start.sh`, wait for ssh, `provision.sh` if `packages.txt` changed, then `test.sh`.
- Approved test AppImages (guest only; anything else needs a new approval): `AppImage/appimagetool`, `AppImage/AppImageKit`, `skyjake/lagrange` (the GUI test app), `pkgforge-dev/htop-AppImage` and `pkgforge-dev/Galculator-AppImage` (DwarFS), `ImageMagick/ImageMagick` (X11-only), `mhx/dwarfs` universal-small and `cli/cli` gh tarball (pinned tools). `hluk/CopyQ` cannot run in the Debian 13 guest (glibc 2.43 needed). `cli/cli` is also the repository for API metadata checks. `alberto743/appjail-db` (`catalog.json`, ~1.5 MB text) is approved for the index e2e test.
- GitHub limit: 60 unauthenticated requests per hour, shared by every run from the guest (a full suite with the opt-in suites uses about 45, one `update` about 4). Check `https://api.github.com/rate_limit` (free) before an e2e run and run one group at a time. Each download needs approval.

### Running tests (guest only)
- pytest is a development dependency only; config in `pyproject.toml`. All tests are native pytest (plain `assert`, fixtures, `parametrize`, `skipif`). Shared fixtures (`sandbox`, `runtime`, `h`) are in `tests/conftest.py`, shared helpers (`wait_for`, ...) in `tests/helpers.py`; a test module never imports from another. `tests/test_lint.py` runs `ruff check` over `src` and `tests` (installed by `tests/vm/install-ruff.sh`) and must stay clean. `tests/test_reuse.py` runs `reuse lint`. Guest-only tests skip elsewhere via `APPJAIL_INTEGRATION=1`, which `test.sh` sets.
- Full suite: `tests/vm/test.sh [pytest args]`, e.g. `tests/vm/test.sh -k appimage -x`.
- Opt-in suites: `tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/appjail && <env> python3 -m pytest <file> -v'`.

  | Suite | env | file |
  |---|---|---|
  | Live GitHub metadata (cli/cli, no downloads) | `APPJAIL_LIVE=1` | `tests/test_github.py -k live` |
  | `add`, run, tamper (lagrange, GUI under weston; network via pasta; menu entry) | `APPJAIL_E2E=1` | `tests/test_e2e.py` (the tamper test damages the shared image and must stay last) |
  | X11-only app under Xwayland (ImageMagick) | `APPJAIL_E2E=1` | `tests/test_xwayland_e2e.py` |
  | Real `update`, tier-4 quarantine hash, url apps | `APPJAIL_E2E=1` | `tests/test_update_e2e.py` |
  | DwarFS helper | `APPJAIL_E2E=1 APPJAIL_INTEGRATION=1` | `tests/test_tools.py` |
  | Sigstore verification (pinned `gh`) | `APPJAIL_E2E=1 APPJAIL_INTEGRATION=1` | `tests/test_attest.py` |
  | Packaging (pip install in a venv, sdist) | `APPJAIL_E2E=1` | `tests/test_packaging.py` |
  | appjail-db catalog update/rollback (text only; 1 API request, 1 raw download) | `APPJAIL_E2E=1` | `tests/test_index_e2e.py` |
- Try the CLI: `tests/vm/ssh.sh 'cd ~/appjail && PYTHONPATH=src python3 -m appjail ...'`. It writes to the guest's `~/.local/share/appjail` and `~/.config/appjail`, never the host's. There is no `bin/` launcher; the console script comes from `[project.scripts]`.
- Harness note: a test that launches a jail behind pasta must kill the whole process group; SIGTERM to pasta alone leaves the jail running. Background jobs started in a session do not survive it.

## CI (`.github/`)
- `workflows/ci.yml`: the full suite with `APPJAIL_INTEGRATION=1` on `ubuntu-26.04` (relaxes `kernel.apparmor_restrict_unprivileged_userns` when present, installs `tests/vm/packages.txt` minus the kernel, prints the versions under test; tests needing missing hardware skip). A second job, `package`, runs `tests/test_packaging.py`.
- `workflows/reuse.yml`: `fsfe/reuse-action`. `workflows/e2e.yml`: every suite including the opt-in ones, by hand and weekly, with `GITHUB_TOKEN` for the API limit.
- Releases: `workflows/ci-gate.yml` (reusable) succeeds only if `ci.yml` passed on that commit on `main`. `workflows/release.yml` (on a `vX.Y.Z` tag, after the gate) builds once through `workflows/build-dist.yml` (reusable; the version is derived from the tag by `hatch-vcs`; the sdist must be named after the tag; `twine check`) and creates the GitHub release with generated notes and the sdist (pre-release if the tag has a suffix; `contents: write` only in that job). `workflows/pypi.yml` takes the same artifact and publishes with PyPI trusted publishing (environment `pypi`, limited to `v*` tags; `id-token: write` only in the publish job; no token stored).
- `dependabot.yml`: weekly updates of the actions. Rules for workflows: pin actions to the full commit SHA with a trailing `# vX.Y.Z` comment (Dependabot updates both), keep `permissions: contents: read` unless a job needs more.
- Runner label is `ubuntu-26.04` (see `DECISIONS.md`). Minimum supported systems: Debian 13 and Ubuntu 26.04; add no workarounds for older ones.
- CI runs on GitHub's runners, not on the host. After pushing, read results with `gh run list/view/watch` (read-only). A red CI on `main` is a bug to fix. A failure that only shows on CI is often a test-fixture assumption (the runner's uid is 1001, the guest's 1000): find the cause with a captured log before adding a workaround.

## Hard rules
- Never source, execute or `eval` any text from the network (catalogs included). Parse as text only and strip terminal escape sequences. appjail never reads the AM repository; the sister project `../appjail-db` (github.com/alberto743/appjail-db) converts it to the catalog the built-in `appjail-db` source downloads. The tool has no self-update and never fetches code to run.
- No sudo for Claude (sudo lines in the VM recipe are for the user on a new machine). Install nothing outside this directory and the tool's own data directories (`~/.local/share/appjail`, `~/.config/appjail`).
- Ask before downloading any AppImage or other binary. Network tests use small, well-known repositories the user names.
- Extraction: prefer `unsquashfs` on the SquashFS offset; fall back to `--appimage-extract` only inside the no-network jail. Never run the AppImage runtime outside a jail.
- Git: work in this repository and commit at each completed, tested milestone with a clear message, using the repository's own identity (`.git/config`: GitHub noreply address); never override `user.name`/`user.email`. Commits stay local; push to the private `origin` in batches, at the end of a piece of work or when the user asks (each push starts CI runs and uses GitHub limits). Never rewrite pushed history; never commit `vm/` or secrets.
- No personal data in tracked files or commit messages: no home paths, usernames, session or scratchpad paths, hostnames or emails. Use `~` and placeholders.
- Licensing: MPL-2.0, REUSE-compliant at every commit. Every code file starts with `SPDX-FileCopyrightText: 2026 Alberto P` and `SPDX-License-Identifier: MPL-2.0` (after a shebang if any); other files (Markdown, config, templates) are covered by `REUSE.toml`. New file types need a header or a `REUSE.toml` entry in the same commit.
