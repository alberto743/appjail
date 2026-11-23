# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The link relay under load and at its edges: agreement of its two checks, concurrent writers, a flood, a dead relay,
a killed launcher, racing launches, and the relay combined with `linger` in a real jail. The basic behaviour is in
test_relay.py."""

import argparse
import ast
import json
import os
import random
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from appjail import (
    cmd_open,
    grants,
    jail,
    relay,
    runner,
    runtimejail,
    seccomp,
    store,
)
from appjail.errors import RunError
from appjail.manifest import ManifestError

from .helpers import (
    COMPOSITOR,
    Extractor,
    build,
    headless_weston,
    integration,
    needs_pasta,
    needs_proxy,
    wait_for,
)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPJAIL_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


HELPER = "#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$LOG\"\n"


def start(tmp_path, schemes, command, helper=None, fifo=None):
    """The supervisor, run with plain python, over a FIFO in tmp_path (or the given one)."""
    helper = helper or tmp_path / "helper.sh"
    if not helper.exists():
        helper.write_text(HELPER)
        helper.chmod(0o755)
    if fifo is None:
        fifo = tmp_path / "fifo"
        if not fifo.exists():
            os.mkfifo(fifo)
    argv = [sys.executable, "-I", "-c", relay.RELAY, str(fifo), str(helper), ",".join(schemes), *command]
    proc = subprocess.Popen(argv, env={"LOG": str(tmp_path / "log"), "PATH": "/usr/bin:/bin"}, stderr=subprocess.PIPE)
    return proc, fifo


def supervisor_good():
    """The supervisor's own `good` function, lifted out of the program text that runs in the jail."""
    tree = ast.parse(relay.RELAY)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "good")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MAX" or "MAX" in ast.dump(t) for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<relay>", "exec"), ns)  # noqa: S102  (our own source, never network text)
    return ns["good"]


# -- the host check and the supervisor's check must agree ---------------------------------------


def corpus(rng):
    schemes = ["gemini", "joplin", "a+b.c-d"]
    odd = ["", " ", "-", "--x", ":", "::", "gemini", "gemini:", "GEMINI://x", "Gemini:x", "joplin://a", "JOPLIN:",
           "Kermit:x", "geminí:x", "İ:x", "gemini://x\n", "gemini://x\r", "gemini://x\x00", "gemini://x\x7f",
           "gemini://x\x1b[31m", "gemini://x\x85", "gemini:// x", "a+b.c-d:x", "A+B.C-D:x", " gemini://x", "-gemini://x",
           "gemini://" + "a" * 3991, "gemini://" + "a" * 3992, "gemini://" + "é" * 1995, "gemini://" + "é" * 1996,
           "gemini://\udcff", "gemini://\ud800", "gemini://\udbff\udc00", "gemini://\udc7f", "gemini://\udd00", "file:///etc/passwd", "javascript:alert(1)"]
    alphabet = list("gemini:/ab-+.%\"'&?# \t\n\x00\x1f\x7f") + ["é", "K", "İ", "\U0001f600", " ", "\x85", "\udcff"]
    for _ in range(4000):
        head = rng.choice(["gemini:", "GEMINI:", "joplin:", "-", "", "x:", "Joplin:", "a+b.c-d:"])
        odd.append(head + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12))))
    return schemes, odd


def test_the_host_check_and_the_supervisors_check_agree_on_every_link():
    good = supervisor_good()
    schemes, links = corpus(random.Random(20261123))
    disagreements = []
    for link in links:
        try:
            grants.check_link(link, schemes)
            host = True
        except ManifestError:
            host = False
        # what the supervisor really sees: bytes off the pipe, decoded as it decodes them; a link the host cannot encode
        # (lone surrogates that are not escapes) never reaches the pipe at all
        try:
            wire = link.encode("utf-8", "surrogateescape")
        except UnicodeEncodeError:
            continue
        line = wire.decode("utf-8", "replace")
        if len(wire) > grants.MAX_LINK_BYTES:
            sup = False
        else:
            sup = bool(_call(good, line, schemes))
        if host != sup:
            disagreements.append((link[:40], host, sup))
    assert not disagreements, disagreements[:10]


def _call(good, line, schemes):
    good.__globals__["schemes"] = schemes  # the supervisor reads `schemes` from its module scope
    return good(line)


def test_no_accepted_link_can_read_as_an_option_or_carry_a_control_character():
    schemes, links = corpus(random.Random(7))
    for link in links:
        try:
            grants.check_link(link, schemes)
        except ManifestError:
            continue
        assert link[0].isalpha() and link[0] != "-", link
        assert not any(ord(c) < 32 or ord(c) == 127 for c in link)


# -- concurrency: real processes started together ------------------------------------------------
#
# Each worker is a separate python process (no fork of a multi-threaded test run). They import appjail, then wait on a
# pipe whose write end the test closes once every worker is started, so they all begin in the same instant.

