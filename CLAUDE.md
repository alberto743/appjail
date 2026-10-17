# bjail: instructions for Claude

Read `DESIGN.md` first. It is the specification. Do not deviate from its principles without asking.

## Task
Implement the MVP in Python (not shell), in this directory. MVP order:
1. Manifest parser and schema (TOML).
2. `add owner/repo` for GitHub: resolve latest release, pick the AppImage asset (ask on ambiguity), show owner/age/stars/fork status, download in a network-only jail, hash, pin (TOFU + GitHub digest if available), write manifest.
3. bwrap runner: Wayland, audio, GPU, private home, extracted AppImage with `AppRun`.
4. `search` over the local AM index.
5. `index update` / `index rollback`.
6. `update [app]` (added to the MVP by the user): re-resolve, download in the jail, verify evidence, show the diff (hashes, tier, permissions, release link), quarantine delay (default 7 days, overridable), user approval. A tier downgrade or an owner change blocks the update. `list`, `remove` and `perms` come with it.

Progress (update with every milestone): steps 1-3 done (manifest; `add` with jailed download, digest, extraction, `--tag`, `--dir`; `run` with the bwrap runtime jail and `--dir`), all tests in native pytest, REUSE-compliant. Next: 4 `search`, 5 `index update/rollback`, 6 `update`, `list`, `remove`, `perms`.

Deferred: attestation and GPG tiers, Xwayland isolation, portals, other forges.

