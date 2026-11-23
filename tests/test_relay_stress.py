# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The link relay under load and at its edges: agreement of its two checks, concurrent writers, a flood, a dead relay,
a killed launcher, racing launches, and the relay combined with `linger` in a real jail. The basic behaviour is in
test_relay.py."""

import ast
import os
import random
import select
import signal
import subprocess
import sys
import threading
import time

import pytest

from appjail import grants, jail, relay, runtimejail, seccomp
from appjail.errors import RunError
from appjail.manifest import ManifestError

from .helpers import build, integration, wait_for


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
           "gemini://\udcff", "file:///etc/passwd", "javascript:alert(1)"]
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
