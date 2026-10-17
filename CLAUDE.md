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
- The guest needs a Wayland or headless compositor for GUI tests, user namespaces enabled, bubblewrap, and `unsquashfs`. Keep images, disks and scripts under this directory or the scratchpad, never in the user's home.
- Approved test AppImages (user, 2026-10-17, guest only): `AppImage/appimagetool`, `AppImage/AppImageKit` (obsolete-appimagetool), `hluk/CopyQ`. cli/cli assets may be used for jailed-download checks. Anything else still needs a new approval.
- Ask before creating or downloading a guest image (it is a binary download).
- The VM is reproducible from tracked files only; `vm/` (base image, disk, ssh key, console log) is gitignored and can be deleted and rebuilt at any time.
- Recreate on a new machine:
  1. Host packages (Debian 13): `sudo apt install qemu-system-x86 qemu-utils cloud-image-utils squashfs-tools`; check `/dev/kvm` is readable and writable by the user (`getfacl /dev/kvm`, or join the `kvm` group).
  2. `tests/vm/create.sh` downloads the Debian 13 genericcloud image (~340 MB, binary download: ask first), verifies it against Debian's `SHA512SUMS`, creates an overlay disk, an ssh key and the cloud-init seed from `tests/vm/user-data.tmpl`. `--force` rebuilds the overlay and seed. `PACKAGES="..."` overrides the guest package list (default: bubblewrap squashfs-tools git python3 ca-certificates; add weston/pipewire only for GUI/audio tests).
  3. `tests/vm/start.sh` boots it (ssh on 127.0.0.1:2222, user `tester`, passwordless sudo inside the guest only). Wait with `tests/vm/ssh.sh 'cloud-init status --wait'` (about 1-2 minutes on first boot).
  4. `tests/vm/sync.sh` copies the project into `~/bjail` in the guest (tar over ssh, no host mounts); `tests/vm/ssh.sh <cmd>` runs commands; `tests/vm/down.sh` stops the guest.
- The guest NIC must be virtio (`-nic user,model=virtio-net-pci`, already in `start.sh`); the default NIC left the guest without DNS and cloud-init failed. The cloud-init seed only runs on a fresh overlay.
- Verified guest (2026-10-17): bubblewrap 0.12.0, unsquashfs, git, Python 3.13.5, unprivileged user namespaces, HTTPS to api.github.com from Python.

## Running tests (guest only)
- Full suite: `tests/vm/test.sh` (syncs the project into the guest, runs `BJAIL_INTEGRATION=1 python3 -m unittest` there). Pass unittest arguments through, e.g. `tests/vm/test.sh -v tests.test_appimage`.
- Live GitHub metadata check (cli/cli, no downloads; 4 of the 60 requests/hour): `tests/vm/sync.sh && tests/vm/ssh.sh 'cd ~/bjail && BJAIL_LIVE=1 python3 -m unittest tests.test_github.LiveTests'`.
- Try the CLI: `tests/vm/ssh.sh 'cd ~/bjail && python3 -m bjail ...'`. It writes to the guest's `~/.local/share/bjail` and `~/.config/bjail`, never to the host's.
- Tests that need tools missing on the host (`bwrap` use, `mksquashfs`, `unsquashfs`) skip when run elsewhere; do not install them on the host.

## Verification status (done; results in DESIGN.md "Findings")
GitHub `digest` and attestations, AM commit signatures, `sas` vs direct bwrap, Flatpak comparison. Re-verify only if DESIGN.md is contradicted by new evidence.

## Hard rules
- Never source, execute or `eval` any AM script or any text from the network. Parse as text only and strip terminal escape sequences.
- No sudo for Claude (the sudo lines in the VM recipe are for the user to run on a new machine). Install nothing outside this directory and the tool's own data directory (`~/.local/share/bjail`, `~/.config/bjail`).
- Ask before downloading any AppImage or other binary. Tests that need the network should use small, well-known repos the user names.
- The tool has no self-update and must never fetch code to run.
- Work in the git repository in this directory. The user asked for progress to be traced, so commit at each completed, tested milestone with a clear message. Commit with the repository's own git identity (`.git/config`: GitHub noreply address); never override `user.name`/`user.email` with `-c`. Never push, never rewrite pushed history, never commit `vm/` or secrets.
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
