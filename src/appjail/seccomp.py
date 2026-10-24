# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Seccomp filter for the app jail and the helper jails, as a classic BPF program that bubblewrap loads (`--seccomp FD`).

Default allow, deny list: the calls below fail with EPERM. The list follows what Flatpak blocks for
applications (kernel modules, kexec, bpf, perf, keyrings, userfaultfd, mount API, NUMA policy,
cross-process memory access, handle-based opens, socket families beyond unix/inet/netlink, personality
switches) plus the terminal-injection ioctls and io_uring (ENOSYS). Unless the
manifest grants `userns`, creating namespaces and mounting are denied too (`clone` with any
CLONE_NEW* flag, `unshare`, `setns`, `mount` and friends; `clone3` answers ENOSYS so libc falls back
to `clone`, whose flags can be inspected). x86_64 only; other architectures are refused rather than
left unfiltered. Written by hand to stay stdlib-only.
"""

import errno
import os
import platform
import struct

from .jail import RunError

AUDIT_ARCH_X86_64 = 0xC000003E
X32_BIT = 0x40000000

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000

BPF_LD, BPF_JMP, BPF_RET = 0x00, 0x05, 0x06
BPF_W, BPF_ABS = 0x00, 0x20
BPF_JA, BPF_JEQ, BPF_JGE, BPF_JSET = 0x00, 0x10, 0x30, 0x40
BPF_K = 0x00

OFF_NR, OFF_ARCH, OFF_ARGS = 0, 4, 16

SYSCALLS = {
    "_sysctl": 156, "acct": 163, "add_key": 248, "bpf": 321, "chroot": 161, "clone": 56, "clone3": 435,
    "create_module": 174, "delete_module": 176, "fanotify_init": 300, "finit_module": 313, "fsconfig": 431,
    "fsmount": 432, "fsopen": 430, "fspick": 433, "get_kernel_syms": 177, "init_module": 175, "ioctl": 16,
    "io_uring_enter": 426, "io_uring_register": 427, "io_uring_setup": 425,
    "ioperm": 173, "iopl": 172, "kexec_file_load": 320, "kexec_load": 246, "keyctl": 250,
    "lookup_dcookie": 212, "mbind": 237, "migrate_pages": 256, "mount": 165, "mount_setattr": 442,
    "move_mount": 429, "move_pages": 279, "name_to_handle_at": 303, "nfsservctl": 180,
    "open_by_handle_at": 304, "open_tree": 428, "perf_event_open": 298, "personality": 135,
    "pivot_root": 155, "process_vm_readv": 310, "process_vm_writev": 311, "ptrace": 101, "query_module": 178,
    "quotactl": 179, "reboot": 169, "request_key": 249, "set_mempolicy": 238, "setns": 308,
    "socket": 41, "socketpair": 53,
    "swapoff": 168, "swapon": 167, "syslog": 103, "umount2": 166, "unshare": 272, "uselib": 134,
    "userfaultfd": 323,
}

# Always denied, whatever the manifest says.
ALWAYS = ("_sysctl", "acct", "add_key", "bpf", "create_module", "delete_module", "fanotify_init", "finit_module",
          "get_kernel_syms", "init_module", "ioperm", "iopl", "kexec_file_load", "kexec_load", "keyctl",
          "lookup_dcookie", "mbind", "migrate_pages", "move_pages", "name_to_handle_at", "nfsservctl",
          "open_by_handle_at", "perf_event_open", "process_vm_readv", "process_vm_writev", "ptrace",
          "query_module", "quotactl", "reboot", "request_key", "set_mempolicy", "swapoff", "swapon", "syslog",
          "uselib", "userfaultfd")
# Denied unless the manifest grants `userns`: namespace creation and the mount API.
NAMESPACE = ("chroot", "fsconfig", "fsmount", "fsopen", "fspick", "mount", "mount_setattr", "move_mount",
             "open_tree", "pivot_root", "setns", "umount2", "unshare")
CLONE_NEW_MASK = 0x02020000 | 0x04000000 | 0x08000000 | 0x10000000 | 0x20000000 | 0x40000000 | 0x00000080
TIOCSTI, TIOCLINUX = 0x5412, 0x541C
# Socket families an app may create, as Flatpak allows: AF_UNSPEC, AF_UNIX, AF_INET, AF_INET6, AF_NETLINK. The rest
# (AF_VSOCK, AF_TIPC, AF_ALG, AF_PACKET, AF_BLUETOOTH, ...) is rarely needed and has been a steady source of kernel bugs.
SOCKET_FAMILIES = (0, 1, 2, 10, 16)
# personality(2): only PER_LINUX and the query value; switching personalities can turn off ASLR (ADDR_NO_RANDOMIZE)
# or make data executable (READ_IMPLIES_EXEC) for the programs the app starts.
PERSONALITIES = (0, 0xFFFFFFFF)
# io_uring has been the source of many kernel privilege escalations; ENOSYS, so libraries fall back to plain calls.
IO_URING = ("io_uring_enter", "io_uring_register", "io_uring_setup")


def _ins(code, k, jt=0, jf=0):
    return struct.pack("HBBI", code, jt, jf, k)


def _ld(offset):
    return _ins(BPF_LD | BPF_W | BPF_ABS, offset)


def _ret(value):
    return _ins(BPF_RET | BPF_K, value)


DENY = _ret(SECCOMP_RET_ERRNO | errno.EPERM)


def _block(nr, checks=(), action=DENY):
    """If the syscall is nr (and any check matches), return action; otherwise fall to the next block.

    checks: (arg index, "set"|"eq", value), tested on the low 32 bits of the argument.
    """
    head = [_ld(OFF_NR)]
    if not checks:
        return head + [_ins(BPF_JMP | BPF_JEQ | BPF_K, nr, 0, 1), action]
    n = len(checks)
    body = []
    for i, (arg, op, value) in enumerate(checks):
        to_action = 2 * (n - 1 - i) + 1  # instructions left after this jump, up to the action
        body += [_ld(OFF_ARGS + 8 * arg),
                 _ins(BPF_JMP | (BPF_JSET if op == "set" else BPF_JEQ) | BPF_K, value, to_action, 0)]
    body += [_ins(BPF_JMP | BPF_JA, 1), action]
    return head + [_ins(BPF_JMP | BPF_JEQ | BPF_K, nr, 0, len(body))] + body


def _block_unless(nr, arg, allowed, action):
    """If the syscall is nr and its argument (low 32 bits) is none of `allowed`, return action; else fall through."""
    n = len(allowed)
    body = [_ld(OFF_ARGS + 8 * arg)]
    body += [_ins(BPF_JMP | BPF_JEQ | BPF_K, value, n - i, 0) for i, value in enumerate(allowed)]  # a match skips the action
    body.append(action)
    return [_ld(OFF_NR), _ins(BPF_JMP | BPF_JEQ | BPF_K, nr, 0, len(body))] + body


def program(userns=False):
    """The BPF program as bytes (struct sock_filter array)."""
    if platform.machine() != "x86_64":
        raise RunError("the seccomp filter is only implemented for x86_64; refusing to run unfiltered")
    prog = [_ld(OFF_ARCH), _ins(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0), _ret(SECCOMP_RET_KILL_PROCESS),
            _ld(OFF_NR), _ins(BPF_JMP | BPF_JGE | BPF_K, X32_BIT, 0, 1), DENY]  # x32 ABI would dodge the table
    for name in ALWAYS:
        prog += _block(SYSCALLS[name])
    prog += _block(SYSCALLS["ioctl"], [(1, "eq", TIOCSTI), (1, "eq", TIOCLINUX)])
    for name in ("socket", "socketpair"):
        prog += _block_unless(SYSCALLS[name], 0, SOCKET_FAMILIES, _ret(SECCOMP_RET_ERRNO | errno.EAFNOSUPPORT))
    prog += _block_unless(SYSCALLS["personality"], 0, PERSONALITIES, DENY)
    for name in IO_URING:
        prog += _block(SYSCALLS[name], action=_ret(SECCOMP_RET_ERRNO | errno.ENOSYS))
    if not userns:
        for name in NAMESPACE:
            prog += _block(SYSCALLS[name])
        prog += _block(SYSCALLS["clone"], [(0, "set", CLONE_NEW_MASK)])
    prog += _block(SYSCALLS["clone3"], action=_ret(SECCOMP_RET_ERRNO | errno.ENOSYS)) if not userns else []
    prog.append(_ret(SECCOMP_RET_ALLOW))
    if len(prog) > 4096:
        raise RunError("seccomp program too long")
    return b"".join(prog)


def open_fd(userns=False):
    """A memfd holding the program, positioned at 0 and inheritable, for bwrap's --seccomp."""
    fd = os.memfd_create("appjail-seccomp", 0)
    os.write(fd, program(userns))
    os.lseek(fd, 0, os.SEEK_SET)
    os.set_inheritable(fd, True)
    return fd
