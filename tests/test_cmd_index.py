# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from appjail import amsource, catalog, cli, index, indexstore
from appjail.catalog import App, Catalog, IndexProblem

from .helpers import Script

C1, C2 = "1" * 40, "2" * 40
NOW = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPJAIL_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def cat(*apps, revision="r1", origin=""):
    return Catalog(tuple(App(*a) for a in apps), origin, revision)


BASE = cat(("cura", "slicer", "Ultimaker/Cura"), ("gh", "GitHub CLI", "cli/cli"), ("old", "going away", "a/old"), revision=C1)


def am_fetch(catalog_, commit=C1, signed=False):
    """A fake git fetch: lays out a tree that convert() turns back into `catalog_`."""
    def fetch(workdir, requested="HEAD"):
        root = Path(workdir) / "repo"
        (root / "programs/x86_64").mkdir(parents=True)
        (root / "programs/x86_64-appimages").write_text("".join(f"◆ {a.name} : {a.description}\n" for a in catalog_.apps))
        for a in catalog_.apps:
            if a.source:
                (root / "programs/x86_64" / a.name).write_text(f'SITE="{a.source}"\n')
        return amsource.Fetched(commit, signed, root)
    return fetch


def downloader(text, http_hop=False):
    def download(url, stage, filename, max_size):
        path = Path(stage) / filename
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return path, {"size": path.stat().st_size, "final_url": url, "http_hop": http_hop, "etag": None, "last_modified": None}
    return download


def run_index(*argv, answers=("y",), fetch=None, download=None):
    console = Script(answers)
    args = cli.build_parser().parse_args(["index", *argv])
    handlers = {"update": lambda: cli.cmd_index_update(args, console, fetch=fetch, download_url=download, now=NOW),
                "add": lambda: cli.cmd_index_add(args, console, download_url=download, now=NOW)}
    result = handlers[argv[0]]()
    return console, result


def leftovers():
    return sorted(p.name for p in indexstore.base().iterdir() if p.name.startswith("work-"))


# -- the AM source ---------------------------------------------------------------------------


def test_first_update_asks_installs_and_cleans_up():
    console, status = run_index("update", fetch=am_fetch(BASE, signed=True))
    assert status == 0 and leftovers() == []
    assert indexstore.current("am")["revision"] == C1
    assert "no previous catalog to compare" in console.text and "signature header present (not verified)" in console.text
    assert "Accept this catalog" in console.text
    assert index.search(["cura"])[1:] == (1, ["am"])


def test_declining_changes_nothing():
    run_index("update", fetch=am_fetch(BASE))
    console, status = run_index("update", answers=("n",), fetch=am_fetch(cat(("x", "y", "p/q"), revision=C2), C2))
    assert status == 1 and "cancelled" in console.text
    assert indexstore.current("am")["revision"] == C1 and indexstore.previous("am") is None and leftovers() == []


def test_same_catalog_is_reported_without_prompting():
    run_index("update", fetch=am_fetch(BASE))
    console, status = run_index("update", answers=(), fetch=am_fetch(BASE))
    assert status == 0 and "already up to date" in console.text and "Accept" not in console.text


def test_owner_change_is_a_loud_warning_and_the_old_catalog_is_kept_for_rollback():
    run_index("update", fetch=am_fetch(BASE))
    changed = cat(("cura", "slicer", "Ultimaker/Cura"), ("gh", "GitHub CLI", "evil/cli"), ("old", "going away", "a/old"), revision=C2)
    console, _ = run_index("update", fetch=am_fetch(changed, C2))
    assert "WARNING: OWNER CHANGE for gh: cli/cli -> evil/cli" in console.text and "1 owner changes" in console.text
    assert (indexstore.current("am")["revision"], indexstore.previous("am")["revision"]) == (C2, C1)


def test_diff_lists_added_removed_and_source_changes():
    run_index("update", fetch=am_fetch(BASE))
    new = cat(("cura", "slicer", "Ultimaker/Cura2"), ("gh", "GitHub CLI", "cli/cli"), ("fresh", "new", "n/n"), revision=C2)
    console, _ = run_index("update", fetch=am_fetch(new, C2))
    assert "1 apps added, 1 removed, 0 owner changes, 1 other source changes" in console.text
    assert "added: fresh" in console.text and "removed: old" in console.text
    assert "source changed: cura: Ultimaker/Cura -> Ultimaker/Cura2" in console.text


def test_fetch_failure_leaves_no_work_directory():
    def failing(workdir, requested="HEAD"):
        (Path(workdir) / "junk").write_text("x")
        raise IndexProblem("git failed: network")

    console, status = run_index("update", fetch=failing)
    assert status == 1 and "git failed: network" in console.text
    assert leftovers() == [] and indexstore.current("am") is None


