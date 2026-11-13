# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The sandbox an installed app runs in: bwrap arguments for its private home, display, audio, GPU, camera and grants."""

import fcntl
import os
import stat
import struct
from pathlib import Path
from typing import NamedTuple

from . import dbusproxy, grants, linger, manifest, reopen, store, wayland
from .errors import RunError
from .jail import etc_args, system_args

APP_HOME = "/home/app"
APP_DIR = "/app"
RUNTIME_ETC = ("/etc/fonts", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/localtime",
               "/etc/alternatives")
GPU_RO = ("/sys/dev/char", "/sys/devices", "/usr/share/glvnd", "/usr/share/vulkan", "/etc/vulkan", "/etc/glvnd")
FIRST_PASTA_FD = 10  # above the single digits jail.net_wrap and the portal pipes use


def _guard_dirs():
    return [store.data_dir().resolve(), store.config_dir().resolve()]


class Grant(NamedTuple):
    fd: int
    real: str  # the path the descriptor had when it was checked
    dest: str  # where it appears in the jail
    rw: bool
    dev: int
    ino: int


class Grants:
    """The granted directories and files of one run, each opened once and checked through its descriptor.

    bwrap binds the descriptor, not a path, so swapping a path for a symlink after the checks changes nothing. The checks
    look at what was really opened, so the path may contain symlinks. A context manager: the descriptors stay open for
    the whole run, which also keeps the inode numbers `reopen` compares from being reused. Behind pasta, which closes
    inherited descriptors, `reopened` opens the paths again inside its namespace and compares them.
    """

    def __init__(self, dirs, files, home):
        self.items, self.file_dests = [], []
        self._open_fds = []
        try:
            home_real = Path(home).resolve()
            for entry in dirs:
                self._add_dir(entry, Path(home), home_real)
            for entry in files:
                self._add_file(entry, home_real)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        while self._open_fds:
            os.close(self._open_fds.pop())

    @property
    def fds(self):
        return tuple(item.fd for item in self.items)

    def args(self, behind_pasta=False):
        """The bwrap bind arguments; behind pasta the numbers are those `reopened` gives the descriptors."""
        args = []
        for i, item in enumerate(self.items):
            args += ["--bind-fd" if item.rw else "--ro-bind-fd", str(FIRST_PASTA_FD + i if behind_pasta else item.fd), item.dest]
        return args

    def reopened(self, argv):
        """argv preceded by the wrapper that reopens the grants inside pasta's namespace; argv if there are none."""
        if not self.items:
            return argv
        return reopen.wrap([(FIRST_PASTA_FD + i, g.dev, g.ino, g.real) for i, g in enumerate(self.items)], argv)

    def _open(self, path, flags=0):
        """(descriptor, real path, stat) of `path`. O_PATH does not block on a FIFO or run a device's open."""
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC | flags)
        self._open_fds.append(fd)
        st = os.fstat(fd)
        real = Path(os.readlink(f"/proc/self/fd/{fd}"))
        try:
            same = os.path.samestat(os.stat(real), st)
        except OSError:  # unlinked: the link reads "... (deleted)", a name the policy cannot judge
            same = False
        if not same:
            raise RunError(f"granted path {path} changed while it was being checked")
        return fd, real, st

    def _add_dir(self, entry, home, home_real):
        path, _, mode = entry.partition(":")
        host = home / path[2:] if path.startswith("~/") else Path(path)
        dest = f"{APP_HOME}/{path[2:]}" if path.startswith("~/") else path
        try:
            fd, real, st = self._open(host, os.O_DIRECTORY)
        except NotADirectoryError:
            raise RunError(f"granted directory {host} is not a directory") from None
        except OSError:
            raise RunError(f"granted directory does not exist: {host}") from None
        if real == home_real or real in home_real.parents:
            raise RunError(f"granted directory {host} would expose the whole home directory")
        for guard in _guard_dirs():
            if real == guard or guard in real.parents or real in guard.parents:
                raise RunError(f"granted directory {host} would expose appjail's own data")
        try:
            rel = real.relative_to(home_real)
        except ValueError:
            rel = None
        why = grants.directory_reason(f"~/{rel}" if rel else str(real), mode)
        if why:
            raise RunError(f"granted directory {host} is refused: {why}")
        self.items.append(Grant(fd, str(real), dest, mode == "rw", st.st_dev, st.st_ino))

    def _add_file(self, entry, home_real):
        """A single file for one run: PATH, PATH:ro or PATH:rw, absolute. Only the file itself is bound, read-only unless
        :rw. The directory policy applies to the real path, and only regular files are accepted. Files below the real
        home appear under the app's home."""
        path, mode = grants.split_file_mode(entry)
        try:
            fd, real, st = self._open(path)
        except OSError:
            raise RunError(f"granted file does not exist: {path}") from None
        if not stat.S_ISREG(st.st_mode):
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
        self.items.append(Grant(fd, str(real), dest, mode == "rw", st.st_dev, st.st_ino))
        self.file_dests.append(dest)


