# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from bjail import appimage, history

from .helpers import Harness


@pytest.fixture(autouse=True)
def no_history(monkeypatch):
    """Most tests do not need (or want) a git repository in the fake config directory."""
    monkeypatch.setattr(history, "enabled", False)


@pytest.fixture
def h(tmp_path, monkeypatch):
    monkeypatch.setenv("BJAIL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BJAIL_CONFIG_DIR", str(tmp_path / "config"))
    return Harness()


@pytest.fixture
def sandbox(monkeypatch):
    base = Path(tempfile.mkdtemp(prefix="bj"))
    monkeypatch.setenv("BJAIL_DATA_DIR", str(base / "data"))
    monkeypatch.setenv("BJAIL_CONFIG_DIR", str(base / "config"))
    yield base
    appimage.remove_tree(base)


@pytest.fixture
def runtime():
    """A fake XDG_RUNTIME_DIR holding real unix sockets (short path: sun_path is limited)."""
    base = Path(tempfile.mkdtemp(prefix="rt"))
    (base / "pulse").mkdir()
    socks = []

    def sock(rel):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(base / rel))
        s.listen(1)
        socks.append(s)

    sock("wayland-test")
    sock("pipewire-0")
    sock("pulse/native")
    yield base
    for s in socks:
        s.close()
    shutil.rmtree(base)
