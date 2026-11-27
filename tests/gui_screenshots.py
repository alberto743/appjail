# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Screenshots of appjail-gui, light and dark, for reviewing a change to the window. Run in the guest from the
repository, never on the host: `python3 tests/gui_screenshots.py OUTDIR [WIDTHxHEIGHT]` (tests/vm/ssh.sh runs it).

It starts its own Xvfb, installs three fake apps (no download: the test harness) in a throwaway data directory under
the home directory, gives one of them an icon, and writes one PNG per page and dialog to OUTDIR."""

import atexit
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISPLAY = ":77"


def setup(base):
    os.environ.update(APPJAIL_DATA_DIR=str(base / "data"), APPJAIL_CONFIG_DIR=str(base / "config"),
                      XDG_DATA_HOME=str(base / "share"), DISPLAY=DISPLAY)
    sys.path[:0] = [str(HERE.parent), str(HERE.parent / "src")]
    from appjail import history
    from appjail.gui import icons
    from tests.helpers import Harness

    history.enabled = False
    (base / "Documents").mkdir()
    h = Harness()
    h.add(extra=["--name", "lagrange", "--allow", "network", "--allow", "gpu", "--allow", "audio", "--dir", f"{base}/Documents:rw"],
          source="skyjake/lagrange")
    h.add(extra=["--name", "htop"], source="pkgforge-dev/htop-AppImage")
    h.add(extra=["--name", "obsidian", "--allow", "network", "--allow", "portals", "--portal", "OpenURI"],
          source="obsidianmd/obsidian-releases")
    c = icons.Canvas(256, 256)  # an icon as `desktop` would have installed it
    c.paint(icons.rounded_rect(8, 8, 248, 248, 56), "#7c3aed")
    c.paint(icons.circle(128, 128, 70), "#fde68a")
    c.paint(icons.circle(150, 110, 60), "#7c3aed")
    target = base / "share/icons/hicolor/256x256/apps/appjail-lagrange.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(c.png())


def screenshot(path):
    """The whole X screen as a PNG (xwd output, 32 bits per pixel, converted here)."""
    from appjail.gui import icons
    raw = subprocess.run(["xwd", "-root", "-silent", "-display", DISPLAY], capture_output=True, check=True).stdout
    f = struct.unpack(">25I", raw[:100])
    header, width, height, msb, bpl, ncolors = f[0], f[4], f[5], f[7], f[12], f[19]
    pos = header + ncolors * 12
    rgba = bytearray()
    for y in range(height):
        row = raw[pos + y * bpl:pos + y * bpl + width * 4]
        for x in range(0, width * 4, 4):
            rgba += bytes((row[x + 1], row[x + 2], row[x + 3], 255) if msb else (row[x + 2], row[x + 1], row[x], 255))
    path.write_bytes(icons.encode_png(width, height, rgba))


def main(out, size="1280x800"):
    out.mkdir(parents=True, exist_ok=True)
    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{size}x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(xvfb.terminate)
    time.sleep(1)
    setup(Path(tempfile.mkdtemp(dir=Path.home())))  # not under /tmp: appjail refuses to grant a directory there
    import tkinter as tk

    from appjail.gui import app, dialogs
    from appjail.gui import apps as gui_apps
    from appjail.gui.console import Request

    for dark in (False, True):
        mode = "dark" if dark else "light"
        root = tk.Tk()
        window = app.App(root, dark=dark)
        root.geometry("+0+0")

        def settle(root=root, rounds=20):
            for _ in range(rounds):
                root.update()
                time.sleep(0.03)

        def grab(name, root=root, mode=mode):
            settle(root)
            screenshot(out / f"{mode}-{name}.png")
            for w in root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()

        settle(rounds=40)  # the icon is decoded on a thread
        window.tree.selection_set("lagrange")
        for page in window.pages:
            window.show(page)
            if page == "tools":
                for line in ("$ appjail version", "appjail", "note: a note", "! warning: a warning", "error: an error",
                             "-- exit status 0 --"):
                    window.say(line)
                window.toggle_log(True)
            settle()
            screenshot(out / f"{mode}-{page}.png")
        root.after(700, lambda: grab("permissions"))
        dialogs.permissions_editor(root, "lagrange", gui_apps.load_permissions("lagrange"))
        root.after(700, lambda: grab("confirm"))
        dialogs.answer(root, Request("confirm", "Install lagrange with these permissions?",
                                     review=("Source     : github:skyjake/lagrange", "Permissions: network, gpu, audio")))
        root.destroy()
    print(f"screenshots in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), *sys.argv[2:3])
