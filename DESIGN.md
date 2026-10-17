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

Implemented in `bjail/github.py` (client with injectable transport) and `bjail/textsafe.py` (escape-sequence and control-character stripping for every untrusted string shown to the user):
- Per `add`: `/repos/{o}/{r}`, `/users/{o}` (owner age), `/releases/latest` (or the first non-draft of `/releases` with prereleases), then one attestation lookup per chosen asset: 4 requests of the 60/hour budget.
- `GITHUB_TOKEN` is optional and sent only to api.github.com. Redirects are followed by hand within that host (a moved repo yields `RepoInfo.renamed`); a redirect elsewhere is refused.
- Assets whose download URL is not under `https://github.com/{owner}/{repo}/releases/download/`, or whose name has odd characters, are dropped. Digest `sha256:<hex>` is parsed; null or other algorithms mean "no digest".
- AppImage selection: `.AppImage` suffix (case-insensitive), other architectures excluded by name token; explicitly x86_64/amd64 names win over untagged ones; several candidates means the caller asks the user. `.zsync` files never match.
- `asset_pattern` is suggested by replacing the release version in the chosen name with `*`, and matched with `fnmatch`.
- Open design point for `add`/`update`: a repo that is deleted and re-registered under the same owner name keeps the same `owner/repo` string. `RepoInfo.owner_id` allows pinning the account; adding an optional `owner_id` to the manifest is proposed so that "owner change blocks the update" holds in that case too.

Other forges (GitLab, Codeberg, SourceForge, vendor sites) are later resolvers.

## `add` (implemented in `bjail/cli.py`, `bjail/jail.py`, `bjail/fetcher.py`)
`bin/bjail add owner/repo [--name N] [--prerelease] [--tag TAG] [--dir PATH[:ro|:rw]] [--allow network|portals] [--no-audio] [--no-gpu] [--display wayland|xwayland]`. `--tag` pins a specific release (looked up with `/releases/tags/<tag>`) instead of the latest; the manifest records the version, and `update` will move such an app to the latest release unless told otherwise (to be decided with `update`).
1. Refuse early if the name exists. Fetch repo data and show the review (owner, id, account age, stars, fork/archived/renamed warnings).
2. Resolve the release, select the AppImage (ask on several, abort on none), show GitHub's digest and whether an attestation exists.
3. Ask before downloading. The download runs `bjail/fetcher.py` inside the network-only jail: `--unshare-all --share-net --cap-drop ALL --clearenv --new-session --die-with-parent`, system dirs and `/etc/ssl` read-only, only the staging dir writable, root remounted read-only. The fetcher follows only https redirects within github.com / *.githubusercontent.com and stops at the size GitHub announced.
4. On the host: size must equal the announced size, sha256 is computed, a GitHub digest must match, the file must be a type-2 AppImage (ELF + `AI\x02`). Any failure deletes the staging directory and writes nothing.
5. Tier 3 if GitHub gave a digest, else tier 4 (with a warning). An attestation that merely exists is shown but not counted: tier 1 needs real verification (deferred).
6. Move the file to `~/.local/share/bjail/apps/<name>/app.AppImage`, extract it to `apps/<name>/root/` (see Extraction), record the source hash in `apps/<name>/root.sha256`, and write the manifest (with `owner_id`) last. If extraction fails, nothing is kept. Defaults: audio and gpu on, network and portals off, Wayland.
- Verified in the qemu guest on 2026-10-17 (real downloads, user-approved): `AppImage/appimagetool` (14.4 MiB, digest, tier 3), `AppImage/AppImageKit` obsolete-appimagetool (2.1 MiB, no digest, tier 4 with warning), `hluk/CopyQ` (43.9 MiB, digest, tier 3). Stored sha256 equals an independent `sha256sum`; the staging directory is empty afterwards. A 2 KB cli/cli text asset also confirmed that a wrong announced size and a non-GitHub URL are refused inside the jail. None of the three had a GitHub attestation.
- Observations: appimagetool's release tag is the rolling `continuous`, so `update` must compare `sha256`/`published_at`, never the tag alone. Assets of a renamed repo live under the new canonical name, so release lookup must use `RepoInfo.full_name` (as `add` does). No "hello world" AppImage release exists on GitHub; appimagetool is the small test fixture.
- Known limitation: `--share-net` shares the host network namespace, so the download jail can reach localhost and LAN services. Only our own fetcher runs there and it connects solely to the URL chain above, but a per-jail network (pasta/slirp4netns) would be stricter. Extraction and runtime jails use `--unshare-net`.

