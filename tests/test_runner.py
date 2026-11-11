# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from appjail import (
    jail,
    linger,
    manifest,
    runner,
    runtimejail,
    seccomp,
    store,
)
from appjail.errors import RunError

from .helpers import (
    COMPOSITOR,
    NO_RESTRICTION,
    RESTRICTED,
    Extractor,
    build,
    install,
    integration,
    needs_pasta,
    outside_dir,
    pairs,
    wait_for,
)

SHA = "a" * 64


# -- argument builder (pure) ------------------------------------------------------------


def test_baseline_isolation(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime))
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
    args = runtimejail.runtime_args(**build(sandbox, runtime))
    env = {k: v for k, v in pairs(args, "--setenv")}
    assert "SECRET" not in env
    assert env["HOME"] == "/home/app" and env["WAYLAND_DISPLAY"] == "wayland-0" and env["LANG"] == "it_IT.UTF-8"
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{os.getuid()}"
    assert not any(k in env for k in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK"))


def test_wayland_socket_is_bound(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime))
    assert (str(runtime / "wayland-test"), f"/run/user/{os.getuid()}/wayland-0") in pairs(args, "--ro-bind")


@pytest.mark.parametrize("audio", [False, True])
def test_audio_sockets_only_when_granted(sandbox, runtime, audio):
    args = runtimejail.runtime_args(**build(sandbox, runtime, audio=audio))
    dests = [d for _, d in pairs(args, "--ro-bind")]
    env = dict(pairs(args, "--setenv"))
    rt = f"/run/user/{os.getuid()}"
    assert (f"{rt}/pulse/native" in dests) is audio and ("PULSE_SERVER" in env) is audio
    assert f"{rt}/pipewire-0" not in dests  # never: it would expose cameras and screen casts (see test_audio.py)


def test_gpu_only_when_granted(sandbox, runtime):
    off = runtimejail.runtime_args(**build(sandbox, runtime, gpu=False))
    assert "/dev/dri" not in off and not pairs(off, "--dev-bind")
    if os.path.isdir("/dev/dri"):
        assert ("/dev/dri", "/dev/dri") in pairs(runtimejail.runtime_args(**build(sandbox, runtime, gpu=True)), "--dev-bind")


def test_network_is_opt_in(sandbox, runtime):
    assert "--share-net" in runtimejail.runtime_args(**build(sandbox, runtime, network=True))


def test_network_host_keeps_the_host_resolver(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(jail, "find_pasta", lambda: "/usr/bin/pasta")
    private = runtimejail.runtime_args(**build(sandbox, runtime, network=True))
    host = runtimejail.runtime_args(**build(sandbox, runtime, network=True, network_host=True))
    assert "/etc/resolv.conf" in private and "resolv.conf.pasta" in " ".join(private)
    assert "resolv.conf.pasta" not in " ".join(host)


def test_networked_app_runs_in_pasta_and_is_refused_without_it(sandbox, runtime, monkeypatch):
    install(sandbox, network=True)
    captured = []
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}

    def go():
        return runner.launch("app", [], host_env=env, extract=Extractor(), say=lambda *_: None,
                             runner=lambda argv: captured.append(argv) or 0, **COMPOSITOR)
    monkeypatch.setattr(jail, "find_pasta", lambda: "/usr/bin/pasta")
    go()
    assert captured[0][0] == "/usr/bin/pasta" and "--share-net" in captured[0]
    monkeypatch.setattr(jail, "find_pasta", lambda: None)
    with pytest.raises(RunError, match="passt"):
        go()
    assert len(captured) == 1


