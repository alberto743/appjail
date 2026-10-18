# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import hashlib
import os
import shutil
import struct
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from bjail import appimage, cli, jail, store, tools

from .test_appimage import stub, write_image
from .test_cli_add import Script
from .test_runner import integration, sandbox  # noqa: F401

BODY = b"#!/bin/sh\necho fake dwarfs tool\n"


@pytest.fixture
def fake_tool(monkeypatch):
    pin = replace(tools.TOOLS["dwarfs"], size=len(BODY), sha256=hashlib.sha256(BODY).hexdigest())
    monkeypatch.setitem(tools.TOOLS, "dwarfs", pin)
    return pin


def downloader(content):
    def download(url, stage, filename, size):
        p = Path(stage) / filename
        p.write_bytes(content)
        return p
    return download


def test_pin_is_well_formed():
    t = tools.TOOLS["dwarfs"]
    assert t.url.startswith("https://github.com/mhx/dwarfs/releases/download/v") and len(t.sha256) == 64 and t.size > 0


def test_missing_then_installed_then_corrupt(sandbox, fake_tool):
    assert tools.status("dwarfs") == "missing"
    with pytest.raises(tools.ToolError, match="bjail tools install dwarfs"):
        tools.require("dwarfs")
    tools.install("dwarfs", downloader(BODY))
    assert tools.status("dwarfs") == "ok" and tools.require("dwarfs") == tools.path("dwarfs")
    assert oct(tools.path("dwarfs").stat().st_mode & 0o777) == "0o700"
    tools.path("dwarfs").write_bytes(BODY + b"x")
    assert tools.status("dwarfs") == "corrupt"
    with pytest.raises(tools.ToolError, match="does not match"):
        tools.require("dwarfs")


def test_mismatching_download_keeps_nothing(sandbox, fake_tool):
    with pytest.raises(tools.ToolError, match="nothing was kept"):
        tools.install("dwarfs", downloader(b"evil" * 10))
    assert not tools.path("dwarfs").exists() and list(store.staging_root().iterdir()) == []


def test_locate_fs_recognises_dwarfs(tmp_path):
    p = tmp_path / "a.AppImage"
    write_image(p, b"DWARFS" + b"\0" * 50)
    assert appimage.locate_fs(p) == ("dwarfs", 64)


def test_dwarfs_image_without_the_tool_says_what_to_do(sandbox, tmp_path):
    p = tmp_path / "a.AppImage"
    write_image(p, b"DWARFS" + b"\0" * 50)
    with pytest.raises(appimage.ExtractError, match="bjail tools install dwarfs"):
        appimage.extract(p, tmp_path / "root")
    assert not (tmp_path / "root").exists()


def test_tools_command(sandbox, fake_tool):
    c = Script(["y"])
    cli.cmd_tools(cli.build_parser().parse_args(["tools", "install", "dwarfs"]), c, download=downloader(BODY))
    assert "Installed dwarfs" in c.text
    c = Script()
    cli.cmd_tools(cli.build_parser().parse_args(["tools", "status"]), c)
    assert "dwarfs: ok" in c.text
    with pytest.raises(cli.Abort):
        cli.cmd_tools(cli.build_parser().parse_args(["tools", "install", "dwarfs"]), Script(["n"]))


@integration
@pytest.mark.skipif(os.environ.get("BJAIL_E2E") != "1", reason="set BJAIL_E2E=1 in the test guest (downloads the pinned dwarfs tool, 2 MB)")
def test_real_dwarfs_appimage_is_extracted_and_validated(sandbox, tmp_path):
    tools.install("dwarfs")
    tool = tools.require("dwarfs")
    app = tmp_path / "appdir"
    (app / "usr" / "bin").mkdir(parents=True)
    (app / "AppRun").write_text("#!/bin/sh\necho hello\n")
    (app / "AppRun").chmod(0o755)
    (app / "usr" / "bin" / "up").symlink_to("../../x")
    image = tmp_path / "app.dwarfs"
    proc = jail.run(jail.extract_args(tmp_path / "appdir", tmp_path, ["/dwarfs-tool", "--tool=mkdwarfs", "-i", "/app.AppImage",
                                                                      "-o", "/out/app.dwarfs"], tools=((tool, "/dwarfs-tool"),)))
    assert proc.returncode == 0, proc.stderr
    runtime = Path("/usr/bin/true").read_bytes()
    elf = bytearray(runtime)
    elf[8:11] = b"AI\x02"
    shoff, = struct.unpack_from("<Q", elf, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", elf, 0x3A)
    assert shoff + shentsize * shnum == len(elf), "runtime stub must end with its section table"
    (tmp_path / "x.AppImage").write_bytes(bytes(elf) + image.read_bytes())
    entries, size = appimage.extract(tmp_path / "x.AppImage", tmp_path / "root")
    assert (tmp_path / "root" / "AppRun").is_file() and entries >= 3
    assert not any((tmp_path / "root").rglob("*.tmp"))
