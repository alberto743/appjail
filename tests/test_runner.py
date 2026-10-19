# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from bjail import appimage, jail, manifest, runner, seccomp, store
from bjail.jail import RunError
from bjail.manifest import Manifest, Permissions

integration = pytest.mark.skipif(os.environ.get("BJAIL_INTEGRATION") != "1",
                                 reason="real bwrap: run in the test guest (BJAIL_INTEGRATION=1)")
SHA = "a" * 64


@contextlib.contextmanager
def NO_RESTRICTION(env, app_id=None):
    """Stands in for a compositor without wp_security_context_v1."""
    yield None


@pytest.fixture
def sandbox(monkeypatch):
    base = Path(tempfile.mkdtemp(prefix="bj"))
    monkeypatch.setenv("BJAIL_DATA_DIR", str(base / "data"))
    monkeypatch.setenv("BJAIL_CONFIG_DIR", str(base / "config"))
    yield base
    appimage.remove_tree(base)


@pytest.fixture
def runtime():
    """A fake XDG_RUNTIME_DIR holding real unix sockets (short path: sun_path is limited)."""
    base = Path(tempfile.mkdtemp(prefix="rt"))
    (base / "pulse").mkdir()
    socks = []

    def sock(rel):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(base / rel))
        s.listen(1)
        socks.append(s)

    sock("wayland-test")
    sock("pipewire-0")
    sock("pulse/native")
    yield base
    for s in socks:
        s.close()
    shutil.rmtree(base)


def build(sandbox, runtime, **perms):
    root = sandbox / "root"
    root.mkdir(exist_ok=True)
    etc = sandbox / "etc"
    etc.mkdir(exist_ok=True)
    (etc / "passwd").write_text("app:x:1000:1000::/home/app:/bin/sh\n")
    (etc / "group").write_text("app:x:1000:\n")
    home = sandbox / "home"
    home.mkdir(exist_ok=True)
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test", "LANG": "it_IT.UTF-8", "SECRET": "x"}
    kw = dict(root=root, home=home, etc_dir=etc, perms=Permissions(**perms), uid=os.getuid(), host_env=env,
              command=["/app/AppRun"], host_home=Path.home())
    return kw


def pairs(args, flag):
    return [tuple(args[i + 1:i + 3]) for i, a in enumerate(args) if a == flag]


# -- argument builder (pure) ------------------------------------------------------------


def test_baseline_isolation(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime))
    for flag in ("--unshare-all", "--die-with-parent", "--new-session", "--clearenv"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "--share-net" not in args
    assert ("--dev-bind" not in args) and ("--bind", str(sandbox / "home"), "/home/app") in [
        tuple(args[i:i + 3]) for i in range(len(args))]
    assert (str(sandbox / "root"), "/app") in pairs(args, "--ro-bind")
    i = args.index("--remount-ro")
    assert args[i:i + 2] == ["--remount-ro", "/"]
    assert args[args.index("--") + 1:] == ["/app/AppRun"]


def test_only_whitelisted_environment_is_set(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime))
    env = {k: v for k, v in pairs(args, "--setenv")}
    assert "SECRET" not in env
    assert env["HOME"] == "/home/app" and env["WAYLAND_DISPLAY"] == "wayland-0" and env["LANG"] == "it_IT.UTF-8"
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{os.getuid()}"
    assert not any(k in env for k in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK"))


def test_wayland_socket_is_bound(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime))
    assert (str(runtime / "wayland-test"), f"/run/user/{os.getuid()}/wayland-0") in pairs(args, "--ro-bind")


@pytest.mark.parametrize("audio", [False, True])
def test_audio_sockets_only_when_granted(sandbox, runtime, audio):
    args = jail.runtime_args(**build(sandbox, runtime, audio=audio))
    dests = [d for _, d in pairs(args, "--ro-bind")]
    env = dict(pairs(args, "--setenv"))
    rt = f"/run/user/{os.getuid()}"
    assert (f"{rt}/pipewire-0" in dests) is audio and (f"{rt}/pulse/native" in dests) is audio
    assert ("PULSE_SERVER" in env) is audio