def test_network_host_and_offline_apps_are_not_wrapped(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(jail, "find_pasta", lambda: None)  # would refuse a wrapped app
    env = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"}
    for perms in ({}, {"network": True, "network_host": True}):
        install(sandbox, **perms)
        captured = []
        runner.launch("app", [], host_env=env, extract=Extractor(), say=lambda *_: None,
                      runner=lambda argv, captured=captured: captured.append(argv) or 0, **COMPOSITOR)
        assert captured[0][0] != "/usr/bin/pasta"


def test_dirs_map_into_private_home(sandbox, runtime, monkeypatch):
    fake_home = sandbox / "fakehome"
    (fake_home / "Docs").mkdir(parents=True)
    (fake_home / "Out").mkdir()
    shared = outside_dir()
    with runtimejail.Grants(("~/Docs", "~/Out:rw", shared), (), fake_home) as opened:
        assert [(g.real, g.dest, g.rw) for g in opened.items] == [
            (str(fake_home / "Docs"), "/home/app/Docs", False), (str(fake_home / "Out"), "/home/app/Out", True), (shared, shared, False)]
        docs, out, other = opened.fds
        args = runtimejail.runtime_args(**build(sandbox, runtime), binds=opened.args())
        assert pairs(args, "--ro-bind-fd") == [(str(docs), "/home/app/Docs"), (str(other), shared)]
        assert pairs(args, "--bind-fd") == [(str(out), "/home/app/Out")]


@pytest.mark.parametrize("base", ["/tmp", "/var/tmp"])
def test_shared_temp_dirs_refused_after_symlink_resolution(sandbox, runtime, base):
    """A home link into /tmp must not get its sockets (X11, tmux, ...) into the jail, not even read-only.
    The target is a fresh directory there, since the sandbox (and so the fake home) itself lives below /tmp."""
    fake_home = sandbox / "fakehome"
    fake_home.mkdir()
    target = tempfile.mkdtemp(prefix="appjail-test-", dir=base)
    try:
        (fake_home / "scratch").symlink_to(target)
        with pytest.raises(RunError, match="shared by every program"):
            runtimejail.Grants(["~/scratch"], (), fake_home)
    finally:
        os.rmdir(target)


def test_a_single_file_in_tmp_can_still_be_granted(sandbox):
    """Only directories carry other programs' sockets: a download opened from /tmp stays possible."""
    fd, path = tempfile.mkstemp(prefix="appjail-test-", dir="/tmp")
    os.close(fd)
    try:
        with runtimejail.Grants((), [path], sandbox) as opened:
            assert opened.file_dests == [path] and opened.items[0].real == path
    finally:
        os.unlink(path)


def test_missing_granted_dir_is_an_error(sandbox, runtime):
    with pytest.raises(RunError, match="does not exist"):
        runtimejail.Grants(("~/NoSuchDir",), (), sandbox)


def test_a_granted_dir_must_be_a_directory(sandbox):
    (sandbox / "plain").write_text("x")
    with pytest.raises(RunError, match="not a directory"):
        runtimejail.Grants(("~/plain",), (), sandbox)


@pytest.mark.parametrize("what", ["home", "parent"])
def test_dirs_cannot_expose_the_whole_home(sandbox, what):
    with pytest.raises(RunError, match="whole home"):
        runtimejail.Grants((str(sandbox if what == "home" else sandbox.parent),), (), sandbox)


@pytest.mark.parametrize("where", ["data", "config", "inside_data", "parent_of_data"])
def test_dirs_cannot_expose_appjail_itself(sandbox, where):
    store.data_dir().mkdir(parents=True)
    store.config_dir().mkdir(parents=True)
    (store.data_dir() / "apps").mkdir()
    path = {"data": store.data_dir(), "config": store.config_dir(), "inside_data": store.data_dir() / "apps",
            "parent_of_data": store.data_dir().parent}[where]
    with pytest.raises(RunError, match="appjail's own data"):
        runtimejail.Grants((str(path),), (), Path.home())


@pytest.mark.parametrize("perms,match", [
    ({"portals": True}, "filtered bus socket"),
    ({"dbus_filter": ("org.freedesktop.Notifications",)}, "filtered bus socket"),
])
def test_unimplemented_permissions_are_refused_not_ignored(sandbox, runtime, perms, match):
    with pytest.raises(RunError, match=match):
        runtimejail.runtime_args(**build(sandbox, runtime, **perms))


def test_xwayland_wraps_the_command_and_switches_the_toolkits(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "XWAYLAND_PATHS", ("/bin/sh",))  # any executable stands in for the binary
    args = runtimejail.runtime_args(**build(sandbox, runtime, display="xwayland"))
    env = {v[0]: v[1] for v in (args[i + 1:i + 3] for i, a in enumerate(args) if a == "--setenv")}
    assert "WAYLAND_DISPLAY" not in env and env["GDK_BACKEND"] == "x11" and env["QT_QPA_PLATFORM"] == "xcb"
    cmd = args[args.index("--") + 1:]
    assert cmd[:2] == ["/bin/sh", "-c"] and cmd[4:7] == ["/bin/sh", "rootless", "1280x800"] and cmd[8].endswith("/AppRun")
    assert not any("X11" in a for a in args if a != cmd[2])  # the host X11 socket is never bound


def test_rootful_xwayland_has_a_window_of_its_own_and_a_window_manager(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "XWAYLAND_PATHS", ("/bin/sh",))
    monkeypatch.setattr(runtimejail, "OPENBOX_PATHS", ("/bin/true",))
    args = runtimejail.runtime_args(**build(sandbox, runtime, display="xwayland-rootful", display_size="1024x768"))
    env = {v[0]: v[1] for v in (args[i + 1:i + 3] for i, a in enumerate(args) if a == "--setenv")}
    assert "WAYLAND_DISPLAY" not in env and env["GDK_BACKEND"] == "x11"
    cmd = args[args.index("--") + 1:]
    assert cmd[4:8] == ["/bin/sh", "rootful", "1024x768", "/bin/true"] and cmd[8].endswith("/AppRun")
    assert "-geometry" in cmd[2]
    assert not any("X11" in a for a in args if a != cmd[2])


def test_rootful_xwayland_without_openbox_is_an_error(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "XWAYLAND_PATHS", ("/bin/sh",))
    monkeypatch.setattr(runtimejail, "OPENBOX_PATHS", ("/nonexistent/openbox",))
    with pytest.raises(RunError, match="openbox"):
        runtimejail.runtime_args(**build(sandbox, runtime, display="xwayland-rootful"))


def test_xwayland_without_the_binary_is_an_error(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "XWAYLAND_PATHS", ("/nonexistent/Xwayland",))
    with pytest.raises(RunError, match="Xwayland"):
        runtimejail.runtime_args(**build(sandbox, runtime, display="xwayland"))


def test_linger_runs_the_command_under_the_supervisor_inside_the_xwayland_wrapper(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(runtimejail, "XWAYLAND_PATHS", ("/bin/sh",))
    plain = runtimejail.runtime_args(**build(sandbox, runtime))
    assert plain[plain.index("--") + 1:] == ["/app/AppRun"]
    args = runtimejail.runtime_args(**build(sandbox, runtime, linger=True))
    assert args[args.index("--") + 1:] == [linger.PYTHON, "-I", "-c", linger.SUPERVISOR, "/app/AppRun"]
    cmd = runtimejail.runtime_args(**build(sandbox, runtime, linger=True, display="xwayland"))
    cmd = cmd[cmd.index("--") + 1:]
    assert cmd[:2] == ["/bin/sh", "-c"] and cmd[8:11] == [linger.PYTHON, "-I", "-c"] and cmd[-1] == "/app/AppRun"
    monkeypatch.setattr(runtimejail, "OPENBOX_PATHS", ("/bin/true",))
    cmd = runtimejail.runtime_args(**build(sandbox, runtime, linger=True, display="xwayland-rootful"))
    cmd = cmd[cmd.index("--") + 1:]
    assert cmd[5:8] == ["rootful", "1280x800", "/bin/true"] and cmd[8:11] == [linger.PYTHON, "-I", "-c"]


def test_linger_without_python_is_an_error(sandbox, runtime, monkeypatch):
    monkeypatch.setattr(linger, "PYTHON", "/nonexistent/python3")
    with pytest.raises(RunError, match="python3"):
        runtimejail.runtime_args(**build(sandbox, runtime, linger=True))


DETACHING_APP = "#!/bin/sh\n(sleep 1; echo done > /home/app/out.txt) &\nexit 3\n"


@integration
@pytest.mark.parametrize("keep", [False, True])
def test_linger_keeps_the_jail_for_a_detached_child(sandbox, runtime, keep):
    """A launcher that starts the app detached and exits: the child dies with the jail unless `linger` is set, and then
    the jail ends only after it, with the launcher's exit status."""
    kw = build(sandbox, runtime, linger=keep)
    (kw["root"] / "AppRun").write_text(DETACHING_APP)
    (kw["root"] / "AppRun").chmod(0o755)
    fd = seccomp.open_fd(kw["perms"].userns)
    try:
        start = time.monotonic()
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd)], timeout=60, pass_fds=(fd,))
        took = time.monotonic() - start
    finally:
        os.close(fd)
    assert proc.returncode == 3, proc.stderr
    assert (kw["home"] / "out.txt").exists() is keep
    assert (took >= 1.0) is keep


