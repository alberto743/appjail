# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `camera` permission: the V4L2 capture nodes and their own sysfs directory, only when granted.

The integration tests use the `vivid` virtual camera of the guest (a kernel module, loaded here with sudo inside the
guest); they skip where there is no readable /dev/video0.
"""

import glob
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from appjail import jail, manifest, runtimejail, seccomp
from appjail.manifest import Manifest, Permissions

from .helpers import build, integration, pairs, png_info


def sample(**perms):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))


def test_camera_is_denied_by_default_and_written_only_when_granted():
    assert Permissions().camera is False
    assert "camera" not in manifest.dumps(sample())
    text = manifest.dumps(sample(camera=True))
    assert "camera = true" in text
    assert manifest.loads(text).permissions.camera is True
    assert manifest.loads(manifest.dumps(sample())).permissions.camera is False


def test_camera_must_be_a_boolean():
    text = manifest.dumps(sample(camera=True)).replace("camera = true", 'camera = "yes"')
    with pytest.raises(manifest.ManifestError, match="camera"):
        manifest.loads(text)


def test_nothing_is_bound_without_the_grant(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "_capture_nodes", lambda: pytest.fail("the nodes must not even be probed"))
    args = runtimejail.runtime_args(**build(sandbox, runtime, camera=False))
    assert not [p for p in pairs(args, "--dev-bind") if "video" in p[0]]


def test_a_capture_node_and_its_own_sysfs_directory_are_bound(sandbox, runtime, monkeypatch):
    node = "/dev/null"  # a stand-in with a real /sys/dev/char entry (1:3)
    monkeypatch.setattr(runtimejail, "_capture_nodes", lambda: [Path(node)])
    args = runtimejail.runtime_args(**build(sandbox, runtime, camera=True))
    real = os.path.realpath("/sys/dev/char/1:3")
    assert (node, node) in pairs(args, "--dev-bind")
    assert (real, real) in pairs(args, "--ro-bind")
    assert (real, "/sys/dev/char/1:3") in pairs(args, "--symlink")
    assert ("/sys/devices", "/sys/devices") not in pairs(args, "--ro-bind")  # not the whole device tree


def test_no_camera_present_binds_nothing(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "_capture_nodes", list)
    on = runtimejail.runtime_args(**build(sandbox, runtime, camera=True))
    off = runtimejail.runtime_args(**build(sandbox, runtime, camera=False))
    assert on == off


def modprobe(*args):
    if shutil.which("sudo"):
        subprocess.run(["sudo", "-n", "modprobe", *args], capture_output=True)


@pytest.fixture
def vivid():
    """The vivid virtual camera as video0 (capture), video1 (output) and video2/video3 (metadata)."""
    if not shutil.which("v4l2-ctl"):
        pytest.skip("needs v4l-utils (tests/vm/packages.txt)")
    if not glob.glob("/dev/video*"):
        modprobe("vivid", "n_devs=1")
    name = Path("/sys/class/video4linux/video0/name")
    if not (name.exists() and name.read_text().startswith("vivid") and os.access("/dev/video0", os.R_OK | os.W_OK)):
        pytest.skip("needs the vivid virtual camera as a readable /dev/video0 (sudo modprobe vivid in the guest)")


def run(sandbox, command, **perms):
    kw = build(sandbox, sandbox / "rt", display="none", **perms)
    (sandbox / "rt").mkdir(exist_ok=True)
    kw["command"] = command
    fd = seccomp.open_fd(False)
    try:
        args = runtimejail.runtime_args(**kw, seccomp_fd=fd)
        return jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd,), keep=1 << 20)
    finally:
        os.close(fd)


CAPTURE = ["/usr/bin/v4l2-ctl", "-d", "/dev/video0", "--stream-mmap", "--stream-count=1", "--stream-to=/home/app/f.raw"]


@integration
def test_camera_granted_captures_a_frame(sandbox, vivid):
    proc = run(sandbox, CAPTURE, camera=True)
    print(proc.stdout, proc.stderr)
    assert (sandbox / "home" / "f.raw").stat().st_size > 0


@integration
def test_camera_not_granted_has_no_video_nodes(sandbox, vivid):
    proc = run(sandbox, ["/usr/bin/ls", "/dev"])
    assert "video" not in proc.stdout
    proc = run(sandbox, ["/usr/bin/ls", "/dev"], gpu=True, audio=True)
    assert "video" not in proc.stdout


@integration
def test_only_capture_nodes_are_bound(sandbox, vivid):
    listing = run(sandbox, ["/usr/bin/ls", "/dev"], camera=True).stdout.split()
    assert "video0" in listing  # vivid's video capture node
    assert not {"video1", "video2", "video3", "media0"} & set(listing), listing  # output, metadata, media controller
    assert "snd" not in listing  # a webcam's microphone is an ALSA card: the camera grant gives no audio device


@integration
def test_sysfs_is_limited_to_the_capture_nodes_directory(sandbox, vivid):
    sysfs = run(sandbox, ["/usr/bin/python3", "-c",
                          "import os; print(sorted(os.listdir('/sys')), sorted(os.listdir('/sys/dev/char')))"], camera=True).stdout
    assert "'block'" not in sysfs and "'class'" not in sysfs, sysfs
    assert "81:0" in sysfs, sysfs
    proc = run(sandbox, ["/usr/bin/v4l2-ctl", "-d", "/dev/video0", "--all"], camera=True)
    assert proc.returncode == 0 and "vivid" in proc.stdout, proc.stderr


MMAP_CAPTURE = r'''
import fcntl, mmap, os, struct, select
def ioc(d, t, nr, size): return (d << 30) | (size << 16) | (ord(t) << 8) | nr
VIDIOC_REQBUFS = ioc(3, "V", 8, 20)
VIDIOC_QUERYBUF = ioc(3, "V", 9, 88)
VIDIOC_QBUF = ioc(3, "V", 15, 88)
VIDIOC_STREAMON = ioc(1, "V", 18, 4)
VIDIOC_STREAMOFF = ioc(1, "V", 19, 4)
VIDIOC_DQBUF = ioc(3, "V", 17, 88)
fd = os.open("/dev/video0", os.O_RDWR | os.O_NONBLOCK)
req = bytearray(struct.pack("IIII4x", 2, 1, 1, 0))  # count, type=capture, memory=mmap
fcntl.ioctl(fd, VIDIOC_REQBUFS, req)
bufs = []
for i in range(2):
    b = bytearray(88); struct.pack_into("II", b, 0, i, 1)
    fcntl.ioctl(fd, VIDIOC_QUERYBUF, b)
    length = struct.unpack_from("I", b, 72)[0]; offset = struct.unpack_from("I", b, 64)[0]
    bufs.append(mmap.mmap(fd, length, mmap.MAP_SHARED, mmap.PROT_READ, offset=offset))
    fcntl.ioctl(fd, VIDIOC_QBUF, b)
fcntl.ioctl(fd, VIDIOC_STREAMON, struct.pack("I", 1))
select.select([fd], [], [], 5)
d = bytearray(88); struct.pack_into("II", d, 0, 0, 1)
fcntl.ioctl(fd, VIDIOC_DQBUF, d)
used = struct.unpack_from("I", d, 8)[0]
print("frame", used, any(bufs[struct.unpack_from("I", d, 0)[0]][:4096]))
fcntl.ioctl(fd, VIDIOC_STREAMOFF, struct.pack("I", 1))
'''


@integration
def test_mmap_capture_and_gstreamer_in_the_jail(sandbox, vivid):
    out = run(sandbox, ["/usr/bin/python3", "-c", MMAP_CAPTURE], camera=True)
    assert "frame" in out.stdout, out
    gst = run(sandbox, ["/usr/bin/gst-launch-1.0", "-q", "v4l2src", "device=/dev/video0", "num-buffers=3", "!", "fakesink"], camera=True)
    assert gst.returncode == 0, gst


@integration
def test_a_jail_without_any_camera_still_starts(sandbox, monkeypatch):
    monkeypatch.setattr(runtimejail, "_capture_nodes", list)
    proc = run(sandbox, ["/usr/bin/true"], camera=True)
    assert proc.returncode == 0


@integration
def test_two_cameras_are_both_bound_and_isolated(sandbox, vivid):
    modprobe("-r", "vivid")
    modprobe("vivid", "n_devs=2")
    try:
        listing = run(sandbox, ["/usr/bin/ls", "/dev"], camera=True).stdout.split()
        captures = sorted(n for n in listing if n.startswith("video"))
        assert len(captures) == 2, listing
        assert run(sandbox, ["/usr/bin/v4l2-ctl", "-d", "/dev/" + captures[1], "--all"], camera=True).returncode == 0
    finally:
        modprobe("-r", "vivid")
        modprobe("vivid", "n_devs=1")


@integration
def test_a_jailed_app_captures_a_real_frame_from_the_webcam_like_source(sandbox, vivid):
    """End to end: GStreamer's v4l2src in the jail writes one frame as a PNG; the host decodes it (vivid's test pattern is
    colour bars: many distinct colours, not a blank frame)."""
    proc = run(sandbox, ["/usr/bin/gst-launch-1.0", "-q", "v4l2src", "device=/dev/video0", "num-buffers=3", "!", "videoconvert", "!",
                         "pngenc", "snapshot=true", "!", "filesink", "location=/home/app/frame.png"], camera=True)
    assert proc.returncode == 0, proc.stderr
    width, height, colours = png_info((sandbox / "home" / "frame.png").read_bytes())
    assert width >= 320 and height >= 240, (width, height)
    assert colours >= 6, colours
