# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from appjail import catalog, cli, github, index, indexstore, jail
from appjail.catalog import App, Catalog, IndexProblem

from .helpers import Script

DB = indexstore.BUILTIN

C1, C2 = "1" * 40, "2" * 40
NOW = datetime(2026, 10, 22, tzinfo=UTC)


pytestmark = pytest.mark.usefixtures("data")


def cat(*apps, revision="r1", origin=""):
    return Catalog(tuple(App(*a) for a in apps), origin, revision)


BASE = cat(("cura", "slicer", "github:Ultimaker/Cura"), ("gh", "GitHub CLI", "github:cli/cli"), ("old", "going away", "github:a/old"), revision=C1)


class FakeClient:
    """Stands in for github.Client: head_commit answers with the commit the 'repository' is at."""

    def __init__(self, commit=C1, error=None):
        self.commit, self.error, self.asked = commit, error, []

    def head_commit(self, source, ref="HEAD"):
        self.asked.append((source, ref))
        if self.error:
            raise self.error
        return self.commit


def db(catalog_, commit=C1):
    """The built-in source as the fakes serve it: (client, download) for a repository at `commit` holding `catalog_`."""
    return FakeClient(commit), downloader(catalog.dumps(catalog_))


def downloader(text, http_hop=False):
    def download(url, stage, filename, max_size):
        path = Path(stage) / filename
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return path, {"size": path.stat().st_size, "final_url": url, "http_hop": http_hop, "etag": None, "last_modified": None}
    return download


def run_index(*argv, answers=("y",), client=None, download=None):
    console = Script(answers)
    args = cli.build_parser().parse_args(["index", *argv])
    handlers = {"update": lambda: cli.cmd_index_update(args, console, client=client, download_url=download, now=NOW),
                "add": lambda: cli.cmd_index_add(args, console, download_url=download, now=NOW)}
    result = handlers[argv[0]]()
    return console, result


def update_db(catalog_, commit=C1, *argv, answers=("y",)):
    client, download = db(catalog_, commit)
    return run_index("update", *argv, answers=answers, client=client, download=download)


# -- the built-in appjail-db source ---------------------------------------------------------------


def test_the_built_in_source_is_always_there_and_cannot_be_removed():
    assert indexstore.sources()[DB] == indexstore.Source(DB, "repo", "alberto743/appjail-db")
    console = Script(["y"])
    assert cli.main(["index", "remove", DB], console=console) == 1 and "cannot be removed" in console.text


def test_first_update_resolves_the_commit_downloads_that_commit_and_records_it():
    urls = []
    client, download = db(BASE)

    def spy(url, stage, filename, max_size):
        urls.append(url)
        return download(url, stage, filename, max_size)

    console, status = run_index("update", client=client, download=spy)
    assert status == 0 and client.asked == [("alberto743/appjail-db", "HEAD")]
    assert urls == [f"https://raw.githubusercontent.com/alberto743/appjail-db/{C1}/catalog.json"]
    assert indexstore.current(DB)["commit"] == C1 and indexstore.current(DB)["revision"] == C1
    assert f"commit {C1[:12]}" in console.text and "no previous catalog to compare" in console.text
    assert "Accept this catalog" in console.text
    assert index.search(["cura"])[1:] == (1, [DB])


def test_commit_option_fetches_exactly_that_commit_without_asking_the_api():
    urls = []
    client, download = db(BASE, C2)
    run_index("update", DB, "--commit", C2, client=client, download=lambda u, *a: (urls.append(u), download(u, *a))[1])
    assert client.asked == [] and urls == [f"https://raw.githubusercontent.com/alberto743/appjail-db/{C2}/catalog.json"]
    assert indexstore.current(DB)["commit"] == C2


@pytest.mark.parametrize("argv", [["--commit", "main"], ["--commit", "A" * 40], ["--commit", "1" * 39]])
def test_commit_option_must_be_a_full_lowercase_sha(argv):
    console = Script()
    assert cli.main(["index", "update", DB, *argv], console=console) == 1
    assert "40 lowercase hexadecimal digits" in console.text and indexstore.current(DB) is None


