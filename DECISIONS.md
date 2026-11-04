# appjail: decisions

Why appjail is built the way it is: features deliberately deferred, alternatives that were evaluated and rejected, design decisions, and the facts those choices rest on. How the tool behaves is in [DESIGN.md](DESIGN.md). Each entry gives the decision, the reason, and the condition for revisiting it.

## Deferred features

| Feature | Why | Revisit when |
|---|---|---|
| GPG tier (tier 2) | A signature proves a key, not its owner, so `add` would still be trust on first use for the key fingerprint. It needs a per-app fingerprint pin, a jailed `gpgv`, update rules (a key change blocks, a lost signature is a downgrade) and a source for the signature file. The attestation tier plus the quarantine hash already cover attested and unattested apps. | A wanted app signs with GPG and has no GitHub attestation. |
| Resolvers for other forges (GitLab, Codeberg/Forgejo, SourceForge, vendor sites) | Only GitHub is supported. The appjail-db catalog (built from AM and AppImageHub) lists 13 apps on GitLab or Forgejo and about 180 more whose note points to a vendor site, which `search` shows and `add` cannot install. Other forges expose release assets with sizes but not GitHub's `digest` or attestations, so apps from them would be tier 4 at best. The catalog format already carries `gitlab:`, `forgejo:` and `codeberg:` sources. | A wanted app lives only on another forge. A resolver sits behind the interface of `github.py`. |
| Other architectures | x86-64 only; see "arm64" below. | The arm64 work is resumed. |
| Allowlisting proxy for the LAN | With `network`, other hosts on the LAN stay reachable (pasta has no filtering). Attacks from an app against LAN hosts are outside the threat model; the goal is to keep apps off the user's own host services. | Host filtering for the app jail's `network` permission is wanted. |
| `mic` permission | The Pulse server cannot restrict a client by device without a portal-style filter; a separate permission would be a promise appjail cannot keep. | A portal-based audio path exists. |
| Native PipeWire audio | `audio` binds only the Pulse socket: a native PipeWire client is unrestricted and sees every node, cameras and screen casts included. Details below. | xdg-desktop-portal gains an audio portal, or WirePlumber can hide video nodes from restricted clients without a custom script. |

### Native PipeWire audio (deferred)

`audio` binds only the Pulse socket. PipeWire restricts only clients it identifies as Flatpak sandboxes through a `.flatpak-info` in the client's root (checked against PipeWire 1.4 and WirePlumber 0.5); a jailed client on `pipewire-0` is unrestricted and sees every node, cameras and screen casts included (shown by `tests/test_audio.py`). A restricted client is not enough either. Both ways to get one were tried against PipeWire 1.4.2 and WirePlumber 0.5.8 with a test video source: a `.flatpak-info` in the app jail (access `flatpak`), and a second socket marked `restricted` through `module-access`'s `access.socket` (which must keep `pipewire-0-manager` for WirePlumber). WirePlumber's default rules give such clients `r,x` on every object. That stops them changing anything, but they can still play, record, link to the camera and receive its frames. WirePlumber limits cameras per object only for the portal's own connections. A `.flatpak-info` in the app jail would also make GLib and Electron believe they run under Flatpak. **Revisit when:** xdg-desktop-portal gains an audio portal, or WirePlumber can hide video nodes from restricted clients without a custom script.

### arm64 (aarch64): evaluated, not implemented, paused

Feasible and moderate in code, expensive in verification. Scope if done: aarch64 only (armhf, riscv64 and i386 stay out; the ELF parsers accept 64-bit little-endian only).
- **Where x86-64 is hard-wired:**
  - `seccomp.py`: `AUDIT_ARCH_X86_64`, the `SYSCALLS` numbers, the x32 guard and the `platform.machine()` refusal. aarch64 uses the generic syscall table (different numbers; no `_sysctl`, `uselib`, `create_module`, `get_kernel_syms`, `query_module`, `nfsservctl`, `ioperm`, `iopl`), `AUDIT_ARCH_AARCH64 = 0xC00000B7`, no x32. The table becomes per architecture, skipping names the architecture lacks, still refusing unknown architectures. `clone` flags stay argument 0. A wrong number either leaves a hole or denies a needed call, so every name must be cross-checked against the kernel header table and probed natively.
  - `github.py` (`X86_64_TOKENS`, `OTHER_ARCH_RE`, `appimage_candidates`) and the error text in `cmd_add.py`: parametrize by host architecture; add an ELF `e_machine` check (0x3E, 0xB7) in `appimage.py`/`fetcher.py` as the backstop (also covers `add --file/--url`).
  - `tools.py`: `dwarfs` and `gh` are single x86-64 pins; `Tool` would carry per-architecture variants. Both projects publish aarch64 builds; the pins need real, user-approved downloads.
  - Catalog: AM has parallel aarch64 lists (to confirm), so appjail-db would publish one catalog per architecture and `indexstore.py` would select by host architecture, keeping a snapshot of one architecture from serving another.
  - `seccomp.py` also filters `socket`, `socketpair` and `personality`, which have other numbers on aarch64; the `io_uring` calls share theirs.
  - `landlock.py`: the Landlock system calls have the same numbers on aarch64; only its `platform.machine()` check is x86-64.
  - `runtimejail.py`/`jail.py` look architecture-neutral (to verify: the `/lib64` bind).
