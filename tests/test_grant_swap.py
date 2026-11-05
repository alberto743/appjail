# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A granted path swapped for a symlink between the checks and the exec must not reach what the symlink points at."""

import os
from pathlib import Path

import pytest

from appjail import runner, runtimejail
from appjail.errors import RunError

from .helpers import Extractor, install, integration, needs_pasta

SECRET, GRANTED = "SECRET-CONTENT", "GRANTED-CONTENT"


class CatExtractor(Extractor):
    """A tree whose AppRun is `script`; by default it prints the files named in its arguments."""

    def __init__(self, script='#!/bin/sh\nexec /usr/bin/cat "$@"\n'):
        super().__init__()
        self.script = script

    def __call__(self, image, dest, fallback=False):
        result = super().__call__(image, dest, fallback)
        (Path(dest) / "AppRun").write_text(self.script)
        (Path(dest) / "AppRun").chmod(0o755)
        return result


@pytest.fixture
def world(sandbox, runtime, monkeypatch):
    """A fake home with a granted file and directory, and a forbidden file and directory outside it."""
    home = sandbox / "fakehome"
    (home / "docs").mkdir(parents=True)
    (home / "doc.txt").write_text(GRANTED)
    (home / "docs" / "f").write_text(GRANTED)
    (sandbox / "secret.txt").write_text(SECRET)
    (sandbox / "secretdir").mkdir()
    (sandbox / "secretdir" / "f").write_text(SECRET)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def swap(path, target):
    os.rename(path, f"{path}.orig")
    os.symlink(target, path)


CASES = {
    # kind: launch arguments, the path to swap, its forbidden target
    "file": (lambda home: {"extra_files": (f"{home}/doc.txt:ro",)}, "doc.txt", "secret.txt"),
    "dir": (lambda home: {"extra_dirs": ("~/docs",), "extra_args": ["/home/app/docs/f"]}, "docs", "secretdir"),
    "parent": (lambda home: {"extra_files": (f"{home}/docs/f:ro",)}, "docs", "secretdir"),
}


def launch_with_swap(sandbox, runtime, home, monkeypatch, kind, **perms):
    install(sandbox, display="none", **perms)
    args, name, target = CASES[kind]
    run_app = runner._run_app

    def swap_then_run(*a, **kw):
        swap(home / name, sandbox / target)
        return run_app(*a, **kw)
    monkeypatch.setattr(runner, "_run_app", swap_then_run)
    return runner.launch("app", host_env={"XDG_RUNTIME_DIR": str(runtime)}, extract=CatExtractor(),
                         say=lambda *_: None, **args(home))


@integration
@pytest.mark.parametrize("kind", CASES)
def test_the_jail_gets_what_was_checked_after_a_swap(sandbox, runtime, world, monkeypatch, capfd, kind):
    code = launch_with_swap(sandbox, runtime, world, monkeypatch, kind)
    out = capfd.readouterr().out
    assert SECRET not in out
    assert (code, out) == (0, GRANTED)


@integration
@needs_pasta
@pytest.mark.parametrize("kind", CASES)
def test_a_swap_behind_pasta_is_refused(sandbox, runtime, world, monkeypatch, capfd, kind):
    """pasta closes inherited descriptors: the path is opened again inside its namespace and must be the same file."""
    code = launch_with_swap(sandbox, runtime, world, monkeypatch, kind, network=True)
    got = capfd.readouterr()
    assert SECRET not in got.out
    assert code != 0 and "changed" in got.err


READ_AND_WRITE = '#!/bin/sh\necho written > /home/app/rw.txt\nexec /usr/bin/cat /home/app/docs/f /home/app/docs/inner.txt\n'


@integration
@pytest.mark.parametrize("network", [False, pytest.param(True, marks=needs_pasta)], ids=["plain", "pasta"])
def test_granted_paths_reach_the_app(sandbox, runtime, world, capfd, network):
    """Several grants, a file nested in a granted directory, and a writable file, with and without pasta."""
    (world / "docs" / "inner.txt").write_text("-INNER")
    (world / "rw.txt").write_text("old")
    install(sandbox, display="none", network=network)
    code = runner.launch("app", [], host_env={"XDG_RUNTIME_DIR": str(runtime)}, extract=CatExtractor(READ_AND_WRITE),
                         say=lambda *_: None, extra_dirs=("~/docs",),
                         extra_files=(f"{world}/docs/inner.txt:ro", f"{world}/rw.txt:rw"))
    assert (code, capfd.readouterr().out) == (0, f"{GRANTED}-INNER")
    assert (world / "rw.txt").read_text() == "written\n"


def test_a_file_unlinked_while_it_is_checked_is_refused(sandbox, monkeypatch):
    """A deleted file's link reads "name (deleted)", which the path policy cannot judge."""
    f = sandbox / "doc.txt"
    f.write_text("x")
    readlink = os.readlink

    def unlink_first(path):
        f.unlink()
        return readlink(path)
    monkeypatch.setattr(os, "readlink", unlink_first)
    with pytest.raises(RunError, match="changed while"):
        runtimejail.Grants((), [str(f)], sandbox)


def test_descriptors_are_closed_on_a_refusal_and_at_the_end(sandbox):
    f = sandbox / "doc.txt"
    f.write_text("x")
    before = sorted(os.listdir("/proc/self/fd"))
    with pytest.raises(RunError):
        runtimejail.Grants((), [str(f), str(sandbox / "missing")], sandbox)
    assert sorted(os.listdir("/proc/self/fd")) == before
    with runtimejail.Grants((), [str(f)], sandbox) as opened:
        assert len(opened.fds) == 1
    assert sorted(os.listdir("/proc/self/fd")) == before


def test_behind_pasta_the_arguments_name_the_numbers_the_wrapper_gives(sandbox):
    f = sandbox / "doc.txt"
    f.write_text("x")
    st = f.stat()
    with runtimejail.Grants((), [str(f)], sandbox) as opened:
        n = str(runtimejail.FIRST_PASTA_FD)
        assert opened.args(behind_pasta=True) == ["--ro-bind-fd", n, f"{runtimejail.APP_HOME}/doc.txt"]
        wrapped = opened.reopened(["bwrap"])
        assert wrapped[-6:] == ["1", n, str(st.st_dev), str(st.st_ino), str(f.resolve()), "bwrap"]
    with runtimejail.Grants((), (), sandbox) as none:
        assert none.reopened(["bwrap"]) == ["bwrap"]
