# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The `raw_terminal` permission: manifest, command line, warnings (the filter itself is in test_terminal_filter.py)."""

import pytest

from appjail import cli, manifest, store
from appjail.gui import argv
from appjail.manifest import Manifest, Permissions

from .helpers import Script


def sample(**perms):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", permissions=Permissions(**perms))


def perms(*command, answers=("y",)):
    console = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *command]), console)
    return console


def saved():
    return manifest.load(store.manifest_path("app")).permissions


def test_it_is_off_by_default_and_written_only_when_on():
    assert Permissions().raw_terminal is False
    assert "raw_terminal" not in manifest.dumps(sample())
    assert "raw_terminal = true" in manifest.dumps(sample(raw_terminal=True))


def test_it_round_trips():
    assert manifest.loads(manifest.dumps(sample(raw_terminal=True))).permissions.raw_terminal is True


def test_it_must_be_a_boolean():
    text = manifest.dumps(sample(raw_terminal=True)).replace("raw_terminal = true", 'raw_terminal = "yes"')
    with pytest.raises(manifest.ManifestError, match="raw_terminal"):
        manifest.loads(text)


def test_a_plain_add_does_not_grant_it(h):
    assert "raw_terminal" not in h.add().text
    assert saved().raw_terminal is False


def test_add_with_the_grant_writes_it_and_warns(h):
    console = h.add(extra=["--allow", "raw_terminal"])
    assert saved().raw_terminal is True
    assert "this grants your terminal as it is" in console.text


def test_perms_allow_and_deny_show_the_change_and_warn_once(h):
    h.add()
    console = perms("--allow", "raw_terminal")
    assert saved().raw_terminal is True
    assert "raw_terminal" in console.text and "no → yes" in console.text
    assert "this grants your terminal as it is" in console.text
    console = perms("--deny", "raw_terminal")
    assert saved().raw_terminal is False
    assert "yes → no" in console.text and "this grants" not in console.text


def test_the_window_builds_the_same_command_and_never_says_yes():
    old = {flag: False for flag in cli.PERMISSION_FLAGS}
    command = argv.perms_argv("app", old, dict(old, raw_terminal=True))
    assert command == ["perms", "app", "--allow", "raw_terminal"]
    assert argv.perms_argv("app", dict(old, raw_terminal=True), old) == ["perms", "app", "--deny", "raw_terminal"]
    assert "--yes" not in command
