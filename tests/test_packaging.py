# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Install appjail into a fresh virtual environment the way a user would (pip), and run the entry point."""

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git", ".claude", "vm", "build", "*.egg-info")

pytestmark = pytest.mark.skipif(os.environ.get("APPJAIL_E2E") != "1",
                                reason="set APPJAIL_E2E=1 (pip downloads the build backend, hatchling and hatch-vcs, from PyPI)")


# The copied tree has no git history, so the build is told which version the tag would give.
VERSION = "1.2.3"


@pytest.fixture(autouse=True)
def pretend_version(monkeypatch):
    monkeypatch.setenv("SETUPTOOLS_SCM_PRETEND_VERSION", VERSION)


def run(*argv, **kw):
    proc = subprocess.run(argv, capture_output=True, text=True, **kw)
    assert proc.returncode == 0, f"{argv}: {proc.stdout[-1500:]}{proc.stderr[-1500:]}"
    return proc.stdout


def test_pip_install_provides_the_appjail_command(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT, src, ignore=IGNORE)  # pip builds in the tree: keep the checkout clean
    venv = tmp_path / "venv"
    run(sys.executable, "-m", "venv", str(venv))
    pip, python, appjail = venv / "bin" / "pip", venv / "bin" / "python", venv / "bin" / "appjail"
    run(str(pip), "install", "--quiet", str(src))
    env = {"PATH": "/usr/bin:/bin", "APPJAIL_DATA_DIR": str(tmp_path / "data"), "APPJAIL_CONFIG_DIR": str(tmp_path / "config")}
    assert "Sandboxed AppImage manager" in run(str(appjail), "--help", env=env, cwd=tmp_path)
    assert "No apps installed." in run(str(appjail), "list", env=env, cwd=tmp_path)
    # the download jail binds this file by its path in the package: it must be installed next to the code
    out = run(str(python), "-I", "-c", "import appjail.jail as j; print(j.FETCHER, j.FETCHER.is_file())", cwd=tmp_path)
    assert out.split()[-1] == "True" and str(venv) in out
    assert run(str(appjail), "version", env=env, cwd=tmp_path).strip() == f"appjail {VERSION}"
    assert run(str(appjail), "--version", env=env, cwd=tmp_path).strip() == f"appjail {VERSION}"
    meta = run(str(pip), "show", "appjail")
    assert f"Version: {VERSION}" in meta and "Requires: \n" in meta  # no dependencies
    run(str(pip), "uninstall", "--yes", "appjail")


def test_sdist_is_small_and_installs_on_its_own(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT, src, ignore=IGNORE)
    venv = tmp_path / "venv"
    run(sys.executable, "-m", "venv", str(venv))
    pip, python = venv / "bin" / "pip", venv / "bin" / "python"
    run(str(pip), "install", "--quiet", "hatchling", "hatch-vcs")
    run(str(python), "-m", "hatchling", "build", "-t", "sdist", "-d", str(tmp_path / "dist"), cwd=src)
    sdist = next((tmp_path / "dist").glob("appjail-*.tar.gz"))
    with tarfile.open(sdist) as tar:
        names = [n.split("/", 1)[1] for n in tar.getnames() if "/" in n]
    top = {n.split("/")[0] for n in names}
    assert {"src", "LICENSES", "README.md", "pyproject.toml"} <= top
    assert not top & {"tests", "DESIGN.md", "CLAUDE.md", "vm", "bin", ".github"}, top
    assert sdist.stat().st_size < 100_000
    # the tarball alone is enough to build and install the command
    fresh = tmp_path / "fresh"
    run(sys.executable, "-m", "venv", str(fresh))
    # no git history and no pretend version here: the sdist's PKG-INFO has to carry the version
    clean = {k: v for k, v in os.environ.items() if k != "SETUPTOOLS_SCM_PRETEND_VERSION"}
    run(str(fresh / "bin" / "pip"), "install", "--quiet", str(sdist), env=clean)
    assert run(str(fresh / "bin" / "appjail"), "version", cwd=tmp_path).strip() == f"appjail {VERSION}"
    assert "Sandboxed AppImage manager" in run(str(fresh / "bin" / "appjail"), "--help", cwd=tmp_path)
