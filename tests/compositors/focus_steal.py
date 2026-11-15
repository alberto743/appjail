# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Can a client with nothing but a window take the keyboard focus from another client, through gtk_shell1?

    python3 tests/compositors/focus_steal.py --out /tmp/focus.json [--only mutter,gnome-shell]

Two bare windows (focus_client.py) on the socket of a compositor that lists gtk_shell1: the victim is mapped and focused last.
The other window (the thief) then sends, one after the other, and each time the log of its keyboard focus says whether it got
it back: nothing (the control), gtk_surface1.present with the timestamp 1 (long before the last user input), present with 0, and
notify_launch followed by request_focus with the same startup id. Guests only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clipboard
import probe

CLIENT = str(Path(__file__).resolve().parent / "focus_client.py")
GNOME = ("mutter", "gnome-shell")


def start(session, directory, name, out):
    return subprocess.Popen(["python3", CLIENT, str(out)], env=probe.tool_env(session, directory, name), stdin=subprocess.PIPE, text=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def lines(out):
    return out.read_text().splitlines() if out.exists() else []


def wait_for(session, out, wanted, count=1, timeout=20, nudge=True):
    """Wait until the log has `count` lines equal to `wanted`; the compositor is nudged (a click) when it does not focus by itself."""
    end, last = time.monotonic() + timeout, 0.0
    while time.monotonic() < end:
        if lines(out).count(wanted) >= count:
            return True
        if nudge and time.monotonic() - last > 3 and getattr(session, "focus", None):
            session.focus()
            last = time.monotonic()
        time.sleep(0.3)
    return False


def focused(log):
    """Whether the last focus line of the log is an enter."""
    focus = [line for line in log if line.startswith("keyboard-")]
    return bool(focus) and focus[-1] == "keyboard-enter"


def command(proc, line):
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def trial(thief, thief_out, victim_out, line):
    """Send one command from the thief; whether the thief has the focus afterwards, and the victim has lost it."""
    before = len(lines(thief_out))
    if line:
        command(thief, line)
    time.sleep(3.0)
    return {"command": line or "nothing", "thief_focused": focused(lines(thief_out)), "victim_focused": focused(lines(victim_out)),
            "thief_events": lines(thief_out)[before:]}


def evaluate(key):
    packages, argv_for, extra = probe.COMPOSITORS[key]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        procs = []
        try:
            before = probe.sockets(session.rt)
            proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
            procs.append(proc)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            session.display = display
            if "gtk_shell1" not in probe.registry(session.rt, display):
                result["status"] = "no gtk_shell1"
                return result
            if key in GNOME:
                kproc, _press = clipboard.remote_desktop_keyboard(session)
            else:
                kproc, _press = clipboard.wtype_keyboard(session, session.rt, display)
            procs.append(kproc)
            work = session.rt / "work"
            work.mkdir(exist_ok=True)
            thief_out = work / "thief.log"
            thief = start(session, session.rt, display, thief_out)
            procs.append(thief)
            if not wait_for(session, thief_out, "mapped") or not wait_for(session, thief_out, "keyboard-enter"):
                result["status"] = "untestable: the first window never got the keyboard focus"
                return result
            result["status"] = "ok"
            steps = []
            for number, line in enumerate(("", "present 1", "present 0", "notify appjail-test;request_focus appjail-test")):
                victim_out = work / f"victim{number}.log"  # a new window each time: it is mapped last and gets the focus
                victim = start(session, session.rt, display, victim_out)
                procs.append(victim)
                if not wait_for(session, victim_out, "keyboard-enter"):
                    steps.append({"command": line or "nothing", "status": "untestable: the new window never got the focus"})
                    continue
                time.sleep(1.0)
                if focused(lines(thief_out)):
                    steps.append({"command": line or "nothing", "status": "untestable: both windows have the focus"})
                    continue
                steps.append(trial(thief, thief_out, victim_out, line))
                probe.stop(victim)
                time.sleep(1.0)
            result["gtk_shell1"] = [line for line in lines(thief_out) if line.startswith("gtk_shell1")]
            result["steps"] = steps
            result["steals_focus"] = any(s.get("thief_focused") for s in steps if s["command"] != "nothing")
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
    keys = [k for k in ("mutter", "gnome-shell", "muffin", "cinnamon") if not args.only or k in args.only.split(",")]
    data = {"distro": probe.distro(), "compositors": {}}
    for key in keys:
        print(f"== {key}", flush=True)
        data["compositors"][key] = evaluate(key)
        print(json.dumps(data["compositors"][key]), flush=True)
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
