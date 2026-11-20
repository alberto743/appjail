# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Memory, CPU and process limits: the three permissions, their checks, the scope around the launch, and what a real
scope does to a jailed app (docs/decisions/isolation/resource-limits.md)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from appjail import cli, limits, manifest, runner, store, valid
from appjail.console import Abort
from appjail.errors import RunError
from appjail.gui import argv
from appjail.manifest import Manifest, Permissions

from .helpers import COMPOSITOR, Script, install, integration, wait_for


def sample(**perms):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))


def perms(*command, answers=("y",)):
    console = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *command]), console)
    return console


def saved():
    return manifest.load(store.manifest_path("app")).permissions


GOOD = {
    "memory_max": ["512M", "2G", "1T", "64K", "1048576", "50%", "100%"],
    "cpu_quota": ["1%", "50%", "200%", "10000%"],
    "tasks_max": ["1", "512", "1000000", "20%", "100%"],
}
BAD = {
    "memory_max": ["", "0", "0M", "2g", "2 G", "2G;rm", "-1G", "150%", "0%", "2GB", "infinity", "1e3", "1.5G", "12345678901"],
    "cpu_quota": ["", "0%", "50", "20000%", "1.5%", "50 %", "-5%", "50%\n"],
    "tasks_max": ["", "0", "-1", "20000000", "101%", "0%", "512 ", "max", "infinity"],
}
CHECK = {"memory_max": valid.memory_max, "cpu_quota": valid.cpu_quota, "tasks_max": valid.tasks_max}


@pytest.mark.parametrize("key,value", [(k, v) for k, vs in GOOD.items() for v in vs])
def test_systemds_own_syntax_is_accepted(key, value):
    assert CHECK[key](value) == value


@pytest.mark.parametrize("key,value", [(k, v) for k, vs in BAD.items() for v in vs])
def test_anything_else_is_refused(key, value):
    with pytest.raises(manifest.ManifestError, match=key.replace("_", "[-_]") + "|permissions"):
        CHECK[key](value)


@pytest.mark.parametrize("key", ["memory_max", "cpu_quota", "tasks_max"])
def test_not_a_string_is_refused(key):
    for value in (5, True, None, ["2G"]):
        with pytest.raises(manifest.ManifestError):
            CHECK[key](value)


def test_they_are_off_by_default_and_written_only_when_set():
    assert (Permissions().memory_max, Permissions().cpu_quota, Permissions().tasks_max) == ("", "", "")
    text = manifest.dumps(sample())
    assert not any(k in text for k in ("memory_max", "cpu_quota", "tasks_max"))
    text = manifest.dumps(sample(memory_max="2G", cpu_quota="150%", tasks_max="512"))
    assert 'memory_max = "2G"' in text and 'cpu_quota = "150%"' in text and 'tasks_max = "512"' in text


def test_they_round_trip_and_a_bad_value_is_refused_when_loading():
    p = Permissions(memory_max="2G", cpu_quota="150%", tasks_max="20%")
    assert manifest.loads(manifest.dumps(sample(**vars_of(p)))).permissions == p
    text = manifest.dumps(sample(memory_max="2G"))
    for bad in ('"lots"', "2", "0"):
        with pytest.raises(manifest.ManifestError, match="memory_max"):
            manifest.loads(text.replace('memory_max = "2G"', f"memory_max = {bad}"))


def vars_of(p):
    return {k: getattr(p, k) for k in ("memory_max", "cpu_quota", "tasks_max")}


def test_add_writes_the_limits(h):
    h.add(extra=["--memory-max", "2G", "--cpu-quota", "200%", "--tasks-max", "512"])
    assert vars_of(saved()) == {"memory_max": "2G", "cpu_quota": "200%", "tasks_max": "512"}


def test_a_plain_add_sets_no_limit(h):
    h.add()
    assert vars_of(saved()) == {"memory_max": "", "cpu_quota": "", "tasks_max": ""}


def test_add_refuses_a_bad_value_before_anything_is_written(h):
    with pytest.raises(Abort, match="--memory-max"):
        h.add(extra=["--memory-max", "lots"])
    assert not store.manifest_path("app").exists()


