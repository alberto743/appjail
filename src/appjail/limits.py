# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Memory, CPU and process limits: the app's launch runs in a systemd user scope (docs/decisions/isolation/resource-limits.md).

`systemd-run --user --scope` runs the command in place, so the process appjail starts stays the leader of its session
and process group, and `pasta`, the jails and the app all share the scope's cgroup. Nothing changes for an app without a
limit: no scope, no extra process. A limit that cannot be applied stops the launch (a limit that is silently not
applied is worse than none).
"""

import shutil
import subprocess

from .errors import RunError
from .manifest import LIMIT_KEYS

SYSTEMD_RUN = "systemd-run"
PROPERTY = {"memory_max": "MemoryMax", "cpu_quota": "CPUQuota", "tasks_max": "TasksMax"}
CHECK_SECONDS = 20


def active(perms):
    """True when the app has at least one limit."""
    return any(getattr(perms, key) for key in LIMIT_KEYS)


def properties(perms):
    """The `Name=value` properties of the scope. With a memory limit swap is refused too, so the limit means what it says;
    an out-of-memory kill ends the whole scope (OOMPolicy=kill), so the exit status is the same on every system."""
    props = [f"{PROPERTY[key]}={getattr(perms, key)}" for key in LIMIT_KEYS if getattr(perms, key)]
    if perms.memory_max:
        props.append("MemorySwapMax=0")
    return [*props, "OOMPolicy=kill"]


def _prefix(perms, env, description):
    """The command that starts a command in the scope. systemd-run needs XDG_RUNTIME_DIR to reach the user manager, and
    the app's own start has a minimal environment, so it is given through env(1); the jail clears it again."""
    runtime = env.get("XDG_RUNTIME_DIR")
    tool, env_tool = shutil.which(SYSTEMD_RUN), shutil.which("env")
    if not runtime or not tool or not env_tool:
        raise RunError("resource limits (memory_max, cpu_quota, tasks_max) need systemd-run and a systemd user session "
                       "(XDG_RUNTIME_DIR); log in through a session, or remove the limits with `appjail perms APP "
                       "--memory-max infinity` (and --cpu-quota, --tasks-max)")
    return [env_tool, f"XDG_RUNTIME_DIR={runtime}", tool, "--user", "--scope", "--quiet", "--collect",
            f"--description={description}", *(arg for prop in properties(perms) for arg in ("-p", prop)), "--"]


def wrap(argv, perms, name, env):
    """argv run in a scope that carries the app's limits."""
    return [*_prefix(perms, env, f"appjail {name}"), *argv]


def check(perms, env, run=subprocess.run):
    """Raise RunError unless a scope with these limits can be started now (checked before anything else is set up)."""
    if not active(perms):
        return
    argv = [*_prefix(perms, env, "appjail check"), "true"]
    try:
        done = run(argv, capture_output=True, text=True, timeout=CHECK_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RunError(f"the resource limits could not be applied: {e}") from e
    if done.returncode != 0:
        lines = (done.stderr or "").strip().splitlines()
        raise RunError("the resource limits could not be applied (systemd refused the scope"
                       + (f": {lines[-1][:200]}" if lines else "") + "); remove them with `appjail perms APP --memory-max "
                       "infinity` (and --cpu-quota, --tasks-max) or run from a login session")
