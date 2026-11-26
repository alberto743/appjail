# Flatpak compared

*Decision on [the project](index.md). Facts as read in Flatpak 1.18's documentation and in the `main` branch of its
source in November 2026; check them before relying on them. Flatpak was not installed or run.*

**Context.** Flatpak and appjail both confine desktop apps with bubblewrap, and appjail follows Flatpak's choices where
they fit (the [seccomp](../isolation/seccomp.md) deny list, `xdg-dbus-proxy`, the [portal
identity](../desktop/portal-identity.md)). This page records where the two differ in security and in function, so that
a gap is a known choice rather than an oversight.

**Decision.** appjail does not try to become Flatpak. It stays a provenance and containment layer for upstream
AppImages: no runtimes, no repositories, no repackaging. Gaps that fit that scope are listed as open items in [deferred
work](../deferred.md); the others are limits. Where an app is on Flathub and its published permissions suit you,
Flatpak remains the mature route.

## Where appjail is stricter

| Area | Flatpak | appjail |
|---|---|---|
| Who chooses the permissions | the packager, in the app's metadata (`finish-args`), applied at install; overrides are the user's to add | the user, one grant at a time; `add` grants only the window ([default grants](../isolation/default-grants.md)) |
| X11 | `x11` binds the host's X socket and a filtered `Xauthority`: the app is an ordinary X client of the session | the host's X socket is never bound; a private Xwayland runs inside the jail ([X11 inside the jail](../desktop/xwayland-rootful.md)) |
| Wayland | `security-context-v1` (engine `org.flatpak`); what a client may do is left to the compositor | the same protocol, plus a check of the socket's globals before launch: a privileged one refuses the app unless `full_wayland` ([Wayland](../../understand/desktop/wayland.md)) |
| Sound and microphone | `pulseaudio` binds the host's Pulse socket and `/dev/snd`: playback, capture and MIDI together | a private PipeWire graph whose capture node exists only with `mic`; the host's `pipewire-0` is never bound ([audio](../../understand/desktop/audio.md)) |
| Network | `network` shares the host's network namespace: services on the host's loopback and abstract sockets are reachable, as Flatpak's documentation states | `network` goes through `pasta`, outbound only, without the host's loopback; Landlock blocks abstract sockets, and `network_host` requires it ([network](../../understand/desktop/network.md)) |
| Session bus | filtered by default, with every portal reachable; `socket=session-bus` removes the filter | no bus unless granted; a safe set of portals, the others one by one; the names that control the desktop and the `Flatpak` and `DynamicLauncher` portals are refused ([D-Bus](../../understand/desktop/dbus.md)) |
| Home | `filesystem=home` and `host` exist; only `~/.var/app` and Flatpak's own directories are hidden | the whole home is refused, as are credential stores, browser profiles and key files; autostart and shell start-up files at most read-only ([filesystem](../../understand/isolation/filesystem.md)) |
| System calls | a deny list: 19 calls, the new mount API, `clone` with `CLONE_NEWUSER`, `TIOCSTI` and `TIOCLINUX`; `ptrace`, `perf_event_open` and any `personality` only without `devel`; `modify_ldt` only without `multiarch` | the same rules, plus `bpf`, `userfaultfd`, `process_vm_readv`/`writev`, `open_by_handle_at`, module and kexec calls, `ioperm`/`iopl` and `io_uring`; `ptrace` and one `personality` value allowed with `devel`, perf always denied; a foreign architecture kills the process ([seccomp](../../understand/isolation/seccomp.md)) |
| Namespaces and session | pid, ipc and net (unless granted), user with nested namespaces disabled; no UTS or cgroup namespace, no `--new-session`; `--die-with-parent` only with `flatpak run -p` | `--unshare-all` (UTS and cgroup too), `--new-session`, `--die-with-parent` always, the whole process group killed at the end ([lifetime](../../understand/isolation/lifetime.md)) |
| Host files shown by default | `/etc/machine-id`, the journal sockets, and with `network` the resolver and `gssproxy` sockets | none of these ([bubblewrap](../../understand/isolation/bubblewrap.md)) |
| Handling the downloaded bytes | pulled and deployed by Flatpak itself (by a root helper for system installations), protected by OSTree and GPG checks | download, extraction, attestation check and icon conversion each run in a jail of their own ([jailed steps](../../understand/acquisition/jailed-steps.md)) |
| A compromised publisher | an update goes to the tip of the branch, at once; software centres update automatically | the hash is checked at every start, the owner of the repository is pinned, a lower evidence tier is blocked and a new version waits in [quarantine](../../understand/updates/quarantine.md) |