- **Verification cost:** an arm64 guest on an x86 host runs under TCG (5-20x slower: fine for unit tests and seccomp probes, painful for GUI e2e) and needs `qemu-system-arm` and `qemu-efi-aarch64` on the host and an arm64 Debian image. `tests/vm/*.sh` would take a `VM_ARCH`. Real arm64 AppImages need new approvals. `ubuntu-24.04-arm` is below the minimum supported system. GitHub's September 2026 announcement makes Ubuntu 26.04 generally available on x64 and arm64, so an `ubuntu-26.04-arm` runner should exist (label not checked); with it arm64 could be tested natively in CI, otherwise it would be "supported, tested in an emulated guest only", and the README must say so.
- **Staging if approved:** (1) architecture-aware core with no change on x86, unit-testable on the x86 guest; (2) arm64 guest scripts and suite under TCG; (3) arm64 helper pins and an aarch64 catalog from appjail-db; (4) one real arm64 AppImage smoke test and an arm CI job if a runner exists; (5) docs at each step.

## Planned code work

Seven items are planned. They come from an audit and a later code read; the table records what the code does now, not a design. The read was static (nothing was run), so confirm each gap with a failing test before fixing it. Order is by value for size. Each fix includes its tests and the doc lines named, in the same commit.

| # | Item | Where | Gap | Smallest fix | Tests to add | Docs | Size |
|---|---|---|---|---|---|---|---|
| 1 | Symlinked tree root in the `--appimage-extract` fallback | `appimage.extract` (check `tree.is_dir()`), `check_tree` | The image's own runtime picks the output name `squashfs-root`; if it is a symlink, `is_dir()` follows it, `check_tree` chmods the target tree (set-id cleared, modes changed), and `os.replace` moves the symlink into place, so the app's `/app` becomes a host directory that the tree hash does not notice. The other two extraction branches use a root the host creates. | `os.lstat` the root and require a real directory, in `check_tree` so all branches share it. | A fallback that leaves a symlink as root: rejected, nothing chmodded, nothing kept. | DESIGN Extraction (host-side validation) | S |
| 2 | `:rw` / `:ro` suffix in `--file` and `--dir` names | `grants.split_file_mode`, `permargs.files_from_args`, `runtimejail.file_binds`, `grants.normalize_dir` | `files_from_args` emits a bare path for read-only, which `file_binds` then re-splits: a read-only file named `x:rw` becomes `x` read-write (wrong file, mode raised). Directories have the same split, and any `:` in a directory path is mis-split by `partition(":")` (such directories cannot be granted). `open` already spells the mode out. | Always emit an explicit `:ro`/`:rw` (as `cmd_open.file_spec` does); refuse a `:` left in a directory path after the mode is stripped; say in `--help` how to name such a file. | `run --file` with a read-only file named like a suffix; a directory with `:` in its name. | README Temporary grants, DESIGN `run --file` bullet | S |
| 3 | App-name validation in `run` and `update` | `runner.prepare`/`launch`, `cmd_update.cmd_update`, `store.manifest_path`/`app_dir` | `remove`, `perms`, `history`, `open`, `portals` and `desktop` check `NAME_RE`; `run` and `update` do not, so `run ../x` resolves to `<config>/x.toml` and `<data>/x`. Limited to files that already exist and parse as a manifest, but it is an unvalidated path component. | Check `NAME_RE` at the top of both commands, or in `store.manifest_path`/`app_dir` for every caller (check for an import cycle with `manifest`). Optionally require the loaded `name` to equal the argument. | `run ../x`, `update ../x`, a leading `-`. | DESIGN Manifest (name pattern) | S |
| 4 | More D-Bus names refused | `grants.DBUS_BLOCKED`, `DBUS_NO_OWN`, `check_dbus_name` | `ca.desrt.dconf` (settings, custom keybindings that run commands), `org.gtk.vfs*` (mounts, host locations) and terminal or file-manager names are not refused. Candidates are from the read, not verified on a live desktop; each needs a reason before it is added. On the owner side `org.gtk.` and `ca.desrt.` are not in the no-own list. | Append the confirmed names and prefixes; one prefix entry covers a family. | Extend the parametrized tests in `tests/test_dbus.py`. | DESIGN D-Bus (refused names, owner namespaces) | S |
| 5 | Unbounded output buffering in `jail.supervise` | `jail.supervise` (`communicate` on `PIPE`s, `text=True`) | The full stdout and stderr of a jailed process are held in memory until it ends; only the output directory is size-limited. A hostile image can print gigabytes within the timeout. Callers use a few hundred characters. Strict text decoding can also raise on invalid UTF-8 (not verified). | Drain both pipes with a bounded reader that keeps the first and last few KiB and kills past a cap; decode with `errors="replace"`. | A process that prints more than the cap; invalid UTF-8. | DESIGN Extraction limits (add output cap) | M |
| 6 | Symlinks in files being opened (TOCTOU) | `runtimejail.file_binds` (called twice per launch), `dir_binds`, `permargs.files_from_args`, `cmd_open` | The path is resolved and checked, then bwrap binds the path, not a file descriptor; a same-user process, or an app with a writable directory grant, can swap a component for a symlink in between. Low severity: the attacker already runs as the user or holds a writable grant. | Compare `(st_dev, st_ino)` just before exec at least; better, open `O_PATH\|O_NOFOLLOW` and bind `/proc/self/fd/N` through `pass_fds`. | A swap between check and launch (needs a controllable hook). | DESIGN sensitive paths, `run --file`, `open` | M |
| 7 | `camera` device permission | `manifest.BOOL_PERMS`/`PERM_KEYS`/`Permissions`/writer, `permargs.permissions_from_args`, `runtimejail` (new `_camera_args` like `_gpu_args`), `cmd_apps.RISKY_GRANTS`, GUI (automatic via `PERMISSION_FLAGS`) | Not implemented. PipeWire cannot offer cameras safely (see "Native PipeWire audio"), so a device bind is the only workable path. | Boolean `camera`, default off, written only when true, binding `/dev/video*` and `/dev/media*`; a warning like other risky grants. | Manifest round trip, runner bind gated on the grant, `perms --allow/--deny`, `STATE` in `tests/test_gui_argv.py`; `tests/test_audio.py` must still show the camera unreachable over Pulse. | README permission table, DESIGN (`add --allow`, booleans, `perms`, a Camera bullet), CLAUDE open items | L |

