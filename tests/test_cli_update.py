# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from bjail import appimage, cli, github, manifest, store, updater
from bjail.cli import Abort

from .test_cli_add import FAKE_APPIMAGE, SHA, FakeClient, Harness, Script, asset, h, info, release  # noqa: F401

NEW_IMAGE = FAKE_APPIMAGE + b"-v2"
NEW_SHA = hashlib.sha256(NEW_IMAGE).hexdigest()
T0 = datetime(2026, 10, 17, tzinfo=timezone.utc)


def release2(sha=NEW_SHA, tag="v2.0", published="2026-10-10T00:00:00Z", name="App-2.0-x86_64.AppImage", size=len(NEW_IMAGE)):
    a = github.Asset(name, size, sha, f"https://github.com/o/App/releases/download/{tag}/{name}")
    return github.Release(tag, published, False, f"https://github.com/o/App/releases/tag/{tag}", (a,))


def installed(h, **kw):  # noqa: F811
    h.add(**kw)
    return store.manifest_path("app")


def update(h, client, answers=("y",), days=7, now=T0, app="app", extra=(), download=None, extract=None,
           extract_ok=lambda: True):
    console = Script(answers)
    args = cli.build_parser().parse_args(["update", *([app] if app else []), "--quarantine", str(days), *extra])
    code = cli.cmd_update(args, client, console, download=download or h.download(NEW_IMAGE), now=now,
                          extract=extract or h.extract, extract_ok=extract_ok)
    return code, console


def test_up_to_date_downloads_nothing(h):  # noqa: F811
    installed(h)
    code, c = update(h, FakeClient(release_=release(asset())))
    assert code == 0 and "up to date" in c.text
    assert len(h.downloads) == 1  # only the original add


def test_new_release_waits_out_the_quarantine_without_downloading(h):  # noqa: F811
    path = installed(h)
    before = path.read_text()
    code, c = update(h, FakeClient(release_=release2()))
    assert code == 0 and "quarantine" in c.text and "2026-10-24T00:00:00Z" in c.text
    assert len(h.downloads) == 1 and path.read_text() == before
    assert updater.load_pending("app")["tag"] == "v2.0"


def test_first_seen_clock_is_kept_across_runs_and_resets_for_a_different_candidate(h):  # noqa: F811
    installed(h)
    update(h, FakeClient(release_=release2()))
    update(h, FakeClient(release_=release2()), now=T0 + timedelta(days=3))
    assert updater.load_pending("app")["first_seen"] == "2026-10-17T00:00:00Z"
    other = hashlib.sha256(b"other").hexdigest()
    update(h, FakeClient(release_=release2(sha=other)), now=T0 + timedelta(days=3))
    assert updater.load_pending("app")["first_seen"] == "2026-10-20T00:00:00Z"


def test_update_after_quarantine(h):  # noqa: F811
    path = installed(h)
    update(h, FakeClient(release_=release2()))
    code, c = update(h, FakeClient(release_=release2()), now=T0 + timedelta(days=7))
    assert code == 0 and "updated app: v1.0 -> v2.0" in c.text
    m = manifest.load(path)
    assert (m.version, m.sha256, m.evidence_tier, m.owner_id) == ("v2.0", NEW_SHA, 3, 42)
    assert store.appimage_path("app").read_bytes() == NEW_IMAGE
    assert store.root_marker("app").read_text().strip() == NEW_SHA
    assert (store.root_path("app") / "AppRun").exists()
    assert updater.load_pending("app") is None
    assert list(store.staging_root().iterdir()) == []
    assert m.permissions == manifest.load(path).permissions


def test_permissions_and_name_survive_an_update(h):  # noqa: F811
    path = installed(h, extra=("--allow", "network", "--no-audio"))
    update(h, FakeClient(release_=release2()), days=0)
    m = manifest.load(path)
    assert m.permissions.network and not m.permissions.audio and m.name == "app"


def test_quarantine_zero_installs_at_once_with_a_warning(h):  # noqa: F811
    installed(h)
    code, c = update(h, FakeClient(release_=release2()), days=0)
    assert "updated app" in c.text and "quarantine shortened to 0 days" in c.text


def test_negative_quarantine_refused(h):  # noqa: F811
    installed(h)
    with pytest.raises(Abort):
        update(h, FakeClient(release_=release2()), days=-1)


def test_owner_change_blocks_even_without_quarantine(h):  # noqa: F811
    path = installed(h)
    before = path.read_text()
    code, c = update(h, FakeClient(info_=info(owner="evil", owner_id=666), release_=release2()), days=0)
    assert code == 1 and "OWNER CHANGE" in c.text and "BLOCKED" in c.text
    assert len(h.downloads) == 1 and path.read_text() == before
    assert updater.load_pending("app") is None


