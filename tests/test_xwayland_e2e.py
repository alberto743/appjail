# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A real X11-only AppImage under the jail's private Xwayland (ImageMagick `display`, pure Xlib).

Opt-in because it downloads a 32 MB AppImage (ImageMagick/ImageMagick, approved test app, guest only):
    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_xwayland_e2e.py -v'
"""

import os
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from appjail import cli, jail, manifest, runner, store

pytestmark = pytest.mark.skipif(
    os.environ.get("APPJAIL_E2E") != "1" or not shutil.which("weston") or not shutil.which("Xwayland")
    or not shutil.which("xwininfo"),
    reason="set APPJAIL_E2E=1 in the test guest (downloads an AppImage; needs weston, xwayland, x11-utils)")

# AppRun runs `magick "$@"`, and `magick display` is the legacy `display` tool. It draws the built-in logo: image,
# stays open until timeout stops it, and xwininfo lists the windows the app's X server holds.
SCRIPT = 'timeout 10 /app/AppRun display logo: & sleep 4; xwininfo -root -tree; wait'


class Answers(cli.Console):
    def __init__(self, answers):
        self.answers, self.lines = list(answers), []

    def out(self, line=""):
        self.lines.append(line)

    def warn(self, line):
        self.lines.append("WARNING: " + line)

    def ask(self, prompt):
        return self.answers.pop(0)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    base = tmp_path_factory.mktemp("xw")
    os.environ["APPJAIL_DATA_DIR"] = str(base / "data")
    os.environ["APPJAIL_CONFIG_DIR"] = str(base / "config")
    console = Answers(["2", "y"])  # the gcc build is the second of the two x86_64 AppImages; confirm the download
    assert cli.main(["add", "ImageMagick/ImageMagick", "--name", "imagemagick"], console=console) == 0, console.lines
    assert any("gcc-x86_64.AppImage" in line for line in console.lines), console.lines
    yield
    shutil.rmtree(base, ignore_errors=True)
    del os.environ["APPJAIL_DATA_DIR"], os.environ["APPJAIL_CONFIG_DIR"]


@pytest.fixture
def weston():
    rt = Path(f"/run/user/{os.getuid()}")
    proc = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--socket=appjail-e2xw"],
                            env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (rt / "appjail-e2xw").exists():
                break
            time.sleep(0.1)
        yield {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "appjail-e2xw", "LANG": "C.UTF-8"}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def run_display(display, env):
    m, root, home, etc = runner.prepare("imagemagick", say=lambda *_: None)
    perms = replace(m.permissions, display=display)
    argv = [jail.find_bwrap(), *jail.runtime_args(
        root=root, home=home, etc_dir=etc, perms=perms, uid=os.getuid(), host_env=env,
        command=["/bin/sh", "-c", SCRIPT], host_home=Path.home())]
    return jail.supervise(argv, timeout=60)


def test_add_pinned_the_github_digest(installed):
    m = manifest.load(store.manifest_path("imagemagick"))
    assert m.evidence_tier == 3 and m.permissions.display == "wayland"


def test_x11_only_app_opens_a_window_on_the_private_xwayland(installed, weston):
    proc = run_display("xwayland", weston)
    assert proc.returncode == 0, proc.stderr
    assert '"ImageMagick: "' in proc.stdout, proc.stdout + proc.stderr


def test_x11_only_app_cannot_run_with_display_wayland(installed, weston):
    proc = run_display("wayland", weston)
    assert "unable to open X server" in proc.stderr, proc.stderr
    assert "ImageMagick" not in proc.stdout