Open questions for item 7: whether `/dev/media*` (the media controller, many ioctls, a larger kernel surface than capture nodes) belongs in the same permission or needs its own; whether sysfs (`/sys/class/video4linux`) is needed for enumeration; whether seccomp lets the V4L2 ioctls through (not checked); and a check with a real device in the guest. A manifest with `camera = true` is refused by older appjail versions (strict keys), which is acceptable.

Item 1 is stronger than the "low" label it carried: the image's code, running in the jail, controls where a host-side chmod lands. Do it first.

## Rejected alternatives

Approaches that were evaluated and not taken, with the reason.

### Building on `sas` (Samueru-sama/simple-appimage-sandbox)

A POSIX shell wrapper around bwrap (952 lines when evaluated; the current release, 2.4, makes FUSE optional with `--allow-fuse` and otherwise extracts and runs, which was not re-evaluated). Rejected as a base: it is shell (the project is Python), its defaults are permissive (D-Bus, network, audio, X11 and Wayland sockets all on; `/tmp` and `/etc` shared; `/dev` fully bound; a host `xdg-open` daemon), it mounted with FUSE instead of extracting, and it is a moving external dependency. Taken as reference only: `--unshare-user/pid/uts/ipc/cgroup`, `--die-with-parent`, `--new-session`, GPU binds including nvidia nodes. AM also supports `aisap`, not evaluated.

### Flatpak