def test_commit_option_applies_to_the_built_in_source_only(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    for argv in (["update", "mine"], ["update"]):
        console = Script()
        assert cli.main(["index", *argv, "--commit", C1], console=console) == 1
        assert "built-in" in console.text and indexstore.current(DB) is None
    assert cli.main(["index", "add", "mine2", "--file", "/nonexistent"], console=Script()) == 1


def test_api_failure_leaves_the_index_unchanged_and_does_not_fall_back_to_a_floating_url():
    run_index("update", client=FakeClient(C1), download=downloader(catalog.dumps(BASE)))
    called = []
    console, status = run_index("update", client=FakeClient(error=github.RateLimited("12:00:00Z")),
                                download=lambda *a: called.append(a))
    assert status == 1 and "rate limit" in console.text and called == []
    assert indexstore.current(DB)["commit"] == C1


def test_declining_changes_nothing():
    update_db(BASE)
    console, status = update_db(cat(("x", "y", "github:p/q"), revision=C2), C2, answers=("n",))
    assert status == 1 and "cancelled" in console.text
    assert indexstore.current(DB)["commit"] == C1 and indexstore.previous(DB) is None


def test_same_catalog_is_reported_without_prompting():
    update_db(BASE)
    console, status = update_db(BASE, C2, answers=())
    assert status == 0 and "already up to date" in console.text and "Accept" not in console.text


def test_owner_change_is_a_loud_warning_and_the_old_catalog_is_kept_for_rollback():
    update_db(BASE)
    changed = cat(("cura", "slicer", "github:Ultimaker/Cura"), ("gh", "GitHub CLI", "github:evil/cli"), ("old", "going away", "github:a/old"), revision=C2)
    console, _ = update_db(changed, C2)
    assert "WARNING: OWNER CHANGE for gh: github:cli/cli -> github:evil/cli" in console.text and "1 owner changes" in console.text
    assert f"Changes since {C1[:12]}" in console.text
    assert (indexstore.current(DB)["commit"], indexstore.previous(DB)["commit"]) == (C2, C1)


def test_diff_lists_added_removed_and_source_changes():
    update_db(BASE)
    new = cat(("cura", "slicer", "github:Ultimaker/Cura2"), ("gh", "GitHub CLI", "github:cli/cli"), ("fresh", "new", "github:n/n"), revision=C2)
    console, _ = update_db(new, C2)
    assert "1 apps added, 1 removed, 0 owner changes, 1 other source changes" in console.text
    assert "added: fresh" in console.text and "removed: old" in console.text
    assert "source changed: cura: github:Ultimaker/Cura -> github:Ultimaker/Cura2" in console.text


def test_a_download_failure_leaves_the_index_unchanged():
    def failing(url, stage, filename, max_size):
        raise jail.JailError("network down")

    console, status = run_index("update", client=FakeClient(), download=failing)
    assert status == 1 and "network down" in console.text and indexstore.current(DB) is None


def test_an_invalid_catalog_is_refused():
    console, status = run_index("update", client=FakeClient(), download=downloader("not json"))
    assert status == 1 and "not valid JSON" in console.text and indexstore.current(DB) is None


# -- added sources ---------------------------------------------------------------------------------

def test_a_move_to_another_forge_or_host_is_an_owner_change():
    d = indexstore.diff(cat(("gh", "x", "github:cli/cli")), cat(("gh", "x", "gitlab:gitlab.com/cli/cli")))
    assert [x[0] for x in d.owner_changed] == ["gh"]
    same_owner = indexstore.diff(cat(("gh", "x", "github:cli/a")), cat(("gh", "x", "github:Cli/b")))
    assert not same_owner.owner_changed and len(same_owner.source_changed) == 1


def test_search_hints_depend_on_what_add_can_install():
    indexstore.install(DB, catalog.dumps(cat(
        ("hub", "d", "github:o/hub"), ("web", "d", "url:https://example.org/web.AppImage"),
        ("lab", "d", "gitlab:gitlab.example.org/g/lab"), ("berg", "d", "codeberg:u/berg"))), NOW)
    out = Script()
    assert cli.main(["search", "--all", "d"], console=out) == 0
    assert "->  appjail add o/hub" in out.text
    assert "->  appjail add --url https://example.org/web.AppImage" in out.text
    assert "source gitlab:gitlab.example.org/g/lab   (no resolver for this forge yet" in out.text
    assert "source forgejo:codeberg.org/u/berg   (no resolver" in out.text


MINE = catalog.dumps(cat(("tool", "A tool", "github:me/tool"), ("other", "Another", ""), revision="2026-10-22", origin="https://example.org"))


def test_add_a_file_source_registers_it_and_search_covers_both(tmp_path):
    update_db(BASE)
    path = tmp_path / "mine.json"
    path.write_text(MINE)
    console, _ = run_index("add", "mine", "--file", str(path))
    assert "2 apps" in console.text and "Add 'mine' as an index source?" in console.text
    assert indexstore.get("mine").location == str(path) and list(indexstore.sources()) == [DB, "mine"]
    hits, _total, searched = index.search(["tool"])
    assert [(h.name, h.catalog, h.source) for h in hits] == [("tool", "mine", "github:me/tool")] and searched == [DB, "mine"]
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


@pytest.mark.parametrize("bad", [DB, "Bad Name", "", "x" * 40])
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
    assert "name must match" in console.text and list(indexstore.sources()) == [DB]


def test_declining_the_new_source_registers_nothing(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    console = Script(["n"])
    assert cli.main(["index", "add", "mine", "--file", str(path)], console=console) == 1
    assert "cancelled" in console.text and list(indexstore.sources()) == [DB] and not (indexstore.base() / "mine").exists()


def test_adding_the_same_name_twice_is_refused(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    assert cli.main(["index", "add", "mine", "--file", str(path)], console=Script(["y"])) == 1


def test_updating_a_file_source_rereads_the_file_and_shows_the_diff(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    path.write_text(catalog.dumps(cat(("tool", "A tool", "github:evil/tool"), ("fresh", "New", "github:f/f"), revision="r2")))
    console, status = run_index("update", "mine")
    assert status == 0 and "OWNER CHANGE for tool: github:me/tool -> github:evil/tool" in console.text and "added: fresh" in console.text
    assert indexstore.current("mine")["revision"] == "r2" and indexstore.previous("mine")["revision"] == "2026-10-22"
    path.write_text("not json")
    console, status = run_index("update", "mine", answers=())
    assert status == 1 and "not valid JSON" in console.text and indexstore.current("mine")["revision"] == "r2"


def test_update_without_a_name_does_every_source_and_reports_failures(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    path.unlink()
    console, status = update_db(BASE)
    assert status == 1 and "mine:" in console.text and indexstore.current(DB)["revision"] == C1


def test_update_one_source_leaves_the_others_alone(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(MINE)
    run_index("add", "mine", "--file", str(path))
    console, status = run_index("update", "mine", answers=())
    assert status == 0 and "already up to date" in console.text and indexstore.current(DB) is None


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
    assert list(indexstore.sources()) == [DB] and not (indexstore.base() / "mine").exists()
    console = Script(["y"])
    assert cli.main(["index", "remove", DB], console=console) == 1 and "cannot be removed" in console.text


def test_rollback_swaps_and_can_be_undone():
    update_db(cat(("one", "first", "github:a/one"), revision=C1))
    update_db(cat(("two", "second", "github:b/two"), revision=C2), C2)
    out = Script()
    assert cli.main(["index", "rollback"], console=out) == 0
    assert indexstore.current(DB)["revision"] == C1 and indexstore.previous(DB)["revision"] == C2
    assert index.search(["one"])[1] == 1 and index.search(["two"])[1] == 0
    assert cli.main(["index", "rollback", DB], console=Script()) == 0
    assert indexstore.current(DB)["revision"] == C2


def test_rollback_needs_a_previous_catalog():
    update_db(BASE)
    console = Script()
    assert cli.main(["index", "rollback"], console=console) == 1 and "no previous catalog" in console.text


def test_status_lists_every_source(tmp_path):
    out = Script()
    assert cli.main(["index", "status"], console=out) == 0 and "no catalog yet" in out.text
    path = tmp_path / "c.json"
    path.write_text(MINE)
    update_db(BASE)
    run_index("add", "mine", "--file", str(path))
    out = Script()
    cli.main(["index", "status"], console=out)
    assert f"{DB} (repo: github:alberto743/appjail-db)" in out.text and f"revision {C1[:12]}" in out.text and f"commit {C1[:12]}" in out.text
    assert f"mine (file: {path})" in out.text


# -- the store and search ------------------------------------------------------------------------


def test_install_keeps_two_catalogs_and_ignores_an_identical_one():
    text = catalog.dumps(BASE)
    assert indexstore.install(DB, text, NOW) is True
    assert indexstore.install(DB, text, NOW) is False
    indexstore.install(DB, catalog.dumps(cat(("a", "b", "github:c/d"), revision="x")), NOW)
    indexstore.install(DB, catalog.dumps(cat(("e", "f", "github:g/h"), revision="y")), NOW)
    assert (indexstore.current(DB)["revision"], indexstore.previous(DB)["revision"]) == ("y", "x")
    assert indexstore.current(DB)["updated"] == "2026-10-22T00:00:00Z"
    assert sorted(p.name for p in (indexstore.base() / DB).iterdir()) == ["current.json", "previous.json", "state.json"]
    assert oct((indexstore.base() / DB / "current.json").stat().st_mode & 0o777) == "0o600"


def test_corrupt_state_files_are_clean_errors():
    indexstore.install(DB, catalog.dumps(BASE), NOW)
    (indexstore.base() / DB / "state.json").write_text("{")
    with pytest.raises(IndexProblem, match="cannot read the state"):
        indexstore.current(DB)
    (indexstore.base() / "sources.json").write_text('{"sources": {"x": {"kind": "url"}}}')
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.sources()
    (indexstore.base() / "sources.json").write_text(json.dumps({"sources": {DB: {"kind": "url", "location": "https://x.org/a"}}}))
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.sources()


def test_search_ranking_limit_and_errors():
    indexstore.install(DB, catalog.dumps(cat(
        ("cura", "slicer", "github:Ultimaker/Cura"), ("cura-beta", "pre-release", "github:Ultimaker/Cura"),
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
    indexstore.install(DB, catalog.dumps(cat(("one", "first", "github:a/one"), revision="1")), NOW)
    indexstore.install(DB, catalog.dumps(cat(("two", "second", "github:b/two"), revision="2")), NOW)
    assert index.search(["one"])[1] == 0


# -- crash safety ---------------------------------------------------------------------------------


def test_a_crash_while_installing_leaves_a_readable_catalog_that_the_next_install_heals(monkeypatch):
    first, second = catalog.dumps(BASE), catalog.dumps(cat(("a", "b", "github:c/d"), revision="x"))
    indexstore.install(DB, first, NOW)
    real_write = indexstore._write

    def crash_on_state(path, text):
        if path.name == "state.json":
            raise OSError("power cut")
        real_write(path, text)

    monkeypatch.setattr(indexstore, "_write", crash_on_state)
    with pytest.raises(OSError):
        indexstore.install(DB, second, NOW)
    monkeypatch.setattr(indexstore, "_write", real_write)
    assert indexstore.load(DB).revision == "x"  # current.json is the new one and parses
    assert indexstore.install(DB, second, NOW) is True  # the stale state does not hide it
    assert indexstore.current(DB)["revision"] == "x" and indexstore.load(DB, "previous").revision == "x"


def test_state_without_its_fields_is_a_clean_error():
    indexstore.install(DB, catalog.dumps(BASE), NOW)
    (indexstore.base() / DB / "state.json").write_text('{"current": {"sha256": "ab"}}')
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.current(DB)


@pytest.mark.parametrize("commit", ["abc", "G" * 40, "\x1b[31m" + "1" * 35])
def test_state_with_a_bad_commit_is_malformed(commit):
    indexstore.install(DB, catalog.dumps(BASE), NOW, commit=C1)
    path = indexstore.base() / DB / "state.json"
    data = json.loads(path.read_text())
    data["current"]["commit"] = commit
    path.write_text(json.dumps(data))
    with pytest.raises(IndexProblem, match="malformed"):
        indexstore.current(DB)


def test_update_sweeps_what_an_interrupted_one_left_behind():
    indexstore.install(DB, catalog.dumps(BASE), NOW)
    (indexstore.base() / DB / ".current.json.tmp").write_text("x")
    update_db(BASE)
    assert not (indexstore.base() / DB / ".current.json.tmp").exists()
