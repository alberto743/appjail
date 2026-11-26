# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The Camera portal with a real V4L2 node: an app in its jail gets a frame of the `vivid` virtual camera through the portal.

A private session bus, the real xdg-desktop-portal, and a private PipeWire and WirePlumber that find the `vivid` camera
(guest only). The node is usable only with a PipeWire that can read vivid's controls (before 1.6.9 an array control makes the node's
Props unreadable and WirePlumber never links it, see docs/develop/camera-audio-evidence.md), and WirePlumber 0.5.19 starts
its camera monitors only on an active seat, which a headless guest does not have: the private configuration turns that check
off. Where the node does not appear or cannot be linked, the tests skip.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from appjail import portal, runner
from appjail.manifest import Manifest, Permissions
from appjail.portal import bus_call as real_bus_call

from .helpers import COMPOSITOR, integration, needs_proxy, wait_for
from .test_camera import modprobe
from .test_portal import app_root, needs_portal, portal_stack  # noqa: F401  (a fixture)

HERE = Path(__file__).parent / "portal"
SEAT_OFF = "wireplumber.profiles = {\n  main = {\n    monitor.camera.seat-monitoring = disabled\n  }\n}\n"


@pytest.fixture
def camera_stack(sandbox, runtime, portal_stack):  # noqa: F811
    """The portal stack plus a PipeWire and WirePlumber in the same runtime directory, with the vivid camera visible."""
    env, _ = portal_stack
    for tool in ("pipewire", "wireplumber", "pw-dump", "pw-cli", "gst-launch-1.0"):
        if not shutil.which(tool):
            pytest.skip(f"needs {tool} (tests/vm/packages.txt)")
    if subprocess.run(["gst-inspect-1.0", "pipewiresrc"], capture_output=True).returncode:
        pytest.skip("needs GStreamer's pipewire plugin (tests/vm/packages.txt)")
    if not shutil.which("sudo"):
        pytest.skip("needs sudo to load the vivid camera")
    modprobe("-r", "vivid")
    modprobe("vivid", "n_devs=1", "node_types=0x1")  # capture only
    conf = sandbox / "cfg" / "wireplumber" / "wireplumber.conf.d"
    conf.mkdir(parents=True)
    (conf / "90-test-seat.conf").write_text(SEAT_OFF)
    procs = [subprocess.Popen([c], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for c in ("pipewire", "wireplumber")]

    def camera_node():
        """The registry id of the V4L2 camera node, or None."""
        try:
            out = subprocess.run(["pw-dump"], env=env, capture_output=True, text=True, timeout=10).stdout
            return next((o["id"] for o in json.loads(out)
                         if o.get("info") and o["info"]["props"].get("node.name", "").startswith("v4l2_input")), None)
        except (subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            return None

    def props_readable(node):
        """Whether the node's Props can be read: when they cannot (vivid's array control, before PipeWire 1.6.9), WirePlumber
        never activates the node and links nothing to it."""
        try:
            out = subprocess.run(["pw-cli", "enum-params", str(node), "Props"], env=env, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return "Spa:Pod:Object:Param:Props" in out.stdout

    try:
        if not wait_for(lambda: (runtime / "pipewire-0").is_socket(), 10) or not wait_for(lambda: camera_node() is not None, 15):
            pytest.skip("the vivid camera never became a PipeWire node")
        if not props_readable(camera_node()):
            pytest.skip("the vivid node's Props cannot be read (PipeWire before 1.6.9): WirePlumber does not link it")
        yield env
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in procs:
            p.wait(10)
        modprobe("-r", "vivid")


@integration
@needs_proxy
@needs_portal
def test_an_app_gets_a_frame_of_a_real_camera_through_the_camera_portal(sandbox, runtime, camera_stack, monkeypatch, capfd):
    env = camera_stack
    perms = {"portals": True, "portal_interfaces": ("Camera",)}
    kw = app_root(sandbox, runtime, perms)
    (kw["root"] / "AppRun").write_text("#!/usr/bin/python3\n" + (HERE / "camera_client.py").read_text())
    m = Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    monkeypatch.setattr(portal, "bus_call", real_bus_call)  # conftest stubs it: this test talks to the private bus
    portal.store_call(env, "SetPermission", "string:devices", "boolean:true", "string:camera", f"string:{portal.app_id('app')}",
                      "array:string:yes")
    assert runner.launch("app", host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, **COMPOSITOR) == 0
    r = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert r["present"] is True and "error" not in r, r
    assert r["gst"] == 0 and r["png"] > 1000 and tuple(r["size"]) == (320, 180), r


@integration
@needs_proxy
@needs_portal
def test_a_stored_refusal_gives_the_app_no_camera_remote(sandbox, runtime, camera_stack, monkeypatch, capfd):
    env = camera_stack
    perms = {"portals": True, "portal_interfaces": ("Camera",)}
    kw = app_root(sandbox, runtime, perms)
    (kw["root"] / "AppRun").write_text("#!/usr/bin/python3\n" + (HERE / "camera_client.py").read_text())
    m = Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    monkeypatch.setattr(portal, "bus_call", real_bus_call)
    portal.store_call(env, "SetPermission", "string:devices", "boolean:true", "string:camera", f"string:{portal.app_id('app')}",
                      "array:string:no")
    assert runner.launch("app", host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, **COMPOSITOR) == 0
    r = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert "png" not in r and "NotAllowed" in r.get("error", ""), r
