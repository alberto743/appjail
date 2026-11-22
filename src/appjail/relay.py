# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Links for a running app: a FIFO from the host into the jail, and the relay inside the jail that reads it.

An app granted URL `schemes` runs under a small supervisor, written in Python and run inside the jail by the system
interpreter (like linger.py). It starts the app as its child and reads one link per line from a FIFO. For each link it
starts `AppRun LINK` in the jail, so the app's own single-instance handover finds the running instance (a second jail
could not: every jail has its own pid namespace). Why: docs/decisions/desktop/url-handlers.md.

The FIFO is a node in appjail's private run directory and only that node is bound into the jail, so the app never sees a
directory it could swap. The launcher holds the FIFO open for the whole launch: a client that can open it for writing
knows an appjail launch is alive, a link written while the app starts waits in the pipe, and a FIFO left by a launcher
that was killed has no reader and is replaced. A line is at most LINE_MAX bytes, which a pipe writes atomically.
"""

import contextlib
import errno
import os
import stat

from . import grants, store
from .errors import RunError

PYTHON = "/usr/bin/python3"
JAIL_FIFO = "/run/appjail-link"
JAIL_APPRUN = "/app/AppRun"
LINE_MAX = grants.MAX_LINK_BYTES + 1  # the link and its newline; PIPE_BUF is 4096 on Linux

RELAY = '''\
import os, signal, subprocess, sys, threading, time

fifo, helper, schemes = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
cmd = sys.argv[4:]
MAX, SETTLE = @MAX@, 1.0
fd = os.open(fifo, os.O_RDWR)
app = subprocess.Popen(cmd)
born = time.monotonic()
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, lambda n, _f: app.poll() is None and app.send_signal(n))

def good(link):
    scheme, colon, _ = link.partition(":")
    return (colon and 0 < len(link.encode("utf-8", "replace")) <= MAX and scheme.lower() in schemes
            and not any(ord(c) < 32 or ord(c) == 127 for c in link))

def serve():
    buf = b""
    while True:
        data = os.read(fd, 65536)
        if not data:
            return
        buf += data
        while b"\\n" in buf:
            line, _, buf = buf.partition(b"\\n")
            link = line.decode("utf-8", "replace")
            if len(line) > MAX or not good(link):
                print("appjail: a link was refused", file=sys.stderr)
                continue
            time.sleep(max(0.0, born + SETTLE - time.monotonic()))
            p = subprocess.Popen([helper, link], stdin=subprocess.DEVNULL)
            threading.Thread(target=p.wait, daemon=True).start()
        if len(buf) > MAX:
            buf = b""

threading.Thread(target=serve, daemon=True).start()
code = app.wait()
sys.exit(code if code >= 0 else 128 - code)
'''.replace("@MAX@", str(grants.MAX_LINK_BYTES))


def wrap(command, schemes):
    """The command run under the relay, which reads JAIL_FIFO and checks each link against `schemes` again."""
    if not os.access(PYTHON, os.X_OK):
        raise RunError("URL schemes need python3 in /usr/bin")
    return [PYTHON, "-I", "-c", RELAY, JAIL_FIFO, JAIL_APPRUN, ",".join(schemes), *command]


def fifo_path(name):
    return store.data_dir() / "run" / f"{name}.link"


def _reader_alive(path):
    """Whether something has the FIFO open for reading (a write end can be opened only then); None if there is no FIFO."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False
        raise
    os.close(fd)
    return True


@contextlib.contextmanager
def serving(name):
    """Create the app's link FIFO and hold it open until the launch ends; yields its path, or None when another launch of
    the app already holds one (that launch's relay serves the links). A FIFO nobody reads, left by a killed launcher, is replaced."""
    path = fifo_path(name)
    store.make_private(path.parent)
    for _ in range(2):
        alive = _reader_alive(path)
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


def send(name, links):
    """Write each link to the running app's FIFO. False when no launch of the app is running; RunError when it is but
    cannot take the link."""
    path = fifo_path(name)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False
        raise RunError(f"cannot reach the running {name}: {e.strerror}") from e
    try:
        info = os.fstat(fd)
        if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid():
            raise RunError(f"{path} is not the link queue of {name}")
        for link in links:
            data = link.encode("utf-8", "surrogateescape") + b"\n"
            if len(data) > LINE_MAX:
                raise RunError("the link is too long")
            try:
                os.write(fd, data)
            except BlockingIOError:
                raise RunError(f"{name} is not taking links (its queue is full)") from None
    finally:
        os.close(fd)
    return True