## Where Flatpak is stronger

- **The host's system is hidden.** A runtime is mounted at `/usr`; the host's own files are reachable only through
  `host-os`, `host-etc` or `host`. appjail binds the host's `/usr`, `/lib*` and part of `/etc` read-only: an app can
  list the installed software, every host library is part of what it can reach, and its behaviour depends on the host. Narrowing
  it was studied and not adopted ([the decision](../isolation/host-view.md)).
- **Signed transport and central builds.** OSTree commits are GPG-signed per remote, and Flathub builds most apps from a
  public manifest on its own infrastructure. appjail runs the publisher's binary; GPG is a deferred tier and nothing is
  rebuilt.
- **Resource accounting.** Each instance runs in a systemd scope (`app-flatpak-ID-INSTANCE.scope`), where the session's
  resource control and `systemd-oomd` apply. appjail has the three optional limits `memory_max`, `cpu_quota` and `tasks_max`, applied through a `systemd-run --user --scope` around the launch when set ([resource limits](../isolation/resource-limits.md)); without one an app can exhaust memory or CPU.
- **Mediated hardware.** A USB portal with per-device grants, conditional permissions (`--device-if`, `--socket-if`) and
  parental controls. appjail binds no input, USB or Bluetooth device.
- **Sandboxes inside the app.** `flatpak-spawn --sandbox` gives a child a stricter sandbox without letting the app
  create namespaces. appjail's `userns` instead lifts the namespace and mount rules for the whole app.
- **Maturity.** Flatpak is widely used and reviewed, with a security process and advisories. appjail has had no external
  review.

## Functions Flatpak has and appjail does not

- Runtimes, SDKs and extensions (GL drivers, codecs, translations), deltas and deduplicated storage, OCI bundles,
  side-loading.
- i386 multiarch and aarch64; appjail is x86-64 only ([platform](platform.md)).
- System-wide installations, and any number of remotes; appjail is per user, with GitHub, URL and file sources.
- `flatpak ps`, `kill` and `enter` for running instances.
- Input, USB, KVM and Bluetooth devices; `ssh-auth`, `gpg-agent`, `pcsc` and `cups` sockets.
- The accessibility bus, through a filtered proxy on by default: screen readers work. appjail gives the same filtered
  bus only with the `accessibility` permission ([the decision](../desktop/a11y-bus.md)).
- URL handlers from the app's menu entry (file types are offered with `desktop --mime`); a working Background portal
  (appjail's autostart entries say `flatpak run`); software centres and permission editors; the permission store's
  command line.
- `--persist`, file forwarding, conditional permissions, a `devel` mode for profilers (appjail's `devel` is for debuggers and tracers: no `perf_event_open`).
- Masking and pinning updates, `repair`, end-of-life notices for runtimes.

Some exist in both under another shape: `flatpak override` and `perms`, `--filesystem` and `dirs`, `--talk-name` and
`dbus_filter`, `flatpak history` and the manifest history. appjail's own additions have no Flatpak equivalent: evidence
tiers, build attestations, owner pinning, quarantine, the check of the image and the extracted tree before every start,
the Wayland check, refused credential paths, a network without the host's loopback, a microphone granted apart from
sound, and AppImages run as published.

**Consequences.** The gaps that fit appjail's scope were built: the accessibility bus (opt-in, `accessibility`),
resource limits, file-type handlers and a debugging opt-in; a narrower view of the host's system was studied and not
adopted ([the decision](../isolation/host-view.md)). Runtimes, repositories, system-wide installs and raw device access are not planned. Re-check this page with the
[related projects](related-projects.md) at each minor release.

## References

- Flatpak documentation: [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html),
  [Basic concepts](https://docs.flatpak.org/en/latest/basic-concepts.html),
  [Under the hood](https://docs.flatpak.org/en/latest/under-the-hood.html),
  [Command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html),
  [Portals](https://docs.flatpak.org/en/latest/portals.html).
- Flatpak source, `main` branch:
  [flatpak-run.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run.c) (`flatpak_run_setup_base_argv`,
  `setup_seccomp`, `flatpak_run_in_transient_unit`),
  [flatpak-context.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-context.c),
  [flatpak-exports.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-exports.c),
  [flatpak-run-x11.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-x11.c),
  [flatpak-run-wayland.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-wayland.c),
  [flatpak-run-pulseaudio.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-pulseaudio.c),
  [flatpak-run-dbus.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-dbus.c),
  [flatpak-run-sockets.c](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run-sockets.c).