def test_refused_tree_leaves_nothing_behind():
    def hostile(workdir, requested="HEAD"):
        am_fetch(BASE)(workdir)
        import os
        os.rename(Path(workdir) / "repo/programs/x86_64", Path(workdir) / "elsewhere")
        os.symlink(Path(workdir) / "elsewhere", Path(workdir) / "repo/programs/x86_64")
        return amsource.Fetched(C1, False, Path(workdir) / "repo")

    console, status = run_index("update", fetch=hostile)
    assert status == 1 and "not a directory" in console.text
    assert leftovers() == [] and indexstore.current("am") is None


def test_commit_option_applies_to_am_only():
    console = Script()
    assert cli.main(["index", "update", "--commit", "main"], console=console) == 1
    assert "commit must be" in console.text
    assert cli.main(["index", "add", "mine", "--file", "/nonexistent"], console=Script()) == 1


# -- added sources ---------------------------------------------------------------------------------

MINE = catalog.dumps(cat(("tool", "A tool", "me/tool"), ("other", "Another", ""), revision="2026-10-22", origin="https://example.org"))


def test_add_a_file_source_registers_it_and_search_covers_both(tmp_path):
    run_index("update", fetch=am_fetch(BASE))
    path = tmp_path / "mine.json"
    path.write_text(MINE)
    console, _ = run_index("add", "mine", "--file", str(path))
    assert "2 apps" in console.text and "Add 'mine' as an index source?" in console.text
    assert indexstore.get("mine").location == str(path) and list(indexstore.sources()) == ["am", "mine"]
    hits, _total, searched = index.search(["tool"])
    assert [(h.name, h.catalog, h.source) for h in hits] == [("tool", "mine", "me/tool")] and searched == ["am", "mine"]
    out = Script()
    assert cli.main(["search", "tool"], console=out) == 0
    assert "tool: A tool   [mine]" in out.text and "appjail add me/tool" in out.text


def test_add_a_url_source_downloads_it_in_the_jail():
    run_index("add", "web", "--url", "https://example.org/catalog.json", download=downloader(MINE))
    assert indexstore.get("web") == indexstore.Source("web", "url", "https://example.org/catalog.json")
    assert indexstore.current("web")["revision"] == "2026-10-22"


def test_a_plain_http_redirect_is_warned_about():
    console, _ = run_index("add", "web", "--url", "https://example.org/c.json", download=downloader(MINE, http_hop=True))
    assert "plain http" in console.text


@pytest.mark.parametrize("url", ["http://example.org/c.json", "https://u:p@example.org/c.json", "ftp://x/y"])
def test_add_refuses_bad_urls(url):
    console = Script()
    assert cli.main(["index", "add", "web", "--url", url], console=console) == 1
    assert "--url" in console.text and "web" not in indexstore.sources()