def test_gpu_only_when_granted(sandbox, runtime):
    off = jail.runtime_args(**build(sandbox, runtime, gpu=False))
    assert "/dev/dri" not in off and not pairs(off, "--dev-bind")
    if os.path.isdir("/dev/dri"):
        assert ("/dev/dri", "/dev/dri") in pairs(jail.runtime_args(**build(sandbox, runtime, gpu=True)), "--dev-bind")


def test_network_is_opt_in(sandbox, runtime):
    assert "--share-net" in jail.runtime_args(**build(sandbox, runtime, network=True))


def test_dirs_map_into_private_home(sandbox, runtime, monkeypatch):
    fake_home = sandbox / "fakehome"
    (fake_home / "Docs").mkdir(parents=True)
    (fake_home / "Out").mkdir()
    shared = sandbox / "shared"
    shared.mkdir()
    kw = build(sandbox, runtime, dirs=("~/Docs", "~/Out:rw", str(shared)))
    kw["host_home"] = fake_home
    args = jail.runtime_args(**kw)
    assert (str(fake_home / "Docs"), "/home/app/Docs") in pairs(args, "--ro-bind")
    assert (str(fake_home / "Out"), "/home/app/Out") in pairs(args, "--bind")
    assert (str(shared), str(shared)) in pairs(args, "--ro-bind")


def test_missing_granted_dir_is_an_error(sandbox, runtime):
    kw = build(sandbox, runtime, dirs=("~/NoSuchDir",))
    kw["host_home"] = sandbox
    with pytest.raises(RunError, match="does not exist"):
        jail.runtime_args(**kw)


@pytest.mark.parametrize("what", ["home", "parent"])
def test_dirs_cannot_expose_the_whole_home(sandbox, runtime, what):
    kw = build(sandbox, runtime, dirs=(str(sandbox if what == "home" else sandbox.parent),))
    kw["host_home"] = sandbox
    with pytest.raises(RunError, match="whole home"):
        jail.runtime_args(**kw)


@pytest.mark.parametrize("where", ["data", "config", "inside_data", "parent_of_data"])
def test_dirs_cannot_expose_bjail_itself(sandbox, runtime, where):
    store.data_dir().mkdir(parents=True)
    store.config_dir().mkdir(parents=True)
    (store.data_dir() / "apps").mkdir()
    path = {"data": store.data_dir(), "config": store.config_dir(), "inside_data": store.data_dir() / "apps",
            "parent_of_data": store.data_dir().parent}[where]
    with pytest.raises(RunError, match="bjail's own data"):
        jail.runtime_args(**build(sandbox, runtime, dirs=(str(path),)))


@pytest.mark.parametrize("perms,match", [
    ({"portals": True}, "filtered bus socket"),
    ({"dbus_filter": ("org.freedesktop.Notifications",)}, "filtered bus socket"),
])
def test_unimplemented_permissions_are_refused_not_ignored(sandbox, runtime, perms, match):
    with pytest.raises(RunError, match=match):
        jail.runtime_args(**build(sandbox, runtime, **perms))


