# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The link relay: the host FIFO, the supervisor that reads it, and a single-instance app in a real jail."""

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from appjail import jail, relay, runtimejail, seccomp
from appjail.errors import RunError

from .helpers import build, integration, wait_for


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPJAIL_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


# -- the host side ---------------------------------------------------------------------


def test_nothing_runs_means_no_delivery(data):
    assert relay.send("app", ["gemini://x/"]) is False


def test_a_launch_holds_a_fifo_that_clients_can_write_to_and_removes_it(data):
    with relay.serving("app") as path:
        assert path == relay.fifo_path("app") and path.parent.stat().st_mode & 0o777 == 0o700
        assert relay.send("app", ["gemini://x/a b", "gemini://x/2"]) is True
        assert os.read(os.open(path, os.O_RDONLY | os.O_NONBLOCK), 100) == b"gemini://x/a b\ngemini://x/2\n"
    assert not path.exists() and relay.send("app", ["gemini://x/"]) is False


def test_a_second_launch_does_not_take_over_a_live_fifo(data):
    with relay.serving("app") as first, relay.serving("app") as second:
        assert first is not None and second is None
        assert relay.fifo_path("app").exists()
    assert not relay.fifo_path("app").exists()


def test_a_fifo_nobody_reads_is_stale_and_replaced(data):
    path = relay.fifo_path("app")
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    assert relay.send("app", ["gemini://x/"]) is False
    with relay.serving("app") as got:
        assert got == path and relay.send("app", ["gemini://x/"]) is True


def test_something_that_is_not_a_fifo_is_never_written_to(data):
    path = relay.fifo_path("app")
    path.parent.mkdir(parents=True)
    path.write_text("x")
    with pytest.raises(RunError):
        relay.send("app", ["gemini://x/"])
    assert path.read_text() == "x"


def test_a_full_queue_is_reported(data):
    with relay.serving("app"), pytest.raises(RunError, match="queue is full"):
        for _ in range(100):
            relay.send("app", ["gemini://x/" + "a" * 3900])


# -- the supervisor (run here with plain python; the jail test below runs it for real) --------------------------------


HELPER = "#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$LOG\"\n"


def start(tmp_path, schemes, command, helper=None):
    helper = helper or tmp_path / "helper.sh"
    if not helper.exists():
        helper.write_text(HELPER)
        helper.chmod(0o755)
    fifo = tmp_path / "fifo"
    if not fifo.exists():
        os.mkfifo(fifo)
    argv = [sys.executable, "-I", "-c", relay.RELAY, str(fifo), str(helper), ",".join(schemes), *command]
    proc = subprocess.Popen(argv, env={"LOG": str(tmp_path / "log"), "PATH": "/usr/bin:/bin"}, stderr=subprocess.PIPE)
    return proc, fifo


def push(fifo, *lines):
    fd = os.open(fifo, os.O_WRONLY)
    for line in lines:
        os.write(fd, line if isinstance(line, bytes) else line.encode() + b"\n")
    os.close(fd)


def test_the_supervisor_runs_the_helper_for_each_good_link_and_drops_the_rest(tmp_path):
    proc, fifo = start(tmp_path, ["gemini"], ["/bin/sleep", "30"])
    link = 'GEMINI://x/a b?q="1"&z=%20'
    push(fifo, link, "gopher://x/", "gemini://x/\x01bad", b"\xff\xfe\n", "gemini://" + "a" * 4000, "gemini://x/second")
    log = tmp_path / "log"
    assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 2, 10)
    assert log.read_text().splitlines() == [link, "gemini://x/second"]
    proc.terminate()
    proc.wait(timeout=10)
    assert proc.stderr.read().count(b"refused") == 4


def test_the_supervisor_passes_the_exit_status_and_forwards_the_stop_signal(tmp_path):
    proc, _ = start(tmp_path, ["gemini"], ["/bin/sh", "-c", "exit 7"])
    assert proc.wait(timeout=10) == 7
    proc, _ = start(tmp_path, ["gemini"], ["/bin/sh", "-c", "trap 'exit 9' TERM; while :; do sleep 0.1; done"])
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 9


def test_runtime_args_run_the_command_under_the_supervisor_with_the_fifo_bound_in(sandbox, runtime, data):
    kw = build(sandbox, runtime, schemes=("gemini", "gopher"))
    with relay.serving("app") as fifo:
        args = runtimejail.runtime_args(**kw, link_fifo=fifo)
    assert ("--bind", str(fifo), relay.JAIL_FIFO) in [tuple(args[i:i + 3]) for i in range(len(args))]
    assert args[args.index("--") + 1:] == [relay.PYTHON, "-I", "-c", relay.RELAY, relay.JAIL_FIFO, "/app/AppRun",
                                           "gemini,gopher", "/app/AppRun"]
    plain = runtimejail.runtime_args(**build(sandbox, runtime))
    assert plain[plain.index("--") + 1:] == ["/app/AppRun"] and relay.JAIL_FIFO not in plain


def test_the_supervisor_needs_python_in_the_jail(monkeypatch):
    monkeypatch.setattr(relay, "PYTHON", "/nonexistent/python3")
    with pytest.raises(RunError, match="python3"):
        relay.wrap(["/app/AppRun"], ("gemini",))


# -- a single-instance app in a real jail -----------------------------------------------------


# The first instance leaves a marker in the jail's /tmp and stays; a later process finds it and records its argument,
# as a single-instance app hands a link to the running one. Nothing else is shared between them.
SINGLE_INSTANCE = """#!/bin/sh
if [ -e /tmp/running ]; then
  echo "$1" >> /home/app/links.log
  exit 0
fi
touch /tmp/running
echo started > /home/app/started
while [ ! -e /home/app/stop ]; do sleep 0.1; done
"""


@integration
def test_links_reach_the_running_app_through_the_relay(sandbox, runtime):
    kw = build(sandbox, runtime, schemes=("gemini",))
    (kw["root"] / "AppRun").write_text(SINGLE_INSTANCE)
    (kw["root"] / "AppRun").chmod(0o755)
    fd = seccomp.open_fd(kw["perms"].userns)
    result = {}
    try:
        with relay.serving("app") as fifo:
            argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd, link_fifo=fifo)]
            thread = threading.Thread(target=lambda: result.update(proc=jail.supervise(argv, timeout=60, pass_fds=(fd,))))
            thread.start()
            assert relay.send("app", ["gemini://localhost/early"])  # queued while the app is still starting
            assert wait_for(lambda: (kw["home"] / "started").exists(), 20)
            assert relay.send("app", ["gemini://localhost/a b?x=1&y=\"q\"", "gopher://localhost/refused"])
            log = kw["home"] / "links.log"
            assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 2, 20)
            (kw["home"] / "stop").write_text("")
            thread.join(30)
    finally:
        os.close(fd)
    assert result["proc"].returncode == 0, result["proc"].stderr
    assert sorted((kw["home"] / "links.log").read_text().splitlines()) == ['gemini://localhost/a b?x=1&y="q"', "gemini://localhost/early"]
    assert not relay.fifo_path("app").exists()
