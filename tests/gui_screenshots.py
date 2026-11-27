# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Screenshots of appjail-gui, light and dark, for reviewing a change to the window and for the README. Run in the guest
from the repository, never on the host (tests/vm/ssh.sh runs it):

    python3 tests/gui_screenshots.py OUTDIR [WIDTHxHEIGHT]      every page and dialog, light and dark
    python3 tests/gui_screenshots.py --readme OUTDIR             the four images of the README (docs/assets/screenshots)

It starts its own Xvfb, makes a throwaway home directory with three made-up apps (installed through the test harness:
nothing is downloaded, and their names, sources and icons are inventions), and writes PNGs cropped to the window."""

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
# (name, owner/repo, tag, grants, icon colours or None for the stand-in)
DEMO = (("notes", "example/notes", "v3.2.0", ["--allow", "network", "--dir", "~/Documents:rw"], ("#f59e0b", "#fffbeb")),
        ("sketchbook", "example/sketchbook", "v1.8.2", ["--allow", "gpu", "--dir", "~/Pictures:rw"], ("#8b5cf6", "#ede9fe")),
        ("weather", "example/weather", "v0.9.4", ["--allow", "network", "--allow", "portals", "--portal", "OpenURI"],
         ("#0ea5e9", "#fde047")),
        ("monitor", "example/monitor", "v4.0.1", [], None))
README = ("apps-light", "apps-dark", "add-light", "permissions-dark")


def demo_icon(icons, colours, kind):
    """A made-up 256 px icon: a rounded square with a simple mark, as `desktop` would have installed it."""
    back, mark = colours
    c = icons.Canvas(256, 256)
    c.paint(icons.rounded_rect(12, 12, 244, 244, 56), back)
    if kind == "notes":
        c.paint(icons.rounded_rect(70, 52, 186, 204, 14), mark)
        c.paint(icons.union(*(icons.segment(92, y, 164, y, 10) for y in (96, 128, 160))), back)
    elif kind == "sketchbook":
        c.paint(icons.circle(128, 128, 76), mark)
        for x, y in ((100, 100), (156, 104), (100, 156)):
            c.paint(icons.circle(x, y, 16), back)
    else:
        c.paint(icons.circle(110, 116, 46), mark)
        c.paint(icons.rounded_rect(92, 136, 196, 184, 24), "#ffffff")
    return c.png()


def setup(base):
    """The home directory, the data and config directories and the demo apps, before anything reads HOME."""
    os.environ.update(HOME=str(base), APPJAIL_DATA_DIR=str(base / ".local/share/appjail"),
                      APPJAIL_CONFIG_DIR=str(base / ".config/appjail"), XDG_DATA_HOME=str(base / ".local/share"), DISPLAY=DISPLAY)
    sys.path[:0] = [str(HERE.parent), str(HERE.parent / "src")]
    from appjail import github, history
    from appjail.gui import icons
    from tests.helpers import FAKE_APPIMAGE, SHA, FakeClient, Harness, info

    history.enabled = False
    for folder in ("Documents", "Pictures"):
        (base / folder).mkdir()
    h = Harness()
    for name, repo, tag, grants, colours in DEMO:
        owner = repo.split("/")[0]
        filename = f"{name.title()}-{tag[1:]}-x86_64.AppImage"
        url = f"https://github.com/{repo}/releases/download/{tag}/{filename}"
        client = FakeClient(info(full_name=repo, owner=owner, html_url=f"https://github.com/{repo}", description=f"The {name} app"),
                            github.Release(tag, "2026-10-01T10:00:00Z", False, f"https://github.com/{repo}/releases/tag/{tag}",
                                           (github.Asset(filename, len(FAKE_APPIMAGE), SHA, url),)))
        h.add(client=client, extra=["--name", name, *grants], source=repo)
        if colours:
            target = base / f".local/share/icons/hicolor/256x256/apps/appjail-{name}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(demo_icon(icons, colours, name))


def screenshot(path, box):
    """The window's part of the X screen as a PNG (xwd output, 32 bits per pixel, converted here)."""
    from appjail.gui import icons
    raw = subprocess.run(["xwd", "-root", "-silent", "-display", DISPLAY], capture_output=True, check=True).stdout
    f = struct.unpack(">25I", raw[:100])
    header, width, height, msb, bpl, ncolors = f[0], f[4], f[5], f[7], f[12], f[19]
    x0, y0, w, h = box
    w, h = min(w, width - x0), min(h, height - y0)
    pos = header + ncolors * 12
    rgba = bytearray()
    for y in range(y0, y0 + h):
        row = raw[pos + y * bpl:pos + y * bpl + width * 4]
        for x in range(x0 * 4, (x0 + w) * 4, 4):
            rgba += bytes((row[x + 1], row[x + 2], row[x + 3], 255) if msb else (row[x + 2], row[x + 1], row[x], 255))
    path.write_bytes(icons.encode_png(w, h, rgba))


def main(out, size="1280x800", wanted=None):
    out.mkdir(parents=True, exist_ok=True)
    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{size}x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(xvfb.terminate)
    time.sleep(1)
    setup(Path(tempfile.mkdtemp(prefix="home-", dir=Path.home())))  # not under /tmp: appjail refuses to grant a directory there
    import tkinter as tk

    from appjail.gui import app, dialogs, files
    from appjail.gui import apps as gui_apps
    from appjail.gui.console import Request

    def want(name):
        return wanted is None or name in wanted

    for dark in (False, True):
        mode = "dark" if dark else "light"
        root = tk.Tk()
        window = app.App(root, dark=dark)
        root.geometry("+0+0")

        def settle(root=root, rounds=20):
            for _ in range(rounds):
                root.update()
                time.sleep(0.03)

        def shoot(name, root=root, mode=mode):
            root.event_generate("<Motion>", warp=True, x=2, y=2)  # the pointer off every button: none shows hovered
            settle(root)
            screenshot(out / f"{name}-{mode}.png", (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()))

        def grab(name, root=root, mode=mode):
            shoot(name, root, mode)
            for w in root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()

        settle(rounds=40)  # the icons are decoded on a thread
        window.tree.selection_set("notes")
        for page in window.pages:
            if not want(f"{page}-{mode}"):
                continue
            window.show(page)
            if page == "add":
                window.source.set("example/notes")
                window.flag["network"].set(True)
            if page == "tools":
                for line in ("$ appjail version", "appjail", "note: a note", "! warning: a warning", "error: an error",
                             "-- exit status 0 --"):
                    window.say(line)
                window.toggle_log(True)
            shoot(page)
        for name, opener in (
                ("permissions", lambda r: dialogs.permissions_editor(r, "notes", gui_apps.load_permissions("notes"))),
                ("confirm", lambda r: dialogs.answer(r, Request("confirm", "Install notes with these permissions?", review=(
                    "Source     : github:example/notes", "Version    : v3.2.0", "Permissions: network")))),
                ("chooser", lambda r: files.choose_file(r, "Choose an AppImage", patterns=[("AppImages", "*.appimage")])),
                ("notice", lambda r: dialogs.notice(r, "cannot read the manifest: an example of an error message", error=True))):
            if want(f"{name}-{mode}"):
                root.after(700, lambda n=name: grab(n))
                opener(root)
        root.destroy()
    print(f"screenshots in {out}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--readme"]:
        main(Path(sys.argv[2]), "1280x900", README)
    else:
        main(Path(sys.argv[1]), *sys.argv[2:3])
