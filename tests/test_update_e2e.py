# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""End to end `update` against real GitHub in the test guest (AppImage/appimagetool, approved test app).

Opt-in because it downloads the AppImage twice:
    tests/vm/ssh.sh 'cd ~/appjail && APPJAIL_E2E=1 python3 -m pytest tests/test_update_e2e.py -v'
"""

import os
from dataclasses import replace

import pytest

from appjail import appimage, cli, manifest, runner, store

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