def test_perms_sets_shows_and_removes_a_limit_with_infinity(h):
    h.add()
    console = perms("--memory-max", "2G", "--tasks-max", "20%")
    assert "none → 2G" in console.text and "none → 20%" in console.text
    assert saved().memory_max == "2G" and saved().tasks_max == "20%"
    assert "memory-max" in perms().text  # shown with the other permissions
    console = perms("--memory-max", "infinity")
    assert "2G → none" in console.text and saved().memory_max == "" and saved().tasks_max == "20%"


def test_perms_refuses_a_bad_value_and_keeps_the_manifest(h):
    h.add(extra=["--memory-max", "2G"])
    for flag, value in (("--memory-max", "2 G"), ("--cpu-quota", "50"), ("--tasks-max", "0")):
        with pytest.raises(Abort, match=flag):
            perms(flag, value)
    assert saved().memory_max == "2G"


def test_a_limit_is_not_a_risky_grant(h):
    assert "this grants" not in h.add(extra=["--memory-max", "2G"]).text


def test_the_window_state_does_not_lose_a_limit():
    """The window rebuilds commands from a state; a limit set on the command line must survive an edit made there."""
    old = vars(Permissions(memory_max="2G"))
    assert argv.perms_argv("app", old, dict(old, gpu=True)) == ["perms", "app", "--allow", "gpu"]


def test_list_json_carries_the_limits(h):
    from appjail.cmd_apps import list_json
    h.add(extra=["--memory-max", "2G"])
    entry = list_json("app", manifest.load(store.manifest_path("app")))
    assert entry["permissions"]["memory_max"] == "2G" and "cpu_quota" not in entry["permissions"]


# The scope around the launch.

ENV = {"XDG_RUNTIME_DIR": "/run/user/1000"}


def test_without_a_limit_there_is_no_scope():
    assert not limits.active(Permissions())
    limits.check(Permissions(), {})  # nothing to check, no session needed


def test_the_properties_say_what_each_limit_means():
    assert limits.properties(Permissions(memory_max="2G")) == ["MemoryMax=2G", "MemorySwapMax=0", "OOMPolicy=kill"]
    assert limits.properties(Permissions(cpu_quota="150%", tasks_max="20%")) == ["CPUQuota=150%", "TasksMax=20%", "OOMPolicy=kill"]


