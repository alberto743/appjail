# Resource limits

*Part of [Isolation](index.md). Previous: [Process lifetime](lifetime.md).*

## What it is

A jail decides what an app can reach, not how much it uses. The kernel can also cap use: control groups (cgroups) put
processes in a group and give the group a ceiling for memory, CPU time and number of processes. systemd manages
cgroups for your login session, and an unprivileged user can ask it for a *scope*, a group around a command that is
already running, with limits set on it.

## Why it matters

Without a limit, an app that leaks memory, spins on one CPU or forks without end slows or freezes your whole session,
whatever it was granted. The seccomp filter and the namespaces cannot help: the app asks the kernel for nothing that
is refused, it only asks for a lot.

## How appjail uses it

Three optional permissions, written in systemd's own syntax and off by default:

- `memory_max`: bytes with a `K`, `M`, `G` or `T` suffix (1024-based), or a percentage of the host's memory (`2G`,
  `50%`). With it swap is refused too (`MemorySwapMax=0`), so the limit counts everything the app holds.
- `cpu_quota`: a percentage of one CPU, which may exceed 100% (`200%` is two CPUs).
- `tasks_max`: a number of processes and threads, or a percentage of the host's limit (`512`, `20%`).

With any of them set, appjail starts the app through `systemd-run --user --scope`, with the three limits as properties
and `OOMPolicy=kill`. The scope is outermost, around `pasta` when the app has `network`, so `pasta`, the jail and every
process of the app share one cgroup. `systemd-run --scope` runs the command in place (measured: the process appjail
starts is the scope's main process, still leading the session and process group), so signals sent to the group, and the
cleanup after the app ends, work as they do without a limit. Without a limit nothing changes: no scope and no extra
process.

When the app goes over `memory_max`, the kernel's out-of-memory killer acts inside the scope and, with
`OOMPolicy=kill`, ends every process of it. appjail then returns the status 137 and the app is gone; the user journal
(`journalctl --user`) records the cause. Over `tasks_max` the app's `fork` and thread creation fail with an error, and
over `cpu_quota` the app runs slower.

Before anything else is set up appjail starts a scope for an empty command with the same properties; if systemd
refuses (no user session, no `systemd-run`, a controller that is not delegated to your user), the app does not start and
the message says how to remove the limits (`appjail perms APP --memory-max infinity`, and `--cpu-quota`, `--tasks-max`).
A limit that is silently not applied would be worse than none.

## Connections

- [Process lifetime](lifetime.md): the process group and the lifeline are what end the jail; the scope keeps both.
- [Namespaces](namespaces.md): the jail has a cgroup namespace of its own, so inside it `/proc/self/cgroup` reads
  `0::/` and no cgroup file system is mounted: the app cannot see or change its limits. `org.freedesktop.systemd1` is on
  the list of D-Bus names that are never allowed, so it cannot ask systemd for another scope either.
- Decision: [Memory, CPU and process limits come from a systemd scope](../../decisions/isolation/resource-limits.md).

## Limits

- It needs a systemd user manager with the `cpu`, `memory` and `pids` controllers delegated to your user. The three
  supported systems (Debian 13, Ubuntu 26.04, Fedora 45) have it; elsewhere an app with a limit does not start.
- A limit too low ends the app at once, with no chance to save: start high and lower it.
- The limits cover the app's jail. The helper jails (downloads, extraction, audio, the D-Bus proxy) are not limited.
- Disk space, video memory and network traffic are not limited.

## References

- systemd,
  [systemd.resource-control(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html):
  `MemoryMax=`, `MemorySwapMax=`, `CPUQuota=` and `TasksMax=`.
- systemd, [systemd.scope(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.scope.html): `OOMPolicy=`.
- systemd, [systemd-run(1)](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html): `--scope`,
  `--user`, `--collect` and `--property`.
