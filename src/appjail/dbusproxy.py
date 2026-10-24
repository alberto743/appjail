# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Filtered session bus for an app: `xdg-dbus-proxy` runs outside the app's jail, in a jail of its own.

The app never sees the real bus socket. It gets a socket served by the proxy, which hides every name
and refuses every call except the names listed in `permissions.dbus_filter` (talk access) and `permissions.dbus_own` (own access).
"""

import os
import select
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import grants, jail, portal, seccomp
from .jail import RunError

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


def rules(perms):
    """xdg-dbus-proxy options for the manifest: see nothing, talk to the listed names, own the owned ones."""
    return (["--filter"] + [f"--talk={grants.check_dbus_name(n)}" for n in perms.dbus_filter]
            + [f"--own={grants.check_dbus_own(n)}" for n in perms.dbus_own]
            + portal.proxy_rules(perms))


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

    def __init__(self, perms, host_env, popen=subprocess.Popen, identity=None):
        self.perms, self.host_env, self._popen, self.identity = perms, host_env, popen, identity
        self.proc = self.dir = None

    def __enter__(self):
        if not os.access(PROXY, os.X_OK):
            raise RunError("dbus_filter, dbus_own and portals need xdg-dbus-proxy (apt install xdg-dbus-proxy)")
        bus = host_bus(self.host_env)
        self.dir = Path(tempfile.mkdtemp(prefix="appjail-", dir=self.host_env["XDG_RUNTIME_DIR"]))
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
            self._stop()
            raise
        finally:
            if write_fd is not None:
                os.close(write_fd)
            os.close(filter_fd)
            self._read_fd = read_fd
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
        if getattr(self, "_read_fd", None) is not None:
            os.close(self._read_fd)
            self._read_fd = None
        self._stop()