XWAYLAND_PATHS = ("/usr/bin/Xwayland",)
OPENBOX_PATHS = ("/usr/bin/openbox",)
# Runs inside the jail: an Xwayland of its own, a client of the (restricted) Wayland socket. Its X11 socket lives in
# the jail's private /tmp and abstract namespace, so no other app and no host X server is involved. Arguments: the
# Xwayland binary, the mode (rootless, or rootful with a window of the size in $3 and openbox $4 as its window
# manager), then the command. Rootless needs the compositor to manage the X windows, which mutter does only for the
# Xwayland it starts itself.
XWAYLAND_SCRIPT = (
    'f=/tmp/.appjail-display; l=/tmp/.appjail-xwayland.log; x="$1"; m="$2"; g="$3"; w="$4"; shift 4\n'
    'if [ "$m" = rootful ]; then\n'
    '  WAYLAND_DISPLAY=wayland-0 "$x" -geometry "$g" -decorate -nolisten tcp -displayfd 3 3>"$f" >"$l" 2>&1 &\n'
    'else\n'
    '  WAYLAND_DISPLAY=wayland-0 "$x" -rootless -nolisten tcp -displayfd 3 3>"$f" >"$l" 2>&1 &\n'
    'fi\n'
    'p=$!; i=0; while [ ! -s "$f" ] && kill -0 "$p" 2>/dev/null && [ "$i" -lt 400 ]; do sleep 0.05; i=$((i+1)); done\n'
    'n=$(cat "$f"); [ -n "$n" ] || { cat "$l" >&2; echo "appjail: Xwayland did not start (it exited, or took more than 20 s)" >&2; exit 1; }\n'
    '[ "$m" = rootful ] && DISPLAY=":$n" "$w" >/dev/null 2>&1 &\n'
    'DISPLAY=":$n" exec "$@"')


def _executable(paths):
    return next((p for p in paths if os.access(p, os.X_OK)), None)


def xwayland_command(command, rootful=False, size=manifest.DEFAULT_DISPLAY_SIZE):
    """Wrap the app command so a private Xwayland (rootful: with a window manager) is running before it starts."""
    xwayland = _executable(XWAYLAND_PATHS)
    if not xwayland:
        raise RunError("display = xwayland needs the Xwayland binary in /usr/bin (package xwayland)")
    openbox = _executable(OPENBOX_PATHS) if rootful else ""
    if rootful and not openbox:
        raise RunError("display = xwayland-rootful needs openbox in /usr/bin (package openbox)")
    return ["/bin/sh", "-c", XWAYLAND_SCRIPT, "sh", xwayland, "rootful" if rootful else "rootless", size, openbox, *command]


def _wayland_args(host_env, wayland_socket, rt):
    if wayland_socket:
        sock = Path(wayland_socket)
        if not sock.is_socket():
            raise RunError(f"Wayland socket not found: {sock}")
    else:
        sock = wayland.host_socket_path(host_env)
    return ["--ro-bind", str(sock), f"{rt}/wayland-0"]


