# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Install bjail into a fresh virtual environment the way a user would (pip), and run the entry point."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git", ".claude", "vm", "build", "*.egg-info")

pytestmark = pytest.mark.skipif(os.environ.get("BJAIL_E2E") != "1",
                                reason="set BJAIL_E2E=1 (pip downloads the build backend from PyPI)")


def run(*argv, **kw):
    proc = subprocess.run(argv, capture_output=True, text=True, **kw)
    assert proc.returncode == 0, f"{argv}: {proc.stdout[-1500:]}{proc.stderr[-1500:]}"
    return proc.stdout


def test_pip_install_provides_the_bjail_command(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT, src, ignore=IGNORE)  # pip builds in the tree: keep the checkout clean
    venv = tmp_path / "venv"
    run(sys.executable, "-m", "venv", str(venv))
    pip, python, bjail = venv / "bin" / "pip", venv / "bin" / "python", venv / "bin" / "bjail"
    run(str(pip), "install", "--quiet", str(src))
    env = {"PATH": "/usr/bin:/bin", "BJAIL_DATA_DIR": str(tmp_path / "data"), "BJAIL_CONFIG_DIR": str(tmp_path / "config")}
    assert "Sandboxed AppImage manager" in run(str(bjail), "--help", env=env, cwd=tmp_path)
    assert "No apps installed." in run(str(bjail), "list", env=env, cwd=tmp_path)
    # the download jail binds this file by its path in the package: it must be installed next to the code
    out = run(str(python), "-I", "-c", "import bjail.jail as j; print(j.FETCHER, j.FETCHER.is_file())", cwd=tmp_path)
    assert out.split()[-1] == "True" and str(venv) in out
    meta = run(str(pip), "show", "bjail")
    assert "Version: 0.1.0" in meta and "Requires: \n" in meta  # no dependencies
    run(str(pip), "uninstall", "--yes", "bjail")
