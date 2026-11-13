# Architecture

appjail is a Python package using only the standard library (`src/appjail/`), plus the helper programs of the system
it drives (bubblewrap, `unsquashfs`, `pasta`, `xdg-dbus-proxy`, Xwayland, PipeWire, `git`, ...). This page maps the
code onto the topics of "Understanding appjail": for each concept, the mechanism, the modules that implement it, the
tests that prove it, what users see of it, and the decisions and limits that go with it. The last section shows how the
pieces depend on each other. To follow the code itself, command by command, read [Reading the source](source-tour.md).

## Layout

| Area | Modules |
|---|---|
| Command line | `cli.py` (the parser and the command table) and one `cmd_<name>.py` per command or family of commands |
| Shared install steps | `install.py` (what `add` and `update` share), `imagesrc.py` (URL and file apps), `services.py` (what `add` and `update` do to the outside world, replaceable in tests) |
| Policy, no I/O | `grants.py` (what may be granted), `valid.py` (value checks), `manifest.py` (schema, parser, writer), `permargs.py` (permission options) |
| Jails | `jail.py` (helper jails, `pasta`), `runtimejail.py` (the app jail), `seccomp.py`, `landlock.py`, `reopen.py`, `linger.py` |
| Running | `runner.py` (verify, prepare, launch), `wayland.py`, `dbusproxy.py`, `portal.py`, `audiomode.py`, `audiojail.py` |
| Acquiring | `github.py`, `fetcher.py` (runs inside the download jail), `appimage.py`, `attest.py`, `snappy.py`, `tools.py` |
| Updates and state | `updater.py`, `history.py`, `store.py` (paths, atomic writes, staging) |
| Desktop | `desktop.py`, `pngclean.py` |
| Catalog | `catalog.py`, `indexstore.py`, `index.py` |
| Text and output | `textsafe.py`, `console.py`, `errors.py` |
| Window | `gui/`: a tkinter front end that builds command lines and runs the same CLI |

## Acquisition

Explained in [Acquisition](../understand/acquisition/index.md); decisions in [Acquisition](../decisions/acquisition/index.md).

| Concept | Mechanism | Code | Tests | User surface | Decisions / limits |
|---|---|---|---|---|---|
| **AppImage** (type 2: an ELF runtime followed by a SquashFS or DwarFS image; `AppRun` entry point; runtime normally FUSE-mounts itself) | never mounted, never run on the host; type-2 check (`AI\x02`); filesystem offset from the ELF section table; extracted, `AppRun` executed | `appimage.py` | `test_appimage.py` | `add`, `tools install dwarfs` | Mounting rejected (FUSE in user namespaces); type 1 unsupported |
| **Source** (`github:`, `url:`, `file:`) | kind-prefixed `source` in the manifest; the AppImage's embedded update information is ignored | `manifest.py`, `install.py`, `imagesrc.py` | `test_cli_add*.py`, `test_manifest.py` | `add owner/repo`, `--url`, `--file` | P3; other forges deferred |
| **GitHub releases and the resolver** | REST API with injectable transport; redirects followed by hand within api.github.com; asset URL and name checks; architecture selection; `asset_pattern` | `github.py` | `test_github.py` (+ live) | `add`, `update`, `GITHUB_TOKEN` | rate limit 60/h; only GitHub |
| **Repository review / typosquatting** | owner, account id and age, stars, fork/archived/renamed shown before anything is fetched | `cmd_add.show_review` | `test_cli_add.py` | review screen of `add` | user judgement, not automated |
| **Owner pinning** | GitHub account id recorded at `add`; a different id blocks `update` (re-registered name) | `updater.blocks` | `test_cli_update.py` | update "blocked: OWNER CHANGE" | rename/transfer is a caution only |
| **Hash pinning** (SHA-256) | sha256 in the manifest; checked against GitHub's per-asset `digest`; checked before every `run` | `install.download_verified`, `runner.prepare` | `test_runner.py`, `test_e2e.py` (tamper) | `list`, `perms`, "refusing to run" | proves identity, not safety |
| **Evidence tiers** 1-5 | 1 attestation, (2 GPG, not implemented), 3 publisher digest, 4 TOFU anchored by owner id or matching `--sha256`, 5 TOFU of bytes | `install.gather_evidence`, `imagesrc.check_expected` | `test_cli_*` | `list`, `add`/`update` review | GPG deferred; never silently lowered |
| **Trust on first use** | tier 4/5 meaning; quarantine hash for tier 4 updates | `updater.record_hash` | `test_update_e2e.py` | | swapped asset without new publish time unseen without the hash download |
| **Build attestations** (Sigstore, GitHub artifact attestations, SLSA provenance) | bundles fetched by appjail (bounded Snappy), verified by the pinned `gh` in a network jail without token; certificate re-read: issuer GitHub Actions, repository URI, owner id | `attest.py`, `snappy.py`, `github.attestation_bundles` | `test_attest.py` (opt-in) | `tools install gh`, tier 1 | identity is repo + owner, not workflow/branch |
| **Pinned helper tools** | `gh`, `dwarfs`: URL, size, sha256 in source; downloaded in the network jail; re-hashed before each use; bumped by PR | `tools.py`, `bump-tools.yml` | `test_tools.py`, `test_bump_tools.py` | `tools status|install` | never fetched on its own (P2) |
| **Jailed download** | `fetcher.py` run by `/usr/bin/python3 -I` in the network-only jail; redirect policy from the caller; size cap; https only (url: http hop warned) | `fetcher.py`, `jail.download*` | `test_fetcher_url.py`, `test_jail.py` | download prompts | without pasta: host network with a warning |
| **Jailed extraction** | `unsquashfs` at the offset in a no-network jail; fallback `--appimage-extract` in the same jail with consent; limits on size, entries, time, output | `appimage.extract`, `jail.supervise` | `test_appimage.py` | extraction prompt | DwarFS via pinned tool |
| **Tree validation** | no special files, set-id bits cleared, `AppRun` resolved through relative links inside the tree, tree digest recorded and checked at launch | `appimage.check_tree`, `tree_digest` | `test_appimage.py`, tamper tests | "re-extracting" warning | |
| **Untrusted text** (terminal escape sequences, control characters) | every line through `textsafe.clean`; strict parsers with caps | `textsafe.py`, `console.py`, `catalog.py` | `test_textsafe.py`, `test_console_format.py` | all output | P1 |
| **Manifest** (TOML, schema 1, strict) | deterministic, atomic writer; refuses invalid | `manifest.py`, `valid.py` | `test_manifest.py` | `~/.config/appjail/apps/*.toml`, `perms` | |