def test_xwayland_wraps_the_command_and_switches_the_toolkits(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(jail, "XWAYLAND_PATHS", ("/bin/sh",))  # any executable stands in for the binary
    args = jail.runtime_args(**build(sandbox, runtime, display="xwayland"))
    env = {v[0]: v[1] for v in (args[i + 1:i + 3] for i, a in enumerate(args) if a == "--setenv")}
    assert "WAYLAND_DISPLAY" not in env and env["GDK_BACKEND"] == "x11" and env["QT_QPA_PLATFORM"] == "xcb"
    cmd = args[args.index("--") + 1:]
    assert cmd[:2] == ["/bin/sh", "-c"] and cmd[4] == "/bin/sh" and cmd[5].endswith("/AppRun")
    assert not any("X11" in a for a in args if a != cmd[2])  # the host X11 socket is never bound


def test_xwayland_without_the_binary_is_an_error(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(jail, "XWAYLAND_PATHS", ("/nonexistent/Xwayland",))
    with pytest.raises(RunError, match="Xwayland"):
        jail.runtime_args(**build(sandbox, runtime, display="xwayland"))


def test_missing_or_hostile_wayland_socket(sandbox, runtime):
    kw = build(sandbox, runtime)
    kw["host_env"] = dict(kw["host_env"], WAYLAND_DISPLAY="nope")
    with pytest.raises(RunError, match="not found"):
        jail.runtime_args(**kw)
    kw["host_env"] = dict(kw["host_env"], WAYLAND_DISPLAY="../x")
    with pytest.raises(RunError, match="no usable Wayland"):
        jail.runtime_args(**kw)
    kw["host_env"] = {}
    with pytest.raises(RunError, match="no usable Wayland"):
        jail.runtime_args(**kw)


# -- prepare: pin verification and re-extraction -----------------------------------------


def install(sandbox, name="app", content=b"image-bytes", sha=None):
    store.appimage_path(name).parent.mkdir(parents=True)
    store.appimage_path(name).write_bytes(content)
    digest = appimage.sha256_file(store.appimage_path(name))
    m = Manifest(name=name, source="o/r", asset_pattern="*", version="v1", sha256=sha or digest,
                 evidence_tier=3, published_at="2026-01-01T00:00:00Z")
    manifest.dump(store.manifest_path(name), m)
    return digest


class Extractor:
    def __init__(self):
        self.calls = 0

    def __call__(self, image, dest, fallback=False):
        self.calls += 1
        (Path(dest) / "usr").mkdir(parents=True)
        (Path(dest) / "AppRun").write_text("#!/bin/sh\n")
        return 1, 1


def test_unknown_app(sandbox):
    with pytest.raises(RunError, match="unknown app"):
        runner.prepare("ghost")


def test_tampered_appimage_refused_before_anything_runs(sandbox):
    install(sandbox, sha="b" * 64)
    ex = Extractor()
    with pytest.raises(RunError, match="does not match the pinned sha256"):
        runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 0 and not store.root_path("app").exists()


def test_extracts_once_then_reuses_the_tree(sandbox):
    digest = install(sandbox)
    ex = Extractor()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 1
    assert store.root_marker("app").read_text().strip() == digest


def test_stale_or_missing_marker_forces_reextraction(sandbox):
    install(sandbox)
    ex = Extractor()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    store.root_marker("app").write_text("0" * 64 + "\n")
    runner.prepare("app", extract=ex, say=lambda *_: None)
    store.root_marker("app").unlink()
    runner.prepare("app", extract=ex, say=lambda *_: None)
    assert ex.calls == 3


def test_modified_tree_is_extracted_again(sandbox):
    install(sandbox)
    ex, said = Extractor(), []
    runner.prepare("app", extract=ex, say=said.append)
    (store.root_path("app") / "usr" / "evil").write_text("x")
    runner.prepare("app", extract=ex, say=said.append)
    assert ex.calls == 2 and not (store.root_path("app") / "usr" / "evil").exists()
    assert any("modified" in m for m in said)


def test_tree_digest_sees_content_mode_and_links(tmp_path):
    (tmp_path / "f").write_text("a")
    (tmp_path / "l").symlink_to("f")
    base = appimage.tree_digest(tmp_path)
    assert appimage.tree_digest(tmp_path) == base
    (tmp_path / "f").write_text("b")
    changed = appimage.tree_digest(tmp_path)
    assert changed != base
    os.chmod(tmp_path / "f", 0o755)
    assert appimage.tree_digest(tmp_path) != changed
    mode = appimage.tree_digest(tmp_path)
    (tmp_path / "l").unlink()
    (tmp_path / "l").symlink_to("/etc/passwd")
    assert appimage.tree_digest(tmp_path) != mode


def test_extraction_error_becomes_run_error(sandbox):
    install(sandbox)

    def bad(image, dest, fallback=False):
        raise appimage.ExtractError("boom")

    with pytest.raises(RunError, match="cannot extract app: boom"):
        runner.prepare("app", extract=bad, say=lambda *_: None)


def test_passwd_and_private_home_created(sandbox):
    install(sandbox)
    _, _, home, etc = runner.prepare("app", extract=Extractor(), say=lambda *_: None)
    assert f"app:x:{os.getuid()}:" in (etc / "passwd").read_text()
    assert home.stat().st_mode & 0o777 == 0o700


def test_launch_merges_temporary_directories_without_touching_the_manifest(sandbox, runtime):
    install(sandbox)
    granted = sandbox / "granted"
    granted.mkdir()
    captured = []
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    said = []
    code = runner.launch("app", ["--x"], host_env=env, extract=Extractor(), say=said.append,
                         runner=lambda argv: captured.append(argv) or 0, extra_dirs=(f"{granted}:rw",),
                         restricted=NO_RESTRICTION)
    assert code == 0
    assert any("wp_security_context_v1" in m for m in said)
    argv = captured[0]
    assert (str(granted), str(granted)) in pairs(argv, "--bind")
    assert argv[-2:] == ["/app/AppRun", "--x"]
    assert any("Temporary access" in line for line in said)
    assert manifest.load(store.manifest_path("app")).permissions.dirs == ()


# -- real bwrap (guest only) ---------------------------------------------------------------

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


def facts(sandbox, runtime, **perms):
    proc = run_in_jail(sandbox, runtime, **perms)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@integration
def test_private_home_and_filesystem(sandbox, runtime):
    secret = Path.home() / "bjail-secret-test"
    secret.write_text("x")
    docs = Path.home() / "Documents"
    docs_existed = docs.exists()
    docs.mkdir(exist_ok=True)
    try:
        r = facts(sandbox, runtime)
    finally:
        secret.unlink()
        if not docs_existed:
            docs.rmdir()
    assert r["slash_home"] == ["app"] and r["app_home"] == [] and not r["docs"]
    assert r["tmp"] == [] and not r["x11"]
    assert (r["w_home"], r["w_root"], r["w_app"], r["w_usr"]) == (True, False, False, False)
    assert r["host"] == "bjail"


@integration
def test_no_capabilities_new_pid_namespace_and_env_whitelist(sandbox, runtime, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "x")
    r = facts(sandbox, runtime)
    assert r["caps"] == "0000000000000000" and r["pid"] < 10
    assert "SECRET_TOKEN" not in r["env"] and "SECRET" not in r["env"]
    assert not {"DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK"} & set(r["env"])


@integration
def test_wayland_reachable_and_nothing_else_in_runtime_dir(sandbox, runtime):
    r = facts(sandbox, runtime, audio=False)
    assert r["wayland"] is True
    assert r["rt"] == ["wayland-0"]


@integration
def test_audio_sockets_visible_only_when_granted(sandbox, runtime):
    on, off = facts(sandbox, runtime, audio=True), facts(sandbox, runtime, audio=False)
    assert (on["pipewire"], on["pulse"]) == (True, True)
    assert (off["pipewire"], off["pulse"]) == (False, False)


@integration
def test_no_network_unless_granted(sandbox, runtime):
    assert facts(sandbox, runtime)["ifaces"] == ["lo"]
    assert len(facts(sandbox, runtime, network=True)["ifaces"]) > 1


@integration
@pytest.mark.skipif(not os.path.exists("/dev/dri/renderD128"), reason="no DRM render node (run provision.sh)")
def test_gpu_nodes_only_when_granted(sandbox, runtime):
    script = FACTS.replace('print(json.dumps({', 'print(json.dumps({"dri": ls("/dev/dri"), "render_open": can_open("/dev/dri/renderD128"), ')
    script = script.replace('def connects', 'def can_open(p):\n    try:\n        os.close(os.open(p, os.O_RDWR)); return True\n    except OSError:\n        return False\n\ndef connects')
    on = json.loads(run_in_jail(sandbox, runtime, script=script, gpu=True).stdout)
    off = json.loads(run_in_jail(sandbox, runtime, script=script, gpu=False).stdout)
    assert "renderD128" in on["dri"] and on["render_open"] is True
    assert off["dri"] is None and off["render_open"] is False


@integration
def test_granted_directories_modes(sandbox, runtime):
    ro, rw = sandbox / "ro", sandbox / "rw"
    ro.mkdir()
    rw.mkdir()
    script = FACTS.replace('print(json.dumps({', f'print(json.dumps({{"w_ro": writable("{ro}/x"), "w_rw": writable("{rw}/x"), ')
    proc = run_in_jail(sandbox, runtime, script=script, dirs=(str(ro), f"{rw}:rw"))
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert (r["w_ro"], r["w_rw"]) == (False, True)


@integration
def test_arguments_are_passed_through(sandbox, runtime):
    proc = run_in_jail(sandbox, runtime, extra=("--flag", "a b"))
    assert json.loads(proc.stdout)["args"] == ["--flag", "a b"]


@integration
def test_app_cannot_see_bjail_data_through_home(sandbox, runtime):
    install(sandbox)
    r = facts(sandbox, runtime)
    assert r["app_home"] == []


@integration
@pytest.mark.skipif(not shutil.which("weston") or not shutil.which("weston-simple-shm"), reason="weston not installed")
def test_real_wayland_client_runs_against_headless_weston(sandbox):
    rt = Path(f"/run/user/{os.getuid()}")
    if not rt.is_dir():
        pytest.skip("no /run/user/<uid> in this session")
    log = open(sandbox / "weston.log", "w")
    weston = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--socket=bjail-test"],
                              env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt)}, stdout=log, stderr=log)
    try:
        for _ in range(50):
            if (rt / "bjail-test").exists():
                break
            time.sleep(0.1)
        else:
            pytest.skip("weston headless did not start: " + (sandbox / "weston.log").read_text()[-300:])
        kw = build(sandbox, rt, audio=False)
        kw["host_env"] = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "bjail-test"}
        (kw["root"] / "AppRun").write_text("#!/bin/sh\nexec /usr/bin/timeout 3 /usr/bin/weston-simple-shm\n")
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw)], timeout=30)
        assert proc.returncode == 124, proc.stderr  # killed by timeout while running = it connected
    finally:
        weston.terminate()
        weston.wait(timeout=10)
        log.close()


