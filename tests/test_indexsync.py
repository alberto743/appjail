# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
from pathlib import Path

import pytest

from bjail import cli, index, indexsync, jail
from bjail.indexsync import IndexRefused

C1, C2, C3 = "1" * 40, "2" * 40, "3" * 40
BULLET = "◆"


def make_tree(root, apps):
    """apps: name -> (description, script text or None)."""
    scripts = Path(root) / "programs/x86_64"
    scripts.mkdir(parents=True, exist_ok=True)
    lines = [f"{BULLET} {name} : {desc}" for name, (desc, _) in apps.items()]
    (Path(root) / "programs/x86_64-appimages").write_text("\n".join(lines) + "\n")
    for name, (_, script) in apps.items():
        if script is not None:
            (scripts / name).write_text(script)
    return Path(root)


def site(value):
    return f'SITE="{value}"\n'


BASE = {"cura": ("slicer", site("Ultimaker/Cura")), "gh": ("GitHub CLI", site("cli/cli")),
        "old": ("going away", site("a/old"))}


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("BJAIL_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


# -- collect -------------------------------------------------------------------------------


def test_collect_copies_regular_files_with_private_modes(tmp_path):
    src = make_tree(tmp_path / "src", BASE)
    copied, skipped = indexsync.collect(src, tmp_path / "out")
    assert (copied, skipped) == (3, 0)
    assert (tmp_path / "out/programs/x86_64/cura").read_text() == site("Ultimaker/Cura")
    assert (tmp_path / "out/programs/x86_64/cura").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "out/programs").stat().st_mode & 0o777 == 0o700


def test_collect_skips_odd_names_but_counts_them(tmp_path):
    src = make_tree(tmp_path / "src", BASE)
    (src / "programs/x86_64/has space").write_text("x")
    (src / "programs/x86_64/-dash").write_text("x")
    assert indexsync.collect(src, tmp_path / "out") == (3, 2)
    assert not (tmp_path / "out/programs/x86_64/has space").exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "dir", "big", "list-symlink", "list-big"])
def test_collect_refuses_anomalies(tmp_path, monkeypatch, kind):
    src = make_tree(tmp_path / "src", BASE)
    scripts = src / "programs/x86_64"
    if kind == "symlink":
        os.symlink("/etc/passwd", scripts / "evil")
    elif kind == "fifo":
        os.mkfifo(scripts / "evil")
    elif kind == "dir":
        (scripts / "evil").mkdir()
    elif kind == "big":
        monkeypatch.setattr(index, "MAX_SCRIPT_BYTES", 8)
    elif kind == "list-symlink":
        (src / "programs/x86_64-appimages").unlink()
        os.symlink("/etc/passwd", src / "programs/x86_64-appimages")
    elif kind == "list-big":
        monkeypatch.setattr(index, "MAX_LIST_BYTES", 8)
    with pytest.raises(IndexRefused):
        indexsync.collect(src, tmp_path / "out")


def test_collect_refuses_missing_empty_and_huge(tmp_path, monkeypatch):
    with pytest.raises(IndexRefused, match="missing"):
        indexsync.collect(tmp_path / "nothing", tmp_path / "o1")
    empty = make_tree(tmp_path / "empty", {})
    with pytest.raises(IndexRefused, match="no apps"):
        indexsync.collect(empty, tmp_path / "o2")
    monkeypatch.setattr(indexsync, "MAX_FILES", 2)
    with pytest.raises(IndexRefused, match="too many"):
        indexsync.collect(make_tree(tmp_path / "many", BASE), tmp_path / "o3")


# -- diff ----------------------------------------------------------------------------------


def test_diff_reports_added_removed_and_source_changes(tmp_path):
    old = make_tree(tmp_path / "old", BASE)
    new_apps = {
        "cura": ("slicer", site("Ultimaker/Cura2")),  # repo renamed, same owner
        "gh": ("GitHub CLI", site("evil/cli")),  # owner changed
        "fresh": ("new", site("n/ew")),
    }
    d = indexsync.diff(old, make_tree(tmp_path / "new", new_apps))
    assert d.added == ("fresh",) and d.removed == ("old",)
    assert d.owner_changed == (("gh", "cli/cli", "evil/cli"),)
    assert d.source_changed == (("cura", "Ultimaker/Cura", "Ultimaker/Cura2"),)


