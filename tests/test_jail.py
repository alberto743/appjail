# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path

import pytest

from bjail import fetcher, jail

integration = pytest.mark.skipif(os.environ.get("BJAIL_INTEGRATION") != "1",
                                 reason="real bwrap: run in the test guest (BJAIL_INTEGRATION=1)")


@pytest.fixture
def stage():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def args(stage):
    return jail.download_args(stage, ["/usr/bin/python3", "-I", "/fetcher.py", "u", "o", "1"])


def pairs(argv, flag):
    return [tuple(argv[i + 1:i + 3]) for i, x in enumerate(argv) if x == flag]


# -- download jail arguments -------------------------------------------------------------


def test_isolation_flags(args):
    for flag in ("--unshare-all", "--share-net", "--die-with-parent", "--new-session", "--clearenv"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args.index("--unshare-all") < args.index("--share-net")


def test_root_is_remounted_read_only_after_all_mounts(args):
    i = args.index("--remount-ro")
    assert args[i + 1] == "/"
    assert [x for x in args[i + 2:] if x.startswith("--")][:2] == ["--chdir", "--"]


def test_only_stage_is_writable(args, stage):
    assert pairs(args, "--bind") == [(stage, "/stage")]
    assert pairs(args, "--dev-bind") == []


def test_no_home_or_runtime_dir_exposed(args, stage):
    home = str(Path.home())
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user")
    for a in args:
        assert not (a.startswith(home) and a not in (stage, str(jail.FETCHER))), a
        assert not a.startswith(runtime), a


def test_command_after_separator(args):
    i = args.index("--")
    assert args[i + 1] == "/usr/bin/python3"
    assert "/fetcher.py" in args


def test_env_whitelist(args):
    names = {args[i + 1] for i, x in enumerate(args) if x == "--setenv"}
    assert names == set(jail.SAFE_ENV)


# -- fetcher policy -----------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://github.com/o/r/releases/download/v1/a.AppImage",
    "https://objects.githubusercontent.com/x",
    "https://release-assets.githubusercontent.com/y",
])
def test_fetcher_allows_github_hosts(url):
    assert fetcher.allowed(url)


@pytest.mark.parametrize("url", [
    "http://github.com/o/r", "https://evil.example/", "https://github.com.evil.example/",
    "https://notgithub.com/", "https://user@github.com/", "https://github.com:8443/",
    "https://evilgithubusercontent.com/", "file:///etc/passwd", "ftp://github.com/x",
])
def test_fetcher_refuses_other_urls(url):
    assert not fetcher.allowed(url)


def test_fetcher_main_refuses_bad_url_without_network():
    with contextlib.redirect_stderr(io.StringIO()):
        assert fetcher.main(["f", "http://github.com/x", "/nonexistent/out", "1"]) == 2
        assert fetcher.main(["f"]) == 2


# -- real bwrap (guest only) --------------------------------------------------------------

CODE = r'''
import json, os, urllib.request
def can_write(p):
    try:
        open(p, "w").close(); os.unlink(p); return True
    except OSError:
        return False
caps = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1]
try:
    status = urllib.request.urlopen("https://api.github.com/rate_limit", timeout=20).status
except Exception as e:
    status = repr(e)
print(json.dumps({
    "env": sorted(os.environ), "pid": os.getpid(), "caps": caps, "net": status,
    "home_exists": os.path.exists("/home"), "host_marker": os.path.exists("/tmp/host-marker"),
    "write_stage": can_write("/stage/x"), "write_root": can_write("/x"), "write_usr": can_write("/usr/x"),
    "write_tmp": can_write("/tmp/x"), "run_user": os.path.exists("/run/user"),
}))
'''


@integration
def test_download_jail_properties(stage):
    marker = Path("/tmp/host-marker")
    marker.write_text("x")
    try:
        proc = jail.run(jail.download_args(stage, ["/usr/bin/python3", "-I", "-c", CODE]), timeout=120)
    finally:
        marker.unlink()
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["net"] == 200
    assert r["caps"] == "0000000000000000"
    assert r["pid"] < 10
    assert set(r["env"]) - {"PWD"} == set(jail.SAFE_ENV)
    assert not (r["home_exists"] or r["host_marker"] or r["run_user"])
    assert r["write_stage"] and r["write_tmp"]
    assert not (r["write_root"] or r["write_usr"])