@integration
@pytest.mark.parametrize("mode", ["rootless", "rootful"])
def test_linger_does_not_wait_for_the_xwayland_helper(sandbox, mode):
    x = sandbox / "fakeX"
    x.write_text("#!/bin/sh\nsleep 0.3; echo 7 >&3; sleep 300\n")  # the sleep is a child of the helper, as Xwayland's xkbcomp would be
    x.chmod(0o755)
    wm = sandbox / "fakeWM"  # the window manager of the rootful mode is one more helper
    wm.write_text("#!/bin/sh\nsleep 300\n")
    wm.chmod(0o755)
    command = ["/bin/sh", "-c", runtimejail.XWAYLAND_SCRIPT, "sh", "/run/fakeX", mode, "1280x800", "/run/fakeWM" if mode == "rootful" else "",
               *linger.wrap(["/bin/sh", "-c", "echo $DISPLAY"])]
    argv = [jail.find_bwrap(), "--unshare-user", "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--tmpfs", "/run", "--ro-bind", str(x), "/run/fakeX", "--ro-bind", str(wm), "/run/fakeWM", "--", *command]
    start = time.monotonic()
    proc = jail.supervise(argv, timeout=30)
    assert proc.returncode == 0 and proc.stdout.split() == [":7"], proc.stderr
    assert time.monotonic() - start < 10


