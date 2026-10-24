# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Real `index update` / `rollback` against github.com/alberto743/appjail-db from the test guest (opt-in).

    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_index_e2e.py -v'

Uses one GitHub API request per update (the commit lookup) and a ~1.5 MB text download from raw.githubusercontent.com.
"""

import os

import pytest

from appjail import cli, index, indexstore

pytestmark = pytest.mark.skipif(os.environ.get("APPJAIL_E2E") != "1", reason="set APPJAIL_E2E=1 in the test guest (network)")

DB = indexstore.BUILTIN
PINNED = "0c55c852173b25a51365cf393e01056383e2d965"  # the first appjail-db commit that holds a catalog


class Yes(cli.Console):
    def __init__(self):
        self.lines = []

    def out(self, line=""):
        self.lines.append(line)

    def warn(self, line):
        self.lines.append("WARNING: " + line)

    def ask(self, prompt):
        return "y"


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    base = tmp_path_factory.mktemp("idx")
    os.environ["APPJAIL_DATA_DIR"] = str(base)
    yield base
    del os.environ["APPJAIL_DATA_DIR"]


def test_update_to_the_latest_commit_then_search(data):
    console = Yes()
    assert cli.main(["index", "update"], console=console) == 0, console.lines
    entry = indexstore.current(DB)
    assert len(entry["commit"]) == 40
    assert "AppImageHub" in entry["revision"]  # the catalog merges the AM list and the AppImageHub feed
    assert "AppImageHub" in str(console.lines)  # the review shows the whole revision
    hits, _total, searched = index.search(["cura"], limit=5)
    assert searched == [DB] and any(h.name == "cura" and h.source == "github:Ultimaker/Cura" for h in hits)
    assert 5000 < len(indexstore.load(DB).apps)
    assert (indexstore.base() / DB / "current.json").stat().st_size < 4 * 1024 ** 2


def test_update_to_an_older_commit_shows_a_diff_and_rollback_returns(data):
    head = indexstore.current(DB)["commit"]
    console = Yes()
    assert cli.main(["index", "update", DB, "--commit", PINNED], console=console) == 0, console.lines
    assert indexstore.current(DB)["commit"] == PINNED and indexstore.previous(DB)["commit"] == head
    assert any(line.startswith(f"Changes since {head[:12]}") for line in console.lines)
    assert cli.main(["index", "rollback"], console=Yes()) == 0
    assert indexstore.current(DB)["commit"] == head and indexstore.previous(DB)["commit"] == PINNED