def _app_env(host_env, rt, xwayland, windowed=True):
    env = {
        "PATH": f"{APP_DIR}/usr/bin:/usr/local/bin:/usr/bin:/bin", "HOME": APP_HOME, "USER": "app",
        "LOGNAME": "app", "SHELL": "/bin/sh", "LANG": host_env.get("LANG") or "C.UTF-8",
        "XDG_RUNTIME_DIR": rt, "APPDIR": APP_DIR, "APPIMAGE_EXTRACT_AND_RUN": "1", "TMPDIR": "/tmp",
    }
    # without a display nothing tells a toolkit to look for one
    if windowed and xwayland:  # the app only sees X11; WAYLAND_DISPLAY is set for the Xwayland process alone
        env.update({"XDG_SESSION_TYPE": "x11", "GDK_BACKEND": "x11", "QT_QPA_PLATFORM": "xcb",
                    "ELECTRON_OZONE_PLATFORM_HINT": "x11", "SDL_VIDEODRIVER": "x11"})
    elif windowed:
        env.update({"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland", "GDK_BACKEND": "wayland",
                    "QT_QPA_PLATFORM": "wayland", "MOZ_ENABLE_WAYLAND": "1",
                    "ELECTRON_OZONE_PLATFORM_HINT": "wayland", "SDL_VIDEODRIVER": "wayland"})
    if host_env.get("TZ"):
        env["TZ"] = host_env["TZ"]
    return env


def _bus_and_portal_args(perms, rt, host_rt, dbus_socket, portal_docs, env):
    """The filtered bus socket and the document portal's directory; adds their variables to `env`."""
    args = []
    if dbus_socket:
        args += ["--ro-bind", str(dbus_socket), f"{rt}/bus"]
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"
    if perms.portals:
        args += ["--bind", str(portal_docs), f"{rt}/doc"]
        if host_rt and Path(host_rt) != Path(rt):  # the portal hands out paths under the host's runtime dir
            args += ["--bind", str(portal_docs), f"{host_rt}/doc"]
        env["GTK_USE_PORTAL"] = "1"
    return args


def _audio_args(host_rt, rt, env, private=None, host_audio=True):
    """The app's audio sockets.

    private: (pipewire socket, pulse socket) of the app's own graph (audiojail.py), which is all it sees. Without it, the
    host's Pulse socket, unless host_audio is false. The host's PipeWire socket is never bound: PipeWire restricts only
    clients it recognises as sandboxed (by a .flatpak-info in their root), so a jailed app on pipewire-0 would see and use
    every node, cameras and other apps' screen casts included. pipewire-pulse serves audio and nothing else, but cannot
    keep capture apart from playback.
    """
    if private:
        pipewire, pulse = private
        env["PULSE_SERVER"] = f"unix:{rt}/pulse/native"
        return ["--ro-bind", str(pipewire), f"{rt}/pipewire-0", "--ro-bind", str(pulse), f"{rt}/pulse/native"]
    pulse = Path(host_rt) / "pulse" / "native" if host_rt and host_audio else None
    if not (pulse and pulse.is_socket()):
        return []
    env["PULSE_SERVER"] = f"unix:{rt}/pulse/native"
    return ["--ro-bind", str(pulse), f"{rt}/pulse/native"]


def _gpu_args():
    args = []
    if os.path.isdir("/dev/dri"):
        args += ["--dev-bind", "/dev/dri", "/dev/dri"]
    for node in sorted(Path("/dev").glob("nvidia*")):
        args += ["--dev-bind", str(node), str(node)]
    for p in GPU_RO:
        if os.path.exists(p):
            args += ["--ro-bind", p, p]
    return args


V4L2_CAP_VIDEO_CAPTURE, V4L2_CAP_VIDEO_CAPTURE_MPLANE, V4L2_CAP_DEVICE_CAPS = 0x1, 0x1000, 0x80000000
VIDIOC_QUERYCAP = 0x80685600  # _IOR('V', 0, struct v4l2_capability), 104 bytes


def _capture_nodes():
    """The /dev/video* nodes that capture video (not output, metadata or codec nodes), asked of the driver with
    VIDIOC_QUERYCAP, which does not start streaming. A node that cannot be opened or queried is left out."""
    nodes = []
    for node in sorted(Path("/dev").glob("video[0-9]*")):
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
            caps, device_caps = struct.unpack_from("II", buf, 84)
            if (device_caps if caps & V4L2_CAP_DEVICE_CAPS else caps) & (V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE):
                nodes.append(node)
        except OSError:
            pass
        finally:
            os.close(fd)
    return nodes


