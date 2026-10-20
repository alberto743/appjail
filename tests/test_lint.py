# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(subprocess.run([sys.executable, "-m", "pyflakes", "--version"], capture_output=True).returncode != 0,
                    reason="pyflakes is installed in the test guest (packages.txt)")
def test_pyflakes_is_clean():
    """No unused or undefined names, no shadowed imports: shared test fixtures live in conftest.py and helpers.py."""
    proc = subprocess.run([sys.executable, "-m", "pyflakes", "src", "tests"], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