## Runtime jail: implemented (`bjail/jail.py` `runtime_args`, `bjail/runner.py`)
`bin/bjail run <name> [-- app args]`.
- Before every launch: the stored AppImage must hash to the pinned `sha256` (otherwise "refusing to run"); the extracted tree is reused only if `root.sha256` matches, else it is re-extracted.
- Jail: `--unshare-all` (no network unless `network`), `--die-with-parent --new-session --cap-drop ALL --clearenv --hostname bjail`, host system dirs read-only, root remounted read-only, tmpfs `/tmp` and `/run`, `/proc`, minimal `/dev`. The extracted tree is `/app` (read-only); a persistent private home `apps/<name>/home` is `/home/app`. Generated `/etc/passwd` and `/etc/group` hide host users; only fonts, ld.so, localtime and alternatives are taken from the host `/etc` (plus hosts/nsswitch/resolv/ssl when `network`).
- Wayland: the host socket is bound read-only as `$XDG_RUNTIME_DIR/wayland-0`; nothing else from the runtime dir is visible. No X11 socket. Audio: PipeWire and Pulse sockets only when `audio`. GPU: `/dev/dri`, `/dev/nvidia*` and the read-only `/sys` and Vulkan/GLVND data only when `gpu`. `dirs`: bound read-only or read-write (`~/` maps into `/home/app/`); missing directories are errors; directories that are, contain or sit inside bjail's own data/config are refused.
- Environment: a fixed whitelist (HOME, PATH, LANG, TZ, XDG_RUNTIME_DIR, WAYLAND_DISPLAY, toolkit hints, `APPDIR=/app`); no host variables leak.
- Permissions bjail cannot enforce yet are refused, never ignored: `display = "xwayland"`, `portals = true`, a non-empty `dbus_filter`.
- Not done: seccomp filter; blocking nested user namespaces (Electron/Chromium sandboxes need them).
- GPU: the Debian *cloud* kernel has no DRM drivers, so the first guest had no `/dev/dri`. Fixed by `tests/vm/provision.sh`: it installs the regular `linux-image-amd64`, removes the cloud kernel, and `start.sh` adds a `virtio-gpu-pci` device, giving `/dev/dri/card0`, `card1` and `renderD128`. The test `test_gpu_nodes_only_when_granted` opens the render node inside the jail with `gpu = true` and shows that `/dev/dri` is absent with `gpu = false`. Supplementary groups (`render`, `video`) survive in the jail, so group-owned nodes stay usable. This proves the device plumbing only; the guest renders with Mesa software drivers, not real hardware.
- Verified in the guest: all isolation properties by test (private home, host files invisible, no capabilities, own PID namespace, loopback-only network, only the granted sockets and directories, environment whitelist, tamper refusal) and a real Wayland client (`weston-simple-shm`) connecting to a headless weston from inside the jail. appimagetool and AppImageKit run end to end through `bjail run`. CopyQ cannot run in the Debian 13 guest, with or without the jail: it needs glibc 2.43 and Debian 13 has 2.41 (the previous release v16 is as new). AppImages use the host libc, so this is a limit of the guest, not of bjail. The GUI test app is therefore `skyjake/lagrange` (SDL, 11 MB): `tests/test_e2e.py` adds it for real, runs it inside the jail against a headless weston, and checks that its settings land in the private home and nothing reaches the real home.

## Directory access and file isolation
Files are isolated by default. The app sees: the host system directories (`/usr`, `/lib*`, `/bin`, `/sbin`) read-only, its own extracted tree (`/app`, read-only), a private writable home (`/home/app`, stored under `~/.local/share/bjail/apps/<name>/home`), and empty tmpfs `/tmp` and `/run`. It does not see the real home, Documents, Downloads, other apps, bjail's own data or manifests, or any host file that was not granted.

