# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bjail import appimage, jail
from bjail.appimage import ExtractError, UnsafeTree, UnsupportedImage

HAVE_TOOLS = bool(shutil.which("bwrap") and shutil.which("mksquashfs") and appimage.have_unsquashfs())


def stub(extra=b""):
    """Minimal type-2 runtime: ELF64 header whose section table ends at byte 64."""
    h = bytearray(64)
    h[:4] = b"\x7fELF"
    h[4], h[5] = 2, 1
    h[8:11] = b"AI\x02"
    struct.pack_into("<Q", h, 0x28, 64)
    struct.pack_into("<HH", h, 0x3A, 64, 0)
    return bytes(h) + extra


def write_image(path, fs):
    Path(path).write_bytes(stub(fs))


class OffsetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "a.AppImage"

    def test_squashfs_offset(self):
        write_image(self.path, b"hsqs" + b"\0" * 100)
        self.assertEqual(appimage.fs_offset(self.path), 64)

    def test_offset_uses_section_table(self):
        data = bytearray(stub(b"x" * 200 + b"hsqs" + b"\0" * 50))
        struct.pack_into("<Q", data, 0x28, 200)  # shoff 200 + 1 header of 64 bytes -> filesystem at 264
        struct.pack_into("<HH", data, 0x3A, 64, 1)
        data[264:268] = b"hsqs"
        self.path.write_bytes(bytes(data))
        self.assertEqual(appimage.fs_offset(self.path), 264)

    def test_dwarfs_rejected_with_clear_message(self):
        write_image(self.path, b"DWARFS" + b"\0" * 100)
        with self.assertRaisesRegex(UnsupportedImage, "DwarFS"):
            appimage.fs_offset(self.path)

    def test_unknown_filesystem_and_bad_headers(self):
        write_image(self.path, b"\0" * 100)
        with self.assertRaises(UnsupportedImage):
            appimage.fs_offset(self.path)
        self.path.write_bytes(b"\x7fELF\x01\x01" + b"\0" * 100)  # 32-bit
        with self.assertRaises(UnsupportedImage):
            appimage.fs_offset(self.path)
        self.path.write_bytes(stub()[:70])  # offset beyond the end
        with self.assertRaises(UnsupportedImage):
            appimage.fs_offset(self.path)


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(appimage.remove_tree, self.tmp.name)
        self.root = Path(self.tmp.name) / "root"
        (self.root / "usr/bin").mkdir(parents=True)
        self.app = self.root / "usr/bin/app"
        self.app.write_text("#!/bin/sh\n")
        self.app.chmod(0o755)

    def link_apprun(self, target):
        (self.root / "AppRun").symlink_to(target)

    def test_apprun_regular_file(self):
        (self.root / "AppRun").write_text("x")
        (self.root / "AppRun").chmod(0o755)
        self.assertEqual(appimage.resolve_entry(self.root), str(self.root.resolve() / "AppRun"))

    def test_apprun_relative_symlink_chain(self):
        (self.root / "usr/bin/link").symlink_to("app")
        self.link_apprun("usr/bin/link")
        self.assertEqual(appimage.resolve_entry(self.root), str(self.app.resolve()))

    def test_apprun_rejections(self):
        cases = {"absolute": "/usr/bin/env", "escape": "../../etc/passwd", "missing": "usr/bin/none"}
        for label, target in cases.items():
            with self.subTest(label):
                (self.root / "AppRun").unlink(missing_ok=True)
                self.link_apprun(target)
                with self.assertRaises(UnsafeTree):
                    appimage.resolve_entry(self.root)

    def test_apprun_loop_and_not_executable_and_dir(self):
        (self.root / "AppRun").symlink_to("AppRun")
        with self.assertRaisesRegex(UnsafeTree, "too many symlinks"):
            appimage.resolve_entry(self.root)
        (self.root / "AppRun").unlink()
        (self.root / "AppRun").write_text("x")
        (self.root / "AppRun").chmod(0o644)
        with self.assertRaisesRegex(UnsafeTree, "not an executable"):
            appimage.resolve_entry(self.root)
        (self.root / "AppRun").unlink()
        (self.root / "AppRun").mkdir()
        with self.assertRaises(UnsafeTree):
            appimage.resolve_entry(self.root)

    def test_intermediate_absolute_symlink_rejected(self):
        (self.root / "bin").symlink_to("/usr/bin")
        self.link_apprun("bin/env")
        with self.assertRaises(UnsafeTree):
            appimage.resolve_entry(self.root)

    def test_check_tree_clears_setid_fixes_dirs_and_counts(self):
        self.app.chmod(0o4755)
        ro = self.root / "ro"
        ro.mkdir()
        (ro / "f").write_text("12345")
        ro.chmod(0o555)
        entries, size = appimage.check_tree(self.root)
        self.assertEqual(self.app.stat().st_mode & 0o7777, 0o755)
        self.assertTrue(ro.stat().st_mode & 0o200)
        self.assertEqual(entries, 5)  # usr, usr/bin, app, ro, ro/f
        self.assertGreaterEqual(size, 15)

    def test_check_tree_rejects_special_files(self):
        os.mkfifo(self.root / "pipe")
        with self.assertRaisesRegex(UnsafeTree, "special file"):
            appimage.check_tree(self.root)

    def test_check_tree_does_not_follow_symlinks(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "f").write_text("x")
        outside.chmod(0o555)
        (self.root / "out").symlink_to(outside)
        appimage.check_tree(self.root)
        self.assertEqual(outside.stat().st_mode & 0o777, 0o555)
        outside.chmod(0o755)

    def test_remove_tree_handles_readonly_dirs(self):
        d = self.root / "ro"
        d.mkdir()
        (d / "f").write_text("x")
        d.chmod(0o555)
        appimage.remove_tree(self.root)
        self.assertFalse(self.root.exists())


