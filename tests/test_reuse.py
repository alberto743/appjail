# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("reuse"), reason="reuse is installed in the test guest (packages.txt)")
def test_reuse_lint_passes():
    proc = subprocess.run(["reuse", "--root", str(ROOT), "lint"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-500:]
