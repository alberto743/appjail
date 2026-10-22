# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
import shutil
import struct
import subprocess
from unittest import mock

import pytest

from appjail import appimage, jail
from appjail.appimage import ExtractError, UnsafeTree, UnsupportedImage

from .helpers import stub, write_image

HAVE_TOOLS = bool(shutil.which("bwrap") and shutil.which("mksquashfs") and appimage.have_unsquashfs())
needs_tools = pytest.mark.skipif(not HAVE_TOOLS, reason="needs bwrap, mksquashfs and unsquashfs (run in the test guest)")






# -- offset detection -----------------------------------------------------------------------


@pytest.fixture
def image(tmp_path):
    return tmp_path / "a.AppImage"


def test_squashfs_offset(image):
    write_image(image, b"hsqs" + b"\0" * 100)
    assert appimage.locate_fs(image) == ("squashfs", 64)


def test_offset_uses_section_table(image):
    data = bytearray(stub(b"x" * 200 + b"hsqs" + b"\0" * 50))
    struct.pack_into("<Q", data, 0x28, 200)  # shoff 200 + 1 header of 64 bytes -> filesystem at 264
    struct.pack_into("<HH", data, 0x3A, 64, 1)
    data[264:268] = b"hsqs"
    image.write_bytes(bytes(data))
    assert appimage.locate_fs(image) == ("squashfs", 264)


@pytest.mark.parametrize("content", [stub(b"\0" * 100), b"\x7fELF\x01\x01" + b"\0" * 100, stub()[:70]],
                         ids=["unknown-fs", "elf32", "offset-past-end"])
def test_unknown_filesystem_and_bad_headers(image, content):
    image.write_bytes(content)
    with pytest.raises(UnsupportedImage):
        appimage.locate_fs(image)


# -- tree validation ------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    app = root / "usr/bin/app"
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    yield root
    appimage.remove_tree(tmp_path)


def test_apprun_regular_file(tree):
    (tree / "AppRun").write_text("x")
    (tree / "AppRun").chmod(0o755)
    assert appimage.resolve_entry(tree) == str(tree.resolve() / "AppRun")


def test_apprun_relative_symlink_chain(tree):
    (tree / "usr/bin/link").symlink_to("app")
    (tree / "AppRun").symlink_to("usr/bin/link")
    assert appimage.resolve_entry(tree) == str((tree / "usr/bin/app").resolve())


@pytest.mark.parametrize("target", ["/usr/bin/env", "../../etc/passwd", "usr/bin/none"],
                         ids=["absolute", "escape", "missing"])
def test_apprun_rejections(tree, target):
    (tree / "AppRun").symlink_to(target)
    with pytest.raises(UnsafeTree):
        appimage.resolve_entry(tree)


def test_apprun_loop(tree):
    (tree / "AppRun").symlink_to("AppRun")
    with pytest.raises(UnsafeTree, match="too many symlinks"):
        appimage.resolve_entry(tree)


def test_apprun_not_executable_or_directory(tree):
    (tree / "AppRun").write_text("x")
    (tree / "AppRun").chmod(0o644)
    with pytest.raises(UnsafeTree, match="not an executable"):
        appimage.resolve_entry(tree)
    (tree / "AppRun").unlink()
    (tree / "AppRun").mkdir()
    with pytest.raises(UnsafeTree):
        appimage.resolve_entry(tree)


def test_intermediate_absolute_symlink_rejected(tree):
    (tree / "bin").symlink_to("/usr/bin")
    (tree / "AppRun").symlink_to("bin/env")
    with pytest.raises(UnsafeTree):
        appimage.resolve_entry(tree)


def test_check_tree_clears_setid_fixes_dirs_and_counts(tree):
    app = tree / "usr/bin/app"
    app.chmod(0o4755)
    ro = tree / "ro"
    ro.mkdir()
    (ro / "f").write_text("12345")
    ro.chmod(0o555)
    entries, size = appimage.check_tree(tree)
    assert app.stat().st_mode & 0o7777 == 0o755
    assert ro.stat().st_mode & 0o200
    assert entries == 5  # usr, usr/bin, app, ro, ro/f
    assert size >= 15


def test_check_tree_rejects_special_files(tree):
    os.mkfifo(tree / "pipe")
    with pytest.raises(UnsafeTree, match="special file"):
        appimage.check_tree(tree)


