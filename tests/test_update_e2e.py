# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""End to end `update` against real GitHub in the test guest (approved test apps: AppImage/appimagetool, and
AppImage/AppImageKit for the tier-4 case: none of its releases has a GitHub digest).

Opt-in because it downloads AppImages (two of 14 MiB, and four of 2 MiB):
    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_update_e2e.py -v'
"""

import os
from dataclasses import replace

import pytest

from appjail import appimage, cli, manifest, runner, store, updater

pytestmark = pytest.mark.skipif(os.environ.get("APPJAIL_E2E") != "1",
                                reason="set APPJAIL_E2E=1 in the test guest (downloads an AppImage)")


class Answers(cli.Console):
    def __init__(self, answers):
        self.answers, self.lines = list(answers), []

    def out(self, line=""):
        self.lines.append(line)

    def warn(self, line):
        self.lines.append("WARNING: " + line)

    def ask(self, prompt):
        return self.answers.pop(0)


def test_real_update_from_an_older_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("APPJAIL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APPJAIL_CONFIG_DIR", str(tmp_path / "config"))
    c = Answers(["y"])
    assert cli.main(["add", "AppImage/appimagetool", "--name", "tool"], console=c) == 0, c.lines
    path = store.manifest_path("tool")
    real = manifest.load(path)

    # Pretend an older release is installed: a different pin and an older publication date.
    manifest.dump(path, replace(real, version="old", sha256="0" * 64, published_at="2020-01-01T00:00:00Z"))
    c = Answers([])
    assert cli.main(["update", "tool"], console=c) == 0, c.lines
    assert any("quarantine" in line for line in c.lines)  # default delay: nothing is downloaded
    assert manifest.load(path).version == "old"

    # A pinned account that does not match the repository's owner blocks the update.
    manifest.dump(path, replace(manifest.load(path), owner_id=1))
    c = Answers([])
    assert cli.main(["update", "tool", "--quarantine", "0"], console=c) == 1, c.lines
    assert any("OWNER CHANGE" in line for line in c.lines)
    manifest.dump(path, replace(manifest.load(path), owner_id=real.owner_id))

    c = Answers(["y"])
    assert cli.main(["update", "tool", "--quarantine", "0"], console=c) == 0, c.lines
    now = manifest.load(path)
    assert now.sha256 == appimage.sha256_file(store.appimage_path("tool")) != "0" * 64
    assert now.published_at != "2020-01-01T00:00:00Z" and now.owner_id == real.owner_id
    runner.prepare("tool", say=lambda *_: None)  # pin matches, tree matches

    c = Answers([])
    assert cli.main(["update", "tool"], console=c) == 0
    assert any("up to date" in line for line in c.lines)


def test_real_tier4_hash_is_recorded_in_quarantine_and_compared_at_install(tmp_path, monkeypatch):
    """AppImageKit has no GitHub digest, so a candidate can only be tied to its content by hashing it twice."""
    monkeypatch.setenv("APPJAIL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APPJAIL_CONFIG_DIR", str(tmp_path / "config"))
    c = Answers(["y"])
    assert cli.main(["add", "AppImage/AppImageKit", "--name", "kit"], console=c) == 0, c.lines
    path = store.manifest_path("kit")
    real = manifest.load(path)
    assert real.evidence_tier == 4  # no digest, no attestation: trust on first use

    # Pretend an older release is installed, so the same real release is a candidate.
    manifest.dump(path, replace(real, version="old", sha256="0" * 64, published_at="2020-01-01T00:00:00Z"))

    # Inside the quarantine: the user lets bjail hash the candidate now (a real jailed download).
    c = Answers(["y"])
    assert cli.main(["update", "kit"], console=c) == 0, c.lines
    assert any("sha256 recorded for the quarantine" in line for line in c.lines), c.lines
    pending = updater.load_pending("kit")
    assert pending["sha256"] == real.sha256  # the asset did not change between the two real downloads
    assert manifest.load(path).version == "old"

    # Pretend the asset was swapped in place after that hash was recorded: refused, nothing installed.
    updater.record_hash("kit", pending["key"], "f" * 64)
    c = Answers(["y"])
    assert cli.main(["update", "kit", "--quarantine", "0"], console=c) == 1, c.lines
    assert any("CHANGED DURING QUARANTINE" in line for line in c.lines), c.lines
    assert manifest.load(path).version == "old"
    assert updater.load_pending("kit")["sha256"] == real.sha256  # the quarantine restarted on the new content

    # Unchanged since the recorded hash: installed after the tier-4 confirmation.
    c = Answers(["y", "y"])
    assert cli.main(["update", "kit", "--quarantine", "0"], console=c) == 0, c.lines
    now = manifest.load(path)
    assert now.sha256 == real.sha256 == appimage.sha256_file(store.appimage_path("kit"))
    assert now.version == real.version and now.evidence_tier == 4
    assert updater.load_pending("kit") is None
    runner.prepare("kit", say=lambda *_: None)  # pin matches, tree matches
