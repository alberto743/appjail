# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import errno
import re
import struct
from pathlib import Path

import pytest

from appjail import jail, seccomp
from .helpers import integration, run_in_jail


HEADER = Path("/usr/include/x86_64-linux-gnu/asm/unistd_64.h")


@pytest.mark.skipif(not HEADER.is_file(), reason="needs linux-libc-dev (kernel headers) in the guest")
def test_syscall_table_matches_the_kernel_headers():
    numbers = dict(re.findall(r"#define __NR_(\w+)\s+(\d+)", HEADER.read_text()))
    wrong = {n: (v, numbers[n]) for n, v in seccomp.SYSCALLS.items() if n in numbers and str(v) != numbers[n]}
    assert not wrong
    # removed from current headers: only these may be missing
    assert {n for n in seccomp.SYSCALLS if n not in numbers} <= {"_sysctl", "create_module", "get_kernel_syms",
                                                                  "nfsservctl", "query_module", "uselib"}


def decode(prog):
    return [struct.unpack("HBBI", prog[i:i + 8]) for i in range(0, len(prog), 8)]


@pytest.mark.parametrize("userns", [False, True])
def test_program_is_well_formed(userns):
    prog = decode(seccomp.program(userns))
    assert 0 < len(prog) < 4096 and prog[-1][0] == 0x06 and prog[-1][3] == seccomp.SECCOMP_RET_ALLOW
    for i, (code, jt, jf, k) in enumerate(prog):
        if code & 0x07 == 0x05 and code != 0x05:  # conditional jump: both targets inside the program
            assert i + 1 + jt < len(prog) and i + 1 + jf < len(prog)
        if code == 0x05:  # unconditional jump
            assert i + 1 + k < len(prog)


def test_userns_grant_removes_the_namespace_rules():
    assert len(seccomp.program(True)) < len(seccomp.program(False))


PROBE = """#!/usr/bin/python3
import ctypes, errno, json, os, subprocess, threading
libc = ctypes.CDLL(None, use_errno=True)

def sc(nr, *args):
    args = (list(args) + [0] * 6)[:6]
    ctypes.set_errno(0)
    r = libc.syscall(nr, *[ctypes.c_long(a) for a in args])
    return ctypes.get_errno() if r == -1 else 0

out = {}
out["tiocsti"] = sc(16, 0, 0x5412, 0)
out["bpf"] = sc(321, 0, 0, 0)
out["process_vm_readv"] = sc(310, 1, 0, 0, 0, 0, 0)
out["mount"] = sc(165, 0, 0, 0, 0, 0)
out["x32"] = sc(0x40000000 | 39)
out["clone3"] = sc(435, 0, 0)
try:
    os.unshare(os.CLONE_NEWUSER)
    out["newuser"] = 0
except OSError as e:
    out["newuser"] = e.errno
out["getpid"] = sc(39)
t = []
th = threading.Thread(target=lambda: t.append(1)); th.start(); th.join()
out["thread"] = len(t)
out["exec"] = subprocess.run(["/usr/bin/true"]).returncode
print(json.dumps(out))
"""


def probe(sandbox, runtime, **perms):
    proc = run_in_jail(sandbox, runtime, script=PROBE, **perms)
    assert proc.returncode == 0, proc.stderr
    import json
    return json.loads(proc.stdout.strip().splitlines()[-1])


@integration
def test_filter_denies_dangerous_calls_and_keeps_normal_ones(sandbox, runtime):
    r = probe(sandbox, runtime)
    assert r["tiocsti"] == errno.EPERM and r["bpf"] == errno.EPERM and r["process_vm_readv"] == errno.EPERM
    assert r["mount"] == errno.EPERM and r["x32"] == errno.EPERM
    assert r["clone3"] == errno.ENOSYS
    assert r["newuser"] != 0  # no nested user namespace without the grant
    assert r["getpid"] == 0 and r["thread"] == 1 and r["exec"] == 0


@integration
def test_userns_grant_allows_a_nested_user_namespace(sandbox, runtime):
    r = probe(sandbox, runtime, userns=True)
    assert r["newuser"] == 0 and r["clone3"] != errno.ENOSYS
    assert r["bpf"] == errno.EPERM and r["tiocsti"] == errno.EPERM  # the always-denied list still applies


@integration
def test_bwrap_refuses_nested_user_namespaces_without_the_grant(sandbox, runtime):
    """--disable-userns is the kernel-level half: it must be present even if the filter were bypassed."""
    from .test_runner import build
    args = jail.runtime_args(**build(sandbox, runtime))
    assert "--disable-userns" in args
    assert "--disable-userns" not in jail.runtime_args(**build(sandbox, runtime, userns=True))