def test_diff_owner_comparison_ignores_case_and_flags_loss_of_source(tmp_path):
    old = make_tree(tmp_path / "old", {"a": ("x", site("Owner/r")), "b": ("x", site("o/r"))})
    new = make_tree(tmp_path / "new", {"a": ("x", site("owner/r2")), "b": ("x", site("https://vendor.example"))})
    d = indexsync.diff(old, new)
    assert d.owner_changed == ()
    assert {c[0] for c in d.source_changed} == {"a", "b"}
    assert ("b", "o/r", "(none)") in d.source_changed


def test_diff_of_identical_trees_is_empty(tmp_path):
    t = make_tree(tmp_path / "t", BASE)
    d = indexsync.diff(t, t)
    assert not (d.added or d.removed or d.owner_changed or d.source_changed)


# -- pinned state: install and rollback ------------------------------------------------------


def staged(tmp_path, name, apps=BASE):
    root = make_tree(tmp_path / name, apps)
    out = tmp_path / ("staged-" + name)
    indexsync.collect(root, out)
    return out


def test_install_pins_and_points_tree_at_the_snapshot(tmp_path):
    indexsync.install(staged(tmp_path, "a"), C1, signed=True)
    assert indexsync.current() == C1 and indexsync.previous() == ""
    link = index.tree_path()
    assert link.is_symlink() and os.readlink(link) == f"snapshots/{C1}"
    hits, total = index.search(["cura"])
    assert total == 1 and hits[0].source == "Ultimaker/Cura"
    assert "signed=yes" in (indexsync._dir() / "PINNED").read_text()
    assert index.pinned_commit() == C1


def test_second_install_keeps_previous_and_third_prunes_the_oldest(tmp_path):
    for i, c in enumerate((C1, C2, C3)):
        indexsync.install(staged(tmp_path, f"s{i}"), c)
    assert (indexsync.current(), indexsync.previous()) == (C3, C2)
    assert sorted(p.name for p in (indexsync._dir() / "snapshots").iterdir()) == sorted([C2, C3])


def test_reinstalling_the_current_commit_changes_nothing(tmp_path):
    indexsync.install(staged(tmp_path, "a"), C1)
    indexsync.install(staged(tmp_path, "b"), C1)
    assert (indexsync.current(), indexsync.previous()) == (C1, "")
    assert not (tmp_path / "staged-b").exists()


def test_rollback_swaps_and_can_be_undone(tmp_path):
    indexsync.install(staged(tmp_path, "a", {"one": ("first", site("a/one"))}), C1)
    indexsync.install(staged(tmp_path, "b", {"two": ("second", site("b/two"))}), C2)
    assert indexsync.rollback() == (C2, C1)
    assert indexsync.current() == C1 and indexsync.previous() == C2
    assert index.search(["first"])[1] == 1 and index.search(["second"])[1] == 0
    assert indexsync.rollback() == (C1, C2)
    assert index.search(["second"])[1] == 1


def test_rollback_needs_a_previous_snapshot(tmp_path):
    with pytest.raises(IndexRefused, match="no previous"):
        indexsync.rollback()
    indexsync.install(staged(tmp_path, "a"), C1)
    with pytest.raises(IndexRefused, match="no previous"):
        indexsync.rollback()


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
    got = indexsync.fetch(tmp_path, C2, run=run)
    assert (got.commit, got.signed, got.tree) == (C1, True, tmp_path / "repo")
    args, timeout, watch = run.calls[0]
    assert args[args.index("--") + 1:][-2:] == [C2, indexsync.AM_URL]
    assert watch[0] == tmp_path and watch[1] == indexsync.MAX_WORK_BYTES


@pytest.mark.parametrize("bad", ["main", "A" * 40, C1[:39], "HEAD~1", "--upload-pack=x", "$(id)"])
def test_fetch_refuses_odd_commit_arguments_before_running(tmp_path, bad):
    run = FakeRun()
    with pytest.raises(IndexRefused, match="commit must be"):
        indexsync.fetch(tmp_path, bad, run=run)
    assert run.calls == []


def test_fetch_failures(tmp_path):
    with pytest.raises(IndexRefused, match="git failed: boom"):
        indexsync.fetch(tmp_path, run=FakeRun(rc=128, stderr="\x1b[31mboom"))
    with pytest.raises(IndexRefused, match="could not determine"):
        indexsync.fetch(tmp_path, run=FakeRun("commit nothex\n"))


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
    s = indexsync.GIT_SCRIPT
    for needle in ("core.hooksPath=/dev/null", "core.attributesFile=/dev/null", "submodule.recurse=false",
                   "--no-recurse-submodules", "protocol.allow=never", "protocol.https.allow=always",
                   "sparse-checkout set --no-cone /programs/x86_64-appimages /programs/x86_64/"):
        assert needle in s