WORKER = r'''
import contextlib, os, sys, time
mode, data_dir, app, gate = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
os.environ["APPJAIL_DATA_DIR"] = data_dir
from appjail import relay
from appjail.errors import RunError

@contextlib.contextmanager
def old_serving(name):  # the algorithm before the directory lock: the control that shows the window is real
    path = relay.fifo_path(name)
    relay.store.make_private(path.parent)
    for _ in range(2):
        alive = relay._reader_alive(path)
        if alive:
            yield None
            return
        if alive is False:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        try:
            os.mkfifo(path, 0o600)
            break
        except FileExistsError:
            continue
    else:
        yield None
        return
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        yield path
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)

if mode in ("serve", "old"):
    hold, slow, after = float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7])
    if slow:  # widen the window between mkfifo and the open
        real = os.mkfifo
        def slow_mkfifo(*a, **k):
            real(*a, **k)
            time.sleep(slow)
        os.mkfifo = slow_mkfifo
    os.read(gate, 1)
    time.sleep(after)
    with (relay.serving if mode == "serve" else old_serving)(app) as path:
        print("HELD" if path else "NONE", flush=True)
        time.sleep(hold)
elif mode == "send":
    count, seed = int(sys.argv[5]), int(sys.argv[6])
    os.read(gate, 1)
    retries = 0
    for i in range(count):
        link = f"gemini://w{seed}/{i}/" + "z" * (1 + (seed * 131 + i * 17) % 3900)
        while True:
            try:
                if not relay.send(app, [link]):
                    sys.exit(3)  # nothing runs: the test never expects this
                break
            except RunError as e:
                assert "queue is full" in str(e), e
                retries += 1
                time.sleep(0.002)
    print(f"SENT {retries}", flush=True)
'''