def test_missing_or_hostile_wayland_socket(sandbox, runtime):
    kw = build(sandbox, runtime)
    kw["host_env"] = dict(kw["host_env"], WAYLAND_DISPLAY="nope")
    with pytest.raises(RunError, match="not found"):
        runtimejail.runtime_args(**kw)
    kw["host_env"] = dict(kw["host_env"], WAYLAND_DISPLAY="../x")
    with pytest.raises(RunError, match="no usable Wayland"):
        runtimejail.runtime_args(**kw)
    kw["host_env"] = {}
    with pytest.raises(RunError, match="no usable Wayland"):
        runtimejail.runtime_args(**kw)


# -- single files (run --file) -------------------------------------------------------------

def test_file_grants_read_only_by_default_and_rw_on_request(sandbox):
    home = sandbox / "fakehome"
    (home / "docs").mkdir(parents=True)
    ro, rw, outside = home / "docs" / "a.txt", home / "docs" / "b.txt", sandbox / "c.txt"
    for f in (ro, rw, outside):
        f.write_text("x")
    with runtimejail.Grants((), [str(ro), f"{rw}:rw", str(outside)], home) as opened:
        dests = [f"{runtimejail.APP_HOME}/docs/a.txt", f"{runtimejail.APP_HOME}/docs/b.txt", str(outside)]
        assert opened.file_dests == dests
        assert [(g.real, g.rw) for g in opened.items] == [(str(ro), False), (str(rw), True), (str(outside), False)]
        a, b, c = opened.fds
        assert pairs(opened.args(), "--ro-bind-fd") == [(str(a), dests[0]), (str(c), dests[2])]
        assert pairs(opened.args(), "--bind-fd") == [(str(b), dests[1])]


def test_file_grants_refuse_directories_missing_and_special_files(sandbox):
    (sandbox / "d").mkdir()
    for bad, msg in [(sandbox / "d", "not a regular file"), (sandbox / "nope", "does not exist"), (Path("/dev/null"), "not a regular file")]:
        with pytest.raises(RunError, match=msg):
            runtimejail.Grants((), [str(bad)], sandbox)


@pytest.mark.parametrize("rel,mode", [(".ssh/id_ed25519", ""), (".gnupg/pubring.kbx", ""), ("vault.kdbx", ""), (".bashrc", ":rw")])
def test_file_grants_apply_the_sensitive_path_policy(sandbox, rel, mode):
    home = sandbox / "fakehome"
    f = home / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    link = sandbox / "innocent.txt"
    link.symlink_to(f)
    for path in (f, link):  # a link must not dodge the policy
        with pytest.raises(RunError, match="refused"):
            runtimejail.Grants((), [f"{path}{mode}"], home)


def test_file_grants_refuse_appjails_own_data(sandbox):
    f = store.data_dir() / "x"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    with pytest.raises(RunError, match="own data"):
        runtimejail.Grants((), [str(f)], sandbox)


def test_launch_binds_files_and_passes_their_jail_paths_to_the_app(sandbox, runtime):
    install(sandbox)
    f = sandbox / "doc.txt"
    f.write_text("x")
    captured, said = [], []
    runner.launch("app", ["--x"], host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                  extract=Extractor(), say=said.append, runner=lambda argv: captured.append(argv) or 0,
                  extra_files=(str(f),), **COMPOSITOR)
    argv = captured[0]
    assert str(f) in [dest for _, dest in pairs(argv, "--ro-bind-fd")]
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
        with runtimejail.Grants((), [str(d / "in.txt")], Path.home()) as opened:
            args = runtimejail.runtime_args(**kw, seccomp_fd=fd, binds=opened.args())
            proc = jail.supervise([jail.find_bwrap(), *args], timeout=60, pass_fds=(fd, *opened.fds))
    finally:
        os.close(fd)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["hello", "False", "ro"]


APP_PROBE = '''#!/usr/bin/python3
import socket, sys, urllib.request
def reach(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close(); return True
    except OSError:
        return False
import os
port, own = int(sys.argv[1]), sys.argv[2]
urllib.request.urlopen("https://api.github.com/rate_limit", timeout=15).close()  # DNS and TLS work through the namespace; not counted against the limit
print(reach("127.0.0.1", port), reach(own, port), os.getuid() == int(sys.argv[3]) and os.getgid() == int(sys.argv[4]))
'''


