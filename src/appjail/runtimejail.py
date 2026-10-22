# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The sandbox an installed app runs in: bwrap arguments for its private home, display, audio, GPU and grants."""

import os
import stat
from pathlib import Path

from . import grants, store
from .jail import RunError, etc_args, system_args

APP_HOME = "/home/app"
APP_DIR = "/app"
RUNTIME_ETC = ("/etc/fonts", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/localtime",
               "/etc/alternatives")
GPU_RO = ("/sys/dev/char", "/sys/devices", "/usr/share/glvnd", "/usr/share/vulkan", "/etc/vulkan", "/etc/glvnd")


def _guard_dirs():
    return [store.data_dir().resolve(), store.config_dir().resolve()]


def dir_binds(dirs, home):
    """Bind arguments for permissions.dirs. Refuses anything that would expose appjail's own files."""
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
                raise RunError(f"granted directory {host} would expose appjail's own data")
        try:
            rel = real.relative_to(home_real)
        except ValueError:
            rel = None
        why = grants.sensitive_reason(f"~/{rel}" if rel else str(real), mode)
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
        path, mode = grants.split_file_mode(entry)
        try:
            real = Path(path).resolve(strict=True)
            regular = stat.S_ISREG(real.stat().st_mode)
        except OSError:
            raise RunError(f"granted file does not exist: {path}") from None
        if not regular:
            raise RunError(f"granted path is not a regular file: {path}")
        for guard in _guard_dirs():
            if real == guard or guard in real.parents:
                raise RunError(f"granted file {path} would expose appjail's own data")
        try:
            rel = real.relative_to(home_real)
        except ValueError:
            rel = None
        why = grants.sensitive_reason(f"~/{rel}" if rel else str(real), mode)
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
    'f=/tmp/.appjail-display; x="$1"; shift\n'
    'WAYLAND_DISPLAY=wayland-0 "$x" -rootless -nolisten tcp -displayfd 3 3>"$f" >/dev/null 2>&1 &\n'
    'p=$!; i=0; while [ ! -s "$f" ] && kill -0 "$p" 2>/dev/null && [ "$i" -lt 400 ]; do sleep 0.05; i=$((i+1)); done\n'
    'n=$(cat "$f"); [ -n "$n" ] || { echo "appjail: Xwayland did not start (it exited, or took more than 20 s)" >&2; exit 1; }\n'
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
    manifest asks for but appjail cannot enforce yet is refused instead of ignored.
    """
    xwayland = perms.display == "xwayland"
    if xwayland:
        command = xwayland_command(command)
    if (perms.dbus_filter or perms.dbus_own or perms.portals) and not dbus_socket:
        raise RunError("dbus_filter, dbus_own and portals need the filtered bus socket from appjail.dbusproxy")
    if perms.portals and not portal_docs:
        raise RunError("portals need the document portal's directory for this app (appjail.portal.doc_dir)")

    rt = f"/run/user/{uid}"
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--hostname", "appjail"]
    if not perms.userns:
        args += ["--unshare-user", "--disable-userns"]
    if perms.network and not perms.network_host:
        # pasta runs the command as uid 0 of a user namespace that maps to the host user; give the app its own
        # ids back (passwd, D-Bus authentication and file ownership all expect them)
        args += ["--uid", str(uid), "--gid", str(os.getgid())]
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
        args += etc_args(private_net=not perms.network_host)
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