Mature sandbox, portals, signed OSTree remotes and permission overrides; covers the need when the app exists on Flathub. It does not cover AppImages released only on GitHub, user-pinned per-release hashes with a quarantine, or declarative manifests in the user's own git repo. appjail targets that gap and does not replace Flatpak: prefer Flatpak when the app is there. appjail writes a `.flatpak-info` identity file only because xdg-desktop-portal understands no other sandbox identity (see DESIGN.md, Portals).

### Firejail (netblue30/firejail)

A setuid-root C program under GPL-2.0 with 900+ maintainer-written profiles. Not a base and not a dependency: it needs setuid root (appjail runs unprivileged bubblewrap), its profiles are implicitly trusted text rather than pinned declarative manifests, and GPL-2.0 rules out copying code or profile text into this MPL-2.0 project. Only ideas were taken, written from scratch: its denylist categories were the checklist for the `dirs` sensitive-path policy; it strips token variables from the environment (appjail clears the whole environment and passes a whitelist); its `--x11` defaults to Xephyr and it dropped Xpra, which supports a separate X server inside the jail, never the host X11 socket.

### A private network namespace built without pasta

Would have needed a host-side CONNECT proxy with a host allowlist on a unix socket plus an in-jail TCP relay for `git` and `gh`, which speak no HTTP proxy over unix sockets: new code on the path of every download. Superseded: pasta (package `passt`) gives a private namespace with ordinary outbound sockets and is an optional dependency, required only for apps with `network`.

### Related projects compared in the README (November 2026)

The README's "Alternatives and related projects" section was written from each project's GitHub page and website, read in November 2026; commit dates are not shown on those pages, so activity claims are limited to what a release page or search listing showed. None of these was installed or run. Not evaluated as a base, only compared:
- **AppManager (kem-a/AppManager)**, Vala/GTK, GPL-3.0: per-app private home and bubblewrap sandbox with `xdg-dbus-proxy`; the closest in spirit. A GUI over files the user already has; no pinned releases, quarantine or declarative manifests found. Vala and GPL-3.0 rule out reuse here.
- **Soar (pkgforge/soar)**, Rust, MIT: package manager with signature and checksum checks and GitHub/GitLab/Forgejo release tracking; release notes mention Landlock sandboxing, but the configuration reference has no sandbox key and no update delay was found. Re-read its docs before claiming more.
- **Bubblejail (igo95862/bubblejail)**, Python, GPL-3.0-or-later: bubblewrap profiles and a GUI for any desktop app; not AppImage-specific and does not fetch or pin anything.
- **ubi** has `--min-age-days`, the only quarantine-like feature found among the release installers; **eget** verifies a published `.sha256`.
- **Flatpak**: the sandbox and portal claims in the README come from the entry above, not from flatpak.org, whose front page does not describe them.
- FreeBSD **AppJail** (DtxdF/AppJail, BSD-3-Clause) shares only the name.

## Design decisions

Choices that shape the design, with the reason and, where one exists, the condition for revisiting.

### Mounting AppImages

FUSE mounts do not work well in user namespaces. Images are extracted and `AppRun` is executed.

### Landlock: only the abstract-socket scope

An unprivileged kernel filesystem and network filter. appjail uses exactly one part of it: `LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET` (ABI 6, Linux 6.12) on every app jail not behind pasta, applied by a small exec wrapper in front of bwrap (`landlock.py`, raw system calls like the seccomp filter, since bwrap cannot apply Landlock; a wrapper rather than a `preexec_fn`, which is unsafe in a launcher with threads). Behind pasta it is not needed, since pasta's private namespace isolates abstract sockets, and not possible: pasta refuses to start its command under the `no_new_privs` Landlock requires of an unprivileged process. The reason is `network_host`: an app with it shares the host's network namespace, and abstract unix sockets belong to that namespace, not to the filesystem, so the mount namespace does not hide them. The X server's `@/tmp/.X11-unix/X0` is the dangerous one: desktops commonly let any process of the user connect, which means keystrokes and input injection into every X11 app. On a kernel without ABI 6 an app with `network_host` is refused; the other apps still run, since their private network namespace already isolates abstract sockets.
- Not used: filesystem rules (the mount namespace already does that) and network rules, which cover only TCP bind and connect by port (no UDP, DNS or host names), so they add nothing for the download jails and would break apps that need other ports. Signal scoping adds nothing either: the jail has its own pid namespace.
- **Revisit when:** a network jail starts running third-party code, a bwrap release gains Landlock support, or an allowlisting proxy is wanted.

### A graphical front end