An app can be given specific directories, never the whole home:
- In the manifest: `permissions.dirs = ["~/Documents/notes", "~/Pictures:rw"]`. `~/x` appears as `/home/app/x`; absolute paths outside the home appear at the same path. Read-only unless `:rw`.
- `bjail add owner/repo --dir PATH[:ro|:rw]` (repeatable) writes the grant into the manifest. The path must exist, is normalised (relative paths against the current directory, home becomes `~/`), and is checked before any network access.
- `bjail run NAME --dir PATH[:ro|:rw]` grants a directory for that run only; the manifest is unchanged and the run prints "Temporary access for this run: ...".
- Planned with the `perms` command: `bjail perms NAME --add-dir PATH[:rw]` and `--rm-dir PATH`.
- Refused at parse time or launch: `/`, the home directory itself or any parent of it, `..` components, bjail's own data and config trees (and parents/children of them), and missing paths. Symlinks are resolved when the jail starts, so a link cannot point a granted path elsewhere afterwards.
- Not yet designed in detail: passing a single file (`bjail run NAME --file PATH`, binding just that file), and the portal file chooser, which depends on the D-Bus work below.

## Permissions the manifest accepts but bjail does not enforce yet
`display = "xwayland"`, `portals = true` and a non-empty `dbus_filter` are valid in the schema, and `run` refuses them with an error instead of ignoring them. Silently dropping them would be worse than failing: the user would believe the app has, or lacks, an access it does not control.
- `xwayland`: an app that only speaks X11 needs an X server. Binding the host X11 socket would let it read all keystrokes and screen contents of every other X client, so the plan is a rootless Xwayland started per app inside the jail's own namespaces. Until then, Wayland-only apps work and X11-only apps do not.
- `portals`: file choosers, screenshots, opening URLs and similar services are provided by `xdg-desktop-portal` over the D-Bus session bus. The jail has no D-Bus at all today, so portals cannot work. Enabling them needs a filtered bus connection (below).
- `dbus_filter`: an allow-list of D-Bus names the app may talk to (for example `org.freedesktop.Notifications`). It is implemented by running `xdg-dbus-proxy` outside the jail and binding only the proxy socket as the session bus, with `--filter` and `--talk` rules built from the list. Requires the `xdg-dbus-proxy` package and a rule translator with tests; `portals = true` adds `--call=org.freedesktop.portal.*=*` style rules.
These three are the deferred items "Xwayland isolation, portals" in the MVP scope; D-Bus filtering is their shared prerequisite for two of them.