def test_tier_downgrade_blocks(h):  # noqa: F811
    path = installed(h)
    code, c = update(h, FakeClient(release_=release2(sha="")), days=0)
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text
    assert len(h.downloads) == 1 and manifest.load(path).version == "v1.0"


def test_older_release_is_not_installed(h):  # noqa: F811
    installed(h)
    code, c = update(h, FakeClient(release_=release2(published="2026-01-01T00:00:00Z")), days=0)
    assert code == 0 and "older than the installed" in c.text and len(h.downloads) == 1


def test_declined_changes_nothing(h):  # noqa: F811
    path = installed(h)
    before = path.read_text()
    code, c = update(h, FakeClient(release_=release2()), answers=("n",), days=0)
    assert code == 0 and path.read_text() == before and len(h.downloads) == 1


def test_digest_mismatch_keeps_the_old_install(h):  # noqa: F811
    path = installed(h)
    bad = NEW_IMAGE[:-1] + b"X"
    code, c = update(h, FakeClient(release_=release2()), days=0, download=h.download(bad))
    assert code == 1 and "sha256 mismatch" in c.text
    assert manifest.load(path).sha256 == SHA
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert list(store.staging_root().iterdir()) == []


def test_extraction_failure_keeps_the_old_install(h):  # noqa: F811
    path = installed(h)

    def broken(image, dest, fallback=False):
        raise appimage.ExtractError("boom")

    code, c = update(h, FakeClient(release_=release2()), days=0, extract=broken)
    assert code == 1 and "cannot extract" in c.text
    assert manifest.load(path).sha256 == SHA and store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert (store.root_path("app") / "AppRun").exists()
    assert store.root_marker("app").read_text().strip() == SHA


def test_failure_while_swapping_restores_the_old_install(h, monkeypatch):  # noqa: F811
    path = installed(h)
    monkeypatch.setattr(manifest, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    code, c = update(h, FakeClient(release_=release2()), days=0)
    assert code == 1
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert store.root_marker("app").read_text().strip() == SHA
    assert (store.root_path("app") / "AppRun").exists()
    assert manifest.load(path).sha256 == SHA


def test_tier4_rolling_tag_unchanged_is_current(h):  # noqa: F811
    installed(h, client=FakeClient(release_=release(asset(sha=""))))
    same = github.Release("v1.0", "2026-09-30T02:40:02Z", False, "https://x", (asset(sha=""),))
    code, c = update(h, FakeClient(release_=same), days=0)
    assert "up to date" in c.text and len(h.downloads) == 1


def test_tier4_update_shows_the_new_hash_and_asks_again(h):  # noqa: F811
    path = installed(h, client=FakeClient(release_=release(asset(sha=""))))
    code, c = update(h, FakeClient(release_=release2(sha="")), answers=("y", "y"), days=0)
    assert "trust on first use" in c.text and manifest.load(path).evidence_tier == 4
    assert manifest.load(path).sha256 == NEW_SHA
    code, c = update(h, FakeClient(release_=release2(sha="", tag="v3", published="2026-10-12T00:00:00Z")),
                     answers=("y", "n"), days=0)
    assert manifest.load(path).version == "v2.0"


def test_renamed_repo_is_noted_and_recorded(h):  # noqa: F811
    path = installed(h)
    code, c = update(h, FakeClient(info_=info(full_name="o/App2", renamed=True), release_=release2()), days=0)
    assert "renamed or transferred" in c.text and manifest.load(path).source == "o/App2"


def test_missing_owner_pin_is_noted_and_filled_in(h):  # noqa: F811
    path = installed(h)
    m = manifest.load(path)
    from dataclasses import replace
    manifest.dump(path, replace(m, owner_id=None))
    code, c = update(h, FakeClient(release_=release2()), days=0)
    assert "before owner pinning" in c.text and manifest.load(path).owner_id == 42


def test_update_all_reports_each_app_and_fails_if_one_does(h):  # noqa: F811
    installed(h)
    h.add(source="o/Other", extra=("--name", "other"))
    client = FakeClient(release_=release2())
    console = Script(["y"])
    args = cli.build_parser().parse_args(["update", "--quarantine", "0"])

    class Flaky(FakeClient):
        def repo_info(self, source):
            self.n = getattr(self, "n", 0) + 1
            if self.n == 2:  # apps are visited in name order: app, other
                raise github.GitHubError("HTTP 500")
            return super().repo_info(source)

    code = cli.cmd_update(args, Flaky(release_=release2()), console, download=h.download(NEW_IMAGE), now=T0,
                          extract=h.extract, extract_ok=lambda: True)
    assert code == 1 and "app: updated" in console.text and "other: failed" in console.text


def test_unknown_app(h):  # noqa: F811
    with pytest.raises(Abort):
        update(h, FakeClient(), app="nope")


# -- list / remove / perms --------------------------------------------------------------


def test_list(h):  # noqa: F811
    c = Script()
    cli.cmd_list(c)
    assert "No apps" in c.text
    installed(h, extra=("--allow", "network"))
    update(h, FakeClient(release_=release2()))
    c = Script()
    cli.cmd_list(c)
    assert "app  v1.0  o/App  tier 3" in c.text and "network" in c.text and "update seen: v2.0" in c.text


def test_remove_deletes_everything_after_confirmation(h):  # noqa: F811
    installed(h)
    (store.home_path("app")).mkdir(parents=True)
    args = cli.build_parser().parse_args(["remove", "app"])
    with pytest.raises(Abort):
        cli.cmd_remove(args, Script(["n"]))
    assert store.manifest_path("app").exists()
    cli.cmd_remove(args, Script(["y"]))
    assert not store.manifest_path("app").exists() and not store.app_dir("app").exists()


def test_remove_unknown_or_invalid(h):  # noqa: F811
    for name in ("nope", "../x"):
        with pytest.raises(Abort):
            cli.cmd_remove(cli.build_parser().parse_args(["remove", name, "--yes"]), Script())


def perms(h, *argv, answers=("y",)):  # noqa: F811
    c = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *argv]), c)
    return c


