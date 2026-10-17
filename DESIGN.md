# bjail: a thin bwrap AppImage manager (working name)

## Context
AppMan-like convenience for AppImages in user mode: no sudo, each app sandboxed with bubblewrap, full GUI support.

Review of the AM repo (ivan-hc/AM, commit d739e48) showed:
- `AppMan/appman` is a 36-line stub that downloads `APP-MANAGER` from `main`.
- AM self-updates, and runs install and updater scripts from `main` outside any sandbox.
- Only 6 of 8,735 install scripts mention any checksum or signature.
- About 95% of apps come from GitHub releases (8,247 `SITE="owner/repo"` entries).
- Its sandbox generates a wrapper around `sas` or `aisap` (bwrap frontends); see `AM/modules/install.am:723-1011`.

Goal: a small tool with declarative manifests, no remote code execution, no self-update, and a clear evidence model for verifying downloads and updates. Nothing is built or installed yet.

## Principles
1. Declarative manifests only (source, pinned hash, permissions). No shell from the network.
2. No self-update. The tool is updated by a reviewed `git pull` or signed tag.
3. The user provides the GitHub `owner/repo`. That repo is the only fetch source for the app. Update info embedded in an AppImage never decides the source.
4. Containment is the backstop: downloads in a network-only jail; apps in a minimal-permission jail.

## Commands
- `search <kw>`: text-only lookup in the local AM index (candidates only, never installs).
- `add owner/repo`: resolve, review, download, pin, write manifest.
- `run <app>`, `update [app]`, `list`, `remove <app>`, `perms <app>` (edit permissions).
- `index update`, `index rollback`: refresh or roll back the AM search snapshot.

## Resolver (GitHub first)
1. `GET /repos/{o}/{r}/releases/latest` (or `/releases` if prereleases are allowed). Optional token for rate limits (60 requests/hour unauthenticated).
2. Filter assets for `*.AppImage` matching the architecture; ask the user on multiple candidates or none.
3. Show owner, account age, stars, fork and archived status before download (typosquat check).
4. Collect evidence: `published_at`, GitHub per-asset sha256 `digest` (verify it exists), attestation (`gh attestation verify` or the attestations API; verify), embedded GPG signature.
5. Download in a throwaway network-only jail, hash, write manifest.

Other forges (GitLab, Codeberg, SourceForge, vendor sites) are later resolvers.

## Manifest (TOML, stored in the user's own git repo)
`source` (github owner/repo), `asset_pattern`, `version`, `sha256`, `evidence_tier`, `published_at`, `permissions` (network, audio, gpu, display = wayland|xwayland, dbus_filter, portals, dirs[]).

## Trust tiers (never silently downgraded)
1. Build attestation (Sigstore / GitHub artifact attestations).
2. Pinned-key GPG signature.
3. Publisher-pinned hash / GitHub digest.
4. Trust on first use.
5. Cross-check against another source (weak).

Most AppImages will only reach tiers 3-4. That proves "unchanged, same account", not "safe".

## Update flow
1. Resolve the new release.
2. Download in a throwaway jail and verify the evidence.
3. Show a diff: hashes, tier, permissions, release link.
4. Enforce a quarantine delay (default 7 days, overridable).
5. User approves; the manifest is committed to the user's git repo.

A tier downgrade or an owner change blocks the update.

## AM as lookup-only index
- Local snapshot of ivan-hc/AM pinned by commit; read as text only (never sourced or executed); terminal escape sequences stripped.
- `search` reads `programs/x86_64-appimages` (name, description) and `SITE=` from `programs/x86_64/<app>` to suggest a repo.
  - Non-`owner/repo` entries are flagged "resolve manually" (about 224 of them).
  - Repackager repos (e.g. `ivan-hc/Firefox-appimage`, via `SITE2=`) are flagged.
- The user must still type or paste `owner/repo` to `add`. A search hit never installs anything.
- `index update`:
  - shallow sparse fetch of only `programs/x86_64-appimages` and `programs/x86_64/`, in the network-only jail;
  - git run without hooks, submodules, LFS or filters;
  - prints a diff summary: apps added and removed, and changed `SITE=` owner/repo (changed owner gets a loud warning);
  - the user accepts, the tool pins the new commit and keeps the previous one for `index rollback`;
  - AM commit signatures (checked on the last 200 commits up to d739e48): 139 carry a PGP signature (GitHub web-flow key), 2 SSH, 59 unsigned. The pinned commit d739e48 and the maintainer's own commits are unsigned. Signatures therefore cannot prove maintainer authenticity. The controls are pinning by commit hash and the diff review above; verifying the web-flow signature is at most a weak "came through GitHub" signal.
- The index only affects `search`. Installed apps never depend on it.

## Runtime jail (bwrap)
- `--unshare-all`, private home per app, read-only system.
- Wayland socket by default. X11 only through a rootless Xwayland (a raw X11 socket allows keylogging).
- PipeWire/Pulse socket; `/dev/dri` for GPU.
- D-Bus through `xdg-dbus-proxy`; file dialogs through `xdg-desktop-portal`.
- The AppImage is extracted and `AppRun` executed (FUSE mounts do not work well in user namespaces).
- Extraction prefers `unsquashfs` on the SquashFS offset, so the untrusted AppImage runtime never runs. Fallback: `--appimage-extract` inside the throwaway network-only jail. (`unsquashfs` was not found on the host at the time of writing.)

