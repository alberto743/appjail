# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""bwrap argument builders and runners. Every untrusted step runs through here.

Argument builders are pure functions so they can be unit-tested without bwrap.
"""

import os
import shutil
import signal
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


def etc_args():
    args = []
    for f in ETC_FILES:
        if os.path.exists(f):
            args += ["--ro-bind", os.path.realpath(f), f]
    for d in ETC_DIRS:
        if os.path.isdir(d):
            args += ["--ro-bind", d, d]
    # resolv.conf is usually a symlink into /run; bind its content, not the link.
    if os.path.exists("/etc/resolv.conf"):
        args += ["--ro-bind", os.path.realpath("/etc/resolv.conf"), "/etc/resolv.conf"]
    return args


def common_args():
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    for k, v in SAFE_ENV.items():
        args += ["--setenv", k, v]
    return args + system_args() + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]


def download_args(stage_dir, command, fetcher=FETCHER):
    """Network-only jail: no host files except the read-only fetcher and the staging dir."""
    return (common_args() + ["--share-net"] + etc_args()
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
    return supervise([find_bwrap(), *args], timeout=timeout, watch=watch)


def extract_args(appimage, outdir, command):
    """No network, root read-only; the AppImage is read-only and only outdir is writable."""
    return (common_args() + ["--ro-bind", str(appimage), "/app.AppImage", "--bind", str(outdir), "/out",
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


def runtime_args(*, root, home, etc_dir, perms, uid, host_env, command, host_home, dbus_socket=None, wayland_socket=None, seccomp_fd=None):
    """Complete bwrap argv (after the bwrap binary) for running an extracted AppImage.

    Pure function of its inputs: nothing is read from the process environment. Anything the
    manifest asks for but bjail cannot enforce yet is refused instead of ignored.
    """
    if perms.display != "wayland":
        raise RunError(f"display = {perms.display} is not implemented yet (only wayland)")
    if perms.portals:
        raise RunError("portals are not implemented yet (they need a portal-aware identity for the app); remove them from the manifest")
    if perms.dbus_filter and not dbus_socket:
        raise RunError("dbus_filter needs the filtered bus socket from bjail.dbusproxy")

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
        "XDG_RUNTIME_DIR": rt, "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland",
        "APPDIR": APP_DIR, "APPIMAGE_EXTRACT_AND_RUN": "1", "TMPDIR": "/tmp",
        "GDK_BACKEND": "wayland", "QT_QPA_PLATFORM": "wayland", "MOZ_ENABLE_WAYLAND": "1",
        "ELECTRON_OZONE_PLATFORM_HINT": "wayland", "SDL_VIDEODRIVER": "wayland",
    }
    if host_env.get("TZ"):
        env["TZ"] = host_env["TZ"]

    if perms.dbus_filter:
        args += ["--ro-bind", str(dbus_socket), f"{rt}/bus"]
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"

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
    for k, v in env.items():
        args += ["--setenv", k, v]
    return args + ["--remount-ro", "/", "--chdir", APP_HOME, "--"] + command


# -- git jail (index updates) ---------------------------------------------------------

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
           "GIT_ALLOW_PROTOCOL": "https", "GIT_LFS_SKIP_SMUDGE": "1"}


def git_args(workdir, command):
    """Network jail for git: only workdir (at /work) is writable; git's own config is neutralised."""
    env = []
    for k, v in GIT_ENV.items():
        env += ["--setenv", k, v]
    return (common_args() + ["--share-net"] + etc_args() + env
            + ["--bind", str(workdir), "/work", "--remount-ro", "/", "--chdir", "/work", "--"] + command)