## Isolation

Explained in [Isolation](../understand/isolation/index.md); decisions in [Isolation](../decisions/isolation/index.md).

| Concept | Mechanism | Code | Tests | User surface | Decisions / limits |
|---|---|---|---|---|---|
| **Linux namespaces** (user, mount, pid, ipc, uts, net, cgroup) and **unprivileged user namespaces** | `--unshare-all`; one jail per app and per helper step | `runtimejail._namespace_args`, `jail.common_args` | `test_runner_jail.py` | troubleshooting (AppArmor userns restriction) | needs unprivileged userns |
| **bubblewrap** | every jail is a bwrap argv built in Python; `--die-with-parent`, `--new-session`, `--cap-drop ALL`, `--clearenv`, read-only system, tmpfs `/tmp` `/run`, minimal `/dev` | `jail.py`, `runtimejail.py` | `test_jail.py`, `test_runner_jail.py` | | Firejail (setuid) and sas rejected |
| **Helper jails vs app jail** | download/attestation (network only), extraction, git, icon conversion, D-Bus proxy, audio daemons: each sees only what its step needs; all get `--disable-userns` and the seccomp filter | `jail.common_args` | `test_jail.py` | | |
| **Filesystem view** | `/app` read-only tree, private persistent home `/home/app`, generated `passwd`/`group`, minimal `/etc`, environment whitelist | `runtimejail`, `store.py` | `test_runner_jail.py` | `remove` deletes the home | |
| **Directory and file grants** | `dirs`, `run --dir/--file`, `open`; sensitive-path policy; refused `/tmp`; bound by descriptor (`--bind-fd`), reopened and compared behind pasta | `grants.py`, `runtimejail.Grants`, `reopen.py` | `test_grant_swap.py`, `test_manifest.py` | `--dir`, `--add-dir`, `--file` | bwrap ≥ 0.10 (CVE-2024-42472) |
| **seccomp** (classic BPF) | default allow; deny list as Flatpak; socket families; personality; `io_uring` ENOSYS; nested-namespace calls unless `userns`; x86-64 only | `seccomp.py` | `test_seccomp.py` | `userns` permission | arch refusal |
| **Nested user namespaces** | denied by default; `userns` for Chromium/Electron sandboxes | `seccomp`, `runtimejail` | `test_seccomp.py` | `--allow userns` | weakens isolation |
| **Landlock** | only `LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET` (ABI 6), wrapper before bwrap, not behind pasta | `landlock.py` | `test_landlock.py` | `network_host` needs it | FS/net rules not used |
| **Abstract unix sockets** | belong to the network namespace, not the filesystem; the X server's `@/tmp/.X11-unix/X0` | Landlock, pasta | `test_landlock.py` | | why `network_host` needs Landlock |
| **Integrity at launch** | image hash, tree marker and tree digest checked; manifest compared to its last history commit | `runner.prepare`, `history.modified` | tamper tests | warnings | |
| **Process lifetime** | own session; signals forwarded to the group; lifeline FIFO behind pasta; `linger` supervisor (subreaper) | `runner._wait_group`, `jail.Lifeline`, `linger.py` | `test_runner.py` | `--allow linger` | waiting always rejected |