def workers(mode, n, data_dir, app, *args, apps=None, each=None):
    """Start n worker processes at the same instant; returns them. `apps` gives one app name for each instead of `app`,
    `each(i)` more arguments for the i-th."""
    r, w = os.pipe()
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(relay.__file__)))
    procs = []
    try:
        for i in range(n):
            name = apps[i] if apps else app
            procs.append(subprocess.Popen([sys.executable, "-c", WORKER, mode, str(data_dir), name, str(r), *map(str, args), *map(str, each(i) if each else ())],
                                          env=env, pass_fds=(r,), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        time.sleep(0.4)  # every worker has imported appjail and waits at the gate
    finally:
        os.close(r)
        os.close(w)  # closing the write end releases them all together
    return procs


def finish(procs, timeout=60):
    """(first output line, return code, stderr) of each worker."""
    out = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=timeout)
        out.append((stdout.strip(), p.returncode, stderr))
    return out


def test_many_writers_never_interleave_a_line(data):
    """Eight processes write lines of every length up to the limit into one FIFO that a reader drains: a line arrives whole
    or not at all, nothing is lost or doubled, and a full queue is reported and retried."""
    writers, count = 8, 150
    seen, buf = [], b""
    with relay.serving("app") as path:
        rd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        procs = workers("send", writers, data / "data", "app", count, each=lambda i: (i,))
        deadline = time.monotonic() + 120
        while True:
            assert time.monotonic() < deadline, "the writers did not finish"
            if select.select([rd], [], [], 0.05)[0]:
                buf += os.read(rd, 65536)
                *lines, buf = buf.split(b"\n")
                seen.extend(lines)
            elif all(p.poll() is not None for p in procs):
                break
        os.close(rd)
        out = finish(procs, 10)
    assert [rc for _, rc, _ in out] == [0] * writers, out
    assert len(seen) == writers * count and len(set(seen)) == len(seen)
    for line in seen:
        head, _, tail = line.decode().rpartition("/")
        assert head.startswith("gemini://w") and set(tail) == {"z"}, line[:60]  # one writer's line, whole


def test_of_many_launches_started_together_exactly_one_holds_the_fifo(data):
    for rnd in range(20):
        procs = workers("serve", 10, data / "data", "app", 0.5, 0, 0)
        out = finish(procs)
        assert [rc for _, rc, _ in out] == [0] * 10, out
        assert [line for line, _, _ in out].count("HELD") == 1, (rnd, out)
        assert not relay.fifo_path("app").exists()


def test_first_launches_of_different_apps_on_a_fresh_data_directory_all_succeed(data):
    """The run directory does not exist yet: every launch tries to make it."""
    for rnd in range(12):
        names = [f"app{i % 6}" for i in range(18)]
        out = finish(workers("serve", 18, data / f"fresh{rnd}", "", 0.3, 0, 0, apps=names))
        assert [rc for _, rc, _ in out] == [0] * 18, [e for _, _, e in out if e][:1]
        held = [(n, line) for n, (line, _, _) in zip(names, out) if line == "HELD"]
        assert sorted(n for n, _ in held) == sorted(set(names)), held  # one holder for each app


def test_a_holder_killed_while_others_start_is_replaced_by_at_most_one(data):
    for rnd in range(15):
        holder = workers("serve", 1, data / "data", "app", 60, 0, 0)[0]
        assert holder.stdout.readline().strip() == "HELD"
        procs = workers("serve", 6, data / "data", "app", 0.4, 0, 0.005 * (rnd % 5))
        holder.send_signal(signal.SIGKILL)  # while they run
        holder.wait()
        out = finish(procs)
        assert [rc for _, rc, _ in out] == [0] * 6, out
        held = [line for line, _, _ in out].count("HELD")
        assert held <= 1, (rnd, out)  # never two launches serving one app
        if not held:  # all of them saw the holder alive: the leftover FIFO is stale and the next launch replaces it
            with relay.serving("app") as path:
                assert path is not None
        assert not relay.fifo_path("app").exists()


def test_the_window_between_mkfifo_and_the_open_is_closed(data):
    """The first launch pauses right after mkfifo. Without the lock the second finds a FIFO nobody reads, takes it as stale
    and replaces it: two launches serve one app. The control (the old algorithm) shows the window is real."""
    def run(mode):
        both = workers(mode, 2, data / mode, "app", 1.5, each=lambda i: (0.8, 0) if i == 0 else (0, 0.2))
        return sorted(line for line, _, _ in finish(both))
    assert run("old") == ["HELD", "HELD"]  # the control: this is the race that was fixed
    assert run("serve") == ["HELD", "NONE"]


def test_a_launch_that_ends_between_the_open_and_the_write_is_no_traceback(data, monkeypatch):
    """Nothing read the link yet: no delivery, so the caller may start the app with it. After a delivered link: an error."""
    real = os.write
    calls = []

    def write(fd, data):
        calls.append(data)
        if len(calls) > fail_after:
            raise BrokenPipeError(32, "Broken pipe")
        return real(fd, data)

    monkeypatch.setattr(relay.os, "write", write)
    with relay.serving("app"):
        fail_after = 0
        assert relay.send("app", ["gemini://x/1", "gemini://x/2"]) is False
        calls.clear()
        fail_after = 1
        with pytest.raises(RunError, match="ended before it took every link"):
            relay.send("app", ["gemini://x/1", "gemini://x/2"])


def test_senders_racing_the_end_of_a_launch_get_an_answer_never_a_surprise(data):
    holder = workers("serve", 1, data / "data", "app", 0.6, 0, 0)[0]
    assert holder.stdout.readline().strip() == "HELD"
    answers, errors = set(), []

    def sender():
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            try:
                answers.add(relay.send("app", ["gemini://x/"]))
            except RunError as e:
                answers.add(str(e).split(" (")[0].split(": ")[-1])  # "queue is full" after the pipe fills, nothing drains it
            except Exception as e:  # noqa: BLE001  (the point of the test)
                errors.append(e)
            time.sleep(0.001)

    threads = [threading.Thread(target=sender) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
        assert not t.is_alive()
    holder.wait(10)
    assert not errors, errors
    assert False in answers  # after the launch ended, clients are told nothing runs
    assert not relay.fifo_path("app").exists()


def test_senders_racing_a_stale_replacement_get_an_answer_never_a_surprise(data):
    holder = workers("serve", 1, data / "data", "app", 60, 0, 0)[0]
    assert holder.stdout.readline().strip() == "HELD"
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    errors, stop = [], threading.Event()

    def sender():
        while not stop.is_set():
            try:
                relay.send("app", ["gemini://x/"])
            except RunError:
                pass
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=sender) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(60):  # launches replace each other's leftovers while clients keep writing
            with relay.serving("app") as path:
                assert path is not None
    finally:
        stop.set()
        for t in threads:
            t.join(30)
    assert not errors, errors


# -- the real supervisor under concurrent writers ------------------------------------------------


def test_the_supervisor_delivers_every_link_once_under_concurrent_writers(data):
    writers, count = 6, 60
    with relay.serving("app") as fifo:
        proc, _ = start(data, ["gemini"], ["/bin/sleep", "120"], fifo=fifo)
        time.sleep(1.3)
        out = finish(workers("send", writers, data / "data", "app", count, each=lambda i: (i,)), 120)
        assert [rc for _, rc, _ in out] == [0] * writers, out
        log = data / "log"
        assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) >= writers * count, 60)
        time.sleep(0.5)  # a late duplicate would show now
        proc.terminate()
        proc.wait(timeout=10)
    lines = log.read_text().splitlines()
    assert len(lines) == writers * count and len(set(lines)) == len(lines), (len(lines), len(set(lines)))


def test_the_supervisor_ends_with_the_apps_status_while_links_keep_arriving(data):
    with relay.serving("app") as fifo:
        proc, _ = start(data, ["gemini"], ["/bin/sh", "-c", "sleep 2; exit 5"], fifo=fifo)
        time.sleep(1.3)
        end = time.monotonic() + 30
        while proc.poll() is None and time.monotonic() < end:
            try:
                relay.send("app", ["gemini://x/"])
            except RunError:  # the queue fills once nothing reads it
                pass
            time.sleep(0.002)
        assert proc.wait(timeout=10) == 5  # the flood does not hold the exit up, and the status is the app's


