# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The Claude Code hook that keeps execution on the host to an allowlist (.claude/hooks/host_exec_guard.py)."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("host_exec_guard", ROOT / ".claude" / "hooks" / "host_exec_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

PROJECT = "/work/appjail"
CLEAN = {"tests/vm/test.sh", "tests/vm/ssh.sh", "tests/vm/sync.sh", "tests/vm/start.sh", "tests/container/run.sh"}


def verdict(command):
    return guard.check(command, PROJECT, lambda path: path in CLEAN)


ALLOWED = [
    "git status",
    "git log --oneline -5 -- src/appjail/gui/app.py",
    "git -C /work/appjail diff --stat",
    "git config core.hooksPath",
    "git config --get user.name",
    "git add src/x.py && git commit -q -F - <<'EOF'\ngui: a message with $(rm -rf ~) and `id` in it\n\nbody\nEOF\ngit log -1",
    "tests/vm/test.sh -q",
    "./tests/vm/ssh.sh 'cd ~/appjail && python3 -m pytest -q'",
    "GUEST=ubuntu tests/vm/test.sh",
    "$CLAUDE_PROJECT_DIR/tests/container/run.sh check",
    "/work/appjail/tests/vm/start.sh",
    "tests/vm/ssh.sh 'cat > ~/appjail/tests/t.py' < /tmp/claude-UID/x/scratchpad/t.py",
    "tests/vm/test.sh 2>&1 | tail -6",
    "ls $(git rev-parse --show-toplevel)",
    "grep -rn 'geometry' src/ | head -50; sed -n 1,40p tests/vm/sync.sh",
    "sed -n 's/a/b/gp' file",
    "cat .gitignore | head -30",
    "find docs -name '*.md' -newer x",
    "gh run list --limit 5",
    "gh run view 123 --log-failed",
    "gh api repos/o/r/actions/runs",
    "tests/vm/ssh.sh true >/dev/null 2>&1 && echo UP || echo DOWN",
    "for f in a b; do tests/vm/ssh.sh true; done",
    "if test -f x; then cat x; fi",
    "{ ls; echo; }",
    "ls # a note",
    "echo hi > /tmp/claude-UID/x/out.txt",
]

DENIED = [
    "python3 -c 1",
    "python3 tests/policy_tables.py --write",
    "bash -c ls",
    "sh tests/vm/test.sh",
    "/usr/bin/id",
    "./other.sh",
    "tests/vm/new.sh",  # not tracked, or changed since HEAD
    "make",
    "ls $(id)",
    "ls `whoami`",
    "diff <(id) x",
    "echo a#b; rm -rf x",
    "{ ls; rm x; }",
    "git -c core.pager='sh -c id' log",
    "git config alias.x '!id'",
    "git config --unset core.hooksPath",
    "git rebase -x 'make' main",
    "git submodule foreach id",
    "git fetch --upload-pack=id origin",
    "gh pr create --fill",
    "gh api -X DELETE repos/o/r",
    "gh api repos/o/r/issues -f title=x",
    "find . -exec id \\;",
    "find . -delete",
    "sed -i s/a/b/ file",
    "sed 's/a/id/e' file",
    "sed -n '1w out' file",
    "rg --pre id x",
    "sort -o out file",
    "echo x > src/appjail/cli.py",
    "cat x >> tests/vm/test.sh",
    "echo x | tee out",
    "env ls",
    "FOO=1 ls",
    "LD_PRELOAD=x.so tests/vm/test.sh",
    "timeout 5 ls",
    "xargs rm < list",
    "eval ls",
    "source x",
    ". x",
    "$CMD",
    "(ls)",
    "sudo ls",
    "curl https://example.org",
    "echo 'unbalanced",
    "cat <<EOF\n$(id)\nEOF",
    "cat <<EOF\nnever closed",
    "echo $((1+2))",
]


@pytest.fixture(autouse=True)
def _uid(monkeypatch):
    monkeypatch.setattr(guard.os, "getuid", lambda: "UID")


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command):
    assert verdict(command) is None


@pytest.mark.parametrize("command", DENIED)
def test_denied(command):
    assert verdict(command), command


def test_the_hook_denies_through_its_output_and_lets_allowed_commands_through(monkeypatch, capsys):
    monkeypatch.setattr(guard, "tracked_unmodified", lambda project: lambda path: True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", PROJECT)
    for command, denied in (("python3 -c 1", True), ("git status", False)):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})))
        assert guard.main() == 0
        out = capsys.readouterr().out
        if denied:
            decision = json.loads(out)["hookSpecificOutput"]
            assert decision["hookEventName"] == "PreToolUse" and decision["permissionDecision"] == "deny"
            assert decision["permissionDecisionReason"].startswith("host-exec-guard: ")
        else:
            assert out == ""


def test_settings_run_the_hook_and_block_reads_and_edits():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    hook = settings["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Bash"
    assert "host_exec_guard.py" in hook["hooks"][0]["command"]
    perms = settings["permissions"]
    assert perms["blockReadsOutsideWorkingDirectories"] is True
    assert perms["disableBypassPermissionsMode"] == "disable"
    assert {"Edit(./.claude/**)", "Edit(./.git/**)", "Edit(./.githooks/**)"} <= set(perms["deny"])
