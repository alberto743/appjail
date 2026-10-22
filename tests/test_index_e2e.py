# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Real `index update` / `rollback` against github.com/ivan-hc/AM from the test guest (opt-in).

    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_index_e2e.py -v'
"""

import os

import pytest

from appjail import cli, index, indexstore

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
    assert indexstore.current("am")["revision"] == PINNED
    hits, _total, searched = index.search(["cura"], limit=5)
    assert searched == ["am"] and any(h.name == "cura" and h.source == "Ultimaker/Cura" for h in hits)
    assert 8000 < len(indexstore.load("am").apps) <= 8140
    assert (indexstore.base() / "am" / "current.json").stat().st_size < 4 * 1024 ** 2  # the derived form, not 39 MB of scripts
    assert not any(p.name.startswith("work-") for p in indexstore.base().iterdir())


def test_update_to_head_shows_a_diff_and_rollback_returns(data):
    console = Yes()
    assert cli.main(["index", "update"], console=console) == 0, console.lines
    head = indexstore.current("am")["revision"]
    if head == PINNED:
        pytest.skip("remote HEAD is the pinned commit")
    assert any(line.startswith("Changes since d739e48e7538") for line in console.lines)
    assert indexstore.previous("am")["revision"] == PINNED
    assert cli.main(["index", "rollback"], console=Yes()) == 0
    assert indexstore.current("am")["revision"] == PINNED and indexstore.previous("am")["revision"] == head
    assert index.search(["cura"])[1] >= 1