@pytest.mark.parametrize("sub,mode", [(".ssh", ""), (".local/bin", ":rw"), (".config", "")])
def test_sensitive_dirs_refused_after_symlink_resolution(sandbox, runtime, sub, mode):
    """A link in a harmless location pointing at a sensitive one must not get past the policy."""
    fake_home = sandbox / "fakehome"
    target = fake_home / sub
    target.mkdir(parents=True)
    (fake_home / "innocent").symlink_to(target)
    with pytest.raises(RunError, match="refused"):
        jail.dir_binds([f"~/innocent{mode}"], fake_home)


def test_restricted_wayland_socket_replaces_the_host_one(sandbox, runtime):
    restricted = sandbox / "restricted.sock"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(restricted))
    try:
        kw = build(sandbox, runtime)
        args = jail.runtime_args(**kw, wayland_socket=str(restricted))
        rt = f"/run/user/{os.getuid()}"
        assert (str(restricted), f"{rt}/wayland-0") in pairs(args, "--ro-bind")
        assert str(Path(runtime) / kw["host_env"]["WAYLAND_DISPLAY"]) not in [a for a in args if isinstance(a, str)]
    finally:
        s.close()


@integration
@pytest.mark.skipif(not all(shutil.which(c) for c in ("weston", "Xwayland", "xdpyinfo")),
                    reason="weston, xwayland and x11-utils are installed in the test guest")