def test_the_command_runs_in_a_user_scope_with_only_the_runtime_directory_added(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    command = limits.wrap(["/usr/bin/bwrap", "--x"], Permissions(memory_max="2G", tasks_max="64"), "app", ENV)
    assert command[:3] == ["/usr/bin/env", "XDG_RUNTIME_DIR=/run/user/1000", "/usr/bin/systemd-run"]
    assert command[3:6] == ["--user", "--scope", "--quiet"] and "--collect" in command
    assert command[command.index("--") + 1:] == ["/usr/bin/bwrap", "--x"]
    pairs = [command[i + 1] for i, a in enumerate(command) if a == "-p"]
    assert pairs == ["MemoryMax=2G", "TasksMax=64", "MemorySwapMax=0", "OOMPolicy=kill"]
    assert "--description=appjail app" in command


@pytest.mark.parametrize("env,tools", [({}, True), (ENV, False)])
def test_no_session_or_no_systemd_run_refuses_to_start(monkeypatch, env, tools):
    monkeypatch.setattr(shutil, "which", (lambda name: f"/usr/bin/{name}") if tools else (lambda name: None))
    with pytest.raises(RunError, match="systemd user session") as e:
        limits.check(Permissions(tasks_max="64"), env)
    assert "--memory-max infinity" in str(e.value)  # says how to remove the limits


def test_a_scope_that_systemd_refuses_stops_the_launch_with_its_message(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    def refuse(command, **kw):
        return subprocess.CompletedProcess(command, 1, "", "Failed to start transient scope unit: Access denied\n")
    with pytest.raises(RunError, match="Access denied"):
        limits.check(Permissions(memory_max="2G"), ENV, run=refuse)
    seen = []
    limits.check(Permissions(memory_max="2G"), ENV, run=lambda c, **kw: seen.append(c) or subprocess.CompletedProcess(c, 0, "", ""))
    assert seen[0][-1] == "true" and "MemoryMax=2G" in seen[0]


def extract(image, dest, fallback=False):
    (Path(dest) / "AppRun").parent.mkdir(parents=True)
    (Path(dest) / "AppRun").write_text("#!/bin/sh\n")
    return 1, 1


def test_launch_wraps_the_whole_start_and_leaves_an_app_without_limits_alone(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(limits, "check", lambda perms, env: None)
    seen = []
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    install(sandbox)
    runner.launch("app", host_env=env, extract=extract, say=lambda *_: None, runner=seen.append, **COMPOSITOR)
    install(sandbox, tasks_max="64")
    runner.launch("app", host_env=env, extract=extract, say=lambda *_: None, runner=seen.append, **COMPOSITOR)
    plain, scoped = seen
    assert plain[0] != "/usr/bin/env" and "systemd-run" not in " ".join(plain[:3])
    assert scoped[:2] == ["/usr/bin/env", f"XDG_RUNTIME_DIR={runtime}"]
    assert scoped[scoped.index("--") + 1:] == plain


def test_launch_checks_the_limits_before_anything_else(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    install(sandbox, memory_max="2G")
    with pytest.raises(RunError, match="systemd user session"):
        runner.launch("app", host_env={"WAYLAND_DISPLAY": "x"}, extract=extract, say=lambda *_: None, runner=lambda a: 0, **COMPOSITOR)


# What a real scope does to a jailed app, through the real launch.

def user_session():
    return Path(f"/run/user/{os.getuid()}/bus").exists() or os.environ.get("XDG_RUNTIME_DIR")


needs_session = pytest.mark.skipif(not shutil.which("systemd-run") or not user_session(), reason="needs systemd-run and a user session")

HOG = '''#!/usr/bin/python3
buf = []
while True:
    buf.append(bytearray(8 << 20))
'''
BUSY = '''#!/usr/bin/python3
import time
start, cpu = time.time(), time.process_time()
while time.time() - start < 3:
    pass
print("cpu per second: %.2f" % ((time.process_time() - cpu) / (time.time() - start)))
'''
FORK = '''#!/usr/bin/python3
import subprocess
procs = []
for _ in range(120):
    try:
        procs.append(subprocess.Popen(["/usr/bin/sleep", "20"]))
    except OSError:
        break
print("started", len(procs))
for p in procs:
    p.kill()
'''


def run_app(sandbox, script, **perms):
    """Install an app whose AppRun is `script` and run it through the real launch, in a real jail."""
    def real_extract(image, dest, fallback=False):
        (Path(dest) / "AppRun").parent.mkdir(parents=True)
        (Path(dest) / "AppRun").write_text(script)
        (Path(dest) / "AppRun").chmod(0o755)
        return 1, 1
    install(sandbox, display="none", **perms)
    env = {"XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "LANG": "C.UTF-8"}
    return runner.launch("app", host_env=env, extract=real_extract, say=lambda *_: None)


@integration
@needs_session
def test_an_app_that_allocates_without_end_is_stopped_at_its_memory_limit(sandbox):
    assert run_app(sandbox, HOG, memory_max="96M") in (-9, 137)


@integration
@needs_session
def test_an_app_gets_only_its_share_of_the_cpu(sandbox, capfd):
    assert run_app(sandbox, BUSY, cpu_quota="25%") == 0
    share = float(capfd.readouterr().out.rsplit(":", 1)[1])
    assert share < 0.5, f"a quota of 25% still gave {share} CPU per second"


@integration
@needs_session
def test_an_app_cannot_start_more_processes_than_its_limit(sandbox, capfd):
    assert run_app(sandbox, FORK, tasks_max="40") == 0
    limited = int(capfd.readouterr().out.rsplit(" ", 1)[1])
    assert run_app(sandbox, FORK) == 0
    free = int(capfd.readouterr().out.rsplit(" ", 1)[1])
    assert limited < 40 and free > limited


@integration
@needs_session
def test_a_limit_leaves_no_scope_behind(sandbox):
    """`--collect` removes even a scope that failed with an out-of-memory kill (once systemd has finished tearing it down)."""
    def scopes():
        return subprocess.run(["systemctl", "--user", "list-units", "--type=scope", "--all", "--no-legend"],
                              capture_output=True, text=True, timeout=30).stdout
    run_app(sandbox, HOG, memory_max="96M")
    assert wait_for(lambda: "appjail app" not in scopes(), 10), scopes()
