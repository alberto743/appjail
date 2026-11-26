# Memory, CPU and process limits come from a systemd scope

*Decision on [isolation](index.md).*

**Context.** The jail confines what an app can reach, not how much it uses. An app can fill memory, keep every CPU busy
or start processes until the host stops answering. Flatpak runs each instance in a systemd scope
(`app-flatpak-ID-INSTANCE.scope`), where the session's resource control and `systemd-oomd` apply, and sets no limit of
its own either ([compared](../project/flatpak-comparison.md)). Measured in the test guests (Debian 13, Ubuntu 26.04,
Fedora 45): the systemd user manager runs and delegates the `cpu`, `memory` and `pids` controllers to the user, so an
unprivileged `systemd-run --user --scope` can set the limits that follow.

**Options.** Leave it; `setrlimit` limits set before the jail starts; a systemd user scope around the launch; both.

**Decision.** Three optional permissions, off by default and recorded in the manifest like the others, written in
systemd's own syntax:

| Key | Systemd property | Value |
|---|---|---|
| `memory_max` | `MemoryMax` (and `MemorySwapMax=0`) | bytes with a `K`, `M`, `G` or `T` suffix, or a percentage of the host's memory |
| `cpu_quota` | `CPUQuota` | a percentage of one CPU, which may exceed 100% |
| `tasks_max` | `TasksMax` | a number of processes and threads, or a percentage |

appjail validates the value against that syntax and passes it to `systemd-run --user --scope`, which starts the launch
(`pasta` when the app has `network`, otherwise `bwrap`). With any key set the scope also carries `OOMPolicy=kill`.
Without a key nothing changes: no scope, no extra process. Only the app's own jail is limited; the helper jails
(downloads, extraction, audio, the D-Bus proxy) are not.

- **The mechanism enforces what it says, on all three guests.** `MemoryMax=64M` stopped a process that allocated without
  end; `CPUQuota=20%` gave 0.20 seconds of CPU per second for a busy loop; `TasksMax=50` made `fork` fail with "Cannot
  fork".
- **The jail cannot undo it.** Inside it `/proc/self/cgroup` reads `0::/` and `/sys/fs/cgroup` does not exist, and
  `org.freedesktop.systemd1` is already in the refused bus names, so the app cannot create a scope or change one.
- **The scope fits appjail's process handling.** `systemd-run --scope` executes the command in place: the process
  `Popen` returns is the scope's main process, still leader of the session and process group appjail created. With
  `pasta` outermost, one `run-….scope` held `pasta`, both `bwrap` processes and the app, and `SIGTERM` sent to the
  group left nothing behind on any guest. A hog inside `pasta` and the jail was killed with nothing left over.
- **Running out of memory ends the whole app.** Exit status 137 (or 143) on Debian, Ubuntu and Fedora, no process left
  in the scope, on Fedora with `systemd-oomd` running as well. With `OOMPolicy=kill` the status was 137; without it 143
  on Debian and Fedora, the same teardown with a different status, so the policy makes the status predictable. The user
  journal names the cause ("killed by the OOM killer"), which appjail can point to when a jail ends with 137.
- **`MemorySwapMax=0`.** Otherwise the limit counts only resident memory and an app can push the rest into swap and
  slow the whole host. The limit then means what it says.
- **No user session, no limits.** Without `XDG_RUNTIME_DIR` and the session bus (a cron job, a bare `su`)
  `systemd-run --user` fails. An app with a limit then does not start, with a message that says why: a limit that is
  silently not applied is worse than none.

**Rejected.** `setrlimit` alone: `RLIMIT_AS` limits address space, not memory in use, and an app that reserves a large
range (Electron and V8 do) fails under a cap that is generous for real use (measured: a 200 MB cap stopped a 300 MB
allocation with `MemoryError`); `RLIMIT_CPU` is total CPU time, not a rate; `RLIMIT_NPROC` counts the user's processes
host-wide, not the jail's. A limit on by default: it would break apps that need what they use, and no number fits every
app (revisit after real use). `MemoryHigh`: it throttles instead of stopping, so an app that never gives memory back
only gets slower. Limiting the helper jails: they are short, fixed programs, and the app cannot reach their memory. A
systemd-only helper that moves the jail into a service: a scope is enough and keeps the process model.

**Consequences.** The three keys need a systemd user manager with the three controllers delegated, which the three
supported systems have by default; elsewhere the app refuses to start. A limit is a ceiling on the app, not a
reservation. A limit that is too low ends the app abruptly with no chance to save its work (that is what
`OOMPolicy=kill` does), so the guide says to start high. The limits do not cover files on disk, video memory or the
network; those are separate questions.
