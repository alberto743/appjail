# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import pytest

from appjail import cli, store
from appjail.cli import Abort

from .helpers import Script, installed


def reset(*argv, answers=()):
    c = Script(answers)
    cli.cmd_reset(cli.build_parser().parse_args(["reset", "app", *argv]), c)
    return c


def with_home(h):
    installed(h)
    home = store.home_path("app")
    home.mkdir(parents=True)
    (home / "data.txt").write_text("x")
    return home


def test_reset_wipes_the_home_and_keeps_the_app(h):
    home = with_home(h)
    reset("--yes")
    assert not home.exists()
    assert store.manifest_path("app").exists() and store.app_dir("app").exists()


def test_declining_keeps_the_home(h):
    home = with_home(h)
    with pytest.raises(Abort, match="cancelled"):
        reset(answers=[False])
    assert (home / "data.txt").exists()


def test_unknown_app_is_refused(h):
    with pytest.raises(Abort, match="unknown app"):
        reset("--yes")


def test_reset_with_unreadable_dir_in_home_removes_it(h):
    home = with_home(h)
    bad = home / "locked"
    bad.mkdir()
    (bad / "f").write_text("y")
    bad.chmod(0)
    reset("--yes")
    assert not home.exists()


def test_reset_reports_failure_when_the_home_cannot_be_removed(h, monkeypatch):
    home = with_home(h)
    monkeypatch.setattr(store.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(OSError, match="could not remove"):
        reset("--yes")
    assert home.exists()