def test_check_tree_does_not_follow_symlinks(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f").write_text("x")
    outside.chmod(0o555)
    (tree / "out").symlink_to(outside)
    appimage.check_tree(tree)
    assert outside.stat().st_mode & 0o777 == 0o555
    outside.chmod(0o755)


def test_remove_tree_handles_readonly_dirs(tree):
    d = tree / "ro"
    d.mkdir()
    (d / "f").write_text("x")
    d.chmod(0o555)
    appimage.remove_tree(tree)
    assert not tree.exists()


# -- supervision -------------------------------------------------------------------------------


def test_supervise_captures_output():
    proc = jail.supervise(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"])
    assert (proc.returncode, proc.stdout.strip(), proc.stderr.strip()) == (3, "out", "err")


def test_supervise_timeout():
    with pytest.raises(jail.JailError, match="timed out"):
        jail.supervise(["/bin/sleep", "30"], timeout=0.5)


def test_watchdog_kills_oversized_output(tmp_path):
    cmd = ["/bin/sh", "-c", f"head -c 3000000 /dev/urandom > {tmp_path}/big; sleep 30"]
    with pytest.raises(jail.JailError, match="too large"):
        jail.supervise(cmd, timeout=20, watch=(tmp_path, 1_000_000, 100))


def test_watchdog_entry_limit(tmp_path):
    cmd = ["/bin/sh", "-c", f"for i in $(seq 1 200); do : > {tmp_path}/f$i; done; sleep 30"]
    with pytest.raises(jail.JailError, match="too large"):
        jail.supervise(cmd, timeout=20, watch=(tmp_path, 10 ** 9, 50))


# -- real extraction (guest only) ---------------------------------------------------------------


@pytest.fixture
def lab(tmp_path):
    """A source tree plus a helper that packs it into a synthetic type-2 AppImage."""
    src = tmp_path / "src"
    src.mkdir()

    class Lab:
        base = tmp_path

        def good_tree(self):
            (src / "AppRun").write_text("#!/bin/sh\necho hi\n")
            (src / "AppRun").chmod(0o755)
            (src / "usr/share").mkdir(parents=True)
            (src / "usr/share/data").write_text("data")

        def build(self, name="a.AppImage"):
            fs = tmp_path / "fs.sqsh"
            subprocess.run(["mksquashfs", str(src), str(fs), "-noappend", "-no-progress", "-quiet"], check=True)
            img = tmp_path / name
            write_image(img, fs.read_bytes())
            return img

        src_dir = src

        def leftovers(self):
            return sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("root"))

    yield Lab()
    for p in src.rglob("*"):
        if p.is_dir() and not p.is_symlink():
            p.chmod(0o755)
    appimage.remove_tree(tmp_path)


@needs_tools
def test_extracts_and_validates(lab):
    lab.good_tree()
    dest = lab.base / "root"
    entries, _ = appimage.extract(lab.build(), dest)
    assert (dest / "usr/share/data").read_text() == "data"
    assert os.access(dest / "AppRun", os.X_OK)
    assert entries == 4
    assert not (lab.base / "root.tmp").exists()


@needs_tools
def test_setuid_and_readonly_dirs_neutralised(lab):
    lab.good_tree()
    (lab.src_dir / "usr/share/data").chmod(0o4755)
    (lab.src_dir / "usr/share").chmod(0o555)
    dest = lab.base / "root"
    appimage.extract(lab.build(), dest)
    assert (dest / "usr/share/data").stat().st_mode & 0o7000 == 0
    assert (dest / "usr/share").stat().st_mode & 0o200


@needs_tools
def test_absolute_apprun_symlink_rejected_and_nothing_left(lab):
    (lab.src_dir / "AppRun").symlink_to("/usr/bin/env")
    with pytest.raises(UnsafeTree):
        appimage.extract(lab.build(), lab.base / "root")
    assert lab.leftovers() == []


@needs_tools
def test_missing_apprun_rejected(lab):
    (lab.src_dir / "x").write_text("x")
    with pytest.raises(UnsafeTree, match="AppRun not found"):
        appimage.extract(lab.build(), lab.base / "root")


@needs_tools
def test_fifo_in_image_rejected(lab):
    lab.good_tree()
    os.mkfifo(lab.src_dir / "pipe")
    with pytest.raises(UnsafeTree, match="special file"):
        appimage.extract(lab.build(), lab.base / "root")


@needs_tools
def test_decompression_bomb_stopped(lab):
    lab.good_tree()
    with open(lab.src_dir / "pattern", "wb") as f:
        f.writelines(b"A" * 1024 * 1024 for _ in range(400))  # 400 MiB that compresses to almost nothing
    with (mock.patch.object(appimage, "MAX_EXTRACTED_BYTES", 30 * 1024 * 1024),
          pytest.raises(UnsafeTree, match="too large")):
        appimage.extract(lab.build(), lab.base / "root")
    assert lab.leftovers() == []


@needs_tools
def test_sparse_huge_file_rejected_by_apparent_size(lab):
    lab.good_tree()
    with open(lab.src_dir / "sparse", "wb") as f:
        f.truncate(400 * 1024 * 1024)  # holes: no disk blocks, but a huge apparent size
    with (mock.patch.object(appimage, "MAX_EXTRACTED_BYTES", 30 * 1024 * 1024),
          pytest.raises(UnsafeTree, match="too large")):
        appimage.extract(lab.build(), lab.base / "root")
    assert lab.leftovers() == []


@needs_tools
def test_not_a_filesystem(lab):
    img = lab.base / "bad.AppImage"
    write_image(img, b"hsqs" + b"\xff" * 200)
    with pytest.raises(ExtractError, match="extraction failed"):
        appimage.extract(img, lab.base / "root")


@needs_tools
def test_extraction_jail_has_no_network_and_cannot_see_home(lab):
    code = ("import socket,os;print(sorted(os.listdir('/')));s=socket.socket();s.settimeout(3)\n"
            "try:\n s.connect(('1.1.1.1',443));print('NET')\nexcept OSError:\n print('NONET')")
    proc = jail.run(jail.extract_args(lab.base, lab.base, ["/usr/bin/python3", "-I", "-c", code]), timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "NONET" in proc.stdout
    assert "home" not in proc.stdout
