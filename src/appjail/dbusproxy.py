# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Filtered session bus for an app: `xdg-dbus-proxy` runs outside the app's jail, in a jail of its own.

The app never sees the real bus socket. It gets a socket served by the proxy, which hides every name
and refuses every call except to the names listed in `permissions.dbus_filter` and `permissions.dbus_own` (own access).
A listed name of a known service (`CONFINED`) reaches only that service's objects; any other gets talk access, and `run`
first checks that its owner owns no refused name (`check_owners`).

With the `accessibility` permission the app also gets the accessibility bus (AT-SPI), behind a second proxy of its own
(`A11yProxy`): the bus has no policy, so only the proxy keeps the app to its own registration (`A11Y_RULES`).
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


def bus_owners(bus, wanted=None, timeout=5.0):
    """{well-known name: unique name of its owner} of the session bus at `bus`, read with `dbus-send` outside any jail: of
    every name, or of those `wanted(name)` accepts (one call per name, so only the names the check needs are asked)."""
    env = {"PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}"}

    def call(member, *args):
        if not os.access(DBUS_SEND, os.X_OK):
            raise RunError("dbus-send is needed to check who owns the granted D-Bus names (package dbus-bin, or dbus-tools on Fedora)")
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
        if name.startswith(":") or not grants.DBUS_NAME_RE.fullmatch(name) or (wanted and not wanted(name)):
            continue
        r = call("GetNameOwner", f"string:{name}")
        found = _STRING.findall(r.stdout) if r.returncode == 0 else []
        if found:  # a name can lose its owner between the two calls
            owners[name] = found[0]
    return owners


def check_owners(perms, bus, owners=bus_owners):
    """Refuse to start when a granted, unconfined name is owned by the process that owns a refused one: through the proxy
    it would reach that process's refused objects. Only the owners at launch are seen (docs/understand/desktop/dbus.md)."""
    # An owned name is checked too: the proxy's own policy includes talking to whoever owns the name now, and that
    # reaches every object of its connection, like an unconfined talk name.
    owned = list(perms.dbus_own)
    granted = talk_names(perms) + [n for n in owned if n not in perms.dbus_filter]
    if not granted:
        return

    def needed(name):  # the refused names and the granted ones: the others cannot clash
        return _refused(name) or any(_covers(g, name) for g in granted)
    clash = shared_owners(granted, owners(bus, needed))
    if clash:
        entry, name, refused = clash[0]
        shown = name if name == entry else f"{name} (from {entry})"
        key, option = ("dbus_own", "--rm-dbus-own") if entry in owned else ("dbus_filter", "--rm-dbus")
        raise RunError(f"{key} entry {shown} is owned by the same process as {refused}, which is refused: a call to "
                       f"one name reaches every object of the process that owns it, so granting it would reach {refused}. "
                       f"Remove the entry (appjail perms APP {option} {entry})")


# The accessibility bus (AT-SPI) is a second bus with no policy of its own: whoever reaches its socket can list every
# application's controls, register as the keyboard listener, send key events and monitor every message (measured in
# docs/develop/a11y-evidence.md). An app with `accessibility` gets it behind a proxy with Flatpak's rules
# (`flatpak_run_add_a11y_dbus_args`, common/flatpak-run-dbus.c): the app registers its own window and sends its events, and
# may pass its own key events to a screen reader; everything else, the other applications included, is refused.
REGISTRY = "org.a11y.atspi.Registry"
_DEC = "/org/a11y/atspi/registry/deviceeventcontroller"
A11Y_RULES = (
    "--filter", "--sloppy-names",
    f"--broadcast={REGISTRY}={REGISTRY}.EventListenerRegistered@/org/a11y/atspi/registry",
    f"--broadcast={REGISTRY}={REGISTRY}.EventListenerDeregistered@/org/a11y/atspi/registry",
    f"--call={REGISTRY}=org.a11y.atspi.Socket.Embed@/org/a11y/atspi/accessible/root",
    f"--call={REGISTRY}=org.a11y.atspi.Socket.Unembed@/org/a11y/atspi/accessible/root",
    f"--call={REGISTRY}={REGISTRY}.GetRegisteredEvents@/org/a11y/atspi/registry",
    *(f"--call={REGISTRY}=org.a11y.atspi.DeviceEventController.{m}@{_DEC}"
      for m in ("GetKeystrokeListeners", "GetDeviceEventListeners", "NotifyListenersSync", "NotifyListenersAsync")),
)
_ADDRESS = re.compile(r'^\s*string "(unix:path=[^"\\]*)"\s*$', re.MULTILINE)


