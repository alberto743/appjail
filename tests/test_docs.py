# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The documentation stays in step with the code: every command and option is in the command reference, every page is
in the site's navigation, every concept page has the standard headings, and the policy lists are current."""

import argparse
import re
import tomllib
from pathlib import Path

import pytest

from appjail import cli

ROOT = Path(__file__).resolve().parent.parent
DOCS = {name: (ROOT / name).read_text(encoding="utf-8") for name in ("docs/reference/commands.md",)}
HEADINGS = ("What it is", "Why it matters", "How appjail uses it", "Connections", "Limits", "References")


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


def test_policy_page_is_current():
    from .policy_tables import PAGE, render
    assert PAGE.read_text(encoding="utf-8") == render(), "run: python3 tests/policy_tables.py --write"


def nav_pages(items):
    for item in items:
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for value in item.values():
                yield from nav_pages([value] if isinstance(value, str) else value)


def test_every_page_is_in_the_navigation():
    nav = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]["nav"]
    listed = set(nav_pages(nav))
    pages = {str(p.relative_to(ROOT / "docs")) for p in (ROOT / "docs").rglob("*.md")}
    assert sorted(pages - listed) == [], "pages missing from the nav in zensical.toml"
    assert sorted(listed - pages) == [], "nav entries without a page"


def concept_pages():
    for p in sorted((ROOT / "docs" / "understand").glob("*/*.md")):
        if p.name != "index.md" or p.parent.name == "catalog":
            yield p


@pytest.mark.parametrize("page", list(concept_pages()), ids=lambda p: str(p.relative_to(ROOT / "docs")))
def test_concept_pages_have_the_standard_headings_and_references(page):
    text = page.read_text(encoding="utf-8")
    headings = [h.replace("What they are", "What it is") for h in re.findall(r"^## (.+)$", text, re.MULTILINE)]
    assert [h for h in headings if h in HEADINGS] == list(HEADINGS)
    references = text.split("\n## References", 1)[1]
    assert "](https://" in references
