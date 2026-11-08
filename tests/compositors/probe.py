# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What a client of a Wayland compositor can reach, measured: the Wayland registry and the compositor's D-Bus interfaces.

Run in the *-compositors guests (tests/vm/provision.sh installs the compositors), the same way on Debian 13 and Ubuntu 26.04:

    python3 tests/compositors/probe.py [--only NAME]... [--out FILE.json]

Each compositor is started headless in a private runtime directory and on a private session bus, and nothing but the
compositor's own answers is read:

* the Wayland registry on the compositor's own socket, with appjail's protocol code (`appjail.wayland`) and, as a second
  reader, `wayland-info`; whether `wp_security_context_manager_v1` is offered; and, when it is, the registry on the
  restricted socket appjail would give an app (`wayland.RestrictedSocket`);
* every interface of the D-Bus names owned by the compositor (busctl), and a few side-effect-free calls made as an
  ordinary client (an unprivileged process on the same bus) to see whether the compositor itself refuses them;
* whether appjail's D-Bus name policy (`grants.check_dbus_name`) would let a user grant each privileged name.

The interface names that count as privileged (PRIVILEGED) are a first guess, kept next to the data: the whole registry is
saved too, so the list can be judged and changed afterwards without running anything again.
"""

import argparse
import contextlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src")]

from appjail import grants, wayland
from appjail.errors import RunError
from appjail.valid import ManifestError

SECURITY_CONTEXT = "wp_security_context_manager_v1"
START_TIMEOUT = 30.0

# Interfaces by what they let a client do beyond its own windows. A first guess; see the module docstring.
PRIVILEGED = {
    "capture": ("zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1", "ext_output_image_capture_source_manager_v1",
                "ext_foreign_toplevel_image_capture_source_manager_v1", "zwlr_export_dmabuf_manager_v1",
                "hyprland_toplevel_export_manager_v1", "zkde_screencast_unstable_v1", "weston_capture_v1"),
    "input": ("zwlr_virtual_pointer_manager_v1", "zwp_virtual_keyboard_manager_v1", "zwp_input_method_manager_v2",
              "zwp_input_method_v1", "zwp_input_panel_v1", "org_kde_kwin_fake_input", "zwlr_input_inhibit_manager_v1",
              "hyprland_global_shortcuts_manager_v1", "zwp_keyboard_shortcuts_inhibit_manager_v1", "zwf_shell_manager_v2"),
    "clipboard": ("zwlr_data_control_manager_v1", "ext_data_control_manager_v1"),
    "windows": ("zwlr_foreign_toplevel_manager_v1", "ext_foreign_toplevel_list_v1", "org_kde_plasma_window_management",
                "zwlr_layer_shell_v1", "org_kde_plasma_shell", "weston_desktop_shell", "zwlr_output_manager_v1",
                "zwlr_output_power_manager_v1", "zwlr_gamma_control_manager_v1", "kde_output_management_v2",
                "kde_output_management_v1", "ext_session_lock_manager_v1", "ext_workspace_manager_v1"),
}
PRIVILEGED_BY_NAME = {name: kind for kind, names in PRIVILEGED.items() for name in names}

# Words that mark a D-Bus interface as one a desktop should not hand to an arbitrary client.
DBUS_PRIVILEGED = re.compile(r"ScreenCast|Screenshot|ScreenShot|RemoteDesktop|InputCapture|Eval|Script|FakeInput|"
                             r"VirtualKeyboard|GlobalShortcut|KGlobalAccel|ShortcutsInhibit|Extensions|Effects|Plugins|"
                             r"KeyboardMonitor|ServiceChannel|ScreenSaver|ColorPicker|DisplayConfig|Session|Introspect(?!able)",
                             re.IGNORECASE)

# Side-effect-free calls made as an ordinary client: (bus name, object path, interface.method, busctl signature, arguments).
# A call that is refused tells how; a call that works tells that the compositor itself does not gate it.
CALLS = (
    ("org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast", "org.gnome.Mutter.ScreenCast.CreateSession", "a{sv}", ["0"]),
    ("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop", "org.gnome.Mutter.RemoteDesktop.CreateSession", "", []),
    ("org.gnome.Mutter.InputCapture", "/org/gnome/Mutter/InputCapture", "org.gnome.Mutter.InputCapture.CreateSession", "u", ["1"]),
    ("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig.GetCurrentState", "", []),
    ("org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot", "org.gnome.Shell.Screenshot.SelectArea", "", []),
    ("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Eval", "s", ["1+1"]),
    ("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.isScriptLoaded", "s", ["appjail-probe"]),
    ("org.kde.KWin", "/KWin", "org.kde.KWin.supportInformation", "", []),
    ("org.freedesktop.a11y.Manager", "/org/freedesktop/a11y/Manager", "org.freedesktop.a11y.KeyboardMonitor.WatchKeyboard", "", []),
    ("org.gnome.Mutter.ServiceChannel", "/org/gnome/Mutter/ServiceChannel",
     "org.gnome.Mutter.ServiceChannel.OpenWaylandServiceConnection", "u", ["1"]),
    ("org.gnome.Shell.Introspect", "/org/gnome/Shell/Introspect", "org.gnome.Shell.Introspect.GetWindows", "", []),
    ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive", "", []),
    ("org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel.allComponents", "", []),
    ("org.kde.KWin.ScreenShot2", "/org/kde/KWin/ScreenShot2", "org.kde.KWin.ScreenShot2.CaptureActiveScreen", "a{sv}h", None),
)


def run(argv, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 20)
    try:
        return subprocess.run(argv, **kw)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


def package_version(*packages):
    """The installed version of the first of these packages that is installed, as dpkg reports it."""
    for pkg in packages:
        out = run(["dpkg-query", "-W", "-f=${Version}", pkg]).stdout.strip()
        if out:
            return f"{pkg} {out}"
    return None


def distro():
    info = {}
    with contextlib.suppress(OSError):
        for line in Path("/etc/os-release").read_text().splitlines():
            key, _, value = line.partition("=")
            info[key] = value.strip('"')
    return {"id": info.get("ID"), "version": info.get("VERSION_ID"), "name": info.get("PRETTY_NAME"),
            "kernel": platform.release(), "arch": platform.machine()}


class Session:
    """A private runtime directory and a private session bus, removed at the end."""

    def __init__(self):
        self.rt = Path(tempfile.mkdtemp(prefix="cp"))
        os.chmod(self.rt, 0o700)
        self.bus = None
        self.address = ""

    def __enter__(self):
        read_fd, write_fd = os.pipe()
        self.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", f"--print-address={write_fd}"], pass_fds=(write_fd,),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(write_fd)
        with os.fdopen(read_fd) as f:
            self.address = f.readline().strip()
        return self

    def __exit__(self, *exc):
        for proc in (self.bus,):
            if proc and proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
        shutil.rmtree(self.rt, ignore_errors=True)

    def env(self, extra=None):
        env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(self.rt), "DBUS_SESSION_BUS_ADDRESS": self.address,
               "HOME": str(self.rt / "home"), "XDG_CONFIG_HOME": str(self.rt / "home" / ".config"),
               "XDG_CACHE_HOME": str(self.rt / "home" / ".cache"), "XDG_DATA_HOME": str(self.rt / "home" / ".local" / "share"),
               "LANG": "C.UTF-8", **(extra or {})}
        for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)
        return env


RENDER_NODE = "/dev/dri/renderD128"  # wayfire and Hyprland insist on a DRM device even with a headless backend
WLROOTS = {"WLR_BACKENDS": "headless", "WLR_LIBINPUT_NO_DEVICES": "1", "WLR_RENDERER": "pixman"}

# name -> (packages whose version is recorded, argv builder(session) -> argv, extra environment)
COMPOSITORS = {
    "weston": (("weston",), lambda s: ["weston", "--backend=headless", "--renderer=pixman", "--socket=probe-wl"], {}),
    "sway": (("sway",), lambda s: ["sway", "--unsupported-gpu", "-c", "/dev/null"], WLROOTS),
    "labwc": (("labwc",), lambda s: ["labwc"], WLROOTS),
    "wayfire": (("wayfire",), lambda s: ["wayfire"], {**WLROOTS, "WLR_RENDER_DRM_DEVICE": RENDER_NODE}),
    "cage": (("cage",), lambda s: ["cage", "--", "sleep", "3600"], WLROOTS),
    "hyprland": (("hyprland",), lambda s: ["Hyprland"], {"AQ_BACKENDS": "headless", "LIBSEAT_BACKEND": "noop", "AQ_DRM_DEVICES": "/dev/dri/card0"}),
    "kwin": (("kwin-wayland",), lambda s: ["kwin_wayland", "--virtual", "--socket=probe-kwin", "--no-lockscreen", "--no-global-shortcuts"],
             {"QT_QPA_PLATFORM": "offscreen"}),
    "mutter": (("mutter",), lambda s: ["mutter", "--headless", "--wayland", "--no-x11", "--virtual-monitor", "1024x768",
                                       "--wayland-display=probe-mutter"], {}),
    "gnome-shell": (("gnome-shell",), lambda s: ["gnome-shell", "--headless", "--wayland", "--no-x11", "--virtual-monitor",
                                                 "1024x768", "--wayland-display=probe-shell"], {}),
}


def sockets(rt):
    return {p.name for p in Path(rt).iterdir() if p.is_socket() and not p.name.endswith(".lock")}


def registry(rt, display):
    """{interface: version} of the registry, as appjail's own wayland code reads it."""
    sock, _events, found = wayland._connect({"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": display})
    sock.close()
    return {iface: version for iface, (_name, version) in sorted(found.items())}