`appjail-gui` is a tkinter window over the CLI, shipped in the same package. tkinter is in the standard library, so `dependencies` stays empty, but Debian and Ubuntu split it into `python3-tk`; the GUI is therefore optional and imported lazily, and the CLI never needs it. A toolkit from PyPI (Qt, GTK bindings) would break the stdlib-only rule. The GUI does not reimplement any command: it builds an argv, runs `cli.main` with a console that shows prompts as dialogs, and so keeps one parser, one set of checks and the same reviews. The one exception is read-only data for lists: the Apps tab reads the manifests and the Search tab reads the catalogs directly (`gui/apps.py`), so rows can be selected; installing still goes through `add`. It never passes `--yes` for the user; `perms`, `remove`, `update` and the rest ask through a dialog that defaults to No. Revisit when a command needs progress or cancellation that a worker thread cannot give (downloads run in a jail subprocess with no incremental output).

### Output layout and the error stream

- **Decided:** one small vocabulary in `Console` (`kv`, `table`, `item`, `note`, `warn`, `error`) instead of hand-padded strings in each command; errors on stderr, everything else on stdout; `list` is a table and the permissions move to `list -l`.
- **Why:** `list` put every field of an app on one line, and four label styles made the other commands hard to scan. stderr for errors lets a pipe or script see only results. The permissions moved out of the default view because they are what made the line long; `perms APP` and `list -l` show them.
- **Rejected:** a third-party formatting library (stdlib-only rule); `--json` on the commands that change something (their output is a conversation with prompts; a script has `--yes` where it is allowed); always-on colour (breaks pipes and log files).
- **Cost:** tests and any script that matched the old text (`WARNING:`, `Label : value`, `Summary:`) had to change; the GUI shows the same text in its output pane.

### Nothing is granted by default, display `none`

- **Decided:** `add` grants nothing beyond the window: `audio` and `gpu` are `--allow` like the rest (`--no-audio` and `--no-gpu` are gone), and `display = none` is a fourth display value for apps with no window. `wayland` stays the default, since most AppImages are graphical.
- **Why:** audio is the one grant appjail cannot scope (the Pulse server cannot restrict a client by device, so it includes the microphone and the sound other apps play), and the GPU is a large driver attack surface plus hardware information in `/sys`. Most command-line tools, converters and editors need neither. An app that needs them fails visibly (no sound, slow rendering) and `perms APP --allow audio` fixes it, which is the cheaper mistake than a silent microphone grant. The docs said "everything is denied by default" while `Permissions()` denied and `add` granted; both now agree.
- **Cost:** installing a media app or an Electron app takes one more flag (the GUI Add form has the checkboxes unticked). Apps already installed keep their manifests, which record `audio` and `gpu` explicitly.
- **Rejected:** lowering the defaults from the AppImage's own `.desktop` (`Terminal=true`): possible later, since untrusted data may only reduce permissions, but not needed now; a headless `display` inferred automatically (the mode is always chosen by the user, like Xwayland).
- **Revisit when:** a safe way to scope the microphone exists (a portal-based audio path, see Native PipeWire audio).

### Waiting for every process in the jail, by default

The jail ends with its main command; the `linger` permission (opt-in per app) waits for all processes instead. Waiting always was rejected: an app that leaves a crash handler, `dbus-daemon` or an agent behind would keep `appjail run` from ever returning, and "closing the app closes everything" would no longer hold. Found with VSCodium, whose launcher hook runs `cli.js`, which starts the editor detached and exits. **Revisit when:** most catalog apps need `linger`, or a reliable way to tell the app's own processes from helpers exists.

### X11-only apps on GNOME: rootful Xwayland with openbox

A rootless Xwayland needs the compositor to be the X window manager. mutter does that only for the Xwayland it spawns, so on GNOME the windows of the private rootless Xwayland are mapped in the X server and never presented (found with `xeyes`, Java/AWT apps). `display = "xwayland-rootful"` drops `-rootless`: Xwayland makes one window of its own, and a small `openbox` in the jail provides stacking, focus and the cursor that plain rootful lacks. It is a separate `display` value, not an automatic fallback: the choice stays visible in the manifest, and the rootless mode stays for compositors where it shows several real windows. `openbox` over `matchbox` for the familiar behaviour with several windows. Rejected: binding the session's X socket as Flatpak does (every X client could then read the others' keystrokes and screen, and it needs a per-app cookie and a Landlock exemption); a nested kiosk compositor (`cage`; one more dependency with GPU and input quirks for the same result); Xpra (a client on the host, two moving parts). Native Wayland remains the better route for apps whose toolkit has it (Java: `-Dawt.toolkit.name=WLToolkit` where the JDK has it).

