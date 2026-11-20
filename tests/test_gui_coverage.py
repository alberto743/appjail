# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Every command-line option is either something the window can send or is listed here with the reason it cannot.

The check looks for the option's text in the window's source, so it finds an option nobody wired up (a new permission
key, a new `add` flag), not one wired to the wrong command. It cannot tell two commands that share an option name apart
(`--rw` of `desktop` and of `open`): see the known gaps below."""

import argparse
from pathlib import Path

from appjail import cli

GUI = Path(cli.__file__).parent / "gui"

# On purpose: the window does not do these.
NEVER = {
    "--yes": "the window never answers for the user: the command asks, and the answer is the user's",
    "--json": "the window reads the data itself",
    "--long": "the window shows the grants of each app itself",
    "--raw": "a run started from the window has no terminal to hand over (its output is shown in the pane)",
    "--all": "the Search tab's `all` check box reads the index itself",
    "--version": "the Version button runs `version`",
}

# Known gaps: the window cannot send these yet. An entry goes when the window gains the option (the test says so).
GAPS = {
    "--allow-private-redirects": "add, update and `index add/update`: following a redirect to a private address",
    "--pattern": "update: change the release-asset pattern of a GitHub app",
    "--commit": "`index update`: fetch one appjail-db commit",
}


def options(parser, path=()):
    """(command path, option string) for every `--option` of the parser and its sub-commands."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from options(sub, (*path, name))
        else:
            for opt in action.option_strings:
                if opt.startswith("--") and opt not in ("--help",):
                    yield path, opt


def gui_text():
    return "\n".join(p.read_text() for p in sorted(GUI.glob("*.py")))


def test_every_option_is_sent_by_the_window_or_listed_with_its_reason():
    text = gui_text()
    missing = sorted({f"{' '.join(path)} {opt}" for path, opt in options(cli.build_parser())
                      if f'"{opt}"' not in text and opt not in NEVER and opt not in GAPS})
    assert not missing, f"the window cannot send these; wire them up or list them in NEVER or GAPS: {missing}"


def test_the_known_gaps_are_still_gaps():
    text = gui_text()
    fixed = [opt for opt in GAPS if f'"{opt}"' in text]
    assert not fixed, f"the window sends these now: remove them from GAPS: {fixed}"


def test_the_lists_name_real_options():
    real = {opt for _path, opt in options(cli.build_parser())}
    assert set(NEVER) | set(GAPS) <= real
