# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Landlock scoping for the app jail: no connection to abstract unix sockets created outside it.

Abstract unix sockets belong to a network namespace, not to the filesystem, so bwrap's mounts do not hide them. An app
with `network_host` shares the host's network namespace and could otherwise reach every abstract socket there, the X
server's `@/tmp/.X11-unix/X0` first of all (desktops commonly let any process of the user in). Landlock's
LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET (ABI 6, Linux 6.12) refuses a connection to an abstract socket created outside the
caller's Landlock domain; sockets made inside the jail (its own Xwayland) keep working. Only the scope is used: no
filesystem or network rules, which the mount namespace and pasta already cover.

bwrap cannot apply Landlock, so this file is also a tiny exec wrapper, run as `python3 -I landlock.py COMMAND...`: it
puts itself in the domain and execs COMMAND (bwrap), which everything in the jail inherits. A separate process, not a
preexec_fn, so it stays safe in a launcher with threads. Not used behind pasta: pasta's private network namespace
already isolates abstract sockets, and pasta refuses to start its command under the no_new_privs Landlock requires.
Standalone: stdlib only, no appjail imports. x86_64 system call numbers, like seccomp.py.
"""

import ctypes
import os
import platform
import struct
import sys

SYS_LANDLOCK_CREATE_RULESET, SYS_LANDLOCK_RESTRICT_SELF = 444, 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET = 1
PR_SET_NO_NEW_PRIVS = 38
MIN_ABI = 6
NEEDED_FOR_NETWORK_HOST = ("network_host shares the host's network namespace, and with it the abstract unix sockets of "
                           "the X server and other programs; keeping the app off them needs Landlock ABI 6 (Linux 6.12 "
                           "or later, with Landlock enabled), which this kernel does not offer. Use `network` instead")
# struct landlock_ruleset_attr (ABI 6): handled_access_fs, handled_access_net, scoped
RULESET_ATTR = struct.pack("=QQQ", 0, 0, LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET)

_libc = ctypes.CDLL(None, use_errno=True)


def abi():
    """The kernel's Landlock ABI version, or 0 when Landlock is missing, disabled or the architecture is not x86_64."""
    if platform.machine() != "x86_64":
        return 0
    version = _libc.syscall(ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET), None, ctypes.c_size_t(0),
                            ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION))
    return max(version, 0)


def available():
    return abi() >= MIN_ABI


def wrap(argv):
    """argv run inside the Landlock domain (see the module docstring)."""
    return [sys.executable, "-I", os.path.abspath(__file__), *argv]


def restrict_self():
    """Put this process in a Landlock domain scoped against outside abstract sockets; raise OSError if it cannot."""
    if _libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    attr = ctypes.create_string_buffer(RULESET_ATTR, len(RULESET_ATTR))
    fd = _libc.syscall(ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET), attr, ctypes.c_size_t(len(RULESET_ATTR)),
                       ctypes.c_uint32(0))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset failed")
    try:
        if _libc.syscall(ctypes.c_long(SYS_LANDLOCK_RESTRICT_SELF), ctypes.c_int(fd), ctypes.c_uint32(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self failed")
    finally:
        os.close(fd)


def main(argv):
    if len(argv) < 2:
        print("usage: landlock.py COMMAND [ARG...]", file=sys.stderr)
        return 2
    try:
        restrict_self()
    except OSError as e:
        print(f"appjail: cannot enter the Landlock domain: {e}", file=sys.stderr)
        return 126
    os.execvp(argv[1], argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