def _camera_args(sysfs=True):
    """The capture nodes, and for each only its own sysfs directory (tools resolve /sys/dev/char/MAJOR:MINOR to it, which
    is recreated as a symlink). The other video nodes, the media controller and the rest of sysfs are not bound. With no
    camera present nothing is bound.

    sysfs: false when `gpu` already binds the whole of /sys/dev/char and /sys/devices, where the symlink exists already
    (bwrap refuses to replace it).
    """
    args = []
    for node in _capture_nodes():
        args += ["--dev-bind", str(node), str(node)]
        if not sysfs:
            continue
        st = os.stat(node)
        link = f"/sys/dev/char/{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
        real = os.path.realpath(link)
        if real != link and os.path.isdir(real):
            args += ["--ro-bind", real, real, "--symlink", real, link]
    return args


def _namespace_args(perms, uid, seccomp_fd):
    """Namespaces, capabilities, the ids inside the jail and the seccomp filter."""
    args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--hostname", "appjail"]
    if not perms.userns:
        args += ["--unshare-user", "--disable-userns"]
    if perms.pasta:
        # pasta runs the command as uid 0 of a user namespace that maps to the host user; give the app its own
        # ids back (passwd, D-Bus authentication and file ownership all expect them)
        args += ["--uid", str(uid), "--gid", str(os.getgid())]
    if seccomp_fd is not None:
        args += ["--seccomp", str(seccomp_fd)]
    if perms.network:
        args.append("--share-net")
    return args


def _base_filesystem_args(etc_dir, rt, perms):
    """The system directories, /proc, /dev, the tmpfs mounts, the private passwd and group, and the network's /etc files."""
    args = system_args()
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
             "--perms", "0700", "--dir", "/run/user", "--perms", "0700", "--dir", rt]
    args += ["--ro-bind", str(Path(etc_dir) / "passwd"), "/etc/passwd",
             "--ro-bind", str(Path(etc_dir) / "group"), "/etc/group"]
    for f in RUNTIME_ETC:
        if os.path.exists(f):
            args += ["--ro-bind", os.path.realpath(f), f]
    if perms.network:
        args += etc_args(private_net=not perms.network_host)
    return args


def runtime_args(*, root, home, etc_dir, perms, uid, host_env, command, dbus_socket=None, wayland_socket=None, seccomp_fd=None,
                 portal_docs=None, status_fd=None, block_fd=None, binds=(), audio_sockets=None, host_audio=True):
    """Complete bwrap argv (after the bwrap binary) for running an extracted AppImage.

    binds: the directory and file grants, from Grants.args.
    audio_sockets: (pipewire, pulse) sockets of the app's private audio graph; without them `audio` is the host's Pulse
    socket, or nothing when host_audio is false (the private graph could not start and the app has no `mic`).
    Nothing is read from the process environment, only from host_env; the host's files decide what can be bound (which
    system directories, GPU nodes and helper binaries exist). Anything the manifest asks for but appjail cannot enforce
    yet is refused instead of ignored.
    """
    xwayland = perms.xwayland
    if perms.linger:
        command = linger.wrap(command)
    if xwayland:
        command = xwayland_command(command, perms.rootful, perms.display_size)
    if dbusproxy.needed(perms) and not dbus_socket:
        raise RunError("dbus_filter, dbus_own and portals need the filtered bus socket from appjail.dbusproxy")
    if perms.portals and not portal_docs:
        raise RunError("portals need the document portal's directory for this app (appjail.portal.doc_dir)")

    rt, host_rt = f"/run/user/{uid}", host_env.get("XDG_RUNTIME_DIR", "")
    args = _namespace_args(perms, uid, seccomp_fd)
    args += _base_filesystem_args(etc_dir, rt, perms)
    args += ["--ro-bind", str(root), APP_DIR, "--bind", str(home), APP_HOME]
    if perms.windowed:
        args += _wayland_args(host_env, wayland_socket, rt)

    env = _app_env(host_env, rt, xwayland, perms.windowed)
    args += _bus_and_portal_args(perms, rt, host_rt, dbus_socket, portal_docs, env)
    if perms.audio:
        args += _audio_args(host_rt, rt, env, audio_sockets, host_audio)
    if perms.gpu:
        args += _gpu_args()
    if perms.camera:
        args += _camera_args(sysfs=not perms.gpu)
    args += binds
    for k, v in env.items():
        args += ["--setenv", k, v]
    if status_fd is not None:
        args += ["--json-status-fd", str(status_fd)]
    if block_fd is not None:
        args += ["--block-fd", str(block_fd)]
    return args + ["--remount-ro", "/", "--chdir", APP_HOME, "--"] + command