@integration
@needs_pasta
@pytest.mark.parametrize("host_net, expected", [(False, ["False", "False", "True"]), (True, ["True", "True", "True"])])
def test_networked_app_cannot_reach_host_services_unless_network_host(sandbox, runtime, host_net, expected):
    srv = socket.socket()
    srv.bind(("0.0.0.0", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # picks the host's outbound address; nothing is sent
        own = s.getsockname()[0]
        s.close()
        kw = build(sandbox, runtime, network=True, network_host=host_net)
        (kw["root"] / "AppRun").write_text(APP_PROBE)
        (kw["root"] / "AppRun").chmod(0o755)
        kw["command"] = ["/app/AppRun", str(port), own, str(os.getuid()), str(os.getgid())]
        if host_net:
            fd = seccomp.open_fd(False)
            try:
                argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd)]
                proc = jail.supervise(argv, timeout=60, pass_fds=(fd,))
            finally:
                os.close(fd)
        else:
            filt = sandbox / "filter.bpf"
            filt.write_bytes(seccomp.program(False))
            argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=runner.PASTA_SECCOMP_FD)]
            argv = jail.net_wrap(argv, required=True, fd_files={runner.PASTA_SECCOMP_FD: str(filt)})
            assert argv[0] == jail.find_pasta()
            proc = jail.supervise(argv, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == expected
    finally:
        srv.close()


FILTER_PROBE = """#!/usr/bin/python3
import ctypes
r = ctypes.CDLL(None, use_errno=True).syscall(435, 0, 0)  # clone3: ENOSYS under the filter, EFAULT/EINVAL without it
print(ctypes.get_errno() if r == -1 else 0)
"""


@integration
@pytest.mark.parametrize("perms", [{}, {"network": True, "network_host": True}, {"network": True}],
                         ids=["offline", "network_host", "pasta"])
def test_launch_applies_the_seccomp_filter_in_every_network_mode(sandbox, runtime, monkeypatch, capfd, perms):
    """Through runner.launch itself, so the way the filter reaches bwrap (inherited memfd, or a file reopened
    inside pasta's namespace) is what is tested, not a hand-built copy of it."""
    if perms == {"network": True} and not jail.find_pasta():
        pytest.skip("pasta not installed (package passt)")
    kw = build(sandbox, runtime, **perms)
    (kw["root"] / "AppRun").write_text(FILTER_PROBE)
    (kw["root"] / "AppRun").chmod(0o755)
    m = manifest.Manifest("app", "github:o/a", "v1", SHA, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                          permissions=manifest.Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                         say=lambda *_: None, **COMPOSITOR)
    out = capfd.readouterr()
    assert code == 0, out.err
    assert out.out.split() == ["38"], out.err  # ENOSYS: the filter is installed


def test_net_wrap_reopens_files_inside_the_namespace(monkeypatch):
    monkeypatch.setattr(jail, "find_pasta", lambda: "/usr/bin/pasta")
    out = jail.net_wrap(["bwrap", "--seccomp", "9"], fd_files={9: "/run/f"})
    i = out.index("--") + 1
    assert out[i:i + 2] == ["/bin/sh", "-c"] and '9<"$p0"' in out[i + 2]
    assert out[i + 4:] == ["/run/f", "bwrap", "--seccomp", "9"]


def test_net_wrap_opens_fifos_for_the_portal_pipes(monkeypatch):
    monkeypatch.setattr(jail, "find_pasta", lambda: "/usr/bin/pasta")
    out = jail.net_wrap(["bwrap"], fd_files={9: "/f", 8: (">", "/s"), 7: ("<", "/b")})
    i = out.index("--") + 1
    assert out[i + 2].endswith('exec "$@" 9<"$p0" 8>"$p1" 7<"$p2"') and out[i + 4:i + 7] == ["/f", "/s", "/b"]
    with pytest.raises(RunError, match="single digit"):
        jail.net_wrap(["bwrap"], fd_files={10: "/f"})


def test_pipes_over_fifos_have_only_the_parents_ends(tmp_path):
    p = runner.Pipes(str(tmp_path))
    try:
        assert set(p.fds) == {"status_r", "block_w"} and set(p.paths) == {"status", "block"}
        os.write(p.fds["block_w"], b"x")  # read-write opens never block
    finally:
        p.close_all()


@integration
@pytest.mark.parametrize("fake, ok", [("exit 3", False), ("sleep 1.5; echo 7 >&3; sleep 30", True)], ids=["exits-at-once", "starts-slowly"])
def test_xwayland_script_waits_for_a_slow_start_but_not_for_a_dead_one(sandbox, fake, ok):
    x = sandbox / "fakeX"
    x.write_text(f"#!/bin/sh\n{fake}\n")
    x.chmod(0o755)
    argv = [jail.find_bwrap(), "--unshare-user", "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run", "--ro-bind", str(x), "/run/fakeX",
            "--", "/bin/sh", "-c", runtimejail.XWAYLAND_SCRIPT, "sh", "/run/fakeX", "rootless", "1280x800", "", "/bin/sh", "-c", "echo $DISPLAY"]
    start = time.monotonic()
    proc = jail.supervise(argv, timeout=30)
    if ok:
        assert proc.returncode == 0 and proc.stdout.split() == [":7"], proc.stderr
    else:
        assert proc.returncode == 1 and "did not start" in proc.stderr
        assert time.monotonic() - start < 5  # it does not sit out the whole wait


PASTA_PROBE = """#!/usr/bin/python3
import ctypes, socket, sys, urllib.request
urllib.request.urlopen("https://api.github.com/rate_limit", timeout=15).close()  # not counted against the limit
r = ctypes.CDLL(None, use_errno=True).unshare(0x10000000)  # CLONE_NEWUSER: allowed only with the userns permission
errno_ = ctypes.get_errno() if r == -1 else 0
v6 = "none"
if len(sys.argv) > 1:
    try:
        ai = socket.getaddrinfo("api.github.com", 443, socket.AF_INET6, socket.SOCK_STREAM)
        socket.create_connection(ai[0][4][:2], timeout=5).close()
        v6 = "ok"
    except OSError:
        v6 = "fail"
print(errno_, v6)
"""


def _launch_pasta_probe(sandbox, runtime, monkeypatch, capfd, args=(), **perms):
    kw = build(sandbox, runtime, network=True, **perms)
    (kw["root"] / "AppRun").write_text(PASTA_PROBE)
    (kw["root"] / "AppRun").chmod(0o755)
    m = manifest.Manifest("app", "github:o/a", "v1", SHA, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                          permissions=manifest.Permissions(network=True, **perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                         say=lambda *_: None, **COMPOSITOR, extra_args=list(args))
    out = capfd.readouterr()
    assert code == 0, out.err
    return out.out.split()


@integration
@needs_pasta
@pytest.mark.parametrize("userns", [False, True])
def test_network_with_userns_under_pasta(sandbox, runtime, monkeypatch, capfd, userns):
    """Connectivity works in both cases; nested user namespaces are denied (EPERM=1) unless `userns` is granted."""
    errno_, _ = _launch_pasta_probe(sandbox, runtime, monkeypatch, capfd, userns=userns)
    assert errno_ == ("0" if userns else "1")


@integration
@needs_pasta
def test_linger_under_pasta_waits_for_the_detached_child(sandbox, runtime, monkeypatch):
    kw = build(sandbox, runtime, network=True, linger=True)
    (kw["root"] / "AppRun").write_text(DETACHING_APP)
    (kw["root"] / "AppRun").chmod(0o755)
    m = manifest.Manifest("app", "github:o/a", "v1", SHA, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                          permissions=manifest.Permissions(network=True, linger=True))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                         say=lambda *_: None, **COMPOSITOR)
    assert code == 3
    assert (kw["home"] / "out.txt").read_text() == "done\n"


@integration
@needs_pasta
def test_ipv6_under_pasta_matches_the_hosts_reachability(sandbox, runtime, monkeypatch, capfd):
    try:
        ai = socket.getaddrinfo("api.github.com", 443, socket.AF_INET6, socket.SOCK_STREAM)
        socket.create_connection(ai[0][4][:2], timeout=5).close()
    except OSError:
        pytest.skip("the host has no working IPv6 route")
    _, v6 = _launch_pasta_probe(sandbox, runtime, monkeypatch, capfd, args=["v6"])
    assert v6 == "ok"


# IPv6 without a real route: the test re-runs itself in a throwaway user and network namespace that has a dummy interface
# with a ULA address and an IPv6 default route (so pasta sees a usable IPv6 setup and copies it into the jail), plus a
# second dummy interface that holds the listener's address. pasta copies only the addresses of the interface that
# carries the default route, so the listener is not local to the jail: reaching it takes pasta's forwarding.
FAKE_V6_SETUP = """set -e
ip link set lo up
ip link add d0 type dummy; ip link set d0 up
ip link add d1 type dummy; ip link set d1 up
ip addr add 10.9.0.2/24 dev d0; ip route add default via 10.9.0.1 dev d0 onlink
ip addr add fd00::2/64 dev d0 nodad; ip -6 route add default via fd00::1 dev d0 onlink
ip addr add fd01::7/64 dev d1 nodad
exec "$@"
"""
V6_LISTENER = "fd01::7"
V6_PROBE = """#!/usr/bin/python3
import socket, sys, time
err = None
for _ in range(20):  # the router advertisement may arrive a moment after the jail starts
    try:
        socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3).close()
        print("ok"); break
    except OSError as e:
        err = e; time.sleep(0.25)
else:
    print("fail", err)
"""


@integration
@needs_pasta
@pytest.mark.skipif(not os.environ.get("APPJAIL_FAKE_V6"), reason="runs inside the namespace made by the test below")
def test_ipv6_forwarding_inside_the_fake_namespace(sandbox, runtime, monkeypatch, capfd):
    srv = socket.socket(socket.AF_INET6)
    srv.bind((V6_LISTENER, 0))
    srv.listen(5)
    try:
        kw = build(sandbox, runtime, network=True)
        (kw["root"] / "AppRun").write_text(V6_PROBE)
        (kw["root"] / "AppRun").chmod(0o755)
        m = manifest.Manifest("app", "github:o/a", "v1", SHA, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage",
                              permissions=manifest.Permissions(network=True))
        monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
        code = runner.launch("app", host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                             say=lambda *_: None, **COMPOSITOR,
                             extra_args=[V6_LISTENER, str(srv.getsockname()[1])])
        out = capfd.readouterr()
        assert code == 0, out.err
        assert out.out.split() == ["ok"], out.out
    finally:
        srv.close()


@integration
@needs_pasta
@pytest.mark.skipif(bool(os.environ.get("APPJAIL_FAKE_V6")), reason="already inside the fake namespace")
@pytest.mark.skipif(not shutil.which("unshare") or not shutil.which("ip"), reason="needs unshare and ip (iproute2)")
def test_ipv6_is_brought_up_and_forwarded_by_pasta_in_a_fake_network(tmp_path):
    here = Path(__file__).resolve()
    # the user maps to itself (not to root) with its capabilities kept: pasta and bwrap then behave as on a host, whereas
    # under `unshare -r` pasta cannot write its uid map and leaves the jail without a usable user namespace
    cmd = ["unshare", "-Un", f"--map-user={os.getuid()}", f"--map-group={os.getgid()}", "--keep-caps", "sh", "-c", FAKE_V6_SETUP, "sh", sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           f"{here}::test_ipv6_forwarding_inside_the_fake_namespace"]
    proc = subprocess.run(cmd, env={**os.environ, "APPJAIL_FAKE_V6": "1", "APPJAIL_INTEGRATION": "1"},
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 and "unshare" in proc.stderr and "failed" not in proc.stdout:
        pytest.skip("cannot create a user and network namespace: " + proc.stderr.strip())
    assert proc.returncode == 0, proc.stdout + proc.stderr


KILL_DRIVER = """
import sys
from appjail import jail, runner
argv = [jail.find_bwrap(), "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "sleep", sys.argv[1]]
if sys.argv[2] == "pasta":
    life = jail.Lifeline()
    argv = jail.net_wrap(argv, required=True, lifeline=life.path)
sys.exit(runner._run_app(argv))
"""


def _alive(marker):
    return subprocess.run(["pgrep", "-f", f"sleep {marker}$"], capture_output=True).returncode == 0


@integration
@pytest.mark.parametrize("mode", ["plain", "pasta"])
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGKILL"])
def test_terminating_the_launcher_stops_the_whole_jail(tmp_path, mode, sig):
    """Killing pasta alone leaves the jail running; the launcher must take the whole group down. SIGKILL cannot be
    handled, so behind pasta the watcher inside the namespace (jail.Lifeline) must notice the launcher's death."""
    import signal
    if mode == "pasta" and not jail.find_pasta():
        pytest.skip("pasta not installed (package passt)")
    marker = str(30000 + os.getpid() % 10000)
    driver = tmp_path / "driver.py"
    driver.write_text(KILL_DRIVER)
    proc = subprocess.Popen([sys.executable, str(driver), marker, mode],
                            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(runner.__file__).parent.parent)})
    try:
        wait_for(lambda: _alive(marker), 10.0)
        assert _alive(marker), "the jail did not start"
        proc.send_signal(getattr(signal, sig))
        proc.wait(timeout=15)
        wait_for(lambda: not _alive(marker), 8.0)
        assert not _alive(marker), "the jail outlived its launcher"
    finally:
        proc.kill()
        subprocess.run(["pkill", "-f", f"sleep {marker}$"], capture_output=True)