## Desktop access

Explained in [Desktop access](../understand/desktop/index.md); decisions in [Desktop access](../decisions/desktop/index.md).

| Concept | Mechanism | Code | Tests | User surface | Decisions / limits |
|---|---|---|---|---|---|
| **Wayland** (client/compositor, registry of globals, protocols as interfaces) | the app gets a Wayland socket as its only display | `wayland.py`, `runtimejail._wayland_args` | `test_wayland.py` | `display = wayland` | |
| **Privileged Wayland protocols** (screencopy, virtual input, data-control, foreign toplevel, layer shell, ...) | registry rule: refuse privileged or unknown globals unless `full_wayland`; `PRIVILEGED` and `ALLOWED` lists | `wayland.privileged` | `test_wayland.py` (replayed registries) | `--allow full_wayland`, refusal messages | measured on nine compositors; KWin refused |
| **`wp_security_context_v1`** | restricted socket per app with engine `appjail` and app id | `wayland.RestrictedSocket` | `test_wayland.py` | | not sufficient alone (KWin, Hyprland 0.53) |
| **Compositor assessment** | measured registries and real clients; saved results drive tests | `tests/compositors/` | `test_assessment.py` | Wayland compositors page | headless only |
| **X11 and its lack of isolation** | host X socket never bound | | | | Flatpak-style X socket rejected |
| **Private Xwayland** (rootless, rootful + openbox) | Xwayland started inside the jail as a client of the app's Wayland socket | `runtimejail.xwayland_command` | `test_xwayland_e2e.py` | `display = xwayland|xwayland-rootful` | mutter only manages its own Xwayland |
| **D-Bus** (session bus, names, unique names, objects, interfaces, activation) | no bus by default | `dbusproxy.py` | `test_dbus.py` | `--dbus`, `--add-dbus` | |
| **Filtering D-Bus proxy** (`xdg-dbus-proxy`) | proxy in its own jail; `--filter`; confined known services (`--call`/`--broadcast`), others `--talk` + owner check at launch; refused names; unownable namespaces | `dbusproxy.py`, `grants.py` | `test_dbus.py`, `shared_connection.py` | `--dbus-own` | one name reaches its whole connection; owner changes after launch |
| **XDG desktop portals** (frontend, backends, permission store, document portal) | `.flatpak-info` identity written by appjail into the proxy's jail; app id `app.appjail.<name>`; safe set + opt-in interfaces; document portal per-app view; revocation | `portal.py`, `cmd_portals.py` | `test_portal.py`, `tests/portal/` | `--allow portals`, `--portal`, `portals APP` | Flatpak identity as compatibility shim; GNOME/KDE backends untested |
| **Audio servers** (PipeWire, WirePlumber, pipewire-pulse, PulseAudio protocol and its module loading) | private graph per app with pulse-tunnel nodes; module loading off; host PipeWire socket never bound; PulseAudio socket never bound | `audiojail.py`, `audiomode.py` | `test_private_audio.py`, `test_audio*.py`, `test_pulseaudio.py` | `audio`, `mic`, `audio_mode` | Pulse filter proxy rejected; device-change limits |
| **GPU** (DRM card and render nodes, NVIDIA nodes, Vulkan/GLVND data) | bound only with `gpu` | `runtimejail._gpu_args` | `test_runner_jail.py` | `--allow gpu` | off by default (driver attack surface) |
| **Camera** (V4L2 capture nodes, sysfs) | only capture nodes (`VIDIOC_QUERYCAP`) and their own sysfs directory | `runtimejail._camera_args` | `test_camera.py` | `--allow camera`, Camera portal | no per-camera choice |
| **Network namespace and pasta** | private namespace with outbound only, no host loopback; DNS forwarder; required for `network` | `jail.net_wrap` | `test_jail.py`, `test_runner_jail.py` | `--allow network` | LAN reachable; allowlisting proxy deferred |
| **Host network** | `network_host` with Landlock scope | `runner.launch` | `test_landlock.py` | `--allow network_host` | |
| **Desktop integration** (Desktop Entry spec, icon theme, MIME types) | entry generated, never copied; icon canonicalised; types opt-in; `open` binds single files | `desktop.py`, `pngclean.py`, `cmd_desktop.py`, `cmd_open.py` | `test_desktop.py`, `test_pngclean.py`, `test_open.py` | `desktop`, `open`, `--desktop` | no defaults, no URL handlers |
| **Output and consent** | Console vocabulary; stdout/stderr; prompts default No | `console.py`, `gui/` | `test_console_format.py`, `test_gui_*.py` | every command, GUI | |

