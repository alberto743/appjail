# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Helpers shared by several test modules (fixtures are in conftest.py)."""

import contextlib
import hashlib
import os
import shutil
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from appjail import appimage, cli, dbusproxy, github, jail, manifest, seccomp, store
from appjail.cli import Abort
from appjail.manifest import Manifest, Permissions


def stub(extra=b""):
    """Minimal type-2 runtime: ELF64 header whose section table ends at byte 64."""
    h = bytearray(64)
    h[:4] = b"\x7fELF"
    h[4], h[5] = 2, 1
    h[8:11] = b"AI\x02"
    struct.pack_into("<Q", h, 0x28, 64)
    struct.pack_into("<HH", h, 0x3A, 64, 0)
    return bytes(h) + extra


def write_image(path, fs):
    Path(path).write_bytes(stub(fs))


FAKE_APPIMAGE = b"\x7fELF\x02\x01\x01\x00AI\x02" + b"payload" * 10


SHA = hashlib.sha256(FAKE_APPIMAGE).hexdigest()


NOW = datetime(2026, 10, 17, tzinfo=UTC)


class FakeClient:
    def __init__(self, info_=None, release_=None, attestation=True, bundles=()):
        self._info, self._release, self._att = info_ or info(), release_ or release(asset()), attestation
        self._bundles = list(bundles)
        self.calls = []

    def attestation_bundles(self, source, sha):
        self.calls.append(("attestation_bundles", source, sha))
        return self._bundles

    def repo_info(self, source):
        self.calls.append(("repo_info", source))
        return self._info

    def latest_release(self, source, prereleases=False):
        self.calls.append(("latest_release", source))
        return self._release

    def release_by_tag(self, source, tag):
        self.calls.append(("release_by_tag", source, tag))
        return self._release

    def has_attestation(self, source, sha):
        return self._att


class Harness:
    def __init__(self):
        self.downloads, self.extractions = [], []

    def download(self, content=FAKE_APPIMAGE):
        def download(url, stage, filename, expected_size):
            self.downloads.append((url, expected_size))
            path = Path(stage) / filename
            path.write_bytes(content)
            return path
        return download

    def extract(self, appimage_, dest, fallback=False):
        self.extractions.append((Path(appimage_), Path(dest), fallback))
        (Path(dest) / "usr").mkdir(parents=True)
        (Path(dest) / "AppRun").write_text("#!/bin/sh\n")
        return 2, 20

    def add(self, client=None, answers=("y",), extra=(), download=None, extract=None, extract_ok=lambda: True,
            source="o/App"):
        console = Script(answers)
        parsed = cli.build_parser().parse_args(["add", source, *extra])
        cli.cmd_add(parsed, client or FakeClient(), console, download=download or self.download(), now=NOW,
                    extract=extract or self.extract, extract_ok=extract_ok)
        return console

    def assert_nothing_installed(self, name="app"):
        assert not store.manifest_path(name).exists()
        assert not store.app_dir(name).exists()
        assert list(store.staging_root().iterdir()) == []


class Script(cli.Console):
    """Console with scripted answers; records output instead of printing."""

    def __init__(self, answers=()):
        self.answers, self.lines = list(answers), []

    def out(self, line=""):
        self.lines.append(line)

    def warn(self, line):
        self.lines.append("WARNING: " + line)

    def ask(self, prompt):
        self.lines.append("? " + prompt)
        if not self.answers:
            raise Abort("no input available")
        return str(self.answers.pop(0))

    @property
    def text(self):
        return "\n".join(self.lines)


def asset(name="App-1.0-x86_64.AppImage", sha=SHA, size=None):
    size = len(FAKE_APPIMAGE) if size is None else size
    return github.Asset(name, size, sha, f"https://github.com/o/App/releases/download/v1.0/{name}")


def info(**kw):
    base = {"full_name": "o/App", "owner": "o", "owner_id": 42, "owner_type": "User", "owner_created_at": "2015-01-02T03:04:05Z",
                "stars": 500, "fork": False, "parent": "", "archived": False, "description": "An app",
                "html_url": "https://github.com/o/App", "renamed": False}
    base.update(kw)
    return github.RepoInfo(**base)


def release(*assets, tag="v1.0"):
    return github.Release(tag, "2026-09-30T02:40:02Z", False, f"https://github.com/o/App/releases/tag/{tag}", tuple(assets))


NEW_IMAGE = FAKE_APPIMAGE + b"-v2"


NEW_SHA = hashlib.sha256(NEW_IMAGE).hexdigest()


T0 = datetime(2026, 10, 17, tzinfo=UTC)


def release2(sha=NEW_SHA, tag="v2.0", published="2026-10-10T00:00:00Z", name="App-2.0-x86_64.AppImage", size=None):
    size = len(NEW_IMAGE) if size is None else size
    a = github.Asset(name, size, sha, f"https://github.com/o/App/releases/download/{tag}/{name}")
    return github.Release(tag, published, False, f"https://github.com/o/App/releases/tag/{tag}", (a,))