def test_x11_client_runs_through_a_private_xwayland(sandbox):
    rt = Path(f"/run/user/{os.getuid()}")
    if not rt.is_dir():
        pytest.skip("no /run/user/<uid> in this session")
    log = open(sandbox / "weston.log", "w")
    weston = subprocess.Popen(["weston", "--backend=headless", "--renderer=pixman", "--socket=bjail-xtest"],
                              env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(rt)}, stdout=log, stderr=log)
    try:
        for _ in range(50):
            if (rt / "bjail-xtest").exists():
                break
            time.sleep(0.1)
        else:
            pytest.skip("weston headless did not start: " + (sandbox / "weston.log").read_text()[-300:])
        kw = build(sandbox, rt, audio=False, display="xwayland")
        kw["host_env"] = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "bjail-xtest"}
        out = sandbox / "xdpyinfo.txt"
        (kw["root"] / "AppRun").write_text(
            f"#!/bin/sh\n/usr/bin/xdpyinfo > /app/out.txt 2>&1; echo \"display=$DISPLAY wl=$WAYLAND_DISPLAY\" >> /app/out.txt\n"
            .replace("/app/out.txt", "/home/app/out.txt"))
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw)], timeout=30)
        text = (kw["home"] / "out.txt").read_text()
        assert proc.returncode == 0 and "name of display" in text, text + proc.stderr
        assert "wl=\n" in text + "\n" and "display=:" in text
    finally:
        weston.terminate()
        weston.wait(timeout=10)
        log.close()


