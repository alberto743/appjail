# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Does ordinary, focused copy and paste work between an app on the socket appjail would give it and an app outside?

    python3 tests/compositors/clipboard.py --out /tmp/clipboard.json [--only sway,kwin]

For each compositor: the app's socket is the restricted one when the compositor makes it, else the compositor's own. Two
GTK 4 windows (clip_client.py) take turns: outside copies and the app pastes (inbound), the app copies and outside pastes
(outbound). A persistent virtual keyboard (wtype) gives the headless seat a keyboard, so a window can get focus. A result
is `ok` (the text arrived), `failed` (it did not) or `untestable` (a window never got keyboard focus). Guests only.
"""

import argparse
import contextlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

from appjail import wayland
from appjail.errors import RunError

CLIENT = str(Path(__file__).resolve().parent / "clip_client.py")
GTK = {"GDK_BACKEND": "wayland", "GSETTINGS_BACKEND": "memory", "GTK_A11Y": "none", "GSK_RENDERER": "cairo"}
SECRET = "appjail-focused-clipboard"


def start(session, directory, name, mode, out, text=""):
    env = probe.tool_env(session, directory, name)
    env.update(GTK)
    return subprocess.Popen(["python3", CLIENT, mode, str(out), text], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def wait_line(out, prefix, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        lines = out.read_text().splitlines() if out.exists() else []
        for line in lines:
            if line.startswith((prefix, "error:")) or line in ("no-focus", "timeout"):
                return line, lines
        time.sleep(0.3)
    return "", (out.read_text().splitlines() if out.exists() else [])


def wait_active(session, out, timeout):
    """Wait for the window to report keyboard focus. A compositor that does not focus a new window by itself (Mutter) is
    nudged every 3 s with the input its own API offers."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        line, lines = wait_line(out, "active", 3)
        if line:
            return line, lines
        if getattr(session, "focus", None):
            session.focus()
    return "", lines


def verdict(copier_lines, paster_lines):
    """`ok`, `failed (...)`, or `untestable` when a window never had keyboard focus (then nothing could be copied or pasted)."""
    if "active" not in copier_lines or (copier_lines[-1:] == ["copied"] and "active" not in paster_lines):
        return "untestable (a window never got keyboard focus)"
    pasted = [line for line in paster_lines if line.startswith("pasted:")]
    if pasted and pasted[0] == "pasted:" + SECRET:
        return "ok"
    return "failed (" + "; ".join(paster_lines or ["nothing"]) + ")"


def direction(session, work, label, copy_on, paste_on):
    """Copy on one socket, then paste on another (each is (directory, name)); the paster starts after the copy happened."""
    copy_out, paste_out = work / f"{label}-copy", work / f"{label}-paste"
    copier = start(session, *copy_on, "copy", copy_out, SECRET)
    try:
        line, copier_lines = wait_active(session, copy_out, 30)
        if line == "active":
            time.sleep(1.0)  # focus settled; the key gives the copier the input serial a selection needs
            session.press()
            line, copier_lines = wait_line(copy_out, "copied", 8)
        if line != "copied":
            return verdict(copier_lines, [])
        time.sleep(0.5)
        paster = start(session, *paste_on, "paste", paste_out)
        try:
            wait_active(session, paste_out, 30)
            _line, paster_lines = wait_line(paste_out, "pasted:", 16)
        finally:
            probe.stop(paster, signal.SIGKILL)
        return verdict(copier_lines, paster_lines)
    finally:
        probe.stop(copier, signal.SIGKILL)


