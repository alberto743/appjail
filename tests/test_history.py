# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
import shutil

import pytest

from appjail import cli, history, store
from .helpers import Script


needs_git = pytest.mark.skipif(not (os.environ.get("APPJAIL_INTEGRATION") == "1" and shutil.which("git")),
                               reason="real bwrap and git: run in the test guest")


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(history, "enabled", True)


@needs_git
def test_add_perms_and_remove_are_recorded(h, on):
    h.add()
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", "--allow", "network", "--yes"]), Script())
    cli.cmd_remove(cli.build_parser().parse_args(["remove", "app", "--yes"]), Script())
    messages = [line.split("  ", 1)[1] for line in history.log()]
    assert messages[:2] == ["remove app", "permissions app"] and messages[2].startswith("add app")
    assert len(history.log("app")) == 3


@needs_git
def test_outside_edit_is_detected(h, on):
    h.add()
    assert history.modified("app") is False
    path = store.manifest_path("app")
    path.write_text(path.read_text().replace("network = false", "network = true"))
    assert history.modified("app") is True


@needs_git
def test_no_repository_inside_another_one(h, on):
    parent = store.config_dir().parent
    (parent / ".git").mkdir()
    h.add()
    assert not (store.config_dir() / ".git").exists() and history.modified("app") is None


@needs_git
def test_hostile_repo_config_stays_inside_the_jail(h, on, tmp_path):
    h.add()
    marker = tmp_path / "pwned"
    (store.config_dir() / ".git" / "config").write_text(
        f"[core]\n\tfsmonitor = touch {marker}\n[filter \"x\"]\n\tclean = touch {marker}\n")
    (store.config_dir() / ".gitattributes").write_text("* filter=x\n")
    history.record("again")
    history.modified("app")
    assert not marker.exists()


def test_disabled_or_missing_git_is_silent(h):
    h.add()  # history disabled by the autouse fixture
    assert history.log() == [] and history.modified("app") is None
    assert not (store.config_dir() / ".git").exists()


def test_history_command_without_history(h):
    c = Script()
    cli.cmd_history(cli.build_parser().parse_args(["history"]), c)
    assert "No recorded history" in c.text
