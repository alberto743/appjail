# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Can a client with nothing but a Wayland connection draw over the desktop of Cinnamon, through `zwlr_layer_shell_v1`?

    python3 tests/compositors/layer_shell.py --out /tmp/layer-shell.json

Cinnamon (nested in a private Xvfb) is captured twice through its own screenshot service, which is a way to see the screen
and not what is being tested: before and after `swaybg -c '#ff00ff'` is started on the compositor's socket. swaybg is a plain
layer-shell client. The result says whether the layer shell is listed, whether swaybg stayed up, and how much of the second
capture is the colour it draws (the first capture is the control). Guests only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cinnamon_dbus
import probe

COLOUR = (255, 0, 255)


def share(path):
    """The share of the pixels of a PNG that have exactly COLOUR (sampled every 4th pixel), read with GdkPixbuf."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pix = GdkPixbuf.Pixbuf.new_from_file(str(path))
    data, step, stride = pix.get_pixels(), pix.get_n_channels(), pix.get_rowstride()
    hits = total = 0
    for y in range(0, pix.get_height(), 4):
        for x in range(0, pix.get_width(), 4):
            total += 1
            hits += tuple(data[y * stride + x * step:y * stride + x * step + 3]) == COLOUR
    return round(hits / total, 3) if total else 0.0


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
            result["layer_shell_listed"] = "zwlr_layer_shell_v1" in probe.registry(session.rt, display)
            time.sleep(4.0)
            owned = probe.busctl(session, "list", "--json=short", timeout=15).stdout
            name, path, interface, signature, args = next((e for e in cinnamon_dbus.SHOTS if f'"{e[0]}"' in owned), cinnamon_dbus.SHOTS[0])

            def capture(label):
                shot = session.rt / f"{label}.png"
                out = probe.busctl(session, "call", "--json=short", name, path, interface, "Screenshot", signature,
                                   *[str(shot) if a is None else a for a in args], timeout=15)
                return share(shot) if out.returncode == 0 and shot.exists() else None

            result["control_share"] = capture("control")
            client = subprocess.Popen(["swaybg", "-c", "#ff00ff"], env=probe.tool_env(session, session.rt, display), stdout=logfile,
                                      stderr=logfile, start_new_session=True)
            procs.append(client)
            time.sleep(3.0)
            result["client_still_running"] = client.poll() is None
            result["share_with_client"] = capture("with-client")
            result["draws_over_the_desktop"] = bool(result["client_still_running"] and (result["share_with_client"] or 0) > 0.5
                                                    and (result["control_share"] or 0) < 0.01)
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
    data = {"distro": probe.distro(), "cinnamon": evaluate()}
    print(json.dumps(data, indent=1))
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
