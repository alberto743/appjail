# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The themed file chooser's listing (gui/files.py), without a display."""

import pytest

pytest.importorskip("tkinter")

from appjail.gui import files


def test_listing_puts_folders_first_hides_dot_files_and_applies_the_pattern(tmp_path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "Alpha").mkdir()
    for name in ("b.AppImage", "A.appimage", "c.txt", ".x.AppImage"):
        (tmp_path / name).write_bytes(b"12345")
    entries, truncated = files.listing(tmp_path, pattern="*.appimage")
    assert [e[0] for e in entries] == ["Alpha", "zeta", "A.appimage", "b.AppImage"] and not truncated
    assert entries[2][1:3] == (False, 5)
    assert ".x.AppImage" in [e[0] for e in files.listing(tmp_path, hidden=True)[0]]
    assert [e[0] for e in files.listing(tmp_path, directories_only=True)[0]] == ["Alpha", "zeta"]


def test_listing_stops_at_the_limit_and_says_so(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}").write_bytes(b"")
    entries, truncated = files.listing(tmp_path, limit=3)
    assert len(entries) == 3 and truncated


def test_a_broken_link_is_skipped_and_an_unreadable_folder_raises(tmp_path):
    (tmp_path / "dangling").symlink_to(tmp_path / "missing")
    assert files.listing(tmp_path)[0] == []
    with pytest.raises(OSError):
        files.listing(tmp_path / "missing")


def test_places_and_sizes(tmp_path):
    (tmp_path / "Downloads").mkdir()
    assert [label for label, _ in files.places(tmp_path)] == ["Home", "Downloads", "Computer"]
    assert files.human_size(512) == "512 B" and files.human_size(2048) == "2.0 KB" and files.human_size(3 * 1024 ** 3) == "3.0 GB"
