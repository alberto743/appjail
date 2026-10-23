# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path

import pytest

from appjail import amsource, catalog, jail
from appjail.catalog import App, IndexProblem

C1, C2 = "1" * 40, "2" * 40
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
    f"{BULLET} gh : listed twice",
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


pytestmark = pytest.mark.usefixtures("data")


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "programs/x86_64").mkdir(parents=True)
    (tmp_path / "programs/x86_64-appimages").write_text(LIST)
    for name, text in SCRIPTS.items():
        (tmp_path / "programs/x86_64" / name).write_text(text)
    (tmp_path / "secret.txt").write_text('SITE="stolen/secret"\n')
    os.symlink(tmp_path / "secret.txt", tmp_path / "programs/x86_64/local-thing")
    return tmp_path


def apps(tree, **kw):
    return {a.name: a for a in amsource.convert(tree, **kw).apps}


# -- parsing -----------------------------------------------------------------------------


def test_list_parsing_skips_junk_and_cleans_escapes():
    entries = dict(amsource.parse_list(LIST))
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
    assert amsource.parse_sites(text) == expected


@pytest.mark.parametrize("site,source,note", [
    ("cli/cli", "github:cli/cli", ""),
    ("https://github.com/cli/cli.git", "github:cli/cli", ""),
    ("https://github.com/cli/cli/releases", "github:cli/cli", ""),
    ("https://gitlab.com/group/sub/proj", "gitlab:gitlab.com/group/sub/proj", ""),
    ("https://gitlab.com/group/proj/-/releases", "gitlab:gitlab.com/group/proj", ""),
    ("https://gitlab.com/group/proj.git", "gitlab:gitlab.com/group/proj", ""),
    ("https://codeberg.org/user/tool/releases", "forgejo:codeberg.org/user/tool", ""),
    ("https://gitlab.com/solo", "", "resolve manually: https://gitlab.com/solo"),
    ("https://www.firefox.com", "", "resolve manually: https://www.firefox.com"),
    ("https://git.example.org/a/b", "", "resolve manually: https://git.example.org/a/b"),
    ("a b/c", "", "resolve manually: a b/c"),
    ("$VAR", "", "resolve manually: $VAR"),
    ("", "", "no source in the index"),
])
def test_classify(site, source, note):
    assert amsource.classify(site) == (source, note)


# -- convert -----------------------------------------------------------------------------


def test_convert_builds_the_catalog(tree):
    cat = amsource.convert(tree, C1)
    assert (cat.origin, cat.revision) == (amsource.AM_URL, C1)
    found = {a.name: a for a in cat.apps}
    assert found["cura"] == App("cura", "3D printing slicer for Ultimaker", "github:Ultimaker/Cura", "")
    assert found["cura-beta"].source == "github:Ultimaker/Cura"
    assert found["gh"].source == "github:cli/cli" and found["gh"].description == "GitHub CLI"  # the first of two listings
    assert found["novel"].source == "" and found["novel"].note.startswith("resolve manually")
    assert found["firefox"].source == "" and "repackager github:ivan-hc/Firefox-appimage" in found["firefox"].note
    assert found["ghost-writer"].note.startswith("resolve manually: $SOMEWHERE")
    assert found["0ad"].note == "resolve manually: https://play0ad.com"
    assert "evil" not in found and len(cat.apps) == len(found)
    catalog.parse(catalog.dumps(cat))  # what convert makes is a valid catalog


def test_symlinked_and_missing_scripts_are_not_followed(tree):
    found = apps(tree)
    for name in ("local-thing", "noscript"):
        assert found[name].source == "" and found[name].note == "no install script in the index"
    assert "stolen" not in catalog.dumps(amsource.convert(tree))


def test_scripts_are_not_executed(tree, tmp_path):
    marker = tmp_path / "pwned"
    (tree / "programs/x86_64/cura").write_text(f'touch {marker}\nSITE="Ultimaker/Cura"\n$(touch {marker})\n')
    amsource.convert(tree)
    assert not marker.exists()


def test_oversized_script_is_truncated_not_loaded(tree, monkeypatch):
    monkeypatch.setattr(amsource, "MAX_SCRIPT_BYTES", 16)
    (tree / "programs/x86_64/cura").write_text("#" * 100 + '\nSITE="Ultimaker/Cura"\n')
    assert apps(tree)["cura"].source == ""