# -- the commands -------------------------------------------------------------------------------


class Script(cli.Console):
    def __init__(self, answers=()):
        self.answers, self.lines = list(answers), []

    def out(self, line=""):
        self.lines.append(line)

    def warn(self, line):
        self.lines.append("WARNING: " + line)

    def ask(self, prompt):
        self.lines.append("? " + prompt)
        if not self.answers:
            raise cli.Abort("no input available")
        return str(self.answers.pop(0))

    @property
    def text(self):
        return "\n".join(self.lines)


def fake_fetch(commit, apps, signed=False):
    def fetch(workdir, requested="HEAD"):
        make_tree(Path(workdir) / "repo", apps)
        return indexsync.Fetched(commit, signed, Path(workdir) / "repo")
    return fetch


def update(commit="HEAD", answers=("y",), fetch=None):
    console = Script(answers)
    args = cli.build_parser().parse_args(["index", "update", "--commit", commit])
    cli.cmd_index_update(args, console, fetch=fetch)
    return console


def leftovers():
    return sorted(p.name for p in indexsync._dir().iterdir() if p.name.startswith(("work-", "staged-")))


def test_first_update_asks_pins_and_cleans_up():
    console = update(fetch=fake_fetch(C1, BASE, signed=True))
    assert indexsync.current() == C1 and leftovers() == []
    assert "no previous index to compare" in console.text and "signature header present (not verified)" in console.text
    assert "Accept this snapshot" in console.text


def test_declining_changes_nothing():
    update(fetch=fake_fetch(C1, BASE))
    with pytest.raises(cli.Abort, match="unchanged"):
        update(answers=("n",), fetch=fake_fetch(C2, {"x": ("y", site("p/q"))}))
    assert indexsync.current() == C1 and indexsync.previous() == "" and leftovers() == []
    assert index.search(["cura"])[1] == 1


def test_same_commit_is_reported_without_prompting():
    update(fetch=fake_fetch(C1, BASE))
    console = update(answers=(), fetch=fake_fetch(C1, BASE))
    assert "already at" in console.text and "Accept" not in console.text


def test_owner_change_is_a_loud_warning():
    update(fetch=fake_fetch(C1, BASE))
    changed = dict(BASE, gh=("GitHub CLI", site("evil/cli")))
    console = update(fetch=fake_fetch(C2, changed))
    assert "WARNING: OWNER CHANGE for gh: cli/cli -> evil/cli" in console.text
    assert "1 owner changes" in console.text
    assert (indexsync.current(), indexsync.previous()) == (C2, C1)


def test_fetch_failure_leaves_no_work_directory():
    def failing(workdir, requested="HEAD"):
        (Path(workdir) / "junk").write_text("x")
        raise IndexRefused("git failed: network")

    with pytest.raises(IndexRefused):
        update(fetch=failing)
    assert leftovers() == [] and indexsync.current() == ""


def test_refused_tree_leaves_nothing_behind():
    def hostile(workdir, requested="HEAD"):
        make_tree(Path(workdir) / "repo", BASE)
        os.symlink("/etc/passwd", Path(workdir) / "repo/programs/x86_64/evil")
        return indexsync.Fetched(C1, False, Path(workdir) / "repo")

    with pytest.raises(IndexRefused, match="not a regular file"):
        update(fetch=hostile)
    assert leftovers() == [] and indexsync.current() == ""


def test_main_commands_status_rollback_and_bad_commit():
    update(fetch=fake_fetch(C1, {"one": ("first", site("a/one"))}))
    update(fetch=fake_fetch(C2, {"two": ("second", site("b/two"))}))
    out = Script()
    assert cli.main(["index", "status"], console=out) == 0 and C2 in out.text and C1 in out.text
    out = Script()
    assert cli.main(["index", "rollback"], console=out) == 0
    assert f"rolled back from {C2[:12]} to {C1[:12]}" in out.text
    out = Script()
    assert cli.main(["index", "update", "--commit", "main"], console=out) == 1
    assert "commit must be" in out.text