def test_display_none_has_no_wayland_socket_and_no_toolkit_hints(sandbox, runtime):
    args = runtimejail.runtime_args(**build(sandbox, runtime, display="none"), wayland_socket=None)
    env = {k: v for k, v in pairs(args, "--setenv")}
    assert not any("/wayland-0" in a for a in args)
    assert not any(k in env for k in ("WAYLAND_DISPLAY", "DISPLAY", "GDK_BACKEND", "QT_QPA_PLATFORM", "SDL_VIDEODRIVER",
                                      "MOZ_ENABLE_WAYLAND", "ELECTRON_OZONE_PLATFORM_HINT"))
    assert env["HOME"] == "/home/app" and args[args.index("--") + 1:] == ["/app/AppRun"]


def test_display_none_does_not_ask_the_compositor_for_a_socket(sandbox, runtime):
    install(sandbox, display="none")
    asked = []

    def restricted(env, app_id=None):
        asked.append(app_id)
        return RESTRICTED(env, app_id)

    says = []
    runner.launch("app", [], host_env={"XDG_RUNTIME_DIR": str(runtime)}, extract=Extractor(), say=says.append,
                  runner=lambda argv: 0, restricted=restricted)
    assert asked == [] and not any("Wayland" in s for s in says)


@integration
def test_display_none_jail_really_has_no_wayland_socket(sandbox, runtime):
    """The host socket exists in the runtime directory; a headless app must not find it, or any display variable."""
    kw = build(sandbox, runtime, display="none")
    (kw["root"] / "AppRun").write_text('#!/bin/sh\nls "$XDG_RUNTIME_DIR" > /home/app/ls.txt\nenv > /home/app/env.txt\n')
    (kw["root"] / "AppRun").chmod(0o755)
    fd = seccomp.open_fd(kw["perms"].userns)
    try:
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw, seccomp_fd=fd)], timeout=60, pass_fds=(fd,))
    finally:
        os.close(fd)
    assert proc.returncode == 0, proc.stderr
    assert "wayland" not in (kw["home"] / "ls.txt").read_text()
    assert "WAYLAND_DISPLAY" not in (kw["home"] / "env.txt").read_text()