def test_perms_show(h):  # noqa: F811
    installed(h)
    assert "network=False" in perms(h).text


def test_perms_change_and_confirm(h, tmp_path):  # noqa: F811
    path = installed(h)
    d = tmp_path / "docs"
    d.mkdir()
    c = perms(h, "--allow", "network", "--deny", "gpu", "--add-dir", f"{d}:rw")
    p = manifest.load(path).permissions
    assert p.network and not p.gpu and p.dirs == (f"{d}:rw",)
    assert "grants network access" in c.text
    perms(h, "--rm-dir", str(d))
    assert manifest.load(path).permissions.dirs == ()
    assert manifest.load(path).sha256 == SHA


def test_perms_declined_or_invalid_changes_nothing(h, tmp_path):  # noqa: F811
    path = installed(h)
    before = path.read_text()
    with pytest.raises(Abort):
        perms(h, "--allow", "network", answers=("n",))
    with pytest.raises(Abort):
        perms(h, "--allow", "network", "--deny", "network")
    with pytest.raises(Abort):
        perms(h, "--rm-dir", "/nowhere")
    with pytest.raises(Abort):
        perms(h, "--add-dir", str(tmp_path / "missing"))
    assert path.read_text() == before


def test_main_dispatch(h, capsys):  # noqa: F811
    installed(h)
    assert cli.main(["list"]) == 0
    assert "app  v1.0" in capsys.readouterr().out
    assert cli.main(["perms", "nope"]) == 1


# -- D-Bus names ------------------------------------------------------------------------


def test_add_records_dbus_names(h):  # noqa: F811
    path = installed(h, extra=("--dbus", "org.freedesktop.Notifications", "--dbus", "org.freedesktop.Notifications",
                               "--dbus", "org.mpris.MediaPlayer2.*"))
    assert manifest.load(path).permissions.dbus_filter == ("org.freedesktop.Notifications", "org.mpris.MediaPlayer2.*")


def test_add_refuses_dangerous_dbus_names_before_network(h):  # noqa: F811
    client = FakeClient()
    with pytest.raises(Abort, match="systemd1"):
        h.add(client=client, extra=("--dbus", "org.freedesktop.systemd1"))
    assert client.calls == []


def test_add_warns_about_secret_service(h):  # noqa: F811
    c = h.add(extra=("--dbus", "org.freedesktop.secrets"))
    assert "stored secrets" in c.text


def test_perms_add_and_remove_dbus(h):  # noqa: F811
    path = installed(h)
    c = perms(h, "--add-dbus", "org.freedesktop.Notifications", "--add-dbus", "org.freedesktop.secrets")
    assert "stored secrets" in c.text and "dbus=org.freedesktop.Notifications" in c.text
    assert manifest.load(path).permissions.dbus_filter == ("org.freedesktop.Notifications", "org.freedesktop.secrets")
    perms(h, "--rm-dbus", "org.freedesktop.secrets")
    assert manifest.load(path).permissions.dbus_filter == ("org.freedesktop.Notifications",)
    with pytest.raises(Abort, match="not allowed"):
        perms(h, "--rm-dbus", "org.example.Nope")
    with pytest.raises(Abort):
        perms(h, "--add-dbus", "org.gnome.Shell")
    assert manifest.load(path).permissions.dbus_filter == ("org.freedesktop.Notifications",)


def test_list_shows_dbus(h):  # noqa: F811
    installed(h, extra=("--dbus", "org.freedesktop.Notifications"))
    c = Script()
    cli.cmd_list(c)
    assert "dbus: org.freedesktop.Notifications" in c.text