def test_a_launcher_killed_hard_leaves_a_fifo_the_next_launch_replaces(data):
    holder = workers("serve", 1, data / "data", "app", 60, 0, 0)[0]
    assert holder.stdout.readline().strip() == "HELD"
    assert relay.send("app", ["gemini://x/"]) is True
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    assert relay.fifo_path("app").exists()  # left behind: the launcher could not clean up
    assert relay.send("app", ["gemini://x/"]) is False  # nobody reads it: a client is not fooled
    with relay.serving("app") as again:
        assert again == relay.fifo_path("app") and relay.send("app", ["gemini://x/2"]) is True


# -- a flood -------------------------------------------------------------------------------------


def children(pid):
    """The children of every thread of `pid` (the supervisor starts its helpers from a thread)."""
    out = []
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            with open(f"/proc/{pid}/task/{tid}/children") as f:
                out += [int(x) for x in f.read().split()]
    except OSError:
        pass
    return out


def state(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rpartition(")")[2].split()[0]
    except OSError:
        return None


def rss_kb(pid):
    with open(f"/proc/{pid}/status") as f:
        return next(int(line.split()[1]) for line in f if line.startswith("VmRSS"))


def test_a_flood_of_links_is_delivered_and_leaves_no_zombie_or_growth(tmp_path):
    sleepy = tmp_path / "sleepy.sh"
    sleepy.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$LOG\"\nsleep 0.05\n")
    sleepy.chmod(0o755)
    proc, fifo = start(tmp_path, ["gemini"], ["/bin/sleep", "300"], helper=sleepy)
    total = 1500
    log = tmp_path / "log"
    time.sleep(1.3)
    before = rss_kb(proc.pid)
    fd = os.open(fifo, os.O_WRONLY)
    peak = 0
    for i in range(total):
        os.write(fd, f"gemini://x/{i}\n".encode())
        if i % 25 == 0:
            peak = max(peak, len(children(proc.pid)))
    os.close(fd)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        peak = max(peak, len(children(proc.pid)))
        if log.exists() and len(log.read_text().splitlines()) >= total:
            break
        time.sleep(0.05)
    assert len(log.read_text().splitlines()) == total
    assert wait_for(lambda: len(children(proc.pid)) <= 1 and all(state(c) != "Z" for c in children(proc.pid)), 30)
    grew = rss_kb(proc.pid) - before
    print(f"flood: {total} links, peak {peak} concurrent children, supervisor RSS grew {grew} kB")
    proc.terminate()
    proc.wait(timeout=10)
    assert grew < 20000  # a leak per link would show here (1500 links)


# -- a relay that is gone ------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="the launcher holds the FIFO open itself, so a link is accepted after the relay died")
def test_a_link_for_a_dead_relay_is_not_accepted(data):
    with relay.serving("app"):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        proc.kill()
        proc.wait()
        # nothing reads the FIFO any more except the launcher's own descriptor
        assert relay.send("app", ["gemini://x/"]) is False


# -- in a real jail, with `linger` and the jail's confinement -------------------------------------


# The first process stays; later ones record their argument and their own confinement. The relay and `linger` both run in
# the jail, the relay outside the supervisor of `linger`.
CONFINED = """#!/bin/sh
conf() { grep -E '^(NoNewPrivs|Seccomp):' /proc/self/status | tr '\\n\\t' '  '; }
if [ -e /tmp/running ]; then
  echo "$1 | $(conf)" >> /home/app/links.log
  exit 0
fi
touch /tmp/running
echo "main | $(conf)" > /home/app/started
while [ ! -e /home/app/stop ]; do sleep 0.1; done
"""


@integration
@pytest.mark.parametrize("linger", [False, True])
def test_links_reach_the_app_with_the_jails_confinement_also_under_linger(sandbox, runtime, linger):
    kw = build(sandbox, runtime, schemes=("gemini",), linger=linger)
    (kw["root"] / "AppRun").write_text(CONFINED)
    (kw["root"] / "AppRun").chmod(0o755)
    fd = seccomp.open_fd(kw["perms"].userns)
    result = {}
    try:
        with relay.serving("app") as fifo:
            argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd, link_fifo=fifo)]
            thread = threading.Thread(target=lambda: result.update(proc=jail.supervise(argv, timeout=60, pass_fds=(fd,))))
            thread.start()
            assert wait_for(lambda: (kw["home"] / "started").exists(), 20)
            assert relay.send("app", [f"gemini://x/{i}" for i in range(5)])
            log = kw["home"] / "links.log"
            assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 5, 30)
    finally:
        (kw["home"] / "stop").write_text("")  # the jail ends in any case
        thread.join(30)
        os.close(fd)
    assert result["proc"].returncode == 0, result["proc"].stderr
    main = (kw["home"] / "started").read_text().split(" | ")[1].strip()
    assert "NoNewPrivs: 1" in main and "Seccomp: 2" in main
    for line in (kw["home"] / "links.log").read_text().splitlines():
        assert line.split(" | ")[1].strip() == main  # a helper has the same confinement as the app


