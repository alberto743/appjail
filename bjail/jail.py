# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""bwrap argument builders and runners. Every untrusted step runs through here.

Argument builders are pure functions so they can be unit-tested without bwrap.
"""

import os
import shutil
import signal
import stat
import sys
import subprocess
import time
from pathlib import Path

from . import manifest

FETCHER = Path(__file__).with_name("fetcher.py")
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64")
ETC_FILES = ("/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf", "/etc/gai.conf", "/etc/localtime")
ETC_DIRS = ("/etc/ssl", "/etc/ca-certificates")
SAFE_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


class JailError(Exception):
    pass


# pasta answers DNS sent to PASTA_DNS inside the namespace by asking the host's resolver, so the jail never needs the
# host's loopback stub resolver (127.0.0.53) and its resolv.conf names only this address.
PASTA_DNS = "169.254.1.53"
PASTA_ARGS = ("--config-net", "--quiet", "--no-map-gw", "--dns-forward", PASTA_DNS,
              "-t", "none", "-u", "none", "-T", "none", "-U", "none")
_warned_no_pasta = False


def find_pasta():
    return shutil.which("pasta")


def net_wrap(argv):
    """Run a network jail's bwrap inside a private network namespace made by pasta.

    pasta gives the namespace outbound access through ordinary host sockets, but no path to the host's loopback
    (no port forwarding, no gateway mapping), so the jail cannot reach services bound to localhost. Without
    pasta the jail keeps sharing the host network (warned once). argv is a complete bwrap command line that
    uses --share-net, which then shares pasta's namespace and not the host's.
    """
    global _warned_no_pasta
    pasta = find_pasta()
    if pasta is None:
        if not _warned_no_pasta:
            _warned_no_pasta = True
            print("Warning: pasta (package passt) is not installed: network jails share the host network, "
                  "including services on localhost.", file=sys.stderr)
        return argv
    return [pasta, *PASTA_ARGS, "--", *argv]


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
    from . import store
    path = store.data_dir() / "resolv.conf.pasta"
    text = f"nameserver {PASTA_DNS}\n"
    if not path.is_file() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
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
    # resolv.conf is usually a symlink into /run; bind its content, not the link.
    elif os.path.exists("/etc/resolv.conf"):
        args += ["--ro-bind", os.path.realpath("/etc/resolv.conf"), "/etc/resolv.conf"]
    return args


def common_args():
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
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


def supervise(argv, timeout=1800, watch=None, env=None, pass_fds=()):
    """Run argv; kill it when the timeout passes or the watched tree outgrows its limits.

    watch is (directory, max_bytes, max_entries). Returns CompletedProcess (text, captured).
    """
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env or {"PATH": "/usr/bin:/bin"}, start_new_session=True,
                            pass_fds=pass_fds)
    deadline = time.monotonic() + timeout
    reason = None
    while reason is None:
        try:
            out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() > deadline:
            reason = "timed out"
        elif watch:
            used, entries = tree_usage(watch[0])
            if used > watch[1] or entries > watch[2]:
                reason = "output too large"
    if reason:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise JailError(f"jailed command aborted: {reason}")
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run(args, timeout=1800, watch=None):
    """Run bwrap with a minimal host environment."""
    argv = [find_bwrap(), *args]
    return supervise(net_wrap(argv) if "--share-net" in args else argv, timeout=timeout, watch=watch)


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
        from .textsafe import clean
        raise JailError("download failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
    return Path(stage_dir) / filename


# -- runtime jail ------------------------------------------------------------------

APP_HOME = "/home/app"
APP_DIR = "/app"
RUNTIME_ETC = ("/etc/fonts", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/localtime",
               "/etc/alternatives")
GPU_RO = ("/sys/dev/char", "/sys/devices", "/usr/share/glvnd", "/usr/share/vulkan", "/etc/vulkan", "/etc/glvnd")


class RunError(Exception):
    pass


def _guard_dirs():
    from . import store
    return [store.data_dir().resolve(), store.config_dir().resolve()]


def dir_binds(dirs, home):
    """Bind arguments for permissions.dirs. Refuses anything that would expose bjail's own files."""
    args = []
    for entry in dirs:
        path, _, mode = entry.partition(":")
        host = Path(home) / path[2:] if path.startswith("~/") else Path(path)
        dest = f"{APP_HOME}/{path[2:]}" if path.startswith("~/") else path
        try:
            real = host.resolve(strict=True)
        except OSError:
            raise RunError(f"granted directory does not exist: {host}") from None
        home_real = Path(home).resolve()
        if real == home_real or real in home_real.parents:
            raise RunError(f"granted directory {host} would expose the whole home directory")
        for guard in _guard_dirs():
            if real == guard or guard in real.parents or real in guard.parents:
                raise RunError(f"granted directory {host} would expose bjail's own data")
        try:
            rel = real.relative_to(home_real)
        except ValueError:
            rel = None
        why = manifest.sensitive_reason(f"~/{rel}" if rel else str(real), mode)
        if why:
            raise RunError(f"granted directory {host} is refused: {why}")
        args += ["--bind" if mode == "rw" else "--ro-bind", str(real), dest]
    return args


