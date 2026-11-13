# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""What an ordinary client of the session bus can do through Cinnamon's own D-Bus names (no portal, no prompt), on Cinnamon
running nested in a private Xvfb (it has no headless backend). *-compositors guests only:

    python3 tests/compositors/cinnamon_dbus.py --out /tmp/cinnamon-dbus.json

* command: `org.Cinnamon.Eval` runs JavaScript in the shell; the script starts a command that creates a file.
* keystroke: `Eval` again, with a virtual keyboard of the shell's own input stack, types into the window of another client
  (the GTK 4 window of mutter_dbus.py, which logs the keys it receives).
* capture: `org.gnome.Shell.Screenshot.Screenshot`, which Cinnamon owns, writes a picture of the screen; its size and whether
  the other client's red window is in it are recorded.
* crash: `org.gnome.Shell.Screenshot.SelectArea`, and whether Cinnamon is still running afterwards (last, since it may not be).

These are names `grants.DBUS_BLOCKED` refuses (`org.Cinnamon`, `org.gnome.Shell`); this shows what granting them would give.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

HERE = Path(__file__).resolve()
WINDOW = HERE.parent / "mutter_dbus.py"
KEYS = "appjail"
CINNAMON, SHOT = ("org.Cinnamon", "/org/Cinnamon", "org.Cinnamon"), ("org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot",
                                                                     "org.gnome.Shell.Screenshot")
# Run in the shell: activate the window titled "victim", then type KEYS with a virtual keyboard of the shell's seat.
TYPE_JS = """
const Clutter = imports.gi.Clutter, GLib = imports.gi.GLib;
const win = global.get_window_actors().map(a => a.get_meta_window()).find(w => w.get_title() === "victim");
if (win) win.activate(global.get_current_time());
const seat = Clutter.get_default_backend().get_default_seat();
const kbd = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
let t = GLib.get_monotonic_time();
for (const c of "@KEYS@") {
    kbd.notify_keyval(t += 20000, c.charCodeAt(0), Clutter.KeyState.PRESSED);
    kbd.notify_keyval(t += 20000, c.charCodeAt(0), Clutter.KeyState.RELEASED);
}
!!win
""".replace("@KEYS@", KEYS)


def png_facts(path):
    """(width, height, whether a pure red pixel is in it) of a PNG, read with GdkPixbuf."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pix = GdkPixbuf.Pixbuf.new_from_file(str(path))
    data, step, stride = pix.get_pixels(), pix.get_n_channels(), pix.get_rowstride()
    red = any(data[y * stride + x * step:y * stride + x * step + 3] == b"\xff\x00\x00"
              for y in range(0, pix.get_height(), 4) for x in range(0, pix.get_width(), 4))
    return pix.get_width(), pix.get_height(), red


def evaluate():
    packages, argv_for, extra = probe.COMPOSITORS["cinnamon"]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    procs = []
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        try:
            before = probe.sockets(session.rt)
            proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
            procs.append(proc)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            result["status"] = "ok"
            time.sleep(4.0)  # the shell loads its applets after the socket appears

            def call(target, method, signature="", *args):
                out = probe.busctl(session, "call", "--json=short", *target, method, signature, *args, timeout=15)
                text = (out.stdout if out.returncode == 0 else out.stderr).strip()
                return out.returncode == 0, (json.loads(text)["data"] if out.returncode == 0 and text else text[:200])

            proof = session.rt / "eval-proof"
            ok, answer = call(CINNAMON, "Eval", "s", f'imports.gi.GLib.spawn_command_line_async("touch {proof}")')
            time.sleep(1.0)
            result["command"] = {"answer": answer, "ok": ok and proof.exists()}

            log = session.rt / "victim.log"
            wenv = session.env({"WAYLAND_DISPLAY": display, "GDK_BACKEND": "wayland"})
            procs.append(subprocess.Popen(["python3", str(WINDOW), "window", str(log)], env=wenv, stdout=logfile, stderr=logfile,
                                          start_new_session=True))
            time.sleep(4.0)
            ok, answer = call(CINNAMON, "Eval", "s", TYPE_JS)
            time.sleep(1.5)
            received = log.read_text().split() if log.exists() else []
            typed = "".join(line[4:] for line in received if len(line) == 5 and line.startswith("key:"))
            result["type"] = {"answer": answer, "victim_log": received, "received": typed, "ok": ok and KEYS in typed}

            # the nested output is not the Xvfb screen's size: the shell's stage says how large the whole screen is
            _ok, stage = call(CINNAMON, "Eval", "s", "global.stage.width + 'x' + global.stage.height")
            shot = session.rt / "shot.png"
            ok, answer = call(SHOT, "Screenshot", "bbs", "false", "false", str(shot))
            capture = {"answer": answer, "stage": stage[1].strip('"') if isinstance(stage, list) else stage, "ok": False}
            if ok and shot.exists():
                width, height, red = png_facts(shot)
                capture.update(width=width, height=height, red=red, ok=f"{width}x{height}" == capture["stage"] and red)
            result["capture"] = capture

            ok, answer = call(SHOT, "SelectArea")
            time.sleep(2.0)
            result["select_area"] = {"answer": answer, "survived": proc.poll() is None}
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            for p in reversed(procs):
                probe.stop(p)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    data = {"distro": probe.distro(), "compositors": {"cinnamon": evaluate()}}
    print(json.dumps(data["compositors"]["cinnamon"]), flush=True)
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