# -- text that has no bytes -------------------------------------------------------------------------


@pytest.mark.parametrize("code", [0xD800, 0xDBFF, 0xDC7F, 0xDD00], ids=lambda c: f"U+{c:04X}")
def test_a_lone_surrogate_is_refused_not_a_traceback(data, code):
    """argv never holds one (undecodable bytes become U+DC80..U+DCFF), but JSON text can: it has no UTF-8 form."""
    link = "gemini://x/" + chr(code)
    with pytest.raises(ManifestError, match="not valid text"):
        grants.check_link(link, ("gemini",))
    with relay.serving("app"), pytest.raises(RunError, match="not valid text"):
        relay.send("app", [link])


def test_the_bytes_of_an_argument_that_is_not_utf8_round_trip(data):
    link = os.fsdecode(b"gemini://x/\xff\xfe")  # what argv holds for these bytes: U+DCFF U+DCFE
    assert grants.check_link(link, ("gemini",)) == link
    with relay.serving("app") as path:
        rd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        assert relay.send("app", [link]) is True
        assert os.read(rd, 100) == b"gemini://x/\xff\xfe\n"
        os.close(rd)


# -- the relay with every other wrapper and grant, through `runner.launch` --------------------------
#
# The same path as `appjail run`: the order the wrappers are applied in (linger, relay, Xwayland), the file descriptors
# pasta closes, the grants bound next to the FIFO, the private audio graph.


LAUNCH = runner.launch  # the real one, whatever a test puts in its place


class AppRunTree(Extractor):
    """A tree whose AppRun is `script`."""

    def __init__(self, script):
        super().__init__()
        self.script = script

    def __call__(self, image, dest, fallback=False):
        result = super().__call__(image, dest, fallback)
        (Path(dest) / "AppRun").write_text(self.script)
        (Path(dest) / "AppRun").chmod(0o755)
        return result


