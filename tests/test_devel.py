# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `devel` permission: manifest, command line, warnings, the seccomp rules and what a real tracer and debugger do."""

import errno
import json
import shutil
import struct
from pathlib import Path

import pytest

from appjail import cli, manifest, seccomp, store
from appjail.gui import argv
from appjail.manifest import Manifest, Permissions

from .helpers import Script, integration, run_in_jail


def sample(**perms):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))


def perms(*command, answers=("y",)):
    console = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *command]), console)
    return console


def saved():
    return manifest.load(store.manifest_path("app")).permissions


def test_it_is_off_by_default_and_written_only_when_on():
    assert Permissions().devel is False
    assert "devel" not in manifest.dumps(sample())
    assert "devel = true" in manifest.dumps(sample(devel=True))


def test_it_round_trips_and_must_be_a_boolean():
    assert manifest.loads(manifest.dumps(sample(devel=True))).permissions.devel is True
    with pytest.raises(manifest.ManifestError, match="devel"):
        manifest.loads(manifest.dumps(sample(devel=True)).replace("devel = true", 'devel = "yes"'))


def test_a_plain_add_does_not_grant_it(h):
    assert "this grants tracing" not in h.add().text
    assert saved().devel is False


def test_add_with_the_grant_writes_it_and_warns(h):
    console = h.add(extra=["--allow", "devel"])
    assert saved().devel is True
    assert "this grants tracing and debugging" in console.text


def test_perms_allow_and_deny_show_the_change_and_warn_once(h):
    h.add()
    console = perms("--allow", "devel")
    assert saved().devel is True and "no → yes" in console.text and "this grants tracing" in console.text
    console = perms("--deny", "devel")
    assert saved().devel is False and "yes → no" in console.text and "this grants" not in console.text


def test_the_window_builds_the_same_command_and_never_says_yes():
    old = {flag: False for flag in cli.PERMISSION_FLAGS}
    command = argv.perms_argv("app", old, dict(old, devel=True))
    assert command == ["perms", "app", "--allow", "devel"] and "--yes" not in command


def _compares(program, number):
    """Whether the program has a `syscall number == N` test (a BPF_JEQ on the call number)."""
    ins = [struct.unpack("HBBI", program[i:i + 8]) for i in range(0, len(program), 8)]
    return any(code == 0x15 and k == number for code, _, _, k in ins)


def test_devel_lifts_ptrace_and_one_personality_value_and_nothing_else():
    plain, devel = seccomp.program(False, False), seccomp.program(False, True)
    assert seccomp.program() == plain and seccomp.program(False) == plain  # the default, and what helper jails use
    assert _compares(plain, seccomp.SYSCALLS["ptrace"]) and not _compares(devel, seccomp.SYSCALLS["ptrace"])
    for name in seccomp.ALWAYS:  # every other always-refused call, perf_event_open included, is still refused
        if name != "ptrace":
            assert _compares(devel, seccomp.SYSCALLS[name]), name
    assert not _compares(plain, 0x0040000) and _compares(devel, 0x0040000)
    for flag in (0x0100000, 0x0400000):  # MMAP_PAGE_ZERO and READ_IMPLIES_EXEC are never allowed
        assert not _compares(devel, flag)
    assert seccomp.DEVEL == ("ptrace",) and seccomp.DEVEL_PERSONALITIES == (0x0040000,)


PROBE = """#!/usr/bin/python3
import ctypes, json, os, signal
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]

def sc(nr, *args):
    args = (list(args) + [0] * 6)[:6]
    ctypes.set_errno(0)
    r = libc.syscall(nr, *[ctypes.c_long(a) for a in args])
    return ctypes.get_errno() if r == -1 else 0

def traced_child():
    pid = os.fork()
    if pid == 0:
        r = libc.ptrace(0, 0, None, None)  # PTRACE_TRACEME
        os._exit(0 if r == 0 else ctypes.get_errno())
    return os.WEXITSTATUS(os.waitpid(pid, 0)[1])

def regs(pid):
    buf = (ctypes.c_ulonglong * 27)()
    libc.ptrace(12, pid, None, ctypes.byref(buf))
    return buf

def injected(nr, arg):
    \"\"\"Run getpid in a traced child after the tracer rewrote it into system call nr; the child's result.\"\"\"
    pid = os.fork()
    if pid == 0:
        libc.ptrace(0, 0, None, None)
        os.kill(os.getpid(), signal.SIGSTOP)
        libc.syscall(39)
        os._exit(0)
    os.waitpid(pid, 0)
    entry = True
    while True:
        libc.ptrace(24, pid, None, None)  # PTRACE_SYSCALL
        if not os.WIFSTOPPED(os.waitpid(pid, 0)[1]):
            return None
        r = regs(pid)
        if entry and r[15] == 39:  # orig_rax
            r[15], r[14] = nr, arg
            libc.ptrace(13, pid, None, ctypes.byref(r))
            libc.ptrace(24, pid, None, None)
            os.waitpid(pid, 0)
            result = ctypes.c_longlong(regs(pid)[10]).value
            libc.ptrace(7, pid, None, None)
            os.waitpid(pid, 0)
            return -result if result < 0 else 0
        entry = not entry

out = {"traceme": traced_child()}
out["persona_no_aslr"] = sc(135, 0x0040000)
out["persona_page_zero"] = sc(135, 0x0100000)
out["persona_read_implies_exec"] = sc(135, 0x0400000)
out["perf_event_open"] = sc(298, 0, 0, -1, -1, 0)
out["process_vm_readv"] = sc(310, 1, 0, 0, 0, 0, 0)
if out["traceme"] == 0:  # a child that cannot be traced would just stop and never be waited for
    out["injected_persona"] = injected(135, 0x0400000)
    out["injected_io_uring"] = injected(425, 0)
    out["injected_mount"] = injected(165, 0)
print(json.dumps(out))
"""


