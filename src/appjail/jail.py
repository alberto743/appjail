# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""bwrap argument builders and runners. Every untrusted step runs through here.

Argument builders are pure functions so they can be unit-tested without bwrap.
"""

import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import manifest, seccomp, store
from .errors import JailError, RunError
from .textsafe import clean

FETCHER = Path(__file__).with_name("fetcher.py")
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64")
ETC_FILES = ("/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf", "/etc/gai.conf", "/etc/localtime")
ETC_DIRS = ("/etc/ssl", "/etc/ca-certificates")
SAFE_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


class OutputTooLarge(JailError):
    """The watched output directory or an output stream outgrew its limits and the jailed command was killed."""


# pasta answers DNS sent to PASTA_DNS inside the namespace by asking the host's resolver, so the jail never needs the
# host's loopback stub resolver (127.0.0.53) and its resolv.conf names only this address.
PASTA_DNS = "169.254.1.53"
PASTA_ARGS = ("--config-net", "--quiet", "--no-map-gw", "--dns-forward", PASTA_DNS,
              "-t", "none", "-u", "none", "-T", "none", "-U", "none")
NO_PASTA = "pasta (package passt) is not installed: network jails share the host network, including services on localhost"
_warned_no_pasta = False
_warn = None  # the running command's console.warn (see warn_with)


def warn_with(warn):
    """Send this module's warnings to `warn`, the console of the command that starts now (None: to stderr), which is
    told again even if an earlier command in this process was told already: the jails run too deep to be handed one."""
    global _warn, _warned_no_pasta
    _warn, _warned_no_pasta = warn, False


def find_pasta():
    return shutil.which("pasta")


def net_wrap(argv, required=False, fd_files=None, lifeline=None):
    """Run a network jail's bwrap inside a private network namespace made by pasta.

    pasta gives the namespace outbound access through ordinary host sockets, but no path to the host's loopback
    (no port forwarding, no gateway mapping), so the jail cannot reach services bound to localhost. Without
    pasta the jail keeps sharing the host network (warned once). argv is a complete bwrap command line that
    uses --share-net, which then shares pasta's namespace and not the host's. required (an app's jail, which runs
    untrusted code): raise RunError instead of falling back to the host network. pasta closes every inherited
    descriptor, so fd_files ({fd number: host path, or (shell redirect operator, host path)}) are opened inside
    the namespace for bwrap (--seccomp N, and the portal's --json-status-fd / --block-fd through FIFOs): the
    caller keeps those files private and removes them after the run. Descriptor numbers must be one digit (dash).
    lifeline: path of a Lifeline FIFO; when the launcher dies the jail is killed (see Lifeline).
    """
    global _warned_no_pasta
    pasta = find_pasta()
    if pasta is None and required:
        raise RunError("network access needs pasta (package passt) to keep the app off the host's loopback; "
                       "install it, or grant network_host (`appjail perms APP --allow network_host`)")
    if pasta is None:
        if not _warned_no_pasta:
            _warned_no_pasta = True
            if _warn:
                _warn(NO_PASTA)
            else:
                print(f"! warning: {NO_PASTA}", file=sys.stderr)
        return argv
    if not fd_files and not lifeline:
        return [pasta, *PASTA_ARGS, "--", *argv]
    items = [(fd, *(spec if isinstance(spec, tuple) else ("<", spec))) for fd, spec in (fd_files or {}).items()]
    if any(not 0 <= fd <= 9 for fd, _, _ in items):
        raise RunError("net_wrap: descriptor numbers must be a single digit")
    script = (_watchdog(lifeline) if lifeline else "") + "".join(f"p{i}=$1; shift; " for i in range(len(items)))
    script += 'exec "$@" ' + " ".join(f'{fd}{op}"$p{i}"' for i, (fd, op, _) in enumerate(items))
    return [pasta, *PASTA_ARGS, "--", "/bin/sh", "-c", script, "sh", *(path for _, _, path in items), *argv]


class Lifeline:
    """A FIFO held open by the launcher, so a jail behind pasta can notice that the launcher died.

    pasta runs its command as pid 1 of a pid namespace of its own and keeps running it when pasta or appjail is killed
    (bwrap's --die-with-parent does not follow pasta's namespace), so an app with `network` would outlive appjail after
    a SIGKILL. The launcher holds the FIFO open read-write; a watcher inside the namespace reads it, sees end-of-file
    when the launcher's last descriptor closes (a clean end of the run, or sudden death) and kills the jail. The host
    pid cannot be polled instead: the namespace has its own /proc. The kernel closes the descriptor on death, but the
    FIFO's (empty) directory stays behind in that case; it lives in the runtime directory.
    """

    def __init__(self, parent=None):
        self.dir = tempfile.mkdtemp(prefix="appjail-life-", dir=parent or None)
        self.path = os.path.join(self.dir, "fifo")
        os.mkfifo(self.path, 0o600)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CLOEXEC)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _watchdog(fifo):
    """Shell prefix: when the lifeline FIFO reaches end-of-file, kill every process of the namespace but pid 1 (which
    exec'd bwrap and exits with its child). Only if this shell is pid 1 of a private pid namespace: `kill -1` outside
    one would hit all of the user's processes."""
    return (f'( cat < {shlex.quote(fifo)}; if [ "$$" = 1 ]; then for i in 1 2 3 4 5; do kill -KILL -1; sleep 0.2; done; fi ) '
            '>/dev/null 2>&1 & ')


def find_bwrap():
    path = shutil.which("bwrap")
    if not path:
        raise JailError("bwrap (bubblewrap) is not installed")
    return path


def system_args():
    """Read-only system: merged-usr symlinks are recreated, real dirs are bind-mounted."""
    args = []
    for d in SYSTEM_DIRS:
        if os.path.islink(d):
            args += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            args += ["--ro-bind", d, d]
    return args


def _pasta_resolv_conf():
    path = store.data_dir() / "resolv.conf.pasta"
    text = f"nameserver {PASTA_DNS}\n"
    if not path.is_file() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        store.atomic_write(path, text)
    return path


def etc_args(private_net=False):
    """Read-only /etc entries; private_net: the jail runs in a pasta namespace (see net_wrap), so DNS goes through it."""
    args = []
    for f in ETC_FILES:
        if os.path.exists(f):
            args += ["--ro-bind", os.path.realpath(f), f]
    for d in ETC_DIRS:
        if os.path.isdir(d):
            args += ["--ro-bind", d, d]
    if private_net and find_pasta():
        args += ["--ro-bind", str(_pasta_resolv_conf()), "/etc/resolv.conf"]
    elif os.path.exists("/etc/resolv.conf"):  # usually a symlink into /run: bind its content, not the link
        args += ["--ro-bind", os.path.realpath("/etc/resolv.conf"), "/etc/resolv.conf"]
    return args


def common_args():
    """The base of every helper jail (download, extraction, git, gh, icon conversion, D-Bus proxy). No nested user
    namespaces: none of these programs needs one, and they are where most kernel privilege escalations start."""
    args = ["--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent", "--new-session", "--cap-drop",
            "ALL", "--clearenv"]
    for k, v in SAFE_ENV.items():
        args += ["--setenv", k, v]
    return args + system_args() + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]


def download_args(stage_dir, command, fetcher=FETCHER):
    """Network-only jail: no host files except the read-only fetcher and the staging dir."""
    return (common_args() + ["--share-net"] + etc_args(private_net=True)
            + ["--ro-bind", str(fetcher), "/fetcher.py", "--bind", str(stage_dir), "/stage"]
            + ["--remount-ro", "/", "--chdir", "/stage", "--"] + command)


def tree_usage(path):
    """(disk bytes, entries) under path, never following symlinks."""
    total = count = 0
    stack = [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    st = e.stat(follow_symlinks=False)
                    total += st.st_blocks * 512
                    count += 1
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
        except OSError:
            continue
    return total, count


OUTPUT_KEEP = 16 * 1024  # bytes kept from the start and from the end of each output stream
OUTPUT_CAP = 64 * 1024 * 1024  # a stream longer than this kills the jailed command


class _Capture(threading.Thread):
    """Drains a pipe, keeping only its first and last `keep` bytes, and counts the rest."""

    def __init__(self, pipe, keep):
        super().__init__(daemon=True)
        self.pipe, self.keep, self.head, self.tail, self.total = pipe, keep, b"", b"", 0

    def run(self):
        with self.pipe:
            while chunk := self.pipe.read1(65536):
                self.total += len(chunk)
                room = self.keep - len(self.head)
                if room > 0:
                    self.head += chunk[:room]
                    chunk = chunk[room:]
                self.tail = (self.tail + chunk)[-self.keep:]

    def text(self):
        omitted = self.total - len(self.head) - len(self.tail)
        mid = f"\n[... {omitted} bytes omitted ...]\n".encode() if omitted > 0 else b""
        return (self.head + mid + self.tail).decode("utf-8", errors="replace")


def supervise(argv, timeout=1800, watch=None, env=None, pass_fds=(), max_output=OUTPUT_CAP, keep=OUTPUT_KEEP):
    """Run argv; kill it when the timeout passes, the watched tree outgrows its limits or an output stream passes max_output.

    watch is (directory, max_bytes, max_entries). Returns CompletedProcess (text, captured: the first and last
    keep bytes of each stream, decoded with replacement characters).
    """
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env or {"PATH": "/usr/bin:/bin"}, start_new_session=True, pass_fds=pass_fds)
    captures = (_Capture(proc.stdout, keep), _Capture(proc.stderr, keep))
    for c in captures:
        c.start()
    deadline = time.monotonic() + timeout
    reason = None
    try:
        while reason is None:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > deadline:
                reason = "timed out"
            elif any(c.total > max_output for c in captures):
                reason = "output too large"
            elif watch:
                used, entries = tree_usage(watch[0])
                if used > watch[1] or entries > watch[2]:
                    reason = "output too large"
    except BaseException:
        reason = "interrupted"
        raise
    finally:
        if reason:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        for c in captures:
            c.join(timeout=5)
    if reason is None and any(c.total > max_output for c in captures):
        reason = "output too large"
    if reason:
        raise (OutputTooLarge if reason == "output too large" else JailError)(f"jailed command aborted: {reason}")
    return subprocess.CompletedProcess(argv, proc.returncode, captures[0].text(), captures[1].text())


PASTA_SECCOMP_FD = 9  # behind pasta the filter is opened inside its namespace (see net_wrap: one digit only)


def run(args, timeout=1800, watch=None):
    """Run bwrap with a minimal host environment and the seccomp filter of the app jail (without the userns grant)."""
    if "--share-net" in args and find_pasta():
        # pasta closes inherited descriptors: the filter reaches bwrap through a private file instead
        fd, path = tempfile.mkstemp(prefix="appjail-seccomp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(seccomp.program(False))
            argv = net_wrap([find_bwrap(), "--seccomp", str(PASTA_SECCOMP_FD), *args],
                            fd_files={PASTA_SECCOMP_FD: path})
            return supervise(argv, timeout=timeout, watch=watch)
        finally:
            os.unlink(path)
    fd = seccomp.open_fd(False)
    try:
        argv = [find_bwrap(), "--seccomp", str(fd), *args]
        return supervise(net_wrap(argv) if "--share-net" in args else argv, timeout=timeout, watch=watch, pass_fds=(fd,))
    finally:
        os.close(fd)


def extract_args(appimage, outdir, command, tools=()):
    """No network, root read-only; the AppImage is read-only and only outdir is writable.

    tools: (host path, path in the jail) pairs bound read-only, for pinned helper binaries.
    """
    extra = [a for host, dest in tools for a in ("--ro-bind", str(host), dest)]
    return (common_args() + ["--ro-bind", str(appimage), "/app.AppImage", *extra, "--bind", str(outdir), "/out",
                             "--remount-ro", "/", "--chdir", "/out", "--"] + command)


def download(url, stage_dir, filename, expected_size):
    """Download url into stage_dir/filename inside the network-only jail."""
    cmd = ["/usr/bin/python3", "-I", "/fetcher.py", url, f"/stage/{filename}", str(int(expected_size))]
    proc = run(download_args(stage_dir, cmd))
    if proc.returncode != 0:
        raise JailError("download failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
    return Path(stage_dir) / filename


def _fetcher_json(args, stage_dir):
    """Run the fetcher in the network-only jail with `args` and return its one JSON line, checked and cleaned."""
    proc = run(download_args(stage_dir, ["/usr/bin/python3", "-I", "/fetcher.py", *args]))
    if proc.returncode != 0:
        raise JailError("download failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise JailError("the fetcher gave no usable answer") from None
    if not isinstance(data, dict):
        raise JailError("the fetcher gave no usable answer")
    return data


def _opt_str(data, key, limit=256):
    value = data.get(key)
    return (clean(value, limit) or None) if isinstance(value, str) else None  # nothing left after cleaning: no value


def download_url(url, stage_dir, filename, max_size):
    """Download any https URL (see fetcher.py --any). Returns (path, info) where info holds `size`, `final_url`,
    `http_hop` (a redirect went through plain http), `etag` and `last_modified` as the server said them."""
    data = _fetcher_json(["--any", url, f"/stage/{filename}", str(int(max_size))], stage_dir)
    size = data.get("size")
    if type(size) is not int or size < 0:
        raise JailError("the fetcher gave no usable answer")
    info = {"size": size, "final_url": _opt_str(data, "final_url", 2048) or url,
            "http_hop": data.get("http_hop") is True, "etag": _opt_str(data, "etag"),
            "last_modified": _opt_str(data, "last_modified")}
    return Path(stage_dir) / filename, info


def check_url(url, stage_dir, etag=None, last_modified=None):
    """The cheap changed/unchanged test of fetcher.py --check, as a dict with a `status` of "unchanged",
    "fingerprint" (plus `size`, `chunks`, `etag`, `last_modified`) or "no-range"."""
    args = ["--check", url]
    if etag or last_modified:
        args.append(etag or "")
        if last_modified:
            args.append(last_modified)
    data = _fetcher_json(args, stage_dir)
    status = data.get("status")
    if status == "unchanged":
        return {"status": "unchanged"}
    out = {"status": status, "etag": _opt_str(data, "etag"), "last_modified": _opt_str(data, "last_modified")}
    if status == "fingerprint":
        size, chunks = data.get("size"), data.get("chunks")
        if type(size) is not int or size < 1 or not isinstance(chunks, str) or not manifest.SHA256_RE.fullmatch(chunks):
            raise JailError("the fetcher gave no usable answer")
        return out | {"size": size, "chunks": chunks}
    if status == "no-range":
        return out
    raise JailError("the fetcher gave no usable answer")


# -- git jail (manifest history) ------------------------------------------------------

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}


def local_git_args(workdir, command):
    """No network: git on a local repository. Only workdir (at /work) is visible and writable; git's own config
    is neutralised."""
    env = []
    for k, v in GIT_ENV.items():
        env += ["--setenv", k, v]
    return (common_args() + env
            + ["--bind", str(workdir), "/work", "--remount-ro", "/", "--chdir", "/work", "--"] + command)