def a11y_bus(host_env, timeout=5.0):
    """Path of the accessibility bus socket: AT_SPI_BUS_ADDRESS when the user's session has it, else what the session bus
    answers to `org.a11y.Bus.GetAddress` (which starts the bus when it is not running), asked outside any jail.
    Only `unix:path=` addresses are accepted. Raises RunError when there is none: the grant cannot be honoured."""
    address = host_env.get("AT_SPI_BUS_ADDRESS", "")
    if not address:
        session = host_bus(host_env)
        if not os.access(DBUS_SEND, os.X_OK):
            raise RunError("dbus-send is needed to find the accessibility bus (package dbus-bin, or dbus-tools on Fedora)")
        env = {"PATH": "/usr/bin:/bin", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={session}"}
        try:
            r = subprocess.run([DBUS_SEND, "--session", "--print-reply", f"--reply-timeout={int(timeout * 1000)}",
                                "--dest=org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus.GetAddress"],
                               env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout + 2)
        except (OSError, subprocess.SubprocessError) as e:
            raise RunError(f"cannot ask the session bus for the accessibility bus: {e}") from e
        found = _ADDRESS.findall(r.stdout) if r.returncode == 0 else []
        if not found:
            detail = (r.stderr.strip().splitlines() or ["?"])[-1][:200] if r.returncode else "no address in its reply"
            raise RunError("accessibility needs the accessibility bus (package at-spi2-core), and the session bus gave no "
                           f"address for it: {detail}")
        address = found[0]
    first = address.split(";")[0]
    if not first.startswith("unix:path="):
        raise RunError("no usable accessibility bus (only unix:path= addresses are supported)")
    path = first[len("unix:path="):].split(",")[0]
    if not path.startswith("/") or any(c in path for c in "\0\n=") or not Path(path).is_socket():
        raise RunError(f"accessibility bus socket not found: {path}")
    return path


def _argv(bus, sockdir, rule_list, sync_fd, identity=None, seccomp_fd=None):
    """bwrap argv (after the binary) that runs the proxy: no network, nothing but the two sockets."""
    ident = ["--ro-bind", str(identity), "/.flatpak-info"] if identity else []
    return ((["--seccomp", str(seccomp_fd)] if seccomp_fd is not None else []) + jail.common_args()
            + ["--ro-bind", bus, bus, "--bind", str(sockdir), str(sockdir), *ident, "--remount-ro", "/", "--"]
            + [PROXY, f"unix:path={bus}", f"{sockdir}/bus", f"--fd={sync_fd}"] + rule_list)


def proxy_args(bus, sockdir, perms, sync_fd, identity=None, seccomp_fd=None):
    """The argv of the session-bus proxy for the manifest's D-Bus and portal grants.

    identity: file bound as /.flatpak-info, the portal sandbox identity of the app this proxy serves.
    seccomp_fd: the filter the helper jails share (seccomp.open_fd).
    """
    return _argv(bus, sockdir, rules(perms), sync_fd, identity, seccomp_fd)


class _Proxy:
    """Context manager: starts an xdg-dbus-proxy in its own jail, yields the host path of the filtered socket, stops it."""
    NEEDED_BY = ""  # the grants that need the proxy, ending in the verb

    def __init__(self, host_env, popen=subprocess.Popen, identity=None):
        self.host_env, self._popen, self.identity = host_env, popen, identity
        self.proc = self.dir = self._read_fd = None

    def _upstream(self):
        """The host path of the bus socket this proxy filters (after the checks that must hold before it starts)."""
        raise NotImplementedError

    def _rules(self):
        raise NotImplementedError

    def __enter__(self):
        if not os.access(PROXY, os.X_OK):
            raise RunError(f"{self.NEEDED_BY} xdg-dbus-proxy (package xdg-dbus-proxy)")
        bus = self._upstream()
        runtime_dir = self.host_env.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            raise RunError("the D-Bus proxy needs XDG_RUNTIME_DIR")
        self.dir = Path(tempfile.mkdtemp(prefix="appjail-", dir=runtime_dir))
        read_fd, write_fd = os.pipe()
        filter_fd = seccomp.open_fd(False)
        try:
            argv = [jail.find_bwrap(), *_argv(bus, self.dir, self._rules(), write_fd, self.identity, filter_fd)]
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


class Proxy(_Proxy):
    """The proxy of the session bus: the names of dbus_filter and dbus_own and the portals (`rules`)."""
    NEEDED_BY = "dbus_filter, dbus_own and portals need"

    def __init__(self, perms, host_env, popen=subprocess.Popen, identity=None, owners=bus_owners):
        super().__init__(host_env, popen, identity)
        self.perms, self._owners = perms, owners

    def _upstream(self):
        bus = host_bus(self.host_env)
        check_owners(self.perms, bus, self._owners)
        return bus

    def _rules(self):
        return rules(self.perms)


class A11yProxy(_Proxy):
    """The proxy of the accessibility bus (`A11Y_RULES`): the app registers its window and nothing else."""
    NEEDED_BY = "accessibility needs"

    def __init__(self, host_env, popen=subprocess.Popen, address=None):
        super().__init__(host_env, popen)
        self._address = address or a11y_bus

    def _upstream(self):
        return self._address(self.host_env)

    def _rules(self):
        return list(A11Y_RULES)
