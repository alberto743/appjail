# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The comparison part of .github/scripts/check_platforms.py (no network)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_platforms", ROOT / ".github/scripts/check_platforms.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

TODAY = "2026-11-16"
DEBIAN = [
    {"name": "14", "releaseDate": "2027-08-01", "isEol": False, "isEoas": False},
    {"name": "13", "releaseDate": "2025-08-09", "isEol": False, "isEoas": False},
    {"name": "12", "releaseDate": "2023-06-10", "isEol": False, "isEoas": True},
    {"name": "11", "releaseDate": "2021-08-14", "isEol": True, "isEoas": True},
]
UBUNTU = [
    {"name": "26.10", "releaseDate": "2026-10-15", "isLts": False, "isEol": False},
    {"name": "26.04", "releaseDate": "2026-04-23", "isLts": True, "isEol": False},
    {"name": "24.04", "releaseDate": "2024-04-25", "isLts": True, "isEol": False},
]
FEDORA = [
    {"name": "46", "releaseDate": "2027-04-28", "isEol": False},
    {"name": "45", "releaseDate": "2026-11-03", "isEol": False},
    {"name": "42", "releaseDate": "2025-04-15", "isEol": True},
]


def test_selection_ignores_unreleased_and_picks_the_right_release():
    assert cp.current_debian(DEBIAN, TODAY)["name"] == "13"
    assert cp.current_debian(DEBIAN, "2027-09-01")["name"] == "14"
    assert cp.current_ubuntu_lts(UBUNTU, TODAY)["name"] == "26.04"
    assert cp.current_fedora(FEDORA, TODAY)["name"] == "45"


def test_targets_come_from_the_tracked_files():
    guest = (ROOT / "tests/vm/guest.sh").read_text()
    t = cp.targets(guest)
    assert {"debian", "ubuntu", "fedora"} <= set(t)
    assert t["ubuntu"].count(".") == 1  # the guest's release, as the workflows run on ubuntu-latest


def test_no_finding_when_current_and_one_when_newer():
    latest = {"debian": DEBIAN[1], "ubuntu": UBUNTU[1], "fedora": FEDORA[1]}
    assert cp.findings({"debian": "13", "ubuntu": "26.04", "fedora": "45"}, latest) == []
    found = cp.findings({"debian": "12", "ubuntu": "24.04", "fedora": "45"}, latest)
    assert [t for t, _ in found] == ["platforms: Debian 13 is out (the project targets 12)",
                                     "platforms: Ubuntu LTS 26.04 is out (the project targets 24.04)"]


def test_missing_target_or_release_is_skipped():
    assert cp.findings({}, {"debian": DEBIAN[1], "ubuntu": None, "fedora": None}) == []


def test_text_from_the_api_is_reduced_to_a_safe_alphabet():
    assert not set(cp.clean("a\x1b[31m`$(x)`\n<b>")) & set("\x1b`$\n<>[")
