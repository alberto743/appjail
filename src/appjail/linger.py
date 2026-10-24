# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `linger` setting: keep the jail until every process in it has exited.

Some launchers start the real app as a detached child and exit at once (VS Code's CLI does). The jail ends with its main
command, so the app would die with it. With `linger` the command runs under a small supervisor, written in Python and
run inside the jail by the system interpreter: it becomes the subreaper of the jail, so detached descendants report to
it, and it exits, with the command's status, only when nothing but pid 1 and its own starting helpers (a private
Xwayland) and their children is left.
"""

import os

from .jail import RunError

PYTHON = "/usr/bin/python3"
SUPERVISOR = '''\
import ctypes, os, sys, time

def stat(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rpartition(")")[2].split()
    except OSError:
        return None

def live():
    out = {}
    for name in os.listdir("/proc"):
        if name.isdigit() and (s := stat(name)) and s[0] != "Z":
            out[int(name)] = int(s[1])
    return out

def helped(pid, procs):
    while pid in procs:
        if pid in helpers:
            return True
        pid = procs[pid]
    return False

ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
me = os.getpid()
helpers = {p for p, parent in live().items() if parent == me}
cmd = sys.argv[1:]
child = os.fork()
if child == 0:
    try:
        os.execvp(cmd[0], cmd)
    except OSError as e:
        print(f"appjail: cannot run {cmd[0]}: {e.strerror}", file=sys.stderr)
        os._exit(127)
code = None
while code is None:
    try:
        done, status = os.waitpid(-1, 0)
    except ChildProcessError:
        break
    if done == child:
        code = os.waitstatus_to_exitcode(status)
        if code < 0:
            code = 128 - code
while True:
    try:
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass
    except ChildProcessError:
        pass
    procs = live()
    if not [p for p in procs if p not in (1, me) and not helped(p, procs)]:
        break
    time.sleep(0.2)
os._exit(code if code is not None else 0)
'''


def wrap(command):
    """The command run under the supervisor."""
    if not os.access(PYTHON, os.X_OK):
        raise RunError("linger needs python3 in /usr/bin")
    return [PYTHON, "-I", "-c", SUPERVISOR, *command]
