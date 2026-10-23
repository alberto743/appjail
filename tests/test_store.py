# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os

import pytest

from appjail import store


def test_atomic_write_creates_with_the_asked_mode_and_replaces(tmp_path):
    path = tmp_path / "f"
    store.atomic_write(path, "one", 0o600)
    store.atomic_write(path, b"two", 0o600)
    assert path.read_bytes() == b"two" and oct(path.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["f"]


def test_atomic_write_leaves_the_old_file_and_no_temp_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "f"
    path.write_text("old")

    def boom(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.atomic_write(path, "new")
    assert path.read_text() == "old" and [p.name for p in tmp_path.iterdir()] == ["f"]