# -- what the app's Wayland socket lets a client do ------------------------------------------------

QUIET = {"wl_compositor", "xdg_wm_base", "wl_seat", "zwp_keyboard_shortcuts_inhibit_manager_v1"}  # GNOME's extra global
CAPTURE = QUIET | {"zwlr_screencopy_manager_v1"}
CLIPBOARD = QUIET | {"ext_data_control_manager_v1"}  # what KWin's restricted socket still lists


def launch_windowed(sandbox, runtime, restricted, offered, **perms):
    install(sandbox, **perms)
    ran, says = [], []
    code = None
    try:
        code = runner.launch("app", [], host_env={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-test"},
                             extract=Extractor(), say=says.append, warn=says.append, runner=lambda argv: ran.append(argv) or 0,
                             restricted=restricted, registry=lambda env, path: offered)
    except RunError as e:
        says.append(str(e))
    return code, ran, says


def test_a_socket_listing_nothing_privileged_runs_the_app_with_or_without_the_protocol(sandbox, runtime):
    for restricted in (NO_RESTRICTION, RESTRICTED):  # GNOME has no protocol and nothing privileged; sway has both
        code, ran, says = launch_windowed(sandbox, runtime, restricted, QUIET)
        assert code == 0 and len(ran) == 1 and not any("full_wayland" in s for s in says)


def test_the_compositors_own_socket_with_privileged_globals_refuses_the_app_by_default(sandbox, runtime):
    code, ran, says = launch_windowed(sandbox, runtime, NO_RESTRICTION, CAPTURE)
    assert code is None and ran == []  # nothing was started
    assert any("wp_security_context_v1" in s and "zwlr_screencopy_manager_v1" in s and "capture the screen" in s
               and "appjail perms app --allow full_wayland" in s for s in says)


def test_a_restricted_socket_that_still_lists_the_clipboard_is_refused_and_says_so(sandbox, runtime):
    code, ran, says = launch_windowed(sandbox, runtime, RESTRICTED, CLIPBOARD)  # KWin
    assert code is None and ran == []
    assert any("restricted Wayland socket" in s and "ext_data_control_manager_v1" in s and "clipboard" in s for s in says)


def test_full_wayland_lets_the_app_run_with_a_warning_naming_what_is_listed(sandbox, runtime):
    code, ran, says = launch_windowed(sandbox, runtime, NO_RESTRICTION, CAPTURE, full_wayland=True)
    assert code == 0 and len(ran) == 1
    assert any("zwlr_screencopy_manager_v1" in s and "full_wayland is granted" in s for s in says)
    assert (str(runtime / "wayland-test"), f"/run/user/{os.getuid()}/wayland-0") in pairs(ran[0], "--ro-bind")


def test_full_wayland_changes_nothing_on_a_socket_that_lists_nothing(sandbox, runtime):
    code, _, says = launch_windowed(sandbox, runtime, RESTRICTED, QUIET, full_wayland=True)
    assert code == 0 and not any("full_wayland" in s for s in says)


@pytest.mark.parametrize("display", ["xwayland", "xwayland-rootful"])
def test_x11_apps_are_refused_too_because_xwayland_is_a_client_of_the_same_socket(sandbox, runtime, display):
    _, ran, says = launch_windowed(sandbox, runtime, NO_RESTRICTION, CAPTURE, display=display)
    assert ran == [] and any("full_wayland" in s for s in says)


def test_a_headless_app_needs_no_wayland_socket_and_is_not_checked(sandbox, runtime):
    code, _, says = launch_windowed(sandbox, runtime, NO_RESTRICTION, CAPTURE, display="none")
    assert code == 0 and not any("full_wayland" in s for s in says)
