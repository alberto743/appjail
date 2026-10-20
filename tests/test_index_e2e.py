# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Real `index update` / `rollback` against github.com/ivan-hc/AM from the test guest (opt-in).

    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_index_e2e.py -v'
"""

import os

import pytest

from appjail import cli, index, indexsync

pytestmark = pytest.mark.skipif(os.environ.get("APPJAIL_E2E") != "1", reason="set APPJAIL_E2E=1 in the test guest (network)")

PINNED = "d739e48e75382228b7fbe12502a812f0ff97f560"  # the commit the design analysis used


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


def test_update_to_the_analysed_commit_then_search(data):
    console = Yes()
    assert cli.main(["index", "update", "--commit", PINNED], console=console) == 0, console.lines
    assert indexsync.current() == PINNED
    assert any("8735" in line or "install scripts" in line for line in console.lines)
    hits, total = index.search(["cura"], limit=5)
    assert any(h.name == "cura" and h.source == "Ultimaker/Cura" for h in hits)
    entries = index.parse_list(index.read_text(str(index.tree_path() / index.LIST_FILE), index.MAX_LIST_BYTES))
    assert len(entries) == 8140
    assert not any(p.name.startswith(("work-", "staged-")) for p in indexsync._dir().iterdir())


def test_update_to_head_shows_a_diff_and_rollback_returns(data):
    console = Yes()
    assert cli.main(["index", "update"], console=console) == 0, console.lines
    head = indexsync.current()
    if head == PINNED:
        pytest.skip("remote HEAD is the pinned commit")
    assert any(line.startswith("Changes since d739e48e7538") for line in console.lines)
    assert indexsync.previous() == PINNED
    assert cli.main(["index", "rollback"], console=Yes()) == 0
    assert indexsync.current() == PINNED and indexsync.previous() == head
    assert index.search(["cura"])[1] >= 1