# -- single files (run --file) -------------------------------------------------------------

def test_file_binds_read_only_by_default_and_rw_on_request(sandbox):
    home = sandbox / "fakehome"
    (home / "docs").mkdir(parents=True)
    ro, rw, outside = home / "docs" / "a.txt", home / "docs" / "b.txt", sandbox / "c.txt"
    for f in (ro, rw, outside):
        f.write_text("x")
    args, dests = jail.file_binds([str(ro), f"{rw}:rw", str(outside)], home)
    assert pairs(args, "--ro-bind") == [(str(ro), f"{jail.APP_HOME}/docs/a.txt"), (str(outside), str(outside))]
    assert pairs(args, "--bind") == [(str(rw), f"{jail.APP_HOME}/docs/b.txt")]
    assert dests == [f"{jail.APP_HOME}/docs/a.txt", f"{jail.APP_HOME}/docs/b.txt", str(outside)]


def test_file_binds_refuse_directories_missing_and_special_files(sandbox):
    (sandbox / "d").mkdir()
    for bad, msg in [(sandbox / "d", "not a regular file"), (sandbox / "nope", "does not exist"), (Path("/dev/null"), "not a regular file")]:
        with pytest.raises(RunError, match=msg):
            jail.file_binds([str(bad)], sandbox)


@pytest.mark.parametrize("rel,mode", [(".ssh/id_ed25519", ""), (".gnupg/pubring.kbx", ""), ("vault.kdbx", ""), (".bashrc", ":rw")])
def test_file_binds_apply_the_sensitive_path_policy(sandbox, rel, mode):
    home = sandbox / "fakehome"
    f = home / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    link = sandbox / "innocent.txt"
    link.symlink_to(f)
    for path in (f, link):  # a link must not dodge the policy
        with pytest.raises(RunError, match="refused"):
            jail.file_binds([f"{path}{mode}"], home)


def test_file_binds_refuse_bjails_own_data(sandbox):
    f = store.data_dir() / "x"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    with pytest.raises(RunError, match="own data"):
        jail.file_binds([str(f)], sandbox)


def test_launch_binds_files_and_passes_their_jail_paths_to_the_app(sandbox, runtime):
    install(sandbox)
    f = sandbox / "doc.txt"
    f.write_text("x")
    captured, said = [], []
    runner.launch("app", ["--x"], host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                  extract=Extractor(), say=said.append, runner=lambda argv: captured.append(argv) or 0,
                  extra_files=(str(f),), restricted=NO_RESTRICTION)
    argv = captured[0]
    assert (str(f), str(f)) in pairs(argv, "--ro-bind")
    assert argv[-3:] == ["/app/AppRun", "--x", str(f)]
    assert any("Temporary file access" in line for line in said)


@integration
def test_only_the_granted_file_is_visible_in_the_jail(sandbox, runtime):
    d = sandbox / "shared"
    d.mkdir()
    (d / "in.txt").write_text("hello")
    (d / "sibling.txt").write_text("other")
    kw = build(sandbox, runtime)
    script = ('#!/usr/bin/python3\nimport os, sys\np = sys.argv[1]\nprint(open(p).read(), os.path.exists(os.path.dirname(p) + "/sibling.txt"))\n'
              'try:\n    open(p, "w")\nexcept OSError:\n    print("ro")\n')
    (kw["root"] / "AppRun").write_text(script)
    (kw["root"] / "AppRun").chmod(0o755)
    kw["command"] = ["/app/AppRun", str(d / "in.txt")]
    fd = seccomp.open_fd(kw["perms"].userns)
    try:
        proc = jail.supervise([jail.find_bwrap(), *jail.runtime_args(**kw, seccomp_fd=fd, files=[str(d / "in.txt")])], timeout=60, pass_fds=(fd,))
    finally:
        os.close(fd)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["hello", "False", "ro"]