@pytest.mark.parametrize("kind", ["programs-link", "scripts-link", "list-link", "no-list", "no-scripts", "empty"])
def test_convert_refuses_hostile_or_broken_trees(tmp_path, kind):
    import shutil
    outside = tmp_path / "outside"
    (outside / "x86_64").mkdir(parents=True)
    (outside / "x86_64" / "gh").write_text('SITE="evil/cli"\n')
    (outside / "x86_64-appimages").write_text(f"{BULLET} gh : GitHub CLI\n")
    root = tmp_path / "t"
    (root / "programs").mkdir(parents=True)
    if kind == "programs-link":
        shutil.rmtree(root / "programs")
        os.symlink(outside, root / "programs")
    elif kind == "scripts-link":
        os.symlink(outside / "x86_64", root / "programs/x86_64")
        (root / "programs/x86_64-appimages").write_text(f"{BULLET} gh : GitHub CLI\n")
    elif kind == "list-link":
        (root / "programs/x86_64").mkdir()
        os.symlink(outside / "x86_64-appimages", root / "programs/x86_64-appimages")
    elif kind == "no-list":
        (root / "programs/x86_64").mkdir()
    elif kind == "no-scripts":
        (root / "programs/x86_64-appimages").write_text(f"{BULLET} gh : GitHub CLI\n")
    else:
        (root / "programs/x86_64").mkdir()
        (root / "programs/x86_64-appimages").write_text("nothing useful\n")
    with pytest.raises(IndexProblem):
        amsource.convert(root)


# -- fetch (git in the jail, faked runner) -----------------------------------------------------


class FakeRun:
    def __init__(self, stdout="", rc=0, stderr=""):
        self.calls = []
        self.result = jail.subprocess.CompletedProcess([], rc, stdout, stderr)

    def __call__(self, args, timeout=None, watch=None):
        self.calls.append((args, timeout, watch))
        return self.result


def test_fetch_parses_commit_and_signature(tmp_path):
    run = FakeRun(f"commit {C1}\nsigned yes\n")
    got = amsource.fetch(tmp_path, C2, run=run)
    assert (got.commit, got.signed, got.tree) == (C1, True, tmp_path / "repo")
    args, _timeout, watch = run.calls[0]
    assert args[args.index("--") + 1:][-2:] == [C2, amsource.AM_URL]
    assert watch[0] == tmp_path and watch[1] == amsource.MAX_WORK_BYTES


@pytest.mark.parametrize("bad", ["main", "A" * 40, C1[:39], "HEAD~1", "--upload-pack=x", "$(id)"])
def test_fetch_refuses_odd_commit_arguments_before_running(tmp_path, bad):
    run = FakeRun()
    with pytest.raises(IndexProblem, match="commit must be"):
        amsource.fetch(tmp_path, bad, run=run)
    assert run.calls == []


def test_fetch_failures(tmp_path):
    with pytest.raises(IndexProblem, match="git failed: boom"):
        amsource.fetch(tmp_path, run=FakeRun(rc=128, stderr="\x1b[31mboom"))
    with pytest.raises(IndexProblem, match="could not determine"):
        amsource.fetch(tmp_path, run=FakeRun("commit nothex\n"))


def test_git_jail_arguments(tmp_path):
    args = jail.git_args(tmp_path, ["git", "status"])
    assert "--share-net" in args and args.index("--unshare-all") < args.index("--share-net")
    assert [tuple(args[i + 1:i + 3]) for i, a in enumerate(args) if a == "--bind"] == [(str(tmp_path), "/work")]
    env = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}
    assert env["GIT_ALLOW_PROTOCOL"] == "https" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert args[-2:] == ["git", "status"] and "--remount-ro" in args
    home = str(Path.home())
    assert not any(a.startswith(home) and a != str(tmp_path) for a in args)


def test_git_script_neutralises_hooks_filters_and_submodules():
    s = amsource.GIT_SCRIPT
    for needle in ("core.hooksPath=/dev/null", "core.attributesFile=/dev/null", "submodule.recurse=false",
                   "--no-recurse-submodules", "protocol.allow=never", "protocol.https.allow=always",
                   "sparse-checkout set --no-cone /programs/x86_64-appimages /programs/x86_64/"):
        assert needle in s