## Decisions made
- Language: Python 3, stdlib only (confirmed by the user's go-ahead on the plan).
- Extraction: prefer `unsquashfs` on the SquashFS offset; fall back to `--appimage-extract` inside the network-only jail. Never run the AppImage runtime outside a jail.
- AM commit signatures: checked, recorded in DESIGN.md. Do not redo.
- `sas`: read and rejected as a base; write bwrap flags directly. Flatpak comparison done. Both recorded in DESIGN.md.
- GitHub `digest` (sha256:hex) and the repo-scoped attestations endpoint verified live on cli/cli; recorded in DESIGN.md. cli/cli is the user-approved repo for API metadata checks.

## Testing environment
- Never use the host system for this work, except to edit files and run git in this directory and to run qemu itself. All execution happens in the qemu-kvm guest: unit tests, integration tests, `bin/bjail`, network access (GitHub API probes included), downloads, extraction and bwrap. Do not run project code, tests or network clients on the host.
- Host status (checked 2026-10-17): qemu 10.0.13 with KVM, `qemu-img`, `cloud-localds`, `genisoimage` and OVMF are installed; the user has rw access to `/dev/kvm` via ACL. Do not install anything else.
- The guest needs a headless Wayland compositor for GUI tests, user namespaces, bubblewrap, `unsquashfs`, and a kernel with DRM drivers. Keep images, disks and scripts under this directory or the scratchpad, never in the user's home.
- Approved test AppImages (user, 2026-10-17, guest only): `AppImage/appimagetool`, `AppImage/AppImageKit` (obsolete-appimagetool), `hluk/CopyQ` (needs glibc 2.43; Debian 13 has 2.41, so it cannot run in the guest, and the older v16 release is too new as well), and `skyjake/lagrange` (the GUI test app, chosen by Claude on the user's delegation: 11 MB, SDL, runs in the guest). cli/cli assets may be used for jailed-download checks. Anything else still needs a new approval.
- Ask before creating or downloading a guest image (it is a binary download).
- The VM is reproducible from tracked files only; `vm/` (base image, disk, ssh key, console log) is gitignored and can be deleted and rebuilt at any time.
- Recreate on a new machine:
  1. Host packages (Debian 13): `sudo apt install qemu-system-x86 qemu-utils cloud-image-utils`; check `/dev/kvm` is readable and writable by the user (`getfacl /dev/kvm`, or join the `kvm` group).
  2. `tests/vm/create.sh` downloads the Debian 13 genericcloud image (~340 MB, binary download: ask first), verifies it against Debian's `SHA512SUMS`, creates an overlay disk, an ssh key and the cloud-init seed from `tests/vm/user-data.tmpl`. `--force` rebuilds the overlay and seed. The guest package list lives in `tests/vm/packages.txt` (one commented line per package: this is the trace of the guest requirements; change it there, never ad hoc in the guest). `PACKAGES="..."` overrides it for one run.
  3. `tests/vm/start.sh` boots it (ssh on 127.0.0.1:2222, user `tester`, passwordless sudo inside the guest only; virtio NIC and a virtio-gpu device). Wait with `tests/vm/ssh.sh 'cloud-init status --wait'` (1-2 minutes on first boot).
  4. `tests/vm/provision.sh` brings the running guest to the expected state: installs `packages.txt`, replaces the cloud kernel (no DRM drivers, so no `/dev/dri`) with the regular `linux-image-amd64`, adds `tester` to `video` and `render`, and reboots when the kernel changed. Idempotent; run it again after editing `packages.txt`.
  5. `tests/vm/sync.sh` copies the project into `~/bjail` in the guest (tar over ssh, no host mounts); `tests/vm/ssh.sh <cmd>` runs commands; `tests/vm/test.sh` syncs and runs the suite; `tests/vm/down.sh` stops the guest.
- The guest NIC must be virtio (`-nic user,model=virtio-net-pci`, already in `start.sh`); the default NIC left the guest without DNS and cloud-init failed. The cloud-init seed only runs on a fresh overlay.
- Verified guest (2026-10-17): Debian 13, kernel 6.12.113+deb13-amd64 with `/dev/dri/{card0,card1,renderD128}` (virtio-gpu), bubblewrap 0.12.0, unsquashfs 4.6.1, Python 3.13.5, pytest 8.3.5, reuse 5.0.2, weston 14.0.2, unprivileged user namespaces, HTTPS to api.github.com from Python. Supplementary groups survive inside the jail, so group-owned render nodes stay usable.

## Running tests (guest only)
- Test framework: pytest (guest package `python3-pytest`; a development dependency only, the tool itself stays stdlib-only). Config in `pytest.ini`. All tests are native pytest (plain `assert`, fixtures, `parametrize`, `skipif`); write new ones the same way. Guest-only tests are skipped elsewhere via `BJAIL_INTEGRATION=1`, which `tests/vm/test.sh` sets.
- Full suite: `tests/vm/test.sh` (syncs the project into the guest, runs `python3 -m pytest` there). Pass pytest arguments through, e.g. `tests/vm/test.sh -k appimage -x`.
- Live GitHub metadata check (cli/cli, no downloads; 4 of the 60 requests/hour): `tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/bjail && BJAIL_LIVE=1 python3 -m pytest tests/test_github.py -k live'`.
- End to end with a real download (skyjake/lagrange, 11 MB; opt-in): `tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/bjail && BJAIL_E2E=1 python3 -m pytest tests/test_e2e.py -v'`. It adds the app, runs the GUI under headless weston inside the jail, checks the real home stays untouched, and checks the tamper refusal.
- Try the CLI: `tests/vm/ssh.sh 'cd ~/bjail && python3 -m bjail ...'`. It writes to the guest's `~/.local/share/bjail` and `~/.config/bjail`, never to the host's.
- Do not install test tools on the host.

## Verification status (done; results in DESIGN.md "Findings")
GitHub `digest` and attestations, AM commit signatures, `sas` vs direct bwrap, Flatpak comparison. Re-verify only if DESIGN.md is contradicted by new evidence.

## Hard rules
- Never source, execute or `eval` any AM script or any text from the network. Parse as text only and strip terminal escape sequences.
- No sudo for Claude (the sudo lines in the VM recipe are for the user to run on a new machine). Install nothing outside this directory and the tool's own data directory (`~/.local/share/bjail`, `~/.config/bjail`).
- Ask before downloading any AppImage or other binary. Tests that need the network should use small, well-known repos the user names.
- The tool has no self-update and must never fetch code to run.
- Work in the git repository in this directory. The user asked for progress to be traced, so commit at each completed, tested milestone with a clear message. Commit with the repository's own git identity (`.git/config`: GitHub noreply address); never override `user.name`/`user.email` with `-c`. Never push, never rewrite pushed history, never commit `vm/` or secrets.
- No personal data in tracked files or commit messages: no home paths, usernames, session or scratchpad paths, hostnames or emails. Use `~` and placeholders. The only identity in history is the repository's configured GitHub noreply author.
- Licensing: the project is MPL-2.0 and must stay REUSE-compliant at every commit. Every code file starts with `SPDX-FileCopyrightText: 2026 Alberto P` and `SPDX-License-Identifier: MPL-2.0` (after a shebang if there is one); other files (Markdown, config, templates) are covered by `REUSE.toml`; the license text is in `LICENSES/MPL-2.0.txt`. `tests/test_reuse.py` runs `reuse lint` in the guest. New file types need a header or a `REUSE.toml` entry in the same commit.
- Keep the project self-consistent: when code, decisions or the environment change, update CLAUDE.md, DESIGN.md and the tests/scripts in the same commit.

## Reference material
- AM clone used for the analysis: `<scratch>/AM` (commit `d739e48e75382228b7fbe12502a812f0ff97f560`). `/tmp` may have been cleaned; if so, re-clone `https://github.com/ivan-hc/AM` and check out that commit before relying on line numbers.
  - Existing sandbox flags: `modules/install.am:723-1011`.
  - Index sources: `programs/x86_64-appimages` (names, descriptions) and `programs/x86_64/<app>` (`SITE=` line).
  - 8,735 scripts; 8,247 have `SITE="owner/repo"`; about 224 point elsewhere; a few use `SITE2=` for a repackager.
- `<scratch>` was cleaned, and the session scratchpad clones (AM, sas) were lost in a reboot. Findings are in DESIGN.md. If AM files are needed, make a blobless no-checkout clone in the scratchpad (`git clone --no-checkout --filter=blob:none`) and read with `git show <commit>:<path>` (text only).
- Companion repos cloned in `<scratch>`: `AppMan` (stub only), `AppImageUpdate`, `am-utils`, `amcheck`. Not needed for the MVP.
- Host: bubblewrap 0.12.0, unprivileged user namespaces work, fusermount3 present.
- Original planning notes: kept outside this repository (the user's Claude plans directory).