def run_launch(**kw):
    """runner.launch in a thread; returns (thread, result), the exit status or the exception ending up in result."""
    result = {}

    def target():
        try:
            result["code"] = LAUNCH("app", say=lambda *_: None, warn=lambda *_: None, **kw)
        except BaseException as e:  # noqa: BLE001  (reported by the test)
            result["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    return thread, result


def have(*tools):
    return pytest.mark.skipif(not all(shutil.which(t) for t in tools), reason=f"needs {', '.join(tools)} (tests/vm/packages.txt)")


XWAYLAND = have("weston", "Xwayland")

COMBINATIONS = {
    "plain": ({}, ()),
    "linger": ({"linger": True}, ()),
    "pasta": ({"network": True}, (needs_pasta,)),
    "linger+pasta": ({"linger": True, "network": True}, (needs_pasta,)),
    "private-audio": ({"audio": True}, (have("pipewire"),)),
    "linger+private-audio": ({"linger": True, "audio": True}, (have("pipewire"),)),
    # the headless weston has no wp_security_context_v1, so these apps are granted the compositor's own socket
    "xwayland": ({"display": "xwayland", "full_wayland": True}, (XWAYLAND,)),
    "linger+xwayland": ({"linger": True, "display": "xwayland", "full_wayland": True}, (XWAYLAND,)),
    "linger+xwayland+pasta+audio": ({"linger": True, "display": "xwayland", "full_wayland": True, "network": True, "audio": True},
                                    (XWAYLAND, needs_pasta, have("pipewire"))),
}


@integration
@pytest.mark.parametrize("perms,marks", [pytest.param(p, m, id=i, marks=list(m)) for i, (p, m) in COMBINATIONS.items()])
def test_links_reach_the_running_app_in_every_combination(sandbox, runtime, tmp_path, monkeypatch, perms, marks):
    import contextlib

    from .helpers import install
    perms = {"display": "none", **perms}
    install(sandbox, schemes=("gemini",), **perms)
    home = store.home_path("app")
    fake = sandbox / "fakehome"
    (fake / "docs").mkdir(parents=True)
    (fake / "doc.txt").write_text("granted")
    monkeypatch.setattr(Path, "home", lambda: fake)
    with contextlib.ExitStack() as stack:
        env = {"XDG_RUNTIME_DIR": str(runtime), "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "wayland-test"}
        extra = {"extra_files": (f"{fake}/doc.txt:ro",)}
        if perms["display"] != "none":
            rt = stack.enter_context(headless_weston(tmp_path, "appjail-rl"))
            env = {"XDG_RUNTIME_DIR": str(rt), "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "appjail-rl"}
        thread, result = run_launch(host_env=env, extract=AppRunTree(CONFINED), **extra)
        try:
            assert wait_for(lambda: (home / "started").exists() or "error" in result, 40), "the app never started"
            assert "error" not in result, result.get("error")
            links = [f"gemini://x/{i}" for i in range(4)]
            assert relay.send("app", links[:2]) is True
            assert relay.send("app", links[2:]) is True
            log = home / "links.log"
            assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 4, 40), log.read_text() if log.exists() else "no log"
        finally:
            (home / "stop").write_text("")
            thread.join(60)
        assert not thread.is_alive(), "the jail did not end after the app did"
    assert result.get("code") == 0, result
    main = (home / "started").read_text().split(" | ")[1].strip()
    assert "NoNewPrivs: 1" in main and "Seccomp: 2" in main
    got = sorted(line.split(" | ")[0] for line in (home / "links.log").read_text().splitlines())
    assert got == links
    assert {line.split(" | ")[1].strip() for line in (home / "links.log").read_text().splitlines()} == {main}
    assert not relay.fifo_path("app").exists()


# The tree is extracted once and reused, so one script serves both phases: it only records its arguments until the test
# creates /home/app/serve, then behaves as the single-instance app of CONFINED.
ONCE = """#!/bin/sh
if [ ! -e /home/app/serve ]; then
  echo "$@" > /home/app/args
  exit 0
fi
""" + CONFINED.split("\n", 1)[1]


class Console:
    def __init__(self):
        self.lines = []

    def out(self, text):
        self.lines.append(text)

    warn = out


@integration
def test_appjail_open_sends_to_a_running_app_and_starts_one_otherwise(sandbox, runtime, monkeypatch):
    from .helpers import install
    install(sandbox, schemes=("gemini",), display="none")
    home = store.home_path("app")
    env = {"XDG_RUNTIME_DIR": str(runtime), "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "wayland-test"}
    monkeypatch.setattr(runner, "launch", lambda name, args, **kw: LAUNCH(
        name, args, host_env=env, extract=AppRunTree(ONCE), **kw))
    ns = argparse.Namespace(app="app", rw=False)
    console = Console()
    # no launch running: the app is started with the link as its argument
    assert cmd_open.cmd_open(ns, ["GEMINI://x/first"], console) == 0
    assert (home / "args").read_text().strip() == "GEMINI://x/first"
    # a launch running: the link goes through the FIFO and no second app starts
    (home / "serve").write_text("")
    thread, result = run_launch(host_env=env, extract=AppRunTree(ONCE))
    try:
        assert wait_for(lambda: (home / "started").exists() or "error" in result, 40)
        assert cmd_open.cmd_open(ns, ["gemini://x/second"], console) == 0
        assert any("Sent 1 link" in line for line in console.lines)
        log = home / "links.log"
        assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 1, 30)
        assert log.read_text().startswith("gemini://x/second | ")
    finally:
        (home / "stop").write_text("")
        thread.join(60)
    assert result.get("code") == 0, result


DETACH = """#!/bin/sh
( sleep 3; touch /home/app/done ) &
exit 0
"""


@integration
@pytest.mark.parametrize("display", ["none", pytest.param("xwayland", marks=XWAYLAND)])
def test_linger_still_waits_for_a_detached_child_under_the_relay(sandbox, runtime, tmp_path, display):
    """Counting everything that ran before `linger` as infrastructure must not hide what the app leaves behind."""
    import contextlib

    from .helpers import install
    install(sandbox, schemes=("gemini",), linger=True, display=display, **({"full_wayland": True} if display != "none" else {}))
    home = store.home_path("app")
    env = {"XDG_RUNTIME_DIR": str(runtime), "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "wayland-test"}
    with contextlib.ExitStack() as stack:
        if display != "none":
            rt = stack.enter_context(headless_weston(tmp_path, "appjail-rl"))
            env = {"XDG_RUNTIME_DIR": str(rt), "LANG": "C.UTF-8", "WAYLAND_DISPLAY": "appjail-rl"}
        thread, result = run_launch(host_env=env, extract=AppRunTree(DETACH))
        thread.join(90)
        assert not thread.is_alive()
    assert result.get("code") == 0, result
    assert (home / "done").exists()  # the jail lasted until the detached child was done


# -- the relay with the D-Bus proxy, resource limits and the real portals ----------------------------

HERE = Path(__file__).parent / "portal"


def drive(home, script, links, launch_kw, before_stop=None, batches=2):
    """Run the app in a launch, send it `links` in `batches`, wait for each to be logged, then stop it; returns the result
    (the exit status or the error) of the launch."""
    thread, result = run_launch(extract=AppRunTree(script), **launch_kw)
    try:
        assert wait_for(lambda: (home / "started").exists() or "error" in result, 60), "the app never started"
        assert "error" not in result, result.get("error")
        step = max(1, len(links) // batches)
        for i in range(0, len(links), step):
            assert relay.send("app", links[i:i + step]) is True
        log = home / "links.log"
        assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) >= len(links), 60), \
            log.read_text() if log.exists() else "no links delivered"
        if before_stop:
            before_stop()
    finally:
        (home / "stop").write_text("")
        thread.join(90)
    assert not thread.is_alive(), "the jail did not end after the app did"
    return result


def logged(home):
    return [line.split(" | ", 1) for line in (home / "links.log").read_text().splitlines()]


# The same app as CONFINED, whose confinement line also records the bus address it was given.
WITH_BUS = CONFINED.replace("tr '\\n\\t' '  '; }", "tr '\\n\\t' '  '; echo \"bus=$DBUS_SESSION_BUS_ADDRESS\"; }")


@pytest.fixture
def session_bus(runtime):
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1", f"--address=unix:path={runtime}/bus"],
                              stdout=subprocess.PIPE, text=True, env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime)})
    daemon.stdout.readline()
    yield runtime / "bus"
    daemon.terminate()
    daemon.wait()


