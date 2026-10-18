# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git", ".claude", "vm")


@pytest.mark.skipif(not shutil.which("reuse"), reason="reuse is installed in the test guest (packages.txt)")
def test_reuse_lint_passes(tmp_path):
    # Lint a clean copy: in the guest there is no git repository whose .gitignore reuse could honour.
    tree = tmp_path / "tree"
    shutil.copytree(ROOT, tree, ignore=IGNORE)
    proc = subprocess.run(["reuse", "--root", str(tree), "lint"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-500:]