def wtype_keyboard(session, directory, display):
    """A persistent virtual keyboard on this compositor (what gives a headless seat a keyboard) and the function that types."""
    env = probe.tool_env(session, directory, display)
    proc = subprocess.Popen(["wtype", "x", "-s", "100000", "y"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    time.sleep(1.0)
    return proc, lambda: probe.run(["wtype", "z"], env=env, timeout=8)


def remote_desktop_keyboard(session):
    """Mutter's and GNOME Shell's own way: a RemoteDesktop session on the bus."""
    proc = subprocess.Popen(["python3", str(Path(__file__).resolve().parent / "rd_keyboard.py")], env=session.env(), text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    if proc.stdout.readline().strip() != "started":
        raise RuntimeError("RemoteDesktop session did not start")
    time.sleep(2.0)  # the seat takes a moment to show the new devices

    def send(line):
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
    session.focus = lambda: send("click")
    return proc, lambda: send("key")


def sockets_of(session, display, result):
    """(outside, app): the compositor's own socket and the one appjail would give an app."""
    outside = (session.rt, display)
    result["app_socket"] = "full"
    return outside, outside


def run_directions(session, result, outside, app):
    work = session.rt / "work"
    work.mkdir(exist_ok=True)
    result["inbound"] = direction(session, work, "in", outside, app)
    result["outbound"] = direction(session, work, "out", app, outside)


def evaluate(key):
    nested = key == "weston-nested"
    packages, argv_for, extra = probe.COMPOSITORS["weston" if nested else key]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        procs = []
        try:
            host_env = session.env(probe.COMPOSITORS["sway"][2] if nested else extra)
            if nested:  # weston has no input of its own here: it runs as a window of a headless sway, which has a virtual keyboard
                sway = subprocess.Popen(probe.COMPOSITORS["sway"][1](session), env=host_env, stdout=logfile, stderr=logfile, start_new_session=True)
                procs.append(sway)
                host = probe.wait_for_display(sway, session.rt, set())
                if host is None:
                    result["status"] = "host sway did not start"
                    return result
                kproc, press = wtype_keyboard(session, session.rt, host)
                procs.append(kproc)
                before = probe.sockets(session.rt)
                weston_env = session.env({"WAYLAND_DISPLAY": host})
                proc = subprocess.Popen(["weston", "--backend=wayland", "--renderer=pixman", "--socket=probe-wl"], env=weston_env,
                                        stdout=logfile, stderr=logfile, start_new_session=True)
            else:
                before = probe.sockets(session.rt)
                proc = subprocess.Popen(argv_for(session), env=host_env, stdout=logfile, stderr=logfile, start_new_session=True)
            procs.append(proc)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                result["log_tail"] = (session.rt / "compositor.log").read_text(errors="replace")[-400:]
                return result
            result["status"] = "ok"
            session.display = display
            outside, app = sockets_of(session, display, result)
            full = probe.registry(session.rt, display)
            restricted = None
            if probe.SECURITY_CONTEXT in full:
                restricted = wayland.RestrictedSocket({"XDG_RUNTIME_DIR": str(session.rt), "WAYLAND_DISPLAY": display}, app_id="clipboard")
                with contextlib.suppress(OSError, RunError), restricted as path:
                    if path is not None:
                        app, result["app_socket"] = (Path(path).parent, Path(path).name), "restricted"
                    kproc, session.press = wtype_keyboard(session, session.rt, display)
                    procs.append(kproc)
                    run_directions(session, result, outside, app)
                    return result
            if nested:
                session.press = press
            elif key in ("mutter", "gnome-shell"):
                kproc, session.press = remote_desktop_keyboard(session)
                procs.append(kproc)
            else:
                kproc, session.press = wtype_keyboard(session, session.rt, display)
                procs.append(kproc)
            run_directions(session, result, outside, app)
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            for proc in reversed(procs):
                probe.stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    # a standalone headless weston has no input at all, so it is only measured nested (as a window of a headless sway)
    keys = [k for k in [*(c for c in probe.COMPOSITORS if c != "weston"), "weston-nested"] if not args.only or k in args.only.split(",")]
    data = {"distro": probe.distro(), "compositors": {}}
    for key in keys:
        print(f"== {key}", flush=True)
        data["compositors"][key] = evaluate(key)
        print(json.dumps(data["compositors"][key]), flush=True)
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
