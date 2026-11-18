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


def test_make_private_gives_every_new_directory_mode_0700(tmp_path):
    (tmp_path / "keep").mkdir(mode=0o755)
    store.make_private(tmp_path / "keep" / "a" / "b")
    store.make_private(tmp_path / "keep" / "a" / "b")  # already there: nothing to do
    assert oct((tmp_path / "keep").stat().st_mode & 0o777) == "0o755"
    for d in ("a", "a/b"):
        assert oct((tmp_path / "keep" / d).stat().st_mode & 0o777) == "0o700"


# -- per-app lock -------------------------------------------------------------------------------


def test_app_lock_excludes_a_second_holder_of_the_same_app(data, monkeypatch):
    monkeypatch.setattr(store, "LOCK_TIMEOUT", 0.3)
    with store.app_lock("a"):
        with pytest.raises(store.StoreBusy, match="another appjail command"), store.app_lock("a"):
            pass
        with store.app_lock("b"):  # another app is not held up
            pass
    with store.app_lock("a"):  # released when the block ends
        pass


def test_app_lock_is_released_when_the_block_fails(data, monkeypatch):
    monkeypatch.setattr(store, "LOCK_TIMEOUT", 0.3)
    with pytest.raises(RuntimeError), store.app_lock("a"):
        raise RuntimeError("boom")
    with store.app_lock("a"):
        pass


def test_app_lock_is_private_and_not_followed_through_a_symlink(data):
    with store.app_lock("a"):
        lock = store.lock_path("a")
        assert oct(lock.stat().st_mode & 0o777) == "0o600"
        assert oct(lock.parent.stat().st_mode & 0o777) == "0o700"
    lock.unlink()
    lock.symlink_to(data / "elsewhere")
    with pytest.raises(OSError), store.app_lock("a"):
        pass
    assert not (data / "elsewhere").exists()