@integration
@needs_proxy
@pytest.mark.parametrize("linger", [False, True])
def test_links_reach_an_app_behind_the_filtered_bus_and_the_helper_gets_the_same_bus(sandbox, runtime, session_bus, linger):
    from .helpers import install
    install(sandbox, schemes=("gemini",), display="none", dbus_filter=("org.example.Granted",), linger=linger)
    home = store.home_path("app")
    env = {"XDG_RUNTIME_DIR": str(runtime), "LANG": "C.UTF-8", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session_bus}"}
    assert WITH_BUS != CONFINED
    links = [f"gemini://x/{i}" for i in range(4)]
    result = drive(home, WITH_BUS, links, {"host_env": env})
    assert result.get("code") == 0, result
    main = (home / "started").read_text().split(" | ")[1].strip()
    assert f"bus=unix:path=/run/user/{os.getuid()}/bus" in main  # the proxy's socket, not the host's bus
    assert {conf.strip() for _, conf in logged(home)} == {main}  # each helper has the same bus, filter and confinement
    assert sorted(link for link, _ in logged(home)) == links
    assert [p.name for p in runtime.iterdir() if p.name.startswith("appjail-")] == []  # the proxy's directory is gone
    assert not relay.fifo_path("app").exists()


def user_scope_properties(description):
    """MemoryMax, TasksMax and CPUQuotaPerSecUSec of the running user scope with this description."""
    units = subprocess.run(["systemctl", "--user", "list-units", "--type=scope", "--no-legend", "--plain", "--no-pager"],
                           capture_output=True, text=True, timeout=30).stdout
    unit = next((line.split()[0] for line in units.splitlines() if description in line), None)
    if unit is None:
        return None
    shown = subprocess.run(["systemctl", "--user", "show", unit, "-p", "MemoryMax", "-p", "TasksMax", "-p", "CPUQuotaPerSecUSec"],
                           capture_output=True, text=True, timeout=30).stdout
    return dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)


needs_user_manager = pytest.mark.skipif(
    not (shutil.which("systemd-run") and os.path.isdir(f"/run/user/{os.getuid()}/systemd")),
    reason="needs systemd-run and a systemd user session (log in through ssh or a desktop)")