def file_binds(files, home):
    """(bwrap arguments, in-jail paths) for single files granted for one run: PATH or PATH:rw, absolute.

    Only the file itself is bound, read-only unless :rw. The same policy as for directories applies to the
    resolved path, and only regular files are accepted. Files below the real home appear under the app's home.
    """
    args, dests = [], []
    home_real = Path(home).resolve()
    for entry in files:
        path, mode = (entry[:-3], "rw") if entry.endswith(":rw") else (entry[:-3] if entry.endswith(":ro") else entry, "")
        try:
            real = Path(path).resolve(strict=True)
            regular = stat.S_ISREG(real.stat().st_mode)
        except OSError:
            raise RunError(f"granted file does not exist: {path}") from None
        if not regular:
            raise RunError(f"granted path is not a regular file: {path}")
        for guard in _guard_dirs():
            if real == guard or guard in real.parents:
                raise RunError(f"granted file {path} would expose bjail's own data")
        try:
            rel = real.relative_to(home_real)
        except ValueError:
            rel = None
        why = manifest.sensitive_reason(f"~/{rel}" if rel else str(real), mode)
        if why:
            raise RunError(f"granted file {path} is refused: {why}")
        dest = f"{APP_HOME}/{rel}" if rel else str(real)
        args += ["--bind" if mode == "rw" else "--ro-bind", str(real), dest]
        dests.append(dest)
    return args, dests


XWAYLAND_PATHS = ("/usr/bin/Xwayland", "/bin/Xwayland")
# Runs inside the jail: a rootless Xwayland of its own, a client of the (restricted) Wayland socket. Its X11 socket
# lives in the jail's private /tmp and abstract namespace, so no other app and no host X server is involved.
XWAYLAND_SCRIPT = (
    'f=/tmp/.bjail-display; x="$1"; shift\n'
    'WAYLAND_DISPLAY=wayland-0 "$x" -rootless -nolisten tcp -displayfd 3 3>"$f" >/dev/null 2>&1 &\n'
    'i=0; while [ ! -s "$f" ] && [ "$i" -lt 100 ]; do sleep 0.05; i=$((i+1)); done\n'
    'n=$(cat "$f"); [ -n "$n" ] || { echo "bjail: Xwayland did not start" >&2; exit 1; }\n'
    'DISPLAY=":$n" exec "$@"')


def xwayland_command(command):
    """Wrap the app command so a private Xwayland is running before it starts."""
    for path in XWAYLAND_PATHS:
        if os.access(path, os.X_OK):
            return ["/bin/sh", "-c", XWAYLAND_SCRIPT, "sh", path, *command]
    raise RunError("display = xwayland needs the Xwayland binary in /usr/bin (package xwayland)")


