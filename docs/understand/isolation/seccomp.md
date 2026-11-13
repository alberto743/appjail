# seccomp

*Part of [Isolation](index.md). Previous: [the filesystem view](filesystem.md). Next: [Landlock](landlock.md).*

## What it is

Every request a program makes to the kernel (open a file, create a socket, start a process, map memory) is a
**system call**. **seccomp** (secure computing mode) lets a process install a filter that the kernel runs on each of its
system calls before carrying it out. The filter is a small program in classic BPF, a minimal instruction set the
kernel can check and run safely; it sees the number of the call, the processor architecture and the call's arguments
(as numbers, not the memory they point to), and returns a verdict: allow, fail with a chosen error code, or kill the
process. A filter is inherited by every child process and can never be removed, only made stricter.

## Why it matters

[Namespaces](namespaces.md) change what a process can see, not what the kernel will do for it. Every system call of a
jailed app still reaches the same kernel as the rest of your session, and most kernel privilege escalations start from
a system call that ordinary programs rarely make: one that loads a BPF program, creates a namespace, uses
`io_uring`, or opens a socket of a family few people use. A seccomp filter removes those entry points for programs that
do not need them. It is also the only way to refuse a few operations that are harmful without any bug, such as pushing
characters into the input of a terminal.

## How appjail uses it

appjail assembles its filter in Python (`seccomp.py`), instruction by instruction, and bubblewrap loads it before
starting the app (`--seccomp`). The same filter goes into every [helper jail](index.md#helper-jails). It is a
*deny list*: every call is allowed except those below. Most rows follow the filter Flatpak applies to its apps; appjail
adds `io_uring` and, unless the app has `userns`, the refusal of nested namespaces.

| Refused | Answer | Why |
|---|---|---|
| any architecture but x86-64, and the x32 ABI | process killed / `EPERM` | a call made through another architecture's numbering would slip past a filter written for x86-64 |
| loading kernel modules, `kexec`, `reboot`, swap, quotas, `acct`, port I/O (`ioperm`, `iopl`), `syslog` | `EPERM` | administration of the machine, never the business of an app |
| `bpf`, `perf_event_open`, `userfaultfd`, `fanotify_init`, the keyring calls (`add_key`, `keyctl`, `request_key`) | `EPERM` | large kernel interfaces with a history of privilege escalations |
| `ptrace`, `process_vm_readv`, `process_vm_writev` | `EPERM` | reading and changing the memory of other processes |
| `name_to_handle_at`, `open_by_handle_at` | `EPERM` | opening files by handle, which bypasses the paths a mount namespace controls |
| memory-policy calls (`mbind`, `set_mempolicy`, `migrate_pages`, `move_pages`, ...) | `EPERM` | as in Flatpak: rarely needed, a source of bugs |
| `ioctl` with `TIOCSTI` or `TIOCLINUX` | `EPERM` | pushing characters into a terminal's input, which runs commands in the shell the app was started from (`TIOCLINUX` does the same on a virtual console: CVE-2023-28100) |
| `socket` and `socketpair` of any family other than unix, IPv4, IPv6 and netlink | `EAFNOSUPPORT` | Bluetooth, packet, vsock, TIPC, crypto (`AF_ALG`) and other families: rarely needed by desktop apps, a steady source of kernel bugs |
| `personality` other than the default and the query | `EPERM` | switching personality can turn off address-space randomisation or make data executable for the programs the app starts |
| `io_uring_setup`, `io_uring_enter`, `io_uring_register` | `ENOSYS` | a large, fast-moving interface behind 60% of the kernel exploits submitted to Google's kCTF bug bounty in the year to June 2023 |
| creating or joining namespaces (`unshare`, `setns`, `clone` with a "new namespace" flag), the mount API, `pivot_root`, `chroot` | `EPERM` | nested sandboxes; lifted by the `userns` permission ([namespaces](namespaces.md#nested-user-namespaces)) |
| `clone3` | `ENOSYS` | its flags are in memory the filter cannot read; the C library falls back to `clone`, whose flags it can |

The error codes are chosen so programs degrade rather than break: `ENOSYS` means "this kernel does not have that call",
and libraries that use `io_uring` or `clone3` fall back to the older calls; `EAFNOSUPPORT` is what a kernel without that
socket family would answer.

The table of system-call numbers in appjail's source is checked by the test suite against the kernel's own header
(`unistd_64.h`), since a wrong number would either leave a hole or deny a call an app needs. On any architecture other
than x86-64 appjail refuses to start an app at all rather than run it unfiltered.

## Connections

- [bubblewrap](bubblewrap.md) loads the filter; appjail passes it as an in-memory file, or, behind `pasta`, which closes
  inherited descriptors, as a private temporary file opened inside the network namespace.
- The `userns` permission removes exactly the namespace rows of the table; everything else stays.
- [Landlock](landlock.md) is the other kernel restriction appjail adds: seccomp filters *calls*, Landlock filters
  *access to objects*.
- Decision: [A seccomp deny list](../../decisions/isolation/seccomp.md).

## Limits

- A deny list blocks what is known to be risky; it does not reduce the kernel to what an app strictly needs. An
  allow list would, but desktop apps make hundreds of different calls through their toolkits and libraries, and an
  allow list that misses one breaks the app in ways that are hard to diagnose.
- Apps that depend on Bluetooth sockets, raw packet sockets or `io_uring` lose that functionality or fail.
- seccomp sees argument values, not the memory they point to, so it cannot filter by path or by the contents of a
  structure.
- x86-64 only.

## References

- Linux kernel documentation, [Seccomp BPF](https://docs.kernel.org/userspace-api/seccomp_filter.html); manual page
  [seccomp(2)](https://man7.org/linux/man-pages/man2/seccomp.2.html).
- Linux manual pages [personality(2)](https://man7.org/linux/man-pages/man2/personality.2.html),
  [ioctl_tty(2)](https://man7.org/linux/man-pages/man2/ioctl_tty.2.html) (`TIOCSTI`),
  [io_uring_setup(2)](https://man7.org/linux/man-pages/man2/io_uring_setup.2.html).
- Flatpak, [the seccomp rules applied to apps](https://github.com/flatpak/flatpak/blob/main/common/flatpak-run.c)
  (function `setup_seccomp`).
- Google Security Blog, [Learnings from kCTF VRP's 42 Linux kernel exploits submissions](https://security.googleblog.com/2023/06/learnings-from-kctf-vrps-42-linux.html),
  2023: 60% of the submissions exploited `io_uring`.
