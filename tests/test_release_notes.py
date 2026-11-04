# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The grouping part of .github/scripts/release_notes.py (no network)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / ".github/scripts/release_notes.py")
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


def commits(*subjects):
    return [(f"{i:040x}", s) for i, s in enumerate(subjects)]


def test_groups_by_prefix_any_case_and_keeps_other():
    g = notes.group(commits(
        "gui: x", "GUI: y", "Docs: z", "seccomp: s", "list, search, index status: --json",
        "wrap long output on a terminal; tools and portals tables", "Audit fixes: a", "network_host: n",
        "unknown: u"))
    assert [(h, len(i)) for h, i in g.items()] == [
        ("Security", 2), ("Permissions and sandbox", 1), ("Command line", 1), ("GUI", 2),
        ("Documentation", 1), ("Other", 2)]


def test_pull_request_and_merge_commits_are_left_to_github():
    assert notes.group(commits("tools: bump gh to 2.103.0 (#12)", "Merge pull request #3 from x/y")) == {}


def test_empty_groups_are_omitted_and_render_links_the_commit():
    out = notes.render(notes.group(commits("ci: pin")), "https://example.test/o/r")
    assert out.startswith("## Tests and CI\n\n- ci: pin ([`0000000`](https://example.test/o/r/commit/" + "0" * 40 + "))")
    assert "Security" not in out
