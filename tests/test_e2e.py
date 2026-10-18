# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""End to end against real GitHub in the test guest: add -> run -> tamper.

Opt-in because it downloads an 11 MB AppImage (skyjake/lagrange, approved test app):
    tests/vm/ssh.sh 'cd ~/bjail && BJAIL_E2E=1 python3 -m pytest tests/test_e2e.py -v'
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from bjail import cli, manifest, runner, store

pytestmark = pytest.mark.skipif(
    os.environ.get("BJAIL_E2E") != "1" or not shutil.which("weston"),
    reason="set BJAIL_E2E=1 in the test guest (downloads an AppImage)")


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
    base = tmp_path_factory.mktemp("e2e")
    os.environ["BJAIL_DATA_DIR"] = str(base / "data")
    os.environ["BJAIL_CONFIG_DIR"] = str(base / "config")
    console = Answers(["2", "y"])  # the second AppImage of the release is the GUI one; confirm the download
    assert cli.main(["add", "skyjake/lagrange", "--name", "lagrange"], console=console) == 0, console.lines
    yield console
    shutil.rmtree(base, ignore_errors=True)
    del os.environ["BJAIL_DATA_DIR"], os.environ["BJAIL_CONFIG_DIR"]


def test_add_pins_digest_and_extracts(installed):
    m = manifest.load(store.manifest_path("lagrange"))
    assert m.evidence_tier == 3 and len(m.sha256) == 64 and m.owner_id
    assert store.root_marker("lagrange").read_text().strip() == m.sha256
    assert (store.root_path("lagrange") / "AppRun").exists()
    assert list(store.staging_root().iterdir()) == []


def test_gui_app_runs_in_jail_against_headless_weston(installed, tmp_path):
    rt = Path(f"/run/user/{os.getuid()}")
    assert rt.is_dir()
    weston = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--socket=bjail-e2e"],
                              env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (rt / "bjail-e2e").exists():
                break
            time.sleep(0.1)
        env = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "bjail-e2e", "LANG": "C.UTF-8"}
        m, root, home, etc = runner.prepare("lagrange", say=lambda *_: None)
        from bjail import jail
        argv = [jail.find_bwrap(), *jail.runtime_args(
            root=root, home=home, etc_dir=etc, perms=m.permissions, uid=os.getuid(), host_env=env,
            command=["/usr/bin/timeout", "8", "/app/AppRun"], host_home=Path.home())]
        # timeout(1) lives in /usr/bin of the host system, which is mounted read-only in the jail
        proc = jail.supervise(argv, timeout=60)
        assert proc.returncode == 124, proc.stderr  # still running when timeout stopped it
        assert any(home.rglob("*")), "the app should have written its settings into the private home"
    finally:
        weston.terminate()
        weston.wait(timeout=10)
    assert not (Path.home() / ".config" / "lagrange").exists(), "nothing may reach the real home"


@pytest.mark.skipif(not shutil.which("Xwayland"), reason="xwayland is installed in the test guest (packages.txt)")
def test_gui_app_runs_through_a_private_xwayland(installed):
    """Same app, forced onto X11 (no WAYLAND_DISPLAY, SDL_VIDEODRIVER=x11): it can only run through the jail's Xwayland."""
    from dataclasses import replace
    from bjail import jail
    rt = Path(f"/run/user/{os.getuid()}")
    weston = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--socket=bjail-e2x"],
                              env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (rt / "bjail-e2x").exists():
                break
            time.sleep(0.1)
        env = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "bjail-e2x", "LANG": "C.UTF-8"}
        m, root, home, etc = runner.prepare("lagrange", say=lambda *_: None)
        perms = replace(m.permissions, display="xwayland")
        argv = [jail.find_bwrap(), *jail.runtime_args(
            root=root, home=home, etc_dir=etc, perms=perms, uid=os.getuid(), host_env=env,
            command=["/usr/bin/timeout", "8", "/app/AppRun"], host_home=Path.home())]
        proc = jail.supervise(argv, timeout=60)
        assert proc.returncode == 124, proc.stderr
    finally:
        weston.terminate()
        weston.wait(timeout=10)


def test_tampered_image_is_refused(installed):
    with open(store.appimage_path("lagrange"), "ab") as f:
        f.write(b"x")
    with pytest.raises(runner.RunError, match="pinned sha256"):
        runner.prepare("lagrange", say=lambda *_: None)
