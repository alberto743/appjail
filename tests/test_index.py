# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os

import pytest

from bjail import cli, index

BULLET = "◆"

LIST = "\n".join([
    f"{BULLET} 0ad : FOSS historical Real Time Strategy game of ancient warfare.",
    f"{BULLET} cura : 3D printing slicer \x1b[31mfor\x1b[0m Ultimaker",
    f"{BULLET} cura-beta : Pre-release of the Cura slicer",
    f"{BULLET} firefox : Web browser (repackaged)",
    f"{BULLET} gh : GitHub CLI",
    f"{BULLET} ghost-writer : Markdown editor — distraction free",
    f"{BULLET} novel : Plain text writing app that mentions cura in passing",
    f"{BULLET} local-thing : App whose script is a symlink",
    f"{BULLET} ../evil : path traversal attempt",
    f"{BULLET} noscript : listed but without install script",
    "garbage line without the separator",
    "",
])

SCRIPTS = {
    "0ad": 'SITE="https://play0ad.com"\n',
    "cura": '#!/bin/sh\nSITE="Ultimaker/Cura"\nSITE="Ultimaker/Other"\nrm -rf "$HOME" # never executed\n',
    "cura-beta": "SITE='Ultimaker/Cura'\n",
    "firefox": 'SITE="https://www.firefox.com" SITE2="ivan-hc/Firefox-appimage"\nif true; then\n\tSITE="ivan-hc/Firefox-appimage"\nfi\n',
    "gh": 'SITE="https://github.com/cli/cli.git"\n',
    "ghost-writer": "SITE=$SOMEWHERE\n",
    "novel": 'SITE="a b/c"\n',
}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "programs/x86_64").mkdir(parents=True)
    (tmp_path / "programs/x86_64-appimages").write_text(LIST)
    for name, text in SCRIPTS.items():
        (tmp_path / "programs/x86_64" / name).write_text(text)
    (tmp_path / "secret.txt").write_text('SITE="stolen/secret"\n')
    os.symlink(tmp_path / "secret.txt", tmp_path / "programs/x86_64/local-thing")
    return tmp_path


# -- parsing -----------------------------------------------------------------------------


def test_list_parsing_skips_junk_and_cleans_escapes():
    entries = {e.name: e.description for e in index.parse_list(LIST)}
    assert entries["cura"] == "3D printing slicer for Ultimaker"
    assert "garbage" not in " ".join(entries)
    assert "../evil" not in entries and "evil" not in entries
    assert entries["ghost-writer"].endswith("distraction free")


@pytest.mark.parametrize("text,expected", [
    ('SITE="a/b"\n', ("a/b", "")),
    ("SITE='a/b'\n", ("a/b", "")),
    ("SITE=a/b\n", ("a/b", "")),
    ('SITE="x" SITE2="y/z"\n', ("x", "y/z")),
    ('echo hi\n\tSITE="late/one"\nSITE="second/one"\n', ("late/one", "")),
    ("# SITE=\"commented/out\"\nSITE=\"real/one\"\n", ("real/one", "")),
    ("SITE=$VAR\n", ("$VAR", "")),
    ("nothing here\n", ("", "")),
    ("NOTSITE=\"a/b\"\n", ("", "")),
])
def test_site_extraction(text, expected):
    assert index.parse_sites(text) == expected


@pytest.mark.parametrize("site,source,note", [
    ("cli/cli", "cli/cli", ""),
    ("https://github.com/cli/cli.git", "cli/cli", ""),
    ("https://github.com/cli/cli/releases", "cli/cli", ""),
    ("https://www.firefox.com", "", "resolve manually: https://www.firefox.com"),
    ("https://gitlab.com/a/b", "", "resolve manually: https://gitlab.com/a/b"),
    ("a b/c", "", "resolve manually: a b/c"),
    ("$VAR", "", "resolve manually: $VAR"),
    ("", "", "no source in the index"),
])
def test_classify(site, source, note):
    assert index.classify(site) == (source, note)


# -- search ------------------------------------------------------------------------------