class SuperviseTests(unittest.TestCase):
    def test_runs_and_captures(self):
        proc = jail.supervise(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"])
        self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr.strip()), (3, "out", "err"))

    def test_timeout(self):
        with self.assertRaisesRegex(jail.JailError, "timed out"):
            jail.supervise(["/bin/sleep", "30"], timeout=0.5)

    def test_watchdog_kills_oversized_output(self):
        with tempfile.TemporaryDirectory() as d:
            cmd = ["/bin/sh", "-c", f"head -c 3000000 /dev/urandom > {d}/big; sleep 30"]
            with self.assertRaisesRegex(jail.JailError, "too large"):
                jail.supervise(cmd, timeout=20, watch=(d, 1_000_000, 100))

    def test_watchdog_entry_limit(self):
        with tempfile.TemporaryDirectory() as d:
            cmd = ["/bin/sh", "-c", f"for i in $(seq 1 200); do : > {d}/f$i; done; sleep 30"]
            with self.assertRaisesRegex(jail.JailError, "too large"):
                jail.supervise(cmd, timeout=20, watch=(d, 10 ** 9, 50))


@unittest.skipUnless(HAVE_TOOLS, "needs bwrap, mksquashfs and unsquashfs (run in the test guest)")
class ExtractIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(appimage.remove_tree, self.tmp.name)
        self.base = Path(self.tmp.name)
        self.src = self.base / "src"
        self.src.mkdir()

    def build(self, name="a.AppImage"):
        fs = self.base / "fs.sqsh"
        subprocess.run(["mksquashfs", str(self.src), str(fs), "-noappend", "-no-progress", "-quiet"], check=True)
        img = self.base / name
        write_image(img, fs.read_bytes())
        return img

    def good_tree(self):
        (self.src / "AppRun").write_text("#!/bin/sh\necho hi\n")
        (self.src / "AppRun").chmod(0o755)
        (self.src / "usr/share").mkdir(parents=True)
        (self.src / "usr/share/data").write_text("data")

    def test_extracts_and_validates(self):
        self.good_tree()
        dest = self.base / "root"
        entries, size = appimage.extract(self.build(), dest)
        self.assertEqual((dest / "usr/share/data").read_text(), "data")
        self.assertTrue(os.access(dest / "AppRun", os.X_OK))
        self.assertEqual(entries, 4)
        self.assertFalse((self.base / "root.tmp").exists())

    def test_setuid_and_readonly_dirs_neutralised(self):
        self.good_tree()
        (self.src / "usr/share/data").chmod(0o4755)
        (self.src / "usr/share").chmod(0o555)
        self.addCleanup((self.src / "usr/share").chmod, 0o755)
        dest = self.base / "root"
        appimage.extract(self.build(), dest)
        self.assertEqual((dest / "usr/share/data").stat().st_mode & 0o7000, 0)
        self.assertTrue((dest / "usr/share").stat().st_mode & 0o200)

    def test_absolute_apprun_symlink_rejected_and_nothing_left(self):
        (self.src / "AppRun").symlink_to("/usr/bin/env")
        dest = self.base / "root"
        with self.assertRaises(UnsafeTree):
            appimage.extract(self.build(), dest)
        self.assertEqual(sorted(p.name for p in self.base.iterdir() if p.name.startswith("root")), [])

    def test_missing_apprun_rejected(self):
        (self.src / "x").write_text("x")
        with self.assertRaisesRegex(UnsafeTree, "AppRun not found"):
            appimage.extract(self.build(), self.base / "root")

    def test_fifo_in_image_rejected(self):
        self.good_tree()
        os.mkfifo(self.src / "pipe")
        with self.assertRaisesRegex(UnsafeTree, "special file"):
            appimage.extract(self.build(), self.base / "root")

    def test_decompression_bomb_stopped(self):
        self.good_tree()
        with open(self.src / "pattern", "wb") as f:
            for _ in range(400):
                f.write(b"A" * 1024 * 1024)  # 400 MiB that compresses to almost nothing
        with mock.patch.object(appimage, "MAX_EXTRACTED_BYTES", 30 * 1024 * 1024):
            with self.assertRaisesRegex(jail.JailError, "too large"):
                appimage.extract(self.build(), self.base / "root")
        self.assertEqual(sorted(p.name for p in self.base.iterdir() if p.name.startswith("root")), [])

    def test_sparse_huge_file_rejected_by_apparent_size(self):
        self.good_tree()
        with open(self.src / "sparse", "wb") as f:
            f.truncate(400 * 1024 * 1024)  # holes: no disk blocks, but a huge apparent size
        with mock.patch.object(appimage, "MAX_EXTRACTED_BYTES", 30 * 1024 * 1024):
            with self.assertRaisesRegex(UnsafeTree, "too large"):
                appimage.extract(self.build(), self.base / "root")
        self.assertEqual(sorted(p.name for p in self.base.iterdir() if p.name.startswith("root")), [])

    def test_not_a_filesystem(self):
        img = self.base / "bad.AppImage"
        write_image(img, b"hsqs" + b"\xff" * 200)
        with self.assertRaisesRegex(ExtractError, "extraction failed"):
            appimage.extract(img, self.base / "root")

    def test_jail_has_no_network_and_cannot_see_home(self):
        proc = jail.run(jail.extract_args(self.base, self.base, ["/usr/bin/python3", "-I", "-c",
            "import socket,os;print(sorted(os.listdir('/')));"
            "s=socket.socket();s.settimeout(3)\n"
            "try:\n s.connect(('1.1.1.1',443));print('NET')\nexcept OSError:\n print('NONET')"]), timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("NONET", proc.stdout)
        self.assertNotIn("home", proc.stdout)


if __name__ == "__main__":
    unittest.main()