def runtime_args(*, root, home, etc_dir, perms, uid, host_env, command, host_home, dbus_socket=None, wayland_socket=None, seccomp_fd=None,
                 portal_docs=None, status_fd=None, block_fd=None, files=()):
    """Complete bwrap argv (after the bwrap binary) for running an extracted AppImage.

    Pure function of its inputs: nothing is read from the process environment. Anything the
    manifest asks for but bjail cannot enforce yet is refused instead of ignored.
    """
    xwayland = perms.display == "xwayland"
    if xwayland:
        command = xwayland_command(command)
    if (perms.dbus_filter or perms.dbus_own or perms.portals) and not dbus_socket:
        raise RunError("dbus_filter, dbus_own and portals need the filtered bus socket from bjail.dbusproxy")
    if perms.portals and not portal_docs:
        raise RunError("portals need the document portal's directory for this app (bjail.portal.doc_dir)")

    rt = f"/run/user/{uid}"
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--hostname", "bjail"]
    if not perms.userns:
        args += ["--unshare-user", "--disable-userns"]
    if seccomp_fd is not None:
        args += ["--seccomp", str(seccomp_fd)]
    if perms.network:
        args.append("--share-net")
    args += system_args()
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
             "--perms", "0700", "--dir", "/run/user", "--perms", "0700", "--dir", rt]
    args += ["--ro-bind", str(Path(etc_dir) / "passwd"), "/etc/passwd",
             "--ro-bind", str(Path(etc_dir) / "group"), "/etc/group"]
    for f in RUNTIME_ETC:
        if os.path.exists(f):
            args += ["--ro-bind", os.path.realpath(f), f]
    if perms.network:
        args += etc_args()
    args += ["--ro-bind", str(root), APP_DIR, "--bind", str(home), APP_HOME]

    host_rt = host_env.get("XDG_RUNTIME_DIR", "")
    wl = host_env.get("WAYLAND_DISPLAY", "wayland-0")
    if wayland_socket:
        sock = Path(wayland_socket)
    else:
        if "/" in wl or not wl or not host_rt:
            raise RunError("no usable Wayland session (XDG_RUNTIME_DIR / WAYLAND_DISPLAY)")
        sock = Path(host_rt) / wl
    if not sock.is_socket():
        raise RunError(f"Wayland socket not found: {sock}")
    args += ["--ro-bind", str(sock), f"{rt}/wayland-0"]

    env = {
        "PATH": f"{APP_DIR}/usr/bin:/usr/local/bin:/usr/bin:/bin", "HOME": APP_HOME, "USER": "app",
        "LOGNAME": "app", "SHELL": "/bin/sh", "LANG": host_env.get("LANG") or "C.UTF-8",
        "XDG_RUNTIME_DIR": rt, "APPDIR": APP_DIR, "APPIMAGE_EXTRACT_AND_RUN": "1", "TMPDIR": "/tmp",
    }
    if xwayland:  # the app only sees X11; WAYLAND_DISPLAY is set for the Xwayland process alone
        env.update({"XDG_SESSION_TYPE": "x11", "GDK_BACKEND": "x11", "QT_QPA_PLATFORM": "xcb",
                    "ELECTRON_OZONE_PLATFORM_HINT": "x11", "SDL_VIDEODRIVER": "x11"})
    else:
        env.update({"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland", "GDK_BACKEND": "wayland",
                    "QT_QPA_PLATFORM": "wayland", "MOZ_ENABLE_WAYLAND": "1",
                    "ELECTRON_OZONE_PLATFORM_HINT": "wayland", "SDL_VIDEODRIVER": "wayland"})
    if host_env.get("TZ"):
        env["TZ"] = host_env["TZ"]

    if dbus_socket:
        args += ["--ro-bind", str(dbus_socket), f"{rt}/bus"]
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"
    if perms.portals:
        args += ["--bind", str(portal_docs), f"{rt}/doc"]
        if host_rt and Path(host_rt) != Path(rt):  # the portal hands out paths under the host's runtime dir
            args += ["--bind", str(portal_docs), f"{host_rt}/doc"]
        env["GTK_USE_PORTAL"] = "1"

    if perms.audio:
        pw, pulse = Path(host_rt) / "pipewire-0", Path(host_rt) / "pulse" / "native"
        if pw.is_socket():
            args += ["--ro-bind", str(pw), f"{rt}/pipewire-0"]
        if pulse.is_socket():
            args += ["--ro-bind", str(pulse), f"{rt}/pulse/native"]
            env["PULSE_SERVER"] = f"unix:{rt}/pulse/native"

    if perms.gpu:
        if os.path.isdir("/dev/dri"):
            args += ["--dev-bind", "/dev/dri", "/dev/dri"]
        for node in sorted(Path("/dev").glob("nvidia*")):
            args += ["--dev-bind", str(node), str(node)]
        for p in GPU_RO:
            if os.path.exists(p):
                args += ["--ro-bind", p, p]

    args += dir_binds(perms.dirs, host_home)
    args += file_binds(files, host_home)[0]
    for k, v in env.items():
        args += ["--setenv", k, v]
    if status_fd is not None:
        args += ["--json-status-fd", str(status_fd)]
    if block_fd is not None:
        args += ["--block-fd", str(block_fd)]
    return args + ["--remount-ro", "/", "--chdir", APP_HOME, "--"] + command


# -- git jail (index updates) ---------------------------------------------------------

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
           "GIT_ALLOW_PROTOCOL": "https", "GIT_LFS_SKIP_SMUDGE": "1"}


def local_git_args(workdir, command):
    """No network: git on a local repository. Only workdir (at /work) is visible and writable."""
    env = []
    for k, v in GIT_ENV.items():
        env += ["--setenv", k, v]
    return (common_args() + env
            + ["--bind", str(workdir), "/work", "--remount-ro", "/", "--chdir", "/work", "--"] + command)


def git_args(workdir, command):
    """Network jail for git: only workdir (at /work) is writable; git's own config is neutralised."""
    env = []
    for k, v in GIT_ENV.items():
        env += ["--setenv", k, v]
    return (common_args() + ["--share-net"] + etc_args(private_net=True) + env
            + ["--bind", str(workdir), "/work", "--remount-ro", "/", "--chdir", "/work", "--"] + command)