def probe(sandbox, runtime, **perms):
    proc = run_in_jail(sandbox, runtime, script=PROBE, **perms)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@integration
def test_without_devel_nothing_can_be_traced(sandbox, runtime):
    r = probe(sandbox, runtime)
    assert r["traceme"] == errno.EPERM and r["persona_no_aslr"] == errno.EPERM and r["perf_event_open"] == errno.EPERM


@integration
def test_with_devel_ptrace_and_one_personality_work_and_the_rest_stays_refused(sandbox, runtime):
    r = probe(sandbox, runtime, devel=True)
    assert r["traceme"] == 0 and r["persona_no_aslr"] == 0
    assert r["persona_page_zero"] == errno.EPERM and r["persona_read_implies_exec"] == errno.EPERM
    assert r["perf_event_open"] == errno.EPERM and r["process_vm_readv"] == errno.EPERM


@integration
def test_a_tracer_cannot_get_past_the_filter_by_rewriting_a_system_call(sandbox, runtime):
    """The filter runs after the tracer's stop, so a call the tracer swaps in is checked as if the app had made it."""
    r = probe(sandbox, runtime, devel=True)
    assert (r["injected_persona"], r["injected_io_uring"], r["injected_mount"]) == (errno.EPERM, errno.ENOSYS, errno.EPERM)


RUN = """#!/usr/bin/python3
import json, subprocess, sys
r = subprocess.run(sys.argv[1:], capture_output=True, text=True, timeout=60,
                   env={"PATH": "/usr/bin", "HOME": "/tmp", "TERM": "dumb", "LC_ALL": "C"})
print(json.dumps({"rc": r.returncode, "out": r.stdout + r.stderr}))
"""

ADDRESS = "import ctypes;print(hex(ctypes.addressof(ctypes.c_int())))"


def tool(sandbox, runtime, *command, **perms):
    """Run a command (of the guest's /usr) in the jail; (exit code, its output)."""
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} is not installed in the guest")
    proc = run_in_jail(sandbox, runtime, script=RUN, extra=command, **perms)
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    return r["rc"], r["out"]


@integration
def test_strace_needs_devel(sandbox, runtime):
    rc, out = tool(sandbox, runtime, "strace", "-f", "/usr/bin/true")
    assert rc != 0 and "Operation not permitted" in out
    rc, out = tool(sandbox, runtime, "strace", "-f", "/usr/bin/true", devel=True)
    assert rc == 0 and "execve" in out


@integration
def test_gdb_needs_devel_and_then_runs_the_program_at_the_same_address_each_time(sandbox, runtime):
    batch = ("gdb", "-batch", "-ex", "run", "--args", "/usr/bin/python3", "-c", ADDRESS)
    _, out = tool(sandbox, runtime, *batch)
    assert "exited normally" not in out and "Operation not permitted" in out
    addresses = set()
    for _ in range(3):
        _, out = tool(sandbox, runtime, *batch, devel=True)
        assert "exited normally" in out and "Error disabling address space randomization" not in out
        addresses |= {line for line in out.splitlines() if line.startswith("0x")}
    assert len(addresses) == 1


@integration
def test_what_a_debugger_can_attach_to_follows_the_hosts_yama_setting(sandbox, runtime):
    scope = Path("/proc/sys/kernel/yama/ptrace_scope")
    if not scope.is_file():
        pytest.skip("no Yama on this kernel")
    if shutil.which("strace") is None:
        pytest.skip("strace is not installed in the guest")
    command = ("sh", "-c", "sleep 20 & exec timeout 3 strace -p $!")  # the sleeper is a sibling of strace, not its descendant
    _, out = tool(sandbox, runtime, *command, devel=True)
    if scope.read_text().strip() == "0":
        assert "attached" in out
    else:
        assert "Operation not permitted" in out
