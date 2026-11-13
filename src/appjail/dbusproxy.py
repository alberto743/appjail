# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Filtered session bus for an app: `xdg-dbus-proxy` runs outside the app's jail, in a jail of its own.

The app never sees the real bus socket. It gets a socket served by the proxy, which hides every name
and refuses every call except to the names listed in `permissions.dbus_filter` and `permissions.dbus_own` (own access).
A listed name of a known service (`CONFINED`) reaches only that service's objects; any other gets talk access, and `run`
first checks that its owner owns no refused name (`check_owners`).
"""

import os
import re
import select
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import grants, jail, portal, seccomp
from .errors import RunError
from .valid import ManifestError

PROXY = "/usr/bin/xdg-dbus-proxy"
READY_TIMEOUT = 5.0


def needed(perms):
    return bool(perms.dbus_filter or perms.dbus_own or perms.portals)


def host_bus(host_env):
    """Path of the user's session bus socket. Only `unix:path=` addresses are accepted."""
    rt = host_env.get("XDG_RUNTIME_DIR", "")
    address = host_env.get("DBUS_SESSION_BUS_ADDRESS") or (f"unix:path={rt}/bus" if rt else "")
    first = address.split(";")[0]
    if not first.startswith("unix:path="):
        raise RunError("no usable D-Bus session bus (only unix:path= addresses are supported)")
    path = first[len("unix:path="):].split(",")[0]
    if not path.startswith("/") or any(c in path for c in "\0\n=") or not Path(path).is_socket():
        raise RunError(f"D-Bus session bus socket not found: {path}")
    return path


# The proxy filters by destination name, and one process serves all its names on one connection: talking to a name
# reaches every object of its owner (a desktop shell owns ordinary names next to refused ones). A granted name of these
# services is confined to the interfaces and object path its specification defines, for calls to it and for the signals
# it sends. Keys ending in `.*` cover every name below that prefix. Value: (interfaces, object path; `/*` adds the subtree).
CONFINED = {
    "org.freedesktop.Notifications": (("org.freedesktop.Notifications",), "/org/freedesktop/Notifications"),
    "org.gtk.Notifications": (("org.gtk.Notifications",), "/org/gtk/Notifications"),
    "org.freedesktop.secrets": (("org.freedesktop.Secret.Service", "org.freedesktop.Secret.Collection",
                                 "org.freedesktop.Secret.Item", "org.freedesktop.Secret.Session",
                                 "org.freedesktop.Secret.Prompt"), "/org/freedesktop/secrets/*"),
    "org.kde.StatusNotifierWatcher": (("org.kde.StatusNotifierWatcher",), "/StatusNotifierWatcher"),
    "org.mpris.MediaPlayer2.*": (("org.mpris.MediaPlayer2", "org.mpris.MediaPlayer2.Player", "org.mpris.MediaPlayer2.TrackList",
                                  "org.mpris.MediaPlayer2.Playlists"), "/org/mpris/MediaPlayer2"),
}
# Allowed on the confined object too: its properties (and their change signals), introspection and ping.
STANDARD = ("org.freedesktop.DBus.Properties", "org.freedesktop.DBus.Introspectable", "org.freedesktop.DBus.Peer")


def confined(name):
    """(interfaces, path) a granted name is confined to, or None when it gets talk access (and the owner check)."""
    if name in CONFINED:
        return CONFINED[name]
    for key, value in CONFINED.items():
        if key.endswith(".*") and name.startswith(key[:-1]):
            return value
    return None


def name_rules(name):
    """Proxy options for one granted name: `--call` and `--broadcast` rules when it is confined, else `--talk`."""
    grants.check_dbus_name(name)
    rule = confined(name)
    if rule is None:
        return [f"--talk={name}"]
    interfaces, path = rule
    out = [f"--call={name}={i}.*@{path}" for i in (*interfaces, *STANDARD)]
    return out + [f"--broadcast={name}={i}.*@{path}" for i in (*interfaces, "org.freedesktop.DBus.Properties")]


def rules(perms):
    """xdg-dbus-proxy options for the manifest: see nothing, reach the listed names, own the owned ones."""
    return (["--filter"] + [r for n in perms.dbus_filter for r in name_rules(n)]
            + [f"--own={grants.check_dbus_own(n)}" for n in perms.dbus_own]
            + portal.proxy_rules(perms))


def talk_names(perms):
    """The granted names the proxy lets reach their whole owner (not confined): the ones the owner check covers."""
    return [n for n in perms.dbus_filter if confined(n) is None]


def _refused(name):
    try:
        grants.check_dbus_name(name)
    except ManifestError:
        return True
    return False


def _covers(granted, name):
    """Whether a granted entry (a name, or a prefix ending in `.*`) covers a name on the bus, as the proxy matches it."""
    if granted.endswith(".*"):
        return name == granted[:-2] or name.startswith(granted[:-1])
    return name == granted


def shared_owners(granted, owners):
    """[(granted entry, bus name it covers, refused name)] for every granted name owned by the connection of a refused one.

    owners: {well-known name: unique name of its owner}, as the bus listed them.
    """
    refused = {}
    for name, owner in owners.items():
        if not name.startswith(":") and name != "org.freedesktop.DBus" and _refused(name):
            refused.setdefault(owner, name)
    return [(g, name, refused[owner]) for g in granted for name, owner in sorted(owners.items())
            if _covers(g, name) and owner in refused]