@integration
@needs_user_manager
def test_links_reach_an_app_in_a_scope_with_resource_limits(sandbox):
    from .helpers import install
    install(sandbox, schemes=("gemini",), display="none", memory_max="512M", tasks_max="300", cpu_quota="300%")
    home = store.home_path("app")
    env = {"XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "LANG": "C.UTF-8"}
    seen = {}
    links = [f"gemini://x/{i}" for i in range(4)]
    result = drive(home, CONFINED, links, {"host_env": env}, before_stop=lambda: seen.update(user_scope_properties("appjail app") or {}))
    assert result.get("code") == 0, result
    assert seen.get("MemoryMax") == str(512 * 1024 * 1024) and seen.get("TasksMax") == "300", seen
    assert seen.get("CPUQuotaPerSecUSec") == "3s", seen
    assert sorted(link for link, _ in logged(home)) == links


# The single-instance app in python, which waits without forking (a shell loop would need a task for every `sleep`, and
# under the task limit that fork can fail and end the app). Each helper holds its task for a second, so a flood runs many.
SLOW_HELPER = """#!/usr/bin/python3
import os, sys, time
if os.path.exists("/tmp/running"):
    with open("/home/app/links.log", "a") as f:
        f.write(f"{sys.argv[1]} | helper\\n")
    time.sleep(1)
    sys.exit(0)
open("/tmp/running", "w").close()
open("/home/app/started", "w").write("main | app\\n")
while not os.path.exists("/home/app/stop"):
    time.sleep(0.1)
"""


@integration
@needs_user_manager
def test_the_relay_survives_a_flood_that_exhausts_the_task_limit(sandbox):
    """With tasks_max the helpers' fork can fail: the relay must go on delivering once the flood is over."""
    from .helpers import install
    install(sandbox, schemes=("gemini",), display="none", tasks_max="40")
    home = store.home_path("app")
    env = {"XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "LANG": "C.UTF-8"}

    def flood_then_one_more():
        for batch in range(6):
            relay.send("app", [f"gemini://flood/{batch}/{i}" for i in range(20)])
        time.sleep(8)  # the helpers that could start have finished
        assert relay.send("app", ["gemini://after/the/flood"]) is True
        assert wait_for(lambda: any(link == "gemini://after/the/flood" for link, _ in logged(home)), 30), \
            "the relay stopped delivering links after the task limit was hit"

    result = drive(home, SLOW_HELPER, ["gemini://first/one"], {"host_env": env}, before_stop=flood_then_one_more, batches=1)
    assert result.get("code") == 0, result


needs_portal = pytest.mark.skipif(
    not (Path("/usr/libexec/xdg-desktop-portal").exists() and Path("/usr/libexec/xdg-document-portal").exists()
         and shutil.which("fusermount3") and os.access("/dev/fuse", os.R_OK | os.W_OK)),
    reason="needs xdg-desktop-portal, its document portal and FUSE (run provision.sh)")


@pytest.fixture
def portal_stack(sandbox, runtime):
    """A private session bus with the real xdg-desktop-portal and document portal and a fake file chooser."""
    share = sandbox / "share"
    (share / "xdg-desktop-portal" / "portals").mkdir(parents=True)
    (share / "xdg-desktop-portal" / "portals" / "fake.portal").write_text(
        "[portal]\nDBusName=org.freedesktop.impl.portal.desktop.fake\n"
        "Interfaces=org.freedesktop.impl.portal.FileChooser;org.freedesktop.impl.portal.Access\nUseIn=fake\n")
    cfg = sandbox / "cfg"
    (cfg / "xdg-desktop-portal").mkdir(parents=True)
    (cfg / "xdg-desktop-portal" / "portals.conf").write_text("[preferred]\ndefault=fake\n")
    chosen = sandbox / "chosen.txt"
    chosen.write_text("hello from the host")
    log = sandbox / "backend.log"
    env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime), "XDG_DATA_DIRS": f"{share}:/usr/share",
           "XDG_CONFIG_HOME": str(cfg), "XDG_CURRENT_DESKTOP": "fake", "HOME": str(sandbox), "XDG_DATA_HOME": str(sandbox / "data")}
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1", f"--address=unix:path={runtime}/bus"],
                              stdout=subprocess.PIPE, text=True, env=env)
    daemon.stdout.readline()
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
    backend = subprocess.Popen([sys.executable, str(HERE / "fake_backend.py"), str(log), str(chosen)], stdout=subprocess.PIPE, text=True, env=env)
    assert backend.stdout.readline().strip() == "ready"
    yield env, log
    backend.terminate()
    backend.wait()
    daemon.terminate()
    daemon.wait()
    subprocess.run(["fusermount3", "-u", "-z", str(runtime / "doc")], capture_output=True)


class PortalTree(AppRunTree):
    """The single-instance app of CONFINED, whose first instance first asks the real file chooser portal for a file."""

    def __call__(self, image, dest, fallback=False):
        result = super().__call__(image, dest, fallback)
        (Path(dest) / "client.py").write_text((HERE / "client.py").read_text())
        return result


PORTAL_APP = CONFINED.replace("touch /tmp/running\n", "touch /tmp/running\n/usr/bin/python3 /app/client.py > /home/app/portal.json 2>/home/app/portal.err\n")


@integration
@needs_proxy
@needs_portal
def test_links_reach_an_app_that_uses_the_real_file_chooser_portal(sandbox, runtime, portal_stack):
    from .helpers import install
    env, backend_log = portal_stack
    install(sandbox, schemes=("gemini",), portals=True)
    home = store.home_path("app")
    links = [f"gemini://x/{i}" for i in range(4)]
    thread, result = run_launch(host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, extract=PortalTree(PORTAL_APP), **COMPOSITOR)
    try:
        assert wait_for(lambda: (home / "started").exists() or "error" in result, 60), result
        assert "error" not in result, result.get("error")
        assert relay.send("app", links) is True
        log = home / "links.log"
        assert wait_for(lambda: log.exists() and len(log.read_text().splitlines()) == 4, 60)
    finally:
        (home / "stop").write_text("")
        thread.join(90)
    assert not thread.is_alive()
    assert result.get("code") == 0, result
    portal_out = json.loads((home / "portal.json").read_text().strip().splitlines()[-1])
    assert portal_out["response"] == 0 and portal_out["content"] == "hello from the host", (portal_out, (home / "portal.err").read_text())
    assert backend_log.read_text().split() == ["app.appjail.app"]  # the portal knew the app, from appjail's identity only
    main = (home / "started").read_text().split(" | ")[1].strip()
    assert "NoNewPrivs: 1" in main and "Seccomp: 2" in main
    assert {conf.strip() for _, conf in logged(home)} == {main}
    assert sorted(link for link, _ in logged(home)) == links
    assert [p.name for p in runtime.iterdir() if p.name.startswith("appjail-")] == []
