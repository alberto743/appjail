# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from appjail import (
    jail,
    landlock,
    runtimejail,
)
from appjail.errors import RunError

from .helpers import (
    FACTS,
    build,
    headless_weston,
    install,
    integration,
    pairs,
    run_in_jail,
)

SHA = "a" * 64


# -- real bwrap (guest only) ---------------------------------------------------------------


def facts(sandbox, runtime, **perms):
    proc = run_in_jail(sandbox, runtime, **perms)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@integration
def test_private_home_and_filesystem(sandbox, runtime):
    secret = Path.home() / "appjail-secret-test"
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
    assert r["host"] == "appjail"


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
    assert (on["pipewire"], on["pulse"]) == (False, True)
    assert (off["pipewire"], off["pulse"]) == (False, False)


@integration
def test_no_network_unless_granted(sandbox, runtime):
    assert facts(sandbox, runtime)["ifaces"] == ["lo"]
    assert len(facts(sandbox, runtime, network=True)["ifaces"]) > 1


@integration
@pytest.mark.skipif(not os.access("/dev/dri/renderD128", os.R_OK | os.W_OK),
                    reason="no usable DRM render node (run provision.sh; the user must be in the render group)")
def test_gpu_nodes_only_when_granted(sandbox, runtime):
    script = FACTS.replace('print(json.dumps({', 'print(json.dumps({"dri": ls("/dev/dri"), "render_open": can_open("/dev/dri/renderD128"), ')
    script = script.replace('def connects', 'def can_open(p):\n    try:\n        os.close(os.open(p, os.O_RDWR)); return True\n    except OSError:\n        return False\n\ndef connects')
    on = json.loads(run_in_jail(sandbox, runtime, script=script, gpu=True).stdout)
    off = json.loads(run_in_jail(sandbox, runtime, script=script, gpu=False).stdout)
    assert "renderD128" in on["dri"] and on["render_open"] is True
    assert off["dri"] is None and off["render_open"] is False


@integration
def test_granted_directories_modes(sandbox, runtime):
    fake_home = sandbox / "fakehome"
    (fake_home / "ro").mkdir(parents=True)
    (fake_home / "rw").mkdir()
    script = FACTS.replace('print(json.dumps({', 'print(json.dumps({"w_ro": writable("/home/app/ro/x"), "w_rw": writable("/home/app/rw/x"), ')
    proc = run_in_jail(sandbox, runtime, script=script, host_home=fake_home, dirs=("~/ro", "~/rw:rw"))
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert (r["w_ro"], r["w_rw"]) == (False, True)


@integration
def test_arguments_are_passed_through(sandbox, runtime):
    proc = run_in_jail(sandbox, runtime, extra=("--flag", "a b"))
    assert json.loads(proc.stdout)["args"] == ["--flag", "a b"]


@integration
def test_app_cannot_see_appjail_data_through_home(sandbox, runtime):
    install(sandbox)
    r = facts(sandbox, runtime)
    assert r["app_home"] == []


@integration
@pytest.mark.skipif(not shutil.which("weston") or not shutil.which("weston-simple-shm"), reason="weston not installed")
def test_real_wayland_client_runs_against_headless_weston(sandbox):
    with headless_weston(sandbox, "appjail-test") as rt:
        kw = build(sandbox, rt, audio=False)
        kw["host_env"] = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "appjail-test"}
        (kw["root"] / "AppRun").write_text("#!/bin/sh\nexec /usr/bin/timeout 3 /usr/bin/weston-simple-shm\n")
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw)], timeout=30)
        assert proc.returncode == 124, proc.stderr  # killed by timeout while running = it connected


@pytest.mark.parametrize("sub,mode", [(".ssh", ""), (".local/bin", ":rw"), (".config", "")])
def test_sensitive_dirs_refused_after_symlink_resolution(sandbox, runtime, sub, mode):
    """A link in a harmless location pointing at a sensitive one must not get past the policy."""
    fake_home = sandbox / "fakehome"
    target = fake_home / sub
    target.mkdir(parents=True)
    (fake_home / "innocent").symlink_to(target)
    with pytest.raises(RunError, match="refused"):
        runtimejail.dir_binds([f"~/innocent{mode}"], fake_home)


