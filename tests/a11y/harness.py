# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Measurement harness for docs/develop/a11y-evidence.md (guest only; not run by pytest, not part of appjail).

Usage: harness.py MODE COMMAND...   where MODE is
  none   the command runs in a jail with appjail's read-only system view and no accessibility bus;
  proxy  the same, with the accessibility bus behind xdg-dbus-proxy (Flatpak's rules, in a jail of its own), as
         AT_SPI_BUS_ADDRESS;
  raw    the same, with the accessibility bus socket itself (what appjail refuses today).
EXP_DROP=a,b removes every proxy rule containing one of the words. The jail binds ~/a11y read-only at /a11y.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.home() / "appjail" / "src"))  # tests/vm/sync.sh puts the project there
from appjail import jail

RT = f"/run/user/{os.getuid()}"
A11Y = f"{RT}/at-spi/bus"
REG = "org.a11y.atspi.Registry"
DEC = "org.a11y.atspi.DeviceEventController@/org/a11y/atspi/registry/deviceeventcontroller"
# The rules of Flatpak's flatpak_run_add_a11y_dbus_args (common/flatpak-run-dbus.c), without the per-app name rules.
FLATPAK_RULES = [
    "--filter", "--sloppy-names",
    f"--broadcast={REG}={REG}.EventListenerRegistered@/org/a11y/atspi/registry",
    f"--broadcast={REG}={REG}.EventListenerDeregistered@/org/a11y/atspi/registry",
    f"--call={REG}=org.a11y.atspi.Socket.Embed@/org/a11y/atspi/accessible/root",
    f"--call={REG}=org.a11y.atspi.Socket.Unembed@/org/a11y/atspi/accessible/root",
    f"--call={REG}={REG}.GetRegisteredEvents@/org/a11y/atspi/registry",
    f"--call={REG}=org.a11y.atspi.DeviceEventController.GetKeystrokeListeners@{DEC.split('@')[1]}",
    f"--call={REG}=org.a11y.atspi.DeviceEventController.GetDeviceEventListeners@{DEC.split('@')[1]}",
    f"--call={REG}=org.a11y.atspi.DeviceEventController.NotifyListenersSync@{DEC.split('@')[1]}",
    f"--call={REG}=org.a11y.atspi.DeviceEventController.NotifyListenersAsync@{DEC.split('@')[1]}",
]


def kept(rules):
    drop = [d for d in os.environ.get("EXP_DROP", "").split(",") if d]
    return [r for r in rules if not any(d in r for d in drop)]


class A11yProxy:
    """xdg-dbus-proxy on the accessibility bus, in a jail of its own as dbusproxy.Proxy does: no network, system read-only."""

    def __init__(self, rules=FLATPAK_RULES):
        self.rules = kept(rules)

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="appjail-", dir=RT)
        read_fd, write_fd = os.pipe()
        argv = [jail.find_bwrap(), *jail.common_args(), "--ro-bind", A11Y, A11Y, "--bind", self.dir, self.dir,
                "--remount-ro", "/", "--", "/usr/bin/xdg-dbus-proxy", f"unix:path={A11Y}", f"{self.dir}/bus",
                f"--fd={write_fd}", *self.rules]
        self.proc = subprocess.Popen(argv, pass_fds=(write_fd,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(write_fd)
        if not os.read(read_fd, 1):
            raise SystemExit("the proxy did not start")
        self.read_fd = read_fd  # the proxy exits when this end of its sync pipe is closed
        return f"{self.dir}/bus"

    def __exit__(self, *exc):
        os.close(self.read_fd)
        self.proc.terminate()
        self.proc.wait()
        shutil.rmtree(self.dir, ignore_errors=True)


def jail_argv(command, a11y_sock=None, wayland="wl-a11y"):
    args = [jail.find_bwrap(), "--unshare-all", "--unshare-user", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--clearenv"]
    for k, v in jail.SAFE_ENV.items():
        args += ["--setenv", k, v]
    args += jail.system_args() + jail.etc_args() + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home",
                                                    "--perms", "0700", "--tmpfs", RT, "--ro-bind",
                                                    os.path.expanduser("~/a11y"), "/a11y", "--setenv", "HOME", "/home",
                                                    "--setenv", "XDG_RUNTIME_DIR", RT]
    args += ["--ro-bind", f"{RT}/{wayland}", f"{RT}/{wayland}", "--setenv", "WAYLAND_DISPLAY", wayland,
             "--setenv", "GDK_BACKEND", "wayland"]
    if a11y_sock:
        args += ["--ro-bind", a11y_sock, f"{RT}/at-spi-bus", "--setenv", "AT_SPI_BUS_ADDRESS", f"unix:path={RT}/at-spi-bus"]
    return args + ["--remount-ro", "/", "--"] + command


def main(mode, command):
    if mode == "none":
        return subprocess.run(jail_argv(command)).returncode
    if mode == "raw":
        return subprocess.run(jail_argv(command, A11Y)).returncode
    with A11yProxy() as sock:
        return subprocess.run(jail_argv(command, sock)).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