def installed(h, **kw):
    h.add(**kw)
    return store.manifest_path("app")


def update(h, client, answers=("y",), days=7, now=T0, app="app", extra=(), download=None, extract=None,
           extract_ok=lambda: True):
    console = Script(answers)
    args = cli.build_parser().parse_args(["update", *([app] if app else []), "--quarantine", str(days), *extra])
    code = cli.cmd_update(args, client, console, download=download or h.download(NEW_IMAGE), now=now,
                          extract=extract or h.extract, extract_ok=extract_ok)
    return code, console


needs_proxy = pytest.mark.skipif(not os.access(dbusproxy.PROXY, os.X_OK) or not shutil.which("dbus-daemon"),
                                 reason="needs xdg-dbus-proxy and dbus-daemon (run provision.sh)")


integration = pytest.mark.skipif(os.environ.get("APPJAIL_INTEGRATION") != "1",
                                 reason="real bwrap: run in the test guest (APPJAIL_INTEGRATION=1)")


@contextlib.contextmanager
def NO_RESTRICTION(env, app_id=None):
    """Stands in for a compositor without wp_security_context_v1."""
    yield None


def build(sandbox, runtime, **perms):
    root = sandbox / "root"
    root.mkdir(exist_ok=True)
    etc = sandbox / "etc"
    etc.mkdir(exist_ok=True)
    # the real ids, like runner.prepare: a fixed 1000 hid a bug on CI runners (uid 1001), where Xwayland could not
    # look up its user and refused the app's own clients
    (etc / "passwd").write_text(f"app:x:{os.getuid()}:{os.getgid()}::/home/app:/bin/sh\n")
    (etc / "group").write_text(f"app:x:{os.getgid()}:\n")
    home = sandbox / "home"
    home.mkdir(exist_ok=True)
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test", "LANG": "it_IT.UTF-8", "SECRET": "x"}
    kw = {"root": root, "home": home, "etc_dir": etc, "perms": Permissions(**perms), "uid": os.getuid(), "host_env": env,
              "command": ["/app/AppRun"], "host_home": Path.home()}
    return kw


def pairs(args, flag):
    return [tuple(args[i + 1:i + 3]) for i, a in enumerate(args) if a == flag]


FACTS = r'''#!/usr/bin/python3
import json, os, socket

def ls(p):
    try:
        return sorted(os.listdir(p))
    except OSError:
        return None

def writable(p):
    try:
        open(p, "w").close(); os.unlink(p); return True
    except OSError:
        return False

def connects(p):
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(p); return True
    except OSError:
        return False
    finally:
        s.close()

rt = os.environ["XDG_RUNTIME_DIR"]
caps = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1]
print(json.dumps({
    "home": os.environ["HOME"], "slash_home": ls("/home"), "app_home": ls("/home/app"),
    "rt": ls(rt), "wayland": connects(rt + "/wayland-0"),
    "pipewire": os.path.exists(rt + "/pipewire-0"), "pulse": os.path.exists(rt + "/pulse/native"),
    "x11": os.path.exists("/tmp/.X11-unix"), "tmp": ls("/tmp"), "caps": caps, "pid": os.getpid(),
    "ifaces": [n for _, n in socket.if_nameindex()], "env": sorted(os.environ),
    "w_root": writable("/x"), "w_app": writable("/app/x"), "w_home": writable("/home/app/x"),
    "w_usr": writable("/usr/x"), "host": socket.gethostname(), "uid": os.getuid(),
    "docs": os.path.exists("/home/app/Documents"), "args": os.sys.argv[1:],
}))
'''


def run_in_jail(sandbox, runtime, script=FACTS, extra=(), **perms):
    kw = build(sandbox, runtime, **perms)
    (kw["root"] / "AppRun").write_text(script)
    (kw["root"] / "AppRun").chmod(0o755)
    kw["command"] = ["/app/AppRun", *extra]
    fd = seccomp.open_fd(kw["perms"].userns)
    try:
        args = jail.runtime_args(**kw, seccomp_fd=fd)
        return jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd,))
    finally:
        os.close(fd)


def install(sandbox, name="app", content=b"image-bytes", sha=None, **perms):
    store.appimage_path(name).parent.mkdir(parents=True, exist_ok=True)
    store.appimage_path(name).write_bytes(content)
    digest = appimage.sha256_file(store.appimage_path(name))
    m = Manifest(name=name, source="o/r", asset_pattern="*", version="v1", sha256=sha or digest,
                 evidence_tier=3, published_at="2026-01-01T00:00:00Z", permissions=Permissions(**perms))
    manifest.dump(store.manifest_path(name), m)
    return digest
