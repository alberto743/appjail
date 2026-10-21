# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Missing arguments show the help of the command that failed."""

import pytest

from appjail import cli


def run_failing(capsys, argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
    return capsys.readouterr().err


def test_no_command_shows_the_main_help(capsys):
    err = run_failing(capsys, [])
    assert "error:" in err
    assert "Sandboxed AppImage manager" in err
    assert "rollback" not in err
    for command in ("add", "search", "index", "update", "run"):
        assert command in err


def test_nested_command_shows_its_own_help(capsys):
    err = run_failing(capsys, ["index"])
    assert "appjail index: error:" in err
    assert "rollback" in err and "status" in err
    assert "Sandboxed AppImage manager" not in err


def test_tools_without_subcommand_shows_its_help(capsys):
    err = run_failing(capsys, ["tools"])
    assert "appjail tools: error:" in err
    assert "install" in err


@pytest.mark.parametrize("argv, option", [(["add"], "--prerelease"), (["remove"], "app")])
def test_missing_positional_shows_the_command_help(capsys, argv, option):
    err = run_failing(capsys, argv)
    assert f"appjail {argv[0]}: error:" in err
    assert "positional arguments" in err
    assert option in err
