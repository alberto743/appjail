# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The pin-rewriting part of .github/scripts/bump_tools.py (no network)."""

import hashlib
import importlib.util
import io
import re
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bump_tools", ROOT / ".github/scripts/bump_tools.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)

TEXT = (ROOT / "src/appjail/tools.py").read_text()
SHA = "ab" * 32


def test_pinned_versions_are_found():
    for name in bump.SPECS:
        assert re.fullmatch(r"\d+\.\d+\.\d+", bump.pinned_version(TEXT, name))


def test_dwarfs_rewrite_changes_only_its_pin():
    old = bump.pinned_version(TEXT, "dwarfs")
    out = bump.rewrite(TEXT, "dwarfs", "9.9.9", 1234, SHA)
    assert bump.pinned_version(out, "dwarfs") == "9.9.9"
    assert "mhx/dwarfs v9.9.9" in out and old not in out.split('"gh"')[0]
    assert f'1234, "{SHA}"' in out
    assert bump.pinned_version(out, "gh") == bump.pinned_version(TEXT, "gh")
    assert out.split('"gh": Tool(')[1] == TEXT.split('"gh": Tool(')[1]  # gh entry untouched
    compile(out, "tools.py", "exec")


def test_gh_rewrite_moves_tarball_and_executable_pins():
    out = bump.rewrite(TEXT, "gh", "9.9.9", 1234, SHA, 5678, "cd" * 32)
    assert bump.pinned_version(out, "gh") == "9.9.9"
    assert "gh_9.9.9_linux_amd64/bin/gh" in out and "GitHub CLI v9.9.9" in out
    assert f'1234, "{SHA}"' in out and "exe_size=5678" in out and f'exe_sha256="{"cd" * 32}"' in out
    assert bump.pinned_version(out, "dwarfs") == bump.pinned_version(TEXT, "dwarfs")
    compile(out, "tools.py", "exec")


def test_rewrite_to_the_same_values_is_a_no_op():
    out = bump.rewrite(TEXT, "dwarfs", bump.pinned_version(TEXT, "dwarfs"), 1, SHA)
    assert bump.pinned_version(out, "dwarfs") == bump.pinned_version(TEXT, "dwarfs")


def test_version_order_is_numeric():
    assert bump.version_key("0.15.10") > bump.version_key("0.15.9")
    assert bump.version_key("2.102.0") > bump.version_key("2.99.9")


def test_measure_hashes_the_member_without_extracting(tmp_path):
    payload = b"#!fake executable\n" * 10
    arc = tmp_path / "a.tar.gz"
    with tarfile.open(arc, "w:gz") as tar:
        info = tarfile.TarInfo("gh_1.0.0_linux_amd64/bin/gh")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    size, sha, exe_size, exe_sha = bump.measure(arc, "gh_1.0.0_linux_amd64/bin/gh")
    assert size == arc.stat().st_size and sha == hashlib.sha256(arc.read_bytes()).hexdigest()
    assert exe_size == len(payload) and exe_sha == hashlib.sha256(payload).hexdigest()
    assert [p.name for p in tmp_path.iterdir()] == ["a.tar.gz"]


def test_measure_refuses_a_non_regular_member(tmp_path):
    arc = tmp_path / "a.tar.gz"
    with tarfile.open(arc, "w:gz") as tar:
        info = tarfile.TarInfo("m")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(SystemExit):
        bump.measure(arc, "m")


def _fake_run(monkeypatch, pr_status):
    calls = []

    def run(*cmd, capture=False, check=True):
        calls.append(cmd)
        status = pr_status if cmd[:3] == ("gh", "pr", "create") else 0
        return bump.subprocess.CompletedProcess(cmd, status, "", "")
    monkeypatch.setattr(bump, "run", run)
    return calls


def test_a_refused_pull_request_deletes_the_pushed_branch(monkeypatch):
    """Otherwise the next run finds the branch and skips the release for good (seen when Actions could not open PRs)."""
    calls = _fake_run(monkeypatch, pr_status=1)
    with pytest.raises(SystemExit, match="branch was deleted.*Workflow permissions"):
        bump.open_pr("bump-gh-9.9.9", "tools: bump gh to 9.9.9", "body")
    assert calls[-1] == ("git", "push", "origin", "--delete", "bump-gh-9.9.9")


def test_an_opened_pull_request_keeps_the_branch(monkeypatch):
    calls = _fake_run(monkeypatch, pr_status=0)
    bump.open_pr("bump-gh-9.9.9", "tools: bump gh to 9.9.9", "body")
    assert [c[:3] for c in calls] == [("gh", "pr", "create")]