Host verified: bubblewrap 0.12.0, unprivileged user namespaces OK, fusermount3 present.

## MVP scope
Python 3 stdlib only (`tomllib`, `urllib`, `hashlib`, `subprocess`); not shell, no third-party dependencies. Components: manifest parser, `add` for GitHub with TOFU + digest, bwrap runner with Wayland/audio/GPU, `search`, `index update`/`rollback`, `update` (quarantine, diff, tier-downgrade and owner-change block), plus `list`, `remove`, `perms`.
- DwarFS-based AppImages (rather than SquashFS) are rejected in the MVP with a clear message; `unsquashfs` cannot read them.
  - Checked 2026-10-17: Debian 13 (trixie) has no `dwarfs` or `dwarfs-tools` package (`apt-cache search dwarfs` is empty). The only source of `dwarfsextract` would be a static binary from GitHub, i.e. an extra download whose hash bjail itself would have to pin. Support is therefore deferred, not planned for the MVP. Revisit if a distro package appears.
  - `squashfs-tools` 4.6.1 is in trixie/main but not installed on this host; bjail needs it (`apt install squashfs-tools`) and must report its absence clearly.

Deferred: attestation and GPG tiers, Xwayland isolation, portals, other forges.

## Findings: GitHub API (docs, plus live check on cli/cli v2.102.0, 2026-10-17)
- Release assets have a `digest` field ("string or null"). Live: all 22 assets of cli/cli v2.102.0 carry `sha256:<64 hex>`. Treat null as "no digest" and fall back to TOFU (older releases may lack it).
- Attestations: the documented `GET /users/{username}/attestations/{subject_digest}` and the `orgs/` variant return 401 without a token. The repo-scoped `GET /repos/{owner}/{repo}/attestations/{subject_digest}` works unauthenticated (200) and returns `attestations[]` with `repository_id`, `bundle_url` (short-lived signed blob URL); other fields were not inspected. cli/cli publishes attestations for its release assets.
- Use the repo-scoped endpoint, with the digest taken from the release asset. Verifying the Sigstore bundle is deferred, so the MVP only records whether an attestation exists (this alone is not proof: the check must later confirm the signing workflow and repo identity). Existence suggests tier 1 is reachable for some repos.
- Unauthenticated rate limit is 60 requests/hour; a release plus attestation lookup costs 2.

## Findings: AM index format (commit d739e48)
- `programs/x86_64-appimages`: 8,140 lines of the form `◆ name : description` (UTF-8 bullet U+25C6). `programs/x86_64/` holds 8,735 files.
- `SITE="..."` can appear more than once in a script (e.g. `cura` at lines 6 and 34): take the first assignment, match with a regex only, never source.

## Findings: sas (Samueru-sama/simple-appimage-sandbox, 952-line POSIX shell)
- Read at commit bc5802c. Wraps bwrap; depends on dwarfs and squashfuse; mounts the AppImage and runs it.
- Defaults are permissive: dbus, network, audio, pipewire, x11 and wayland sockets all on by default; `/tmp` and `/etc` shared read-only; `/dev` bound with `--dev-bind-try` (full device access); host `xdg-open` daemon; theme and per-app config dirs shared. X11 is dropped only when a Wayland socket exists.
- Good parts to copy: `--unshare-user/pid/uts/ipc/cgroup`, `--die-with-parent`, `--new-session`, GPU binds including nvidia nodes.
- Decision: do not build on `sas`. Write bwrap flags directly in Python. Reasons: shell (violates the language rule), permissive defaults opposite to our model, FUSE mount instead of extraction, and it is a moving external dependency. Use its GPU and runtime-dir handling as reference only.
- AM also supports `aisap` (mgord9518/aisap), not evaluated.

## Findings: Flatpak comparison
- Flatpak already offers a mature sandbox, portals, signed OSTree remotes and permission overrides. It covers the need where the app exists on Flathub.
- It does not cover: AppImages released only on GitHub, user-pinned per-release hashes with a quarantine delay, and declarative manifests in the user's own git repo. bjail targets that gap and does not replace Flatpak. Prefer Flatpak when the same app is available there.

## Open items to verify before implementing
- ~~GitHub asset `digest` algorithm and attestations behaviour.~~ Verified live on cli/cli (see Findings: GitHub API).
- ~~Build on `sas` or write bwrap flags directly.~~ Decided: direct bwrap (see Findings: sas).
- ~~Whether AM commits are signed.~~ Verified: mostly GitHub web-flow signed, the maintainer's commits unsigned (see AM as lookup-only index).
- ~~Flatpak as a baseline comparison.~~ Done (see Findings: Flatpak comparison).

## Verification (for the eventual implementation)
Integration tests run inside a dedicated qemu-kvm guest (rebuilt from `tests/vm/create.sh`; see CLAUDE.md "Testing environment") (snapshot or throwaway disk) so downloads, extraction and jailed apps cannot affect the host. Unit tests run on the host. The guest needs bubblewrap, `unsquashfs`, user namespaces and a compositor (Wayland, or headless for non-GUI checks).

Test with 2-3 real GitHub AppImage repos:
- `add`, then `run`: confirm home is private and Documents are invisible.
- Tamper test: modify the pinned hash; `update` must refuse.
- `index update` diff output with a changed `SITE=`.