## Updates

Explained in [Updates](../understand/updates/index.md); decisions in [Updates](../decisions/updates/index.md).

| Concept | Mechanism | Code | Tests | User surface | Decisions / limits |
|---|---|---|---|---|---|
| **Update channels** | stable, prerelease, pinned | `cmd_update.apply_channel` | `test_cli_update.py` | `--channel`, `--tag` | |
| **Quarantine** | candidate key; first-seen clock in `pending.json`; default 7 days | `updater.py` | `test_cli_update.py`, `test_update_e2e.py` | `--quarantine` | why a delay helps against fast compromises |
| **Blocks and cautions** | owner change, tier downgrade block; rename, archive caution | `updater.blocks/cautions` | `test_cli_update.py` | update results | no override by design |
| **URL fingerprint** | conditional + ranged requests on fixed windows | `fetcher.check`, `cmd_updateimage.py` | `test_cli_updateimage.py` | `update` of url apps, `--verify` | change detection, not integrity |
| **Atomic swap and rollback** | staging, extract, swap image/tree/markers/manifest last; restore on failure | `install.swap_in`, `store.staging` | `test_cli_update.py` | | |
| **Manifest history** | local git repo in a no-network jail; tamper evidence | `history.py` | `test_history.py` | `history`, run warning | not prevention |

## Catalog

Explained in [Catalog](../understand/catalog/index.md); decisions in [Catalog](../decisions/catalog/index.md).

| Concept | Mechanism | Code | Tests | User surface | Decisions / limits |
|---|---|---|---|---|---|
| **Catalog** (format `appjail-catalog` v1) | strict parse, capped, re-serialised; sources as data only | `catalog.py` | `test_catalog.py` | catalog format | |
| **Index sources and snapshots** | built-in appjail-db at a pinned commit; URL/file sources; current/previous, rollback | `indexstore.py`, `cmd_index.py` | `test_cmd_index.py`, `test_index_e2e.py` | `index ...` | unsigned catalog |
| **appjail-db** | builds the catalog from AM and AppImageHub, weekly, with size and shrink checks | sister project | | | conversion moved off the client |
| **Search** | ranking over every source; suggestions only | `index.py` | `test_cmd_index.py` | `search` | |

## How the pieces depend on each other

- **Provenance chain**: source (P3) → resolver → owner id → asset digest / attestation → hash pin → tier → quarantine →
  diff review → history. A weakening anywhere is a *block*, not a warning.
- **Two kinds of jail share one builder**: helper jails (`jail.common_args`) and the app jail (`runtimejail`) share the
  seccomp filter, `--disable-userns` and the read-only system; the app jail adds grants. The `--appimage-extract` fallback
  is why the extraction jail must be as tight as the app jail.
- **`network`** = network namespace + pasta + DNS forwarder + uid restore + seccomp filter as a file + `reopen.py` for
  grants + lifeline FIFO for SIGKILL. pasta closing inherited descriptors is the cause of three of these.
- **`network_host`** = host namespace → host abstract sockets reachable → Landlock abstract scope required → refused
  without ABI 6. Landlock is not applied behind pasta because pasta refuses `no_new_privs`.
- **Display**: Wayland socket → registry rule (privileged and unknown globals) → `full_wayland`; Xwayland runs *on* that
  socket, so the rule protects X11-only apps too; Landlock or the private network namespace keeps the host X server
  unreachable.
- **Desktop privilege moves to D-Bus where Wayland hides it**: GNOME and Cinnamon expose capture and input on the bus,
  so the refused D-Bus names are part of the display defence; one granted name reaches its whole connection, hence
  confined services and the owner check.
- **Portals need the D-Bus proxy and an identity**: the proxy connection is the peer the portal sees, so the identity
  file goes into the proxy's jail; xdg-desktop-portal understands only Flatpak/Snap identities, hence `.flatpak-info`.
  The same "only Flatpak clients are restricted" fact in PipeWire is why the host PipeWire socket is never bound and the
  private graph exists, and why the camera is either V4L2 nodes or the Camera portal.
- **Audio**: Pulse protocol cannot restrict by device → `mic` could not be a promise on the host socket → private graph;
  Pulse clients can load modules → module loading off in the graph; PulseAudio proper loads libraries → its socket never
  bound; fallback chooses silence over an ungranted microphone (P4).
- **Files**: grants checked by descriptor because bwrap re-resolved paths (CVE-2024-42472 class); `/tmp` refused because
  bind mounts do not stop `connect()` to sockets; the same reasoning as abstract sockets.
- **Desktop entry**: the AppImage's own `.desktop` would run outside the jail → generated entry → `open` binds one file
  → choosing the file is the consent, like the portal file chooser.
- **Catalog** is untrusted data feeding only `search`; installing is always an explicit `add`, which does its own review.
