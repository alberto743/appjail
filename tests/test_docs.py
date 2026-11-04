# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The documents stay in step with the command line: every command and option is named in them."""

import argparse
import re
from pathlib import Path

import pytest

from appjail import cli

ROOT = Path(__file__).resolve().parent.parent
DOCS = {name: (ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "DESIGN.md")}


def walk(parser, path=""):
    """(command path, option strings) of every option, and (parent path, (command,)) of every command."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield path, (name,)
                yield from walk(sub, f"{path} {name}".strip())
        elif action.option_strings and "--help" not in action.option_strings:
            yield path, tuple(action.option_strings)


def named(word, text):
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text) is not None


@pytest.mark.parametrize("doc", DOCS)
def test_every_command_and_option_is_documented(doc):
    missing = [f"{path} {words[0]}".strip() for path, words in walk(cli.build_parser())
               if not any(named(word, DOCS[doc]) for word in words)]
    assert missing == []
