# Namespaces

*Part of [Isolation](index.md). Next: [bubblewrap](bubblewrap.md), the program that creates them.*

## What they are

A Linux **namespace** wraps one kind of global resource so that the processes inside it get their own instance of it.
Processes in a new mount namespace have their own table of mounted filesystems; processes in a new PID namespace have
their own numbering of processes and see only each other; and so on. A namespace does not copy anything: it changes
what a name (a path, a process id, a network interface, a user id) refers to for the processes inside.

The kernel has eight kinds:

| Namespace | Isolates | In the app jail |
|---|---|---|
| mount | the tree of mounted filesystems | always new: the app's file view is built from nothing (see [the filesystem view](filesystem.md)) |
| PID | process ids | always new: the app sees only its own processes and cannot signal or trace yours |
| user | user and group ids, and the capabilities that go with them | always new: what makes the rest possible without root |
| network | interfaces, routes, ports, and abstract unix sockets | new unless the app has `network_host` |
| UTS | host name and domain name | always new: the host name is `appjail` |
| IPC | System V IPC and POSIX message queues | always new |
| cgroup | the view of the control-group tree | always new |
| time | the boot and monotonic clocks | not used |

Namespaces are inherited: every process the app starts lives in the same namespaces, and leaving them requires
privileges the app does not have.

## Why it matters

Without namespaces, isolation on Linux rests on file permissions and user ids, and an app runs as you: everything you
can open, it can open. With namespaces, the question "may this process open `~/.ssh/id_ed25519`?" becomes "does that
path exist in its world?", and for an app in a jail it does not. The same holds for the other kinds: a process in its
own PID namespace cannot name your browser's process to send it a signal; a process in its own network namespace with
no interface but loopback cannot open a connection at all.

## How appjail uses it

Every jail unshares all the namespaces bubblewrap offers: those of the table above but time, and the network one only
when the app has no `network_host`. Two of them need more
explanation: the user namespace, which makes the rest possible, and the nested ones an app might create.

### User namespaces, and why appjail needs them unprivileged

Creating most namespaces normally needs the `CAP_SYS_ADMIN` capability, which ordinary users do not have. The **user
namespace** is the exception: since Linux 3.8 an ordinary user can create one, and inside it the process holds a full
set of capabilities *over the resources of that namespace only*. That is enough to create the other namespaces and to
build a private mount table, but not to touch anything owned outside it. This is what lets appjail, bubblewrap and
Flatpak work without root or a set-uid helper.

The same feature exposes code paths of the kernel that were once reachable only by root, and several privilege
escalations have gone through them. Some distributions therefore restrict it: Ubuntu, since 23.10, lets only programs
with an AppArmor profile that allows it create user namespaces (`kernel.apparmor_restrict_unprivileged_userns`).
appjail needs unprivileged user namespaces; where they are restricted, bubblewrap fails with `Operation not permitted`
or `setting up uid map: Permission denied`. Relaxing the restriction, or giving bubblewrap its own AppArmor profile,
changes a protection of the whole system, and is your decision.

Inside the jail, appjail maps the app to your own user and group id, so files it writes in its home and in folders you
grant belong to you, and drops every capability (`--cap-drop ALL`): the app holds no privilege even over its own
namespace. The jail's `/etc/passwd` and `/etc/group` are generated and list only `root` and the app's user `app`, so the
names of the other accounts on the machine are not visible either.

### Nested user namespaces

A process in a user namespace may normally create a further one inside it, and with it new mount and network
namespaces of its own. appjail forbids that by default, in two ways: bubblewrap's `--disable-userns` stops the processes in the jail from
creating further user namespaces, and the [seccomp filter](seccomp.md) refuses the system
calls that create or join namespaces (`unshare`, `setns`, `clone` with any of the "new namespace" flags) and the mount
API. Nested namespaces are where much of the kernel's privilege-escalation history begins, and an app has no need for
them unless it builds a sandbox of its own.

Some apps do: Chromium and every Electron app isolate their renderer processes in namespaces, and an app that runs
`bwrap` itself needs them too. For those, the `userns` permission lifts exactly this restriction and nothing else.
Without it, such apps fail to set up their own sandbox, and depending on the app they refuse to start or start
without it; with it, the jail is weaker against kernel bugs.

## Connections

- [bubblewrap](bubblewrap.md) creates the namespaces and fills the mount namespace.
- [The filesystem view](filesystem.md) is what the mount namespace contains.
- The network namespace is what the `network` permission works with: an app with `network` runs in a separate
  namespace made by `pasta`, which gives it the internet but not your machine's own services. With `network_host` it
  shares yours, and [Landlock](landlock.md) closes the one door that opens.
- [seccomp](seccomp.md) refuses the system calls that would create nested namespaces.
- [Process lifetime](lifetime.md): the PID namespace's first process is what keeps the jail alive.
- Decision: [bubblewrap, not Firejail or sas](../../decisions/isolation/bubblewrap.md).

## Limits

- All namespaces share one kernel. A kernel bug reachable from inside the jail can break out of all of them at once;
  seccomp and the refusal of nested namespaces reduce how much of the kernel is reachable, not whether it is.
- The time namespace is not used: the app sees the real clocks, which are not a secret.
- An app with `userns` can create namespaces of its own inside the jail. It cannot leave the jail through them, but it
  reaches more kernel code.

## References

- Linux manual pages: [namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html),
  [user_namespaces(7)](https://man7.org/linux/man-pages/man7/user_namespaces.7.html),
  [mount_namespaces(7)](https://man7.org/linux/man-pages/man7/mount_namespaces.7.html),
  [pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html),
  [network_namespaces(7)](https://man7.org/linux/man-pages/man7/network_namespaces.7.html),
  [uts_namespaces(7)](https://man7.org/linux/man-pages/man7/uts_namespaces.7.html),
  [ipc_namespaces(7)](https://man7.org/linux/man-pages/man7/ipc_namespaces.7.html),
  [cgroup_namespaces(7)](https://man7.org/linux/man-pages/man7/cgroup_namespaces.7.html),
  [capabilities(7)](https://man7.org/linux/man-pages/man7/capabilities.7.html).
- Michael Kerrisk, [Namespaces in operation, part 1: namespaces overview](https://lwn.net/Articles/531114/),
  LWN.net, 2013.
- Canonical, [Restricted unprivileged user namespaces are coming to Ubuntu 23.10](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces).
