# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The grouping part of .github/scripts/release_notes.py (no network)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / ".github/scripts/release_notes.py")
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


G = "src/appjail/gui/app.py"
C = "src/appjail/cmd_add.py"
R = "src/appjail/runner.py"


def commits(*items):
    return [(f"{i:040x}", s, files) for i, (s, files) in enumerate(items)]


def headings(*items):
    return [heading for heading, _ in notes.group(commits(*items)).items()]


def test_sections_follow_the_files_not_the_wording():
    g = notes.group(commits(
        ("gui: x", [G, "tests/test_gui_smoke.py"]),
        ("wrap long output; tables", ["src/appjail/console.py", "README.md"]),
        ("display: rootful", [C, R]),
        ("docs: y", ["README.md", "DESIGN.md"]),
        ("tests: z", ["tests/test_e2e.py", "CLAUDE.md"]),
        ("ci: w", [".github/workflows/ci.yml"]),
    ))
    assert {h: len(i) for h, i in g.items()} == {
        "Interface": 2, "Logic": 1, "Documentation": 1, "Tests": 1, "Other": 1}
    assert list(g) == ["Interface", "Logic", "Documentation", "Tests", "Other"]


def test_security_by_subject_or_by_module():
    assert headings(("Audit fixes: paths", [R]), ("seccomp: x", [G])) == ["Security"]
    assert headings(("tighten", ["src/appjail/landlock.py", "tests/test_landlock.py"])) == ["Security"]
    assert headings(("tighten", ["src/appjail/landlock.py", R])) == ["Logic"]


def test_pull_request_and_merge_commits_are_left_to_github():
    assert notes.group(commits(("tools: bump gh to 2.103.0 (#12)", ["src/appjail/tools.py"]),
                               ("Merge pull request #3 from x/y", []))) == {}


def test_commits_merged_through_a_pull_request_are_skipped(tmp_path, monkeypatch):
    import subprocess

    def git(*args):
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@example.invalid", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)

    def commit(name):
        (tmp_path / name).write_text(name)
        git("add", name)
        git("commit", "-q", "-m", f"change {name}")

    git("init", "-q", "-b", "main")
    commit("a")
    git("tag", "v1.0.0")
    git("switch", "-q", "-c", "pr")
    commit("from-pr")
    git("switch", "-q", "main")
    commit("on-main")
    git("merge", "-q", "--no-ff", "-m", "Merge pull request #2 from o/pr", "pr")
    git("switch", "-q", "-c", "feature")
    commit("from-branch")
    git("switch", "-q", "main")
    git("merge", "-q", "--no-ff", "-m", "Merge branch 'feature'", "feature")
    git("tag", "v1.0.1")
    monkeypatch.chdir(tmp_path)
    assert sorted(s for _, s, _ in notes.commits("v1.0.1", "v1.0.0")) == ["change from-branch", "change on-main"]


def test_empty_groups_are_omitted_and_render_links_the_commit():
    out = notes.render(notes.group(commits(("docs: pin", ["README.md"]))), "https://example.test/o/r")
    assert out.startswith("## Documentation\n\n- docs: pin ([`0000000`](https://example.test/o/r/commit/" + "0" * 40 + "))")
    assert "Security" not in out
