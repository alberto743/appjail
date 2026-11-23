# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The link relay under load and at its edges: agreement of its two checks, concurrent writers, a flood, a dead relay,
a killed launcher, racing launches, and the relay combined with `linger` in a real jail. The basic behaviour is in
test_relay.py."""

import ast
import multiprocessing
import os
import random
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


def start(tmp_path, schemes, command, helper=None):
    """The supervisor, run with plain python, over a FIFO in tmp_path."""
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


# -- concurrent writers -------------------------------------------------------------------------


def _writer(name, seed, count, ready):
    rng = random.Random(seed)
    ready.wait()
    for i in range(count):
        n = rng.choice([1, 50, 1000, 3900, 3980])
        while True:
            try:
                relay.send(name, [f"gemini://w{seed}/{i}/" + "z" * n])
                break
            except RunError as e:  # a full queue is reported, and a refused write leaves nothing half written
                assert "queue is full" in str(e)
                time.sleep(0.003)


def test_many_writers_never_interleave_a_line(data):
    ctx = multiprocessing.get_context("fork")
    writers, count = 8, 150
    seen, stop = [], threading.Event()
    with relay.serving("app") as path:
        rd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

        def drain():
            buf = b""
            while True:
                try:
                    chunk = os.read(rd, 65536)
                except BlockingIOError:
                    chunk = b""
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    seen.extend(lines)
                elif stop.is_set():
                    break
                else:
                    time.sleep(0.002)

        reader = threading.Thread(target=drain)
        reader.start()
        ready = ctx.Event()
        procs = [ctx.Process(target=_writer, args=("app", s, count, ready)) for s in range(writers)]
        for p in procs:
            p.start()
        ready.set()
        for p in procs:
            p.join(120)
            assert p.exitcode == 0
        stop.set()
        reader.join(30)
        os.close(rd)
    assert len(seen) == writers * count
    for line in seen:
        head, _, tail = line.decode().rpartition("/")
        assert head.startswith("gemini://w") and set(tail) == {"z"}, line[:60]  # one writer's line, whole
    assert len(set(seen)) == len(seen)


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


# -- a killed launcher ----------------------------------------------------------------------------


HOLDER = """
import os, sys, time
os.environ["APPJAIL_DATA_DIR"] = sys.argv[1]
from appjail import relay
with relay.serving("app") as p:
    print(p, flush=True)
    time.sleep(120)
"""


def test_a_launcher_killed_hard_leaves_a_fifo_the_next_launch_replaces(data):
    env = dict(os.environ, APPJAIL_DATA_DIR=str(data / "data"), PYTHONPATH=os.pathsep.join(sys.path))
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(data / "data")], env=env, stdout=subprocess.PIPE, text=True)
    path = holder.stdout.readline().strip()
    assert path and relay.send("app", ["gemini://x/"]) is True
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    assert os.path.exists(path)  # left behind: the launcher could not clean up
    assert relay.send("app", ["gemini://x/"]) is False  # nobody reads it: a client is not fooled
    with relay.serving("app") as again:
        assert str(again) == path and relay.send("app", ["gemini://x/2"]) is True


# -- racing launches ------------------------------------------------------------------------------


def _launch(data_dir, barrier, out):
    os.environ["APPJAIL_DATA_DIR"] = data_dir
    barrier.wait()
    with relay.serving("app") as path:
        out.put(path is not None)
        time.sleep(1.0)


def test_of_many_launches_started_together_exactly_one_holds_the_fifo(data):
    ctx = multiprocessing.get_context("fork")
    for _ in range(5):
        n = 12
        barrier, out = ctx.Barrier(n), ctx.Queue()
        procs = [ctx.Process(target=_launch, args=(str(data / "data"), barrier, out)) for _ in range(n)]
        for p in procs:
            p.start()
        got = [out.get(timeout=30) for _ in range(n)]
        for p in procs:
            p.join(30)
        assert got.count(True) == 1, got
        assert not relay.fifo_path("app").exists()


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