def hit(root, *words, **kw):
    hits, total = index.search(list(words), root=root, **kw)
    return {h.name: h for h in hits}, total


def test_name_beats_description_and_order_is_stable(root):
    hits, _ = index.search(["cura"], root=root)
    assert [h.name for h in hits] == ["cura", "cura-beta", "novel"]


def test_all_keywords_must_match_case_insensitively(root):
    hits, total = hit(root, "SLICER", "ultimaker")
    assert list(hits) == ["cura"] and total == 1
    assert hit(root, "slicer", "markdown")[1] == 0


def test_sources_and_notes(root):
    hits, _ = hit(root, "cura")
    assert (hits["cura"].source, hits["cura"].note) == ("Ultimaker/Cura", "")
    assert hits["cura-beta"].source == "Ultimaker/Cura"
    assert hits["novel"].source == "" and hits["novel"].note.startswith("resolve manually")
    ff, _ = hit(root, "firefox")
    assert ff["firefox"].source == "" and "repackager ivan-hc/Firefox-appimage" in ff["firefox"].note
    assert hit(root, "gh")[0]["gh"].source == "cli/cli"
    assert hit(root, "ghost")[0]["ghost-writer"].note.startswith("resolve manually: $SOMEWHERE")
    assert hit(root, "0ad")[0]["0ad"].note == "resolve manually: https://play0ad.com"


def test_symlinked_and_missing_scripts_are_not_followed(root):
    hits, _ = hit(root, "local-thing")
    assert hits["local-thing"].source == "" and hits["local-thing"].note == "no install script in the index"
    assert hit(root, "noscript")[0]["noscript"].note == "no install script in the index"


def test_traversal_name_never_reaches_the_filesystem(root):
    hits, total = hit(root, "evil")
    assert total == 0


def test_limit_and_total(root):
    hits, total = index.search(["a"], root=root, limit=2)
    assert len(hits) == 2 and total > 2


def test_scripts_are_not_executed(root, tmp_path):
    marker = tmp_path / "pwned"
    (root / "programs/x86_64/cura").write_text(f'touch {marker}\nSITE="Ultimaker/Cura"\n$(touch {marker})\n')
    index.search(["cura"], root=root)
    assert not marker.exists()


def test_oversized_script_is_truncated_not_loaded(root, monkeypatch):
    monkeypatch.setattr(index, "MAX_SCRIPT_BYTES", 16)
    (root / "programs/x86_64/cura").write_text("#" * 100 + '\nSITE="Ultimaker/Cura"\n')
    assert hit(root, "cura")[0]["cura"].source == ""


def test_no_index_and_no_keywords(tmp_path):
    with pytest.raises(index.IndexProblem, match="no local index"):
        index.search(["x"], root=tmp_path)
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs/x86_64-appimages").write_text(LIST)
    with pytest.raises(index.IndexProblem, match="keyword"):
        index.search([" "], root=tmp_path)


# -- command line --------------------------------------------------------------------------


class Out(cli.Console):
    def __init__(self):
        self.lines = []

    def out(self, line=""):
        self.lines.append(line)


def test_cli_search_prints_suggestions(root, monkeypatch, tmp_path):
    store_dir = tmp_path / "data"
    (store_dir / "index").mkdir(parents=True)
    (store_dir / "index" / "tree").symlink_to(root)
    (store_dir / "index" / "PINNED").write_text("d739e48e75382228b7fbe12502a812f0ff97f560\n")
    monkeypatch.setenv("BJAIL_DATA_DIR", str(store_dir))
    console = Out()
    assert cli.main(["search", "cura"], console=console) == 0
    text = "\n".join(console.lines)
    assert "3 match(es) in the AM index at d739e48e7538" in text
    assert "source Ultimaker/Cura   ->  bjail add Ultimaker/Cura" in text
    assert "only a suggestion" in text


def test_cli_search_without_index_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BJAIL_DATA_DIR", str(tmp_path / "empty"))
    console = Out()
    assert cli.main(["search", "x"], console=console) == 1
    assert "bjail index update" in "\n".join(console.lines)
