# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bjail import dbusproxy, jail, manifest, portal, runner
from bjail.jail import RunError
from bjail.manifest import Manifest, ManifestError, Permissions

from . import test_runner
from .test_dbus import needs_proxy
from .test_runner import build, integration, pairs, runtime, sandbox  # noqa: F401

HERE = Path(__file__).parent / "portal"

# -- identity -----------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("lagrange", "app.bjail.lagrange"),
    ("my-app", "app.bjail.my_app"),
    ("a.b-c", "app.bjail.a.b_c"),
    ("7zip", "app.bjail.x7zip"),
    ("a..b", "app.bjail.a.b"),
])
def test_app_id(name, expected):
    assert portal.app_id(name) == expected and portal.APP_ID_RE.fullmatch(expected)


def test_identity_file_is_minimal():
    text = portal.identity_file("app.bjail.x", "123")
    assert text.splitlines()[:2] == ["[Application]", "name=app.bjail.x"]
    assert "instance-id=123" in text and "network" not in text
    assert "shared=network;" in portal.identity_file("app.bjail.x", "123", network=True)
    assert "/home" not in text and "runtime" not in text.lower()


def test_instance_lifecycle(tmp_path):
    with portal.Instance(tmp_path, "app.bjail.x") as inst:
        assert inst.dir.parent == tmp_path / ".flatpak" and (inst.dir.stat().st_mode & 0o777) == 0o700
        assert f"instance-id={inst.id}" in inst.info.read_text()
        assert not (inst.dir / "bwrapinfo.json").exists()
        inst.child_started(4242)
        assert json.loads((inst.dir / "bwrapinfo.json").read_text()) == {"child-pid": 4242}
    assert not (tmp_path / ".flatpak").exists()


def test_instances_do_not_collide(tmp_path):
    with portal.Instance(tmp_path, "app.bjail.x") as a, portal.Instance(tmp_path, "app.bjail.x") as b:
        assert a.id != b.id and a.dir != b.dir


# -- policy -------------------------------------------------------------------------------


def test_no_portals_means_no_interfaces_and_no_rules():
    assert portal.interfaces(Permissions()) == () and portal.proxy_rules(Permissions()) == []


def test_safe_set_and_opt_ins():
    p = Permissions(portals=True)
    assert portal.interfaces(p) == manifest.PORTAL_SAFE
    p = Permissions(portals=True, portal_interfaces=("OpenURI",))
    assert "OpenURI" in portal.interfaces(p) and "Screenshot" not in portal.interfaces(p)
    rules = portal.proxy_rules(p)
    assert "--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.OpenURI.*@/org/freedesktop/portal/desktop" in rules
    assert not any("Flatpak" in r or "DynamicLauncher" in r or "Screenshot" in r for r in rules)
    assert "--talk=org.freedesktop.portal.Documents" in rules


@pytest.mark.parametrize("name", ["Flatpak", "DynamicLauncher", "Nonsense", "openuri", ""])
def test_never_and_unknown_interfaces_are_refused(name):
    with pytest.raises(ManifestError):
        manifest.check_portal_interface(name)


def test_manifest_round_trip_and_consistency():
    m = Manifest("a", "o/a", "*.AppImage", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z",
                 permissions=Permissions(portals=True, portal_interfaces=("OpenURI", "Screenshot")))
    assert manifest.loads(manifest.dumps(m)).permissions.portal_interfaces == ("OpenURI", "Screenshot")
    bad = Manifest("a", "o/a", "*.AppImage", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z",
                   permissions=Permissions(portal_interfaces=("OpenURI",)))
    with pytest.raises(ManifestError, match="needs portals"):
        manifest.dumps(bad)
    text = manifest.dumps(m)
    with pytest.raises(ManifestError):
        manifest.loads(text.replace('"OpenURI"', '"Flatpak"'))
    with pytest.raises(ManifestError, match="needs portals"):
        manifest.loads(text.replace("portals = true", "portals = false"))


# -- proxy and jail arguments ---------------------------------------------------------------


def test_identity_is_bound_into_the_proxy_jail_only(sandbox, runtime, tmp_path):
    info = tmp_path / "info"
    info.write_text("x")
    perms = Permissions(portals=True)
    args = dbusproxy.proxy_args("/run/user/1/bus", tmp_path, perms, 7, identity=info)
    assert (str(info), "/.flatpak-info") in pairs(args, "--ro-bind")
    assert "--filter" in args and any(a.startswith("--call=org.freedesktop.portal.Desktop=") for a in args)
    app = jail.runtime_args(**build(sandbox, runtime, portals=True), dbus_socket="/x/bus", portal_docs=sandbox)
    assert "/.flatpak-info" not in [a for a in app if isinstance(a, str)]
    assert (str(sandbox), f"/run/user/{os.getuid()}/doc") in pairs(app, "--bind")
    assert dict(pairs(app, "--setenv"))["GTK_USE_PORTAL"] == "1"


def test_portals_need_the_proxy_and_the_document_directory(sandbox, runtime):
    with pytest.raises(RunError, match="filtered bus socket"):
        jail.runtime_args(**build(sandbox, runtime, portals=True))
    with pytest.raises(RunError, match="document portal"):
        jail.runtime_args(**build(sandbox, runtime, portals=True), dbus_socket="/x/bus")


def test_status_and_block_fds_are_passed_to_bwrap(sandbox, runtime):
    args = jail.runtime_args(**build(sandbox, runtime), status_fd=11, block_fd=12)
    assert args[args.index("--json-status-fd") + 1] == "11" and args[args.index("--block-fd") + 1] == "12"