@pytest.mark.parametrize("bad", ["am", "Bad Name", "", "x" * 40])
def test_add_refuses_bad_names(bad, tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    console = Script()
    assert cli.main(["index", "add", bad, "--file", str(path)], console=console) == 1


def test_add_refuses_an_invalid_catalog_and_registers_nothing(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"format": "appjail-catalog", "version": 1, "apps": [{"name": "../x"}]}')
    console = Script(["y"])
    assert cli.main(["index", "add", "mine", "--file", str(path)], console=console) == 1
    assert "name must match" in console.text and list(indexstore.sources()) == ["am"]


def test_declining_the_new_source_registers_nothing(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    console = Script(["n"])
    assert cli.main(["index", "add", "mine", "--file", str(path)], console=console) == 1
    assert "cancelled" in console.text and list(indexstore.sources()) == ["am"] and not (indexstore.base() / "mine").exists()


def test_adding_the_same_name_twice_is_refused(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    assert cli.main(["index", "add", "mine", "--file", str(path)], console=Script(["y"])) == 1


def test_updating_a_file_source_rereads_the_file_and_shows_the_diff(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    path.write_text(catalog.dumps(cat(("tool", "A tool", "evil/tool"), ("fresh", "New", "f/f"), revision="r2")))
    console, status = run_index("update", "mine")
    assert status == 0 and "OWNER CHANGE for tool: me/tool -> evil/tool" in console.text and "added: fresh" in console.text
    assert indexstore.current("mine")["revision"] == "r2" and indexstore.previous("mine")["revision"] == "2026-10-22"
    path.write_text("not json")
    console, status = run_index("update", "mine", answers=())
    assert status == 1 and "not valid JSON" in console.text and indexstore.current("mine")["revision"] == "r2"


def test_update_without_a_name_does_every_source_and_reports_failures(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    path.unlink()
    console, status = run_index("update", fetch=am_fetch(BASE))
    assert status == 1 and "mine:" in console.text and indexstore.current("am")["revision"] == C1


def test_update_one_source_leaves_the_others_alone(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    console, status = run_index("update", "mine", answers=())
    assert status == 0 and "already up to date" in console.text and indexstore.current("am") is None


def test_unknown_source_names_are_errors():
    for argv in (["update", "nope"], ["remove", "nope"], ["rollback", "nope"]):
        console = Script(["y"])
        assert cli.main(["index", *argv], console=console) == 1
        assert "unknown index source" in console.text


# -- remove, rollback, status ----------------------------------------------------------------------


def test_remove_deletes_the_source_and_its_catalogs(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    assert cli.main(["index", "remove", "mine"], console=Script(["n"])) == 1
    assert "mine" in indexstore.sources()
    assert cli.main(["index", "remove", "mine"], console=Script(["y"])) == 0
    assert list(indexstore.sources()) == ["am"] and not (indexstore.base() / "mine").exists()
    console = Script(["y"])
    assert cli.main(["index", "remove", "am"], console=console) == 1 and "cannot be removed" in console.text


def test_rollback_swaps_and_can_be_undone():
    run_index("update", fetch=am_fetch(cat(("one", "first", "a/one"), revision=C1)))
    run_index("update", fetch=am_fetch(cat(("two", "second", "b/two"), revision=C2), C2))
    out = Script()
    assert cli.main(["index", "rollback"], console=out) == 0
    assert indexstore.current("am")["revision"] == C1 and indexstore.previous("am")["revision"] == C2
    assert index.search(["one"])[1] == 1 and index.search(["two"])[1] == 0
    assert cli.main(["index", "rollback", "am"], console=Script()) == 0
    assert indexstore.current("am")["revision"] == C2


def test_rollback_needs_a_previous_catalog():
    run_index("update", fetch=am_fetch(BASE))
    console = Script()
    assert cli.main(["index", "rollback"], console=console) == 1 and "no previous catalog" in console.text


def test_status_lists_every_source(tmp_path):
    out = Script()
    assert cli.main(["index", "status"], console=out) == 0 and "no catalog yet" in out.text
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("update", fetch=am_fetch(BASE))
    run_index("add", "mine", "--file", str(path))
    out = Script()
    cli.main(["index", "status"], console=out)
    assert "am (am: https://github.com/ivan-hc/AM)" in out.text and f"revision {C1[:12]}" in out.text
    assert f"mine (file: {path})" in out.text


# -- the store and search ------------------------------------------------------------------------


def test_install_keeps_two_catalogs_and_ignores_an_identical_one():
    text = catalog.dumps(BASE)
    assert indexstore.install("am", text, NOW) is True
    assert indexstore.install("am", text, NOW) is False
    indexstore.install("am", catalog.dumps(cat(("a", "b", "c/d"), revision="x")), NOW)
    indexstore.install("am", catalog.dumps(cat(("e", "f", "g/h"), revision="y")), NOW)
    assert (indexstore.current("am")["revision"], indexstore.previous("am")["revision"]) == ("y", "x")
    assert indexstore.current("am")["updated"] == "2026-10-22T00:00:00Z"
    assert sorted(p.name for p in (indexstore.base() / "am").iterdir()) == ["current.json", "previous.json", "state.json"]
    assert oct((indexstore.base() / "am" / "current.json").stat().st_mode & 0o777) == "0o600"


def test_corrupt_state_files_are_clean_errors():
    indexstore.install("am", catalog.dumps(BASE), NOW)
    (indexstore.base() / "am" / "state.json").write_text("{")
    with pytest.raises(IndexProblem, match="cannot read the state"):
        indexstore.current("am")
    (indexstore.base() / "sources.json").write_text('{"sources": {"x": {"kind": "url"}}}')
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.sources()
    (indexstore.base() / "sources.json").write_text(json.dumps({"sources": {"am": {"kind": "url", "location": "https://x.org/a"}}}))
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.sources()


def test_search_ranking_limit_and_errors():
    indexstore.install("am", catalog.dumps(cat(
        ("cura", "slicer", "Ultimaker/Cura"), ("cura-beta", "pre-release", "Ultimaker/Cura"),
        ("novel", "mentions cura in passing", ""), ("0ad", "game", ""))), NOW)
    hits, total, _ = index.search(["cura"])
    assert [h.name for h in hits] == ["cura", "cura-beta", "novel"] and total == 3
    assert [h.name for h in index.search(["CURA", "passing"])[0]] == ["novel"]
    assert len(index.search(["a"], limit=2)[0]) == 2 and index.search(["a"], limit=2)[1] > 2
    with pytest.raises(IndexProblem, match="keyword"):
        index.search([" "])


def test_search_without_any_catalog_is_an_error():
    console = Script()
    assert cli.main(["search", "x"], console=console) == 1 and "appjail index update" in console.text


def test_search_covers_the_previous_catalog_only_after_a_rollback():
    indexstore.install("am", catalog.dumps(cat(("one", "first", "a/one"), revision="1")), NOW)
    indexstore.install("am", catalog.dumps(cat(("two", "second", "b/two"), revision="2")), NOW)
    assert index.search(["one"])[1] == 0