def wait_for_display(proc, rt, before, timeout=START_TIMEOUT):
    """The name of the Wayland socket the compositor created, or None if it died or none answered in time. A compositor may
    make other sockets too (sway's IPC), so each new one is tried until one speaks Wayland."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        for name in sorted(sockets(rt) - before):
            try:
                registry(rt, name)
            except (OSError, RunError):
                continue
            time.sleep(0.5)  # the globals are announced a moment after the socket answers
            return name
        time.sleep(0.3)
    return None


def wayland_info(session, display):
    """The interface names `wayland-info` prints, a second reader of the same registry."""
    out = run(["wayland-info"], env=session.env({"WAYLAND_DISPLAY": display}))
    return sorted(set(re.findall(r"^interface: '([^']+)'", out.stdout, re.MULTILINE)))


def classify(interfaces):
    found = {}
    for iface in interfaces:
        if iface in PRIVILEGED_BY_NAME:
            found.setdefault(PRIVILEGED_BY_NAME[iface], []).append(iface)
    return found


def tool_env(session, directory, display):
    return session.env({"XDG_RUNTIME_DIR": str(directory), "WAYLAND_DISPLAY": display})


def tool(env, argv, **kw):
    out = run(argv, env=env, timeout=12, **kw)
    return {"ok": out.returncode == 0, "detail": (out.stderr or out.stdout).strip()[:120] if out.returncode else ""}


def functional(session, display, restricted):
    """What a client can really do on a socket, with real tools (advertised is not the same as usable): capture the
    screen, read another client's clipboard, type. `restricted` is (directory, name) of the restricted socket or None.
    Each is tried on the compositor's own socket and on the restricted one."""
    sockets_ = {"full": (session.rt, display)}
    if restricted:
        sockets_["restricted"] = restricted
    result = {}
    for label, (directory, name) in sockets_.items():
        env = tool_env(session, directory, name)
        shot = run(["grim", "-"], env=env, timeout=12, text=False)
        result.setdefault("capture", {})[label] = {"ok": shot.returncode == 0 and shot.stdout[:8] == b"\x89PNG\r\n\x1a\n",
                                                   "detail": shot.stderr.decode(errors="replace").strip()[:120]}
        result.setdefault("type", {})[label] = tool(env, ["wtype", "appjail"])
        # the victim copies on the compositor's own socket; the attacker reads on this one
        victim = subprocess.Popen(["wl-copy", "--foreground", "appjail-secret"], env=tool_env(session, session.rt, display),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        try:
            time.sleep(1.0)
            if victim.poll() is not None:
                result.setdefault("clipboard", {})[label] = {"ok": False, "detail": "no victim: " + victim.stderr.read().decode(errors="replace").strip()[:100]}
            else:
                got = run(["wl-paste", "--no-newline"], env=env, timeout=10)
                result.setdefault("clipboard", {})[label] = {"ok": got.returncode == 0 and got.stdout == "appjail-secret",
                                                             "detail": (got.stderr or got.stdout).strip()[:100] if got.stdout != "appjail-secret" else ""}
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(victim.pid, signal.SIGKILL)
    return result


def wayland_section(session, display, log):
    full = registry(session.rt, display)
    section = {"display": display, "full": full, "full_privileged": classify(full),
               "wayland_info_agrees": None, "security_context": SECURITY_CONTEXT in full}
    with contextlib.suppress(Exception):
        section["wayland_info_agrees"] = sorted(full) == wayland_info(session, display)
    if not section["security_context"]:
        section["functional"] = functional(session, display, None)
        return section
    env = {"XDG_RUNTIME_DIR": str(session.rt), "WAYLAND_DISPLAY": display}
    try:
        with wayland.RestrictedSocket(env, app_id="probe") as path:
            if path is None:
                section["restricted_error"] = "the manager was announced but no socket was made"
                section["functional"] = functional(session, display, None)
            else:
                restricted = None
                for attempt in range(6):  # a compositor may start serving the socket a moment after it accepted it
                    try:
                        restricted = registry(Path(path).parent, Path(path).name)
                        break
                    except (OSError, RunError):
                        if attempt == 5:
                            raise
                        time.sleep(0.5)
                section["restricted_attempts"] = attempt + 1
                section.update(restricted=restricted, restricted_privileged=classify(restricted),
                               hidden_by_restriction=sorted(set(full) - set(restricted)))
                section["functional"] = functional(session, display, (Path(path).parent, Path(path).name))
    except (OSError, RunError) as e:  # report, do not stop the survey
        section["restricted_error"] = f"{type(e).__name__}: {e}"
    return section


def busctl(session, *args, timeout=20):
    return run(["busctl", f"--address={session.address}", "--no-pager", *args], env=session.env(), timeout=timeout)


def owned_by(session, pid):
    """The well-known bus names whose owner is this process or one of its descendants."""
    names = []
    out = busctl(session, "list", "--json=short").stdout
    try:
        entries = json.loads(out)
    except ValueError:
        return names
    family = descendants(pid) | {pid}
    for entry in entries:
        name = entry.get("name", "")
        if not name.startswith(":") and name != "org.freedesktop.DBus" and entry.get("pid") in family:
            names.append(name)
    return sorted(names)


def descendants(pid):
    kids = {}
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            with contextlib.suppress(OSError, ValueError, IndexError):
                stat = (p / "stat").read_text()
                kids.setdefault(int(stat.rpartition(")")[2].split()[1]), []).append(int(p.name))
    out, todo = set(), [pid]
    while todo:
        for kid in kids.get(todo.pop(), []):
            out.add(kid)
            todo.append(kid)
    return out


STANDARD = {"org.freedesktop.DBus.Peer", "org.freedesktop.DBus.Introspectable", "org.freedesktop.DBus.Properties"}


def interfaces_of(session, name):
    """{interface: [method names]} of one bus name, over all its objects (busctl tree, then introspect, whose table has an
    `interface` row per interface and `.Member` rows below it)."""
    found = {}
    for path in busctl(session, "tree", "--list", name).stdout.split()[:400]:
        current = None
        for line in busctl(session, "introspect", name, path, timeout=10).stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "interface":
                current = None if fields[0] in STANDARD else found.setdefault(fields[0], [])
            elif current is not None and len(fields) >= 2 and fields[0].startswith(".") and fields[1] == "method":
                current.append(fields[0][1:])
    return {k: sorted(set(v)) for k, v in found.items()}


def appjail_allows(name):
    try:
        grants.check_dbus_name(name)
    except ManifestError as e:
        return False, str(e)[:90]
    return True, ""


def registry_of_socket(sock):
    """{interface: version} of the registry of a connected socket (one that was handed over, not opened by path)."""
    sock.settimeout(5)
    events, found = wayland.Events(sock), {}
    wayland._send(sock, wayland._message(wayland.DISPLAY_ID, 1, struct.pack("I", wayland.REGISTRY_ID)))
    wayland._roundtrip(sock, events, lambda *a: wayland._collect(*a, found))
    return {iface: version for iface, (_name, version) in sorted(found.items())}


def service_connections(session, display):
    """Mutter's ServiceChannel hands any client on the session bus a Wayland connection (a file descriptor). What its registry
    holds beyond the ordinary socket's, for each client type the service accepts; needs GLib's Python bindings (gi)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        return {"error": "python3-gi is not installed"}
    plain = set(registry(session.rt, display))
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    conn = Gio.DBusConnection.new_for_address_sync(session.address, flags, None, None)
    out = {}
    for client_type in range(8):
        try:
            _res, fds = conn.call_with_unix_fd_list_sync(
                "org.gnome.Mutter.ServiceChannel", "/org/gnome/Mutter/ServiceChannel", "org.gnome.Mutter.ServiceChannel",
                "OpenWaylandServiceConnection", GLib.Variant("(u)", (client_type,)), None, Gio.DBusCallFlags.NONE, 5000, None, None)
        except GLib.Error as e:
            out[str(client_type)] = {"ok": False, "detail": e.message[-90:]}
            continue
        with socket.socket(fileno=fds.get(0)) as sock:
            found = registry_of_socket(sock)
        out[str(client_type)] = {"ok": True, "extra_globals": sorted(set(found) - plain), "missing_globals": sorted(plain - set(found))}
    return out


def dbus_section(session, pid, log, display=None):
    """The well-known names the compositor owns, their interfaces (grouped: the names of one connection share its objects),
    what appjail's D-Bus policy would do with each name, and the outcome of the CALLS made as an ordinary client."""
    names = owned_by(session, pid)
    section = {"names": {}, "connections": [], "calls": []}
    groups = {}
    for name in names:
        ifaces = interfaces_of(session, name)
        allowed, why = appjail_allows(name)
        section["names"][name] = {"appjail_policy_allows": allowed, "appjail_policy_reason": why}
        groups.setdefault(json.dumps(ifaces, sort_keys=True), []).append(name)
    for key, owned in groups.items():
        ifaces = json.loads(key)
        section["connections"].append({"names": owned, "interfaces": ifaces,
                                       "privileged_looking": [i for i in ifaces if DBUS_PRIVILEGED.search(i)]})
    if "org.gnome.Mutter.ServiceChannel" in names and display:
        section["service_channel"] = service_connections(session, display)
    for name, path, member, signature, args in CALLS:
        if name not in names or args is None:
            continue
        iface, _, method = member.rpartition(".")
        out = busctl(session, "call", "--json=short", name, path, iface, method, signature, *args, timeout=15)
        section["calls"].append({"name": name, "member": member, "ok": out.returncode == 0,
                                 "answer": (out.stdout if out.returncode == 0 else out.stderr).strip()[:200]})
    return section


def stop(proc):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def survey(key, log):
    packages, argv_for, extra = COMPOSITORS[key]
    result = {"version": package_version(*packages)}
    if not shutil.which(argv_for(None)[0]):
        result["status"] = "not installed"
        return result
    with Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        before = sockets(session.rt)
        proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
        try:
            display = wait_for_display(proc, session.rt, before)
            if display is None:
                logfile.flush()
                result["status"] = "did not start"
                result["log_tail"] = (session.rt / "compositor.log").read_text(errors="replace")[-600:]
                return result
            result["status"] = "ok"
            result["wayland"] = wayland_section(session, display, log)
            result["dbus"] = dbus_section(session, proc.pid, log, display)
        except Exception as e:  # noqa: BLE001  (one compositor must not stop the others)
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", action="append", choices=sorted(COMPOSITORS), help="survey only these (repeatable)")
    parser.add_argument("--out", help="write the results as JSON to this file")
    args = parser.parse_args(argv)
    results = {"distro": distro(), "compositors": {}}
    for key in args.only or COMPOSITORS:
        print(f"== {key}", flush=True)
        results["compositors"][key] = survey(key, print)
        r = results["compositors"][key]
        wl = r.get("wayland", {})
        print(f"   {r['status']}; {r.get('version')}; security context: {wl.get('security_context')}; "
              f"privileged on the full socket: {sum(len(v) for v in wl.get('full_privileged', {}).values())}", flush=True)
    text = json.dumps(results, indent=1, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