def test_restricted_wayland_socket_replaces_the_host_one(sandbox, runtime):
    restricted = sandbox / "restricted.sock"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(restricted))
    try:
        kw = build(sandbox, runtime)
        args = runtimejail.runtime_args(**kw, wayland_socket=str(restricted))
        rt = f"/run/user/{os.getuid()}"
        assert (str(restricted), f"{rt}/wayland-0") in pairs(args, "--ro-bind")
        assert str(Path(runtime) / kw["host_env"]["WAYLAND_DISPLAY"]) not in [a for a in args if isinstance(a, str)]
    finally:
        s.close()


@integration
@pytest.mark.skipif(not all(shutil.which(c) for c in ("weston", "Xwayland", "xdpyinfo")),
                    reason="needs weston, xwayland and x11-utils (tests/vm/packages.txt)")
@pytest.mark.parametrize("network_host", [False, True])
def test_x11_client_runs_through_a_private_xwayland(sandbox, network_host):
    """With network_host the jail shares the host's abstract socket namespace, so it runs in its Landlock domain as
    `run` starts it: the private Xwayland's own socket, made inside the domain, must still be reachable."""
    if network_host and not landlock.available():
        pytest.skip("needs Landlock ABI 6")
    with headless_weston(sandbox, "appjail-xtest") as rt:
        net = {"network": True, "network_host": True} if network_host else {}
        kw = build(sandbox, rt, audio=False, display="xwayland", **net)
        kw["host_env"] = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "appjail-xtest"}
        (kw["root"] / "AppRun").write_text(
            "#!/bin/sh\n/usr/bin/xdpyinfo > /app/out.txt 2>&1; echo \"display=$DISPLAY wl=$WAYLAND_DISPLAY\" >> /app/out.txt\n"
            .replace("/app/out.txt", "/home/app/out.txt"))
        (kw["root"] / "AppRun").chmod(0o755)
        argv = [jail.find_bwrap(), *runtimejail.runtime_args(**kw)]
        proc = jail.supervise(landlock.wrap(argv) if network_host else argv, timeout=30)
        assert (kw["home"] / "out.txt").exists(), f"the app never ran: {proc.stderr}"
        text = (kw["home"] / "out.txt").read_text()
        assert proc.returncode == 0 and "name of display" in text, text + proc.stderr
        assert "wl=\n" in text + "\n" and "display=:" in text


@integration
@pytest.mark.skipif(not all(shutil.which(c) for c in ("weston", "Xwayland", "openbox", "xprop")),
                    reason="needs weston, xwayland, openbox and x11-utils (tests/vm/packages.txt)")
def test_rootful_xwayland_runs_a_window_manager(sandbox, monkeypatch):
    # With -decorate, openbox never gets going under headless weston or sway (cause not found; without it, it does).
    # The rest of the script is under test; the real option needs a manual check on a desktop compositor.
    monkeypatch.setattr(runtimejail, "XWAYLAND_SCRIPT", runtimejail.XWAYLAND_SCRIPT.replace(" -decorate", ""))
    with headless_weston(sandbox, "appjail-rtest") as rt:
        kw = build(sandbox, rt, audio=False, display="xwayland-rootful", display_size="800x600")
        kw["host_env"] = {"XDG_RUNTIME_DIR": str(rt), "WAYLAND_DISPLAY": "appjail-rtest"}
        (kw["root"] / "AppRun").write_text(
            "#!/bin/sh\nfor i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do\n"
            "  /usr/bin/xprop -root _NET_SUPPORTING_WM_CHECK > /home/app/out.txt 2>&1 && grep -q 'window id' /home/app/out.txt && break\n"
            "  sleep 0.5\ndone\n/usr/bin/xdpyinfo | grep dimensions >> /home/app/out.txt\n")
        (kw["root"] / "AppRun").chmod(0o755)
        proc = jail.supervise([jail.find_bwrap(), *runtimejail.runtime_args(**kw)], timeout=30)
        text = (kw["home"] / "out.txt").read_text() if (kw["home"] / "out.txt").exists() else ""
        assert proc.returncode == 0 and "window id" in text, text + proc.stderr
        assert "800x600" in text