DBUS_SEND = "/usr/bin/dbus-send"
_STRING = re.compile(r'^\s*string "([^"\\]*)"\s*$', re.MULTILINE)


def bus_owners(bus, timeout=5.0):
    """{well-known name: unique name of its owner} of the session bus at `bus`, read with `dbus-send` outside any jail."""
    env = {"PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}"}

    def call(member, *args):
        if not os.access(DBUS_SEND, os.X_OK):
            raise RunError("dbus-send is needed to check who owns the granted D-Bus names (package dbus-bin)")
        try:
            r = subprocess.run([DBUS_SEND, "--session", "--print-reply", f"--reply-timeout={int(timeout * 1000)}",
                                "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus", f"org.freedesktop.DBus.{member}", *args],
                               env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout + 2)
        except (OSError, subprocess.SubprocessError) as e:
            raise RunError(f"cannot check who owns the granted D-Bus names: {e}") from e
        return r
    listed = call("ListNames")
    if listed.returncode != 0:
        raise RunError("cannot check who owns the granted D-Bus names: " + (listed.stderr.strip().splitlines() or ["?"])[-1])
    owners = {}
    for name in _STRING.findall(listed.stdout):
        if name.startswith(":") or not grants.DBUS_NAME_RE.fullmatch(name):
            continue
        r = call("GetNameOwner", f"string:{name}")
        found = _STRING.findall(r.stdout) if r.returncode == 0 else []
        if found:  # a name can lose its owner between the two calls
            owners[name] = found[0]
    return owners


def check_owners(perms, bus, owners=bus_owners):
    """Refuse to start when a granted, unconfined name is owned by the process that owns a refused one: through the proxy
    it would reach that process's refused objects. Only the owners at launch are seen (DESIGN.md, D-Bus)."""
    granted = talk_names(perms)
    if not granted:
        return
    clash = shared_owners(granted, owners(bus))
    if clash:
        entry, name, refused = clash[0]
        shown = name if name == entry else f"{name} (from {entry})"
        raise RunError(f"dbus_filter entry {shown} is owned by the same process as {refused}, which is refused: a call to "
                       f"one name reaches every object of the process that owns it, so granting it would reach {refused}. "
                       "Remove the entry (perms APP --rm-dbus NAME)")


def proxy_args(bus, sockdir, perms, sync_fd, identity=None, seccomp_fd=None):
    """bwrap argv (after the binary) that runs the proxy: no network, nothing but the two sockets.

    identity: file bound as /.flatpak-info, the portal sandbox identity of the app this proxy serves.
    seccomp_fd: the filter the helper jails share (seccomp.open_fd).
    """
    ident = ["--ro-bind", str(identity), "/.flatpak-info"] if identity else []
    return ((["--seccomp", str(seccomp_fd)] if seccomp_fd is not None else []) + jail.common_args()
            + ["--ro-bind", bus, bus, "--bind", str(sockdir), str(sockdir), *ident, "--remount-ro", "/", "--"]
            + [PROXY, f"unix:path={bus}", f"{sockdir}/bus", f"--fd={sync_fd}"] + rules(perms))


class Proxy:
    """Context manager: starts the proxy, yields the host path of the filtered socket, stops it."""

    def __init__(self, perms, host_env, popen=subprocess.Popen, identity=None, owners=bus_owners):
        self.perms, self.host_env, self._popen, self.identity, self._owners = perms, host_env, popen, identity, owners
        self.proc = self.dir = self._read_fd = None

    def __enter__(self):
        if not os.access(PROXY, os.X_OK):
            raise RunError("dbus_filter, dbus_own and portals need xdg-dbus-proxy (apt install xdg-dbus-proxy)")
        bus = host_bus(self.host_env)
        check_owners(self.perms, bus, self._owners)
        runtime_dir = self.host_env.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            raise RunError("the D-Bus proxy needs XDG_RUNTIME_DIR")
        self.dir = Path(tempfile.mkdtemp(prefix="appjail-", dir=runtime_dir))
        read_fd, write_fd = os.pipe()
        filter_fd = seccomp.open_fd(False)
        try:
            argv = [jail.find_bwrap(), *proxy_args(bus, self.dir, self.perms, write_fd, self.identity, filter_fd)]
            self.proc = self._popen(argv, pass_fds=(write_fd, filter_fd), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"},
                                    start_new_session=True)
            os.close(write_fd)
            write_fd = None
            ready, _, _ = select.select([read_fd], [], [], READY_TIMEOUT)
            if not ready or not os.read(read_fd, 1):
                detail = ""
                if self.proc.poll() is not None:
                    detail = ": " + self.proc.stderr.read().decode("utf-8", "replace").strip()[:300]
                raise RunError("the D-Bus proxy did not start" + detail)
        except BaseException:
            os.close(read_fd)
            self._stop()
            raise
        else:
            self._read_fd = read_fd
        finally:
            if write_fd is not None:
                os.close(write_fd)
            os.close(filter_fd)
        return str(self.dir / "bus")

    def _stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            if self.proc.stderr:
                self.proc.stderr.close()
        if self.dir is not None:
            shutil.rmtree(self.dir, ignore_errors=True)

    def __exit__(self, *exc):
        if self._read_fd is not None:
            os.close(self._read_fd)
            self._read_fd = None
        self._stop()