### Catalog built by appjail-db, not on the user's machine

- **Decided:** the built-in `appjail-db` source downloads `catalog.json` from `alberto743/appjail-db` at a commit resolved through the GitHub API. The conversion (sparse git fetch of AM, parsing the install scripts (8,735 at the analysed commit), merging the AppImageHub `feed.json`) lives in appjail-db and runs weekly in CI.
- **Why:** the client no longer needs a network git jail, a 39 MB fetch or a parser of untrusted shell text; one build point carries the size and shrink checks (fewer than 5,000 apps or a drop of more than 10% is refused) and records owner changes in its history; the update is a 1.5 MB text download. The commit pin makes every catalog traceable and an older one re-fetchable (`--commit`).
- **Rejected:** converting AM on the client (the previous design), and an unpinned raw URL (no way to say which state was reviewed, and a failed API lookup would silently skip the pin).
- **Cost:** appjail-db becomes a dependency of `search` (not of installs); the catalog is unsigned, so its integrity rests on HTTPS and on who can write to appjail-db.
- **Revisit when:** appjail-db is unmaintained (any other catalog works with `index add`), or catalog signing becomes worthwhile (a signature by a key pinned in appjail).

## Facts the design rests on

### GitHub API

- Release assets have a `digest` field (`sha256:<64 hex>` or null). Older releases may lack it, hence tier 4 (trust on first use) as the fallback.
- Attestations: `GET /users/{u}/attestations/{digest}` and the `orgs/` variant need a token. The repo-scoped `GET /repos/{owner}/{repo}/attestations/{digest}` works unauthenticated and returns `attestations[]` with `bundle_url` (a short-lived signed blob URL). appjail uses the repo-scoped endpoint with the digest from the release asset. Existence alone is not proof; the bundle is verified (DESIGN.md, Attestation verification).
- The unauthenticated rate limit is 60 requests per hour per address; `GET /rate_limit` is free. One `add` costs about 4 requests, one `update` about 4, one `index update` of the built-in source 1.

### AM index (ivan-hc/AM)

Analysis done for appjail-db, which now converts AM; appjail itself no longer reads AM. Not to be redone.
- `AppMan/appman` is a stub that downloads `APP-MANAGER` from `main`; AM self-updates and runs install and updater scripts from `main` outside any sandbox. Only 6 of 8,735 install scripts mention a checksum or signature (counts at the analysed commit; AM's own release notes later count about 3,600 unique apps, so recount before quoting). Its own sandbox wraps `sas` or `aisap`.
- `programs/x86_64-appimages` has lines `◆ name : description` (U+25C6); `programs/x86_64/<app>` holds the scripts. 8,247 scripts have `SITE="owner/repo"`, about 224 point elsewhere, a few use `SITE2=` for a repackager. `SITE=` may appear more than once in a script: the first assignment counts, matched by regex, never sourced.
- Commit signatures (last 200 commits at the analysed state): 139 carry a PGP signature (GitHub web-flow key), 2 SSH, 59 unsigned; the maintainer's own commits are unsigned. They cannot prove maintainer authenticity. Not to be redone.
- Reference clone for reading: a blobless no-checkout clone, read with `git show <commit>:<path>` as text. Existing sandbox flags are in `modules/install.am`.

## Platform and CI

- Minimum supported systems: Debian 13 and Ubuntu 26.04. On Ubuntu 24.04 the real-portal tests fail (xdg-desktop-portal 1.18 does not export `FileChooser` with the tests' fake backend; cause not investigated) and its `reuse` cannot read `REUSE.toml`. No workarounds for older systems.
- The CI runner label is `ubuntu-26.04`, not `ubuntu-latest` (still Ubuntu 24.04 when tried). GitHub's changelog (2026-09-17) schedules the move of `ubuntu-latest` to 26.04 between 2026-10-19 and 2026-11-19; once it is complete (planned for December 2026), switch the workflows to `ubuntu-latest` and check CI is green.
- Actions are pinned to the full commit SHA with a trailing `# vX.Y.Z` comment: a tag can be moved, a SHA cannot. Dependabot's github-actions ecosystem reads the comment and updates SHA and comment together. For an annotated tag, pin the commit it points to (`git ls-remote ... tag^{}`).