def test_missing_document_portal_is_a_clear_error(tmp_path):
    with pytest.raises(RunError, match="document portal is not running"):
        portal.doc_dir(tmp_path, "app.bjail.x")


# -- the real portal (guest) -------------------------------------------------------------------

needs_portal = pytest.mark.skipif(
    not (Path("/usr/libexec/xdg-desktop-portal").exists() and Path("/usr/libexec/xdg-document-portal").exists()
         and shutil.which("fusermount3") and os.access("/dev/fuse", os.R_OK | os.W_OK)),
    reason="needs xdg-desktop-portal, its document portal and FUSE (run provision.sh)")


@pytest.fixture
def portal_stack(sandbox, runtime):
    """A private session bus with the real xdg-desktop-portal and document portal and a fake file chooser."""
    share = sandbox / "share"
    (share / "xdg-desktop-portal" / "portals").mkdir(parents=True)
    (share / "xdg-desktop-portal" / "portals" / "fake.portal").write_text(
        "[portal]\nDBusName=org.freedesktop.impl.portal.desktop.fake\n"
        "Interfaces=org.freedesktop.impl.portal.FileChooser\nUseIn=fake\n")
    cfg = sandbox / "cfg"
    (cfg / "xdg-desktop-portal").mkdir(parents=True)
    (cfg / "xdg-desktop-portal" / "portals.conf").write_text("[preferred]\ndefault=fake\n")
    chosen = sandbox / "chosen.txt"
    chosen.write_text("hello from the host")
    log = sandbox / "backend.log"
    env = {"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime), "XDG_DATA_DIRS": f"{share}:/usr/share",
           "XDG_CONFIG_HOME": str(cfg), "XDG_CURRENT_DESKTOP": "fake", "HOME": str(sandbox),
           "XDG_DATA_HOME": str(sandbox / "data")}
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1",
                               f"--address=unix:path={runtime}/bus"], stdout=subprocess.PIPE, text=True, env=env)
    daemon.stdout.readline()
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
    backend = subprocess.Popen([sys.executable, str(HERE / "fake_backend.py"), str(log), str(chosen)],
                               stdout=subprocess.PIPE, text=True, env=env)
    assert backend.stdout.readline().strip() == "ready"
    yield env, log
    backend.terminate()
    backend.wait()
    daemon.terminate()
    daemon.wait()
    subprocess.run(["fusermount3", "-u", "-z", str(runtime / "doc")], capture_output=True)


def app_root(sandbox, runtime, perms):
    kw = build(sandbox, runtime, **perms)
    (kw["root"] / "AppRun").write_text("#!/usr/bin/python3\n" + (HERE / "client.py").read_text())
    (kw["root"] / "AppRun").chmod(0o755)
    return kw


@integration
@needs_proxy
@needs_portal
def test_file_chooser_through_the_real_portal(sandbox, runtime, portal_stack, monkeypatch, capfd):
    env, log = portal_stack
    perms = {"portals": True}
    kw = app_root(sandbox, runtime, perms)
    m = Manifest("app", "o/a", "*.AppImage", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, restricted=test_runner.NO_RESTRICTION)
    out = capfd.readouterr()
    assert code == 0, out.err
    r = json.loads(out.out.strip().splitlines()[-1])
    assert log.read_text().split() == ["app.bjail.app"]  # the portal knew who called, from our identity only
    assert r["response"] == 0 and r["uris"][0].startswith(f"file://{runtime}/doc/")
    assert r["content"] == "hello from the host"  # read through the document-portal mount in the jail
    assert r["flatpak_info"] is False
    assert "AccessDenied" in r["OpenURI"]  # not in the safe set: the proxy refuses it
    assert "AccessDenied" in r["host_control"] and "ServiceUnknown" in r["Flatpak"]
    assert not (runtime / ".flatpak").exists()
    assert [p for p in runtime.iterdir() if p.name.startswith("bjail-")] == []


@integration
@needs_proxy
@needs_portal
def test_opt_in_interface_reaches_the_portal(sandbox, runtime, portal_stack, monkeypatch, capfd):
    env, _ = portal_stack
    perms = {"portals": True, "portal_interfaces": ("OpenURI",)}
    kw = app_root(sandbox, runtime, perms)
    m = Manifest("app", "o/a", "*.AppImage", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    assert runner.launch("app", host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, restricted=test_runner.NO_RESTRICTION) == 0
    r = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert "AccessDenied" not in r["OpenURI"]  # allowed through; the fake desktop has no OpenURI backend


@integration
@needs_proxy
@needs_portal
@pytest.mark.skipif(not jail.find_pasta(), reason="pasta not installed (package passt)")
@pytest.mark.parametrize("host_net", [False, True])
def test_portals_work_for_an_app_in_the_pasta_namespace(sandbox, runtime, portal_stack, monkeypatch, capfd, host_net):
    env, log = portal_stack
    perms = {"portals": True, "network": True, "network_host": host_net}  # without network_host the app runs behind pasta
    kw = app_root(sandbox, runtime, perms)
    m = Manifest("app", "o/a", "*.AppImage", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", permissions=Permissions(**perms))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: (m, kw["root"], kw["home"], kw["etc_dir"]))
    code = runner.launch("app", host_env=env | {"WAYLAND_DISPLAY": "wayland-test"}, restricted=test_runner.NO_RESTRICTION)
    out = capfd.readouterr()
    assert code == 0, out.err
    r = json.loads(out.out.strip().splitlines()[-1])
    assert log.read_text().split() == ["app.bjail.app"] and r["response"] == 0
    assert [p for p in runtime.iterdir() if p.name.startswith("bjail-")] == []