## Extraction (implemented in `bjail/appimage.py`, `bjail/jail.py`)
- Offset: end of the ELF runtime = `e_shoff + e_shentsize * e_shnum` (64-bit little-endian ELF only). `hsqs` there means SquashFS; `DWARFS` is rejected with a clear message; anything else is unsupported.
- Preferred path: `/usr/bin/unsquashfs -no-progress -no-xattrs -p 2 -o <offset> -d /out/root /app.AppImage` in a jail with `--unshare-all` (no network), read-only root, the AppImage bound read-only and only the work directory writable. The AppImage runtime never runs.
- Fallback (only with the user's consent, asked before the download when `unsquashfs` is missing): a private copy runs `--appimage-extract` in the same jail. Verified in the guest on appimagetool.
- Limits: the work directory is polled every 0.25 s; the jail is killed beyond 4 GiB of disk use or 500,000 entries, or after 15 minutes. After extraction the apparent size is checked as well, so sparse files cannot hide a huge tree.
- Host-side validation never follows symlinks: only regular files, directories and symlinks are allowed (fifos, sockets and devices reject the image); set-id and sticky bits are cleared; directories get owner access so the tree can always be deleted.
- Entry point: `AppRun` must resolve, through relative symlinks only, to an executable regular file inside the tree. Absolute symlinks, `..` above the root, loops and missing or non-executable targets reject the image.
- Extraction goes to `<root>.tmp` and is renamed on success. A hostile image therefore can fill only the work directory and cannot leave a partial `root`.
- Verified in the guest on the three approved AppImages: appimagetool 20 entries/36.9 MB, AppImageKit 48/15.4 MB, CopyQ 439/132.5 MB, each in under a second, `AppRun` a regular file in all three.

## Manifest (TOML, stored in the user's own git repo)
`source` (github owner/repo), `asset_pattern`, `version`, `sha256`, `evidence_tier`, `published_at`, `permissions` (network, audio, gpu, display = wayland|xwayland, dbus_filter, portals, dirs[]).

Implemented in `bjail/manifest.py` (schema 1), one file per app at `~/.config/bjail/apps/<name>.toml`:
- Top level: `schema = 1`, `name` (`[a-z0-9][a-z0-9._-]{0,63}`), `source`, `asset_pattern` (fnmatch, no `/`), `version`, `sha256` (64 lowercase hex), `evidence_tier` (1-5), `published_at` (UTC `YYYY-MM-DDTHH:MM:SSZ`).
- `[permissions]` is optional and everything defaults to denied: `network`, `audio`, `gpu`, `portals` (bool); `display` (`wayland` default, or `xwayland`); `dbus_filter` (list of D-Bus names, optional `.*` suffix); `dirs` (list of absolute or `~/` paths, optional `:ro`/`:rw`, default read-only; `/`, `~/` and `..` rejected).
- Strict: unknown keys, wrong types, control characters and bad formats are errors. The writer is deterministic and atomic, and refuses invalid manifests.

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

### `index` commands (implemented in `bjail/indexsync.py`, `bjail/jail.py` `git_args`)
- `bjail index update [--commit SHA]`: one script runs in the network-only git jail (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_ALLOW_PROTOCOL=https`, terminal prompts off; `core.hooksPath=/dev/null`, no attributes file, no submodule recursion, https only). It creates a partial clone (`--depth 1 --filter=blob:none`), sparse-checks-out only `/programs/x86_64-appimages` and `/programs/x86_64/`, and reports the commit and whether a signature header is present (not verified). `--commit` accepts only 40 lowercase hex digits (or the default `HEAD`), so no ref or option text from the user or the network reaches git.
- The host never runs git on the result. `collect` copies the list and the install scripts as plain files into a staging snapshot; a symlink, special file, unexpected directory or oversize file refuses the whole snapshot, odd file names are skipped and counted, and the list must contain apps.
- The review: commit, number of scripts, signature note, then apps added and removed, and every app whose suggested source changed. A change of owner (compared case-insensitively) is a loud warning; the same owner with another repository, or a source that appears or disappears, is listed as a source change. Nothing is pinned until the user confirms (default no). Declining or failing removes all temporary directories.
- State under `~/.local/share/bjail/index/`: `snapshots/<commit>/programs/...`, `tree` (a symlink to the current snapshot, swapped atomically), `PINNED`, `PREVIOUS`. Only the current and the previous snapshot are kept. `bjail index rollback` swaps them (so it can be undone), and `bjail index status` prints both commits.
- Measured in the guest: the fetch takes about 3 s and 42 MB of work space; a snapshot is 39 MB. Moving from the analysed commit d739e48 to the remote HEAD (220f506 at the time) showed 128 apps added, 13 removed and no owner or source changes; the remote HEAD was unsigned like the analysed commit.

## Search (implemented in `bjail/index.py`)
`bjail search KEYWORD... [--limit N] [--all]` reads the local snapshot at `~/.local/share/bjail/index/tree/` (filled by `index update`, step 5; the pinned commit is in `index/PINNED`) and prints suggestions only.
- Matching: every keyword must occur (case-insensitive) in the name or the description. Ranking: exact name, name prefix, all keywords in the name, any keyword in the name, description only; alphabetical within a rank.
- For each shown hit the install script `programs/x86_64/<name>` is read as text (256 KiB cap, regular files only, symlinks refused, `O_NOFOLLOW`) and the first `SITE=` / `SITE2=` assignments are extracted with a regex, comment lines ignored. Nothing is sourced, expanded or executed (a test plants `$(touch ...)` in a script and checks it never runs).
- A `SITE` that is `owner/repo` (or a github.com URL) becomes "source owner/repo -> bjail add owner/repo". Anything else (vendor site, shell variable, other forge) is flagged "resolve manually: ...". A `SITE2` is flagged "repackager ...".
- List lines must look like `<bullet> name : description` with a plain name, so `../x` style entries are dropped before any file name is built. All text is cleaned of escape sequences and control characters.
- Measured on AM at d739e48 in the guest: 8,140 list entries, 7,855 with a GitHub source, 284 flagged "resolve manually", 1 without any source, 63 flagged as repackager; parsing takes 0.05 s, resolving every entry 1 s, a search 0.05 s.

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
