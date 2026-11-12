# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The message check of .github/scripts/commit_hygiene.py (no git repository needed)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("commit_hygiene", ROOT / ".github/scripts/commit_hygiene.py")
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)

PATTERNS = hygiene.load_patterns()
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def test_an_ordinary_message_passes():
    message = f"audio: refuse module loading\n\nThe body names ~/.local/share/appjail.\n\n{TRAILER}\n"
    assert hygiene.problems(message, PATTERNS) == []


@pytest.mark.parametrize("line", [
    "Claude-Session: https://claude.ai/code/session_0123456789abcdef",
    "see https://claude.ai/chat/abc",
    "id session_01ABCDEFGHJK",
    "ran /home/someone/developments/appjail/tests",
    "ran /Users/someone/x",
    "wrote /tmp/claude-1000/x",
    "kept it in the scratchpad",
    "reach me at someone@example.org",
])
def test_a_leak_is_found(line):
    assert hygiene.problems(f"subject\n\n{line}\n\n{TRAILER}\n", PATTERNS)


def test_the_trailer_pattern_is_anchored_to_a_line():
    assert hygiene.problems("subject\n\nClaude-Session: x\n", PATTERNS) == ["Claude-Session:"]
