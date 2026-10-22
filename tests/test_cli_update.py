# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import hashlib
from datetime import timedelta

import pytest

from appjail import appimage, cli, github, manifest, store, updater
from appjail.cli import Abort

from .helpers import (
    FAKE_APPIMAGE,
    NEW_IMAGE,
    NEW_SHA,
    SHA,
    T0,
    FakeClient,
    Script,
    asset,
    info,
    installed,
    release,
    release2,
    update,
)


def test_up_to_date_downloads_nothing(h):
    installed(h)
    code, c = update(h, FakeClient(release_=release(asset())))
    assert code == 0 and "up to date" in c.text
    assert len(h.downloads) == 1  # only the original add


def test_new_release_waits_out_the_quarantine_without_downloading(h):
    path = installed(h)
    before = path.read_text()
    code, c = update(h, FakeClient(release_=release2()))
    assert code == 0 and "quarantine" in c.text and "2026-10-24T00:00:00Z" in c.text
    assert len(h.downloads) == 1 and path.read_text() == before
    assert updater.load_pending("app")["tag"] == "v2.0"


def test_first_seen_clock_is_kept_across_runs_and_resets_for_a_different_candidate(h):
    installed(h)
    update(h, FakeClient(release_=release2()))
    update(h, FakeClient(release_=release2()), now=T0 + timedelta(days=3))
    assert updater.load_pending("app")["first_seen"] == "2026-10-17T00:00:00Z"
    other = hashlib.sha256(b"other").hexdigest()
    update(h, FakeClient(release_=release2(sha=other)), now=T0 + timedelta(days=3))
    assert updater.load_pending("app")["first_seen"] == "2026-10-20T00:00:00Z"


def test_update_after_quarantine(h):
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


def test_permissions_and_name_survive_an_update(h):
    path = installed(h, extra=("--allow", "network", "--no-audio"))
    update(h, FakeClient(release_=release2()), days=0)
    m = manifest.load(path)
    assert m.permissions.network and not m.permissions.audio and m.name == "app"


def test_quarantine_zero_installs_at_once_with_a_warning(h):
    installed(h)
    _code, c = update(h, FakeClient(release_=release2()), days=0)
    assert "updated app" in c.text and "quarantine shortened to 0 days" in c.text


def test_negative_quarantine_refused(h):
    installed(h)
    with pytest.raises(Abort):
        update(h, FakeClient(release_=release2()), days=-1)


def test_owner_change_blocks_even_without_quarantine(h):
    path = installed(h)
    before = path.read_text()
    code, c = update(h, FakeClient(info_=info(owner="evil", owner_id=666), release_=release2()), days=0)
    assert code == 1 and "OWNER CHANGE" in c.text and "BLOCKED" in c.text
    assert len(h.downloads) == 1 and path.read_text() == before
    assert updater.load_pending("app") is None


def test_tier_downgrade_blocks(h):
    path = installed(h)
    code, c = update(h, FakeClient(release_=release2(sha="")), days=0)
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text
    assert len(h.downloads) == 1 and manifest.load(path).version == "v1.0"


def test_older_release_is_not_installed(h):
    installed(h)
    code, c = update(h, FakeClient(release_=release2(published="2026-01-01T00:00:00Z")), days=0)
    assert code == 0 and "older than the installed" in c.text and len(h.downloads) == 1


def test_declined_changes_nothing(h):
    path = installed(h)
    before = path.read_text()
    code, _c = update(h, FakeClient(release_=release2()), answers=("n",), days=0)
    assert code == 0 and path.read_text() == before and len(h.downloads) == 1


def test_digest_mismatch_keeps_the_old_install(h):
    path = installed(h)
    bad = NEW_IMAGE[:-1] + b"X"
    code, c = update(h, FakeClient(release_=release2()), days=0, download=h.download(bad))
    assert code == 1 and "sha256 mismatch" in c.text
    assert manifest.load(path).sha256 == SHA
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert list(store.staging_root().iterdir()) == []


def test_extraction_failure_keeps_the_old_install(h):
    path = installed(h)

    def broken(image, dest, fallback=False):
        raise appimage.ExtractError("boom")

    code, c = update(h, FakeClient(release_=release2()), days=0, extract=broken)
    assert code == 1 and "cannot extract" in c.text
    assert manifest.load(path).sha256 == SHA and store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert (store.root_path("app") / "AppRun").exists()
    assert store.root_marker("app").read_text().strip() == SHA


def test_failure_while_swapping_restores_the_old_install(h, monkeypatch):
    path = installed(h)
    monkeypatch.setattr(manifest, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    code, _c = update(h, FakeClient(release_=release2()), days=0)
    assert code == 1
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert store.root_marker("app").read_text().strip() == SHA
    assert (store.root_path("app") / "AppRun").exists()
    assert manifest.load(path).sha256 == SHA


def test_tier4_rolling_tag_unchanged_is_current(h):
    installed(h, client=FakeClient(release_=release(asset(sha=""))))
    same = github.Release("v1.0", "2026-09-30T02:40:02Z", False, "https://x", (asset(sha=""),))
    _code, c = update(h, FakeClient(release_=same), days=0)
    assert "up to date" in c.text and len(h.downloads) == 1


def test_tier4_update_shows_the_new_hash_and_asks_again(h):
    path = installed(h, client=FakeClient(release_=release(asset(sha=""))))
    _code, c = update(h, FakeClient(release_=release2(sha="")), answers=("y", "y"), days=0)
    assert "trust on first use" in c.text and manifest.load(path).evidence_tier == 4
    assert manifest.load(path).sha256 == NEW_SHA
    _code, c = update(h, FakeClient(release_=release2(sha="", tag="v3", published="2026-10-12T00:00:00Z")),
                     answers=("y", "n"), days=0)
    assert manifest.load(path).version == "v2.0"


def test_renamed_repo_is_noted_and_recorded(h):
    path = installed(h)
    _code, c = update(h, FakeClient(info_=info(full_name="o/App2", renamed=True), release_=release2()), days=0)
    assert "renamed or transferred" in c.text and manifest.load(path).source == "o/App2"


def test_missing_owner_pin_is_noted_and_filled_in(h):
    path = installed(h)
    m = manifest.load(path)
    from dataclasses import replace
    manifest.dump(path, replace(m, owner_id=None))
    _code, c = update(h, FakeClient(release_=release2()), days=0)
    assert "before owner pinning" in c.text and manifest.load(path).owner_id == 42


def test_update_all_reports_each_app_and_fails_if_one_does(h):
    installed(h)
    h.add(source="o/Other", extra=("--name", "other"))
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


def test_unknown_app(h):
    with pytest.raises(Abort):
        update(h, FakeClient(), app="nope")


# -- list / remove / perms --------------------------------------------------------------


def test_list(h):
    c = Script()
    cli.cmd_list(c)
    assert "No apps" in c.text
    installed(h, extra=("--allow", "network"))
    update(h, FakeClient(release_=release2()))
    c = Script()
    cli.cmd_list(c)
    assert "app  v1.0  o/App  tier 3" in c.text and "network" in c.text and "update seen: v2.0" in c.text


def test_remove_deletes_everything_after_confirmation(h):
    installed(h)
    (store.home_path("app")).mkdir(parents=True)
    args = cli.build_parser().parse_args(["remove", "app"])
    with pytest.raises(Abort):
        cli.cmd_remove(args, Script(["n"]))
    assert store.manifest_path("app").exists()
    cli.cmd_remove(args, Script(["y"]))
    assert not store.manifest_path("app").exists() and not store.app_dir("app").exists()


def test_remove_unknown_or_invalid(h):
    for name in ("nope", "../x"):
        with pytest.raises(Abort):
            cli.cmd_remove(cli.build_parser().parse_args(["remove", name, "--yes"]), Script())


def perms(h, *argv, answers=("y",)):
    c = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *argv]), c)
    return c


def test_perms_show(h):
    installed(h)
    assert "network=False" in perms(h).text


def test_perms_change_and_confirm(h, tmp_path):
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


def test_perms_declined_or_invalid_changes_nothing(h, tmp_path):
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


def test_main_dispatch(h, capsys):
    installed(h)
    assert cli.main(["list"]) == 0
    assert "app  v1.0" in capsys.readouterr().out
    assert cli.main(["perms", "nope"]) == 1


# -- D-Bus names ------------------------------------------------------------------------


def test_add_records_dbus_names(h):
    path = installed(h, extra=("--dbus", "org.freedesktop.Notifications", "--dbus", "org.freedesktop.Notifications",
                               "--dbus", "org.mpris.MediaPlayer2.*"))
    assert manifest.load(path).permissions.dbus_filter == ("org.freedesktop.Notifications", "org.mpris.MediaPlayer2.*")


def test_add_refuses_dangerous_dbus_names_before_network(h):
    client = FakeClient()
    with pytest.raises(Abort, match="systemd1"):
        h.add(client=client, extra=("--dbus", "org.freedesktop.systemd1"))
    assert client.calls == []


def test_add_warns_about_secret_service(h):
    c = h.add(extra=("--dbus", "org.freedesktop.secrets"))
    assert "stored secrets" in c.text


def test_perms_add_and_remove_dbus(h):
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


def test_add_and_perms_dbus_own(h):
    client = FakeClient()
    with pytest.raises(Abort, match="impersonate"):
        h.add(client=client, extra=("--dbus-own", "org.freedesktop.Notifications"))
    assert client.calls == []
    path = installed(h, extra=("--dbus-own", "org.mpris.MediaPlayer2.*"))
    assert manifest.load(path).permissions.dbus_own == ("org.mpris.MediaPlayer2.*",)
    c = perms(h, "--add-dbus-own", "org.example.App")
    assert "may own this session-bus name" in c.text and "dbus-own=org.example.App" in c.text
    assert manifest.load(path).permissions.dbus_own == ("org.mpris.MediaPlayer2.*", "org.example.App")
    perms(h, "--rm-dbus-own", "org.mpris.MediaPlayer2.*")
    assert manifest.load(path).permissions.dbus_own == ("org.example.App",)
    with pytest.raises(Abort, match="not owned"):
        perms(h, "--rm-dbus-own", "org.example.Nope")
    with pytest.raises(Abort):
        perms(h, "--add-dbus-own", "org.gnome.Shell")
    c = Script()
    cli.cmd_list(c)
    assert "dbus-own: org.example.App" in c.text


def test_list_shows_dbus(h):
    installed(h, extra=("--dbus", "org.freedesktop.Notifications"))
    c = Script()
    cli.cmd_list(c)
    assert "dbus: org.freedesktop.Notifications" in c.text


def test_add_records_the_update_channel(h):
    h.add()
    assert manifest.load(store.manifest_path("app")).channel == "stable"
    h.add(extra=("--name", "pre", "--prerelease"))
    h.add(extra=("--name", "pin", "--tag", "v1.0"))
    assert manifest.load(store.manifest_path("pre")).channel == "prerelease"
    assert manifest.load(store.manifest_path("pin")).channel == "pinned"


def test_pinned_app_is_not_checked_or_downloaded(h):
    h.add(extra=("--tag", "v1.0"))
    client = FakeClient(release_=release2())
    code, c = update(h, client)
    assert code == 0 and "pinned to" in c.text and len(h.downloads) == 1
    assert not [call for call in client.calls if call[0] == "latest_release"]


def test_channel_option_changes_the_policy_and_is_saved(h):
    path = installed(h)
    update(h, FakeClient(release_=release2()), extra=("--channel", "pinned"))
    assert manifest.load(path).channel == "pinned"
    _code, c = update(h, FakeClient(release_=release2()), extra=("--channel", "stable"))
    assert manifest.load(path).channel == "stable" and "quarantine" in c.text


def test_prerelease_channel_asks_for_prereleases(h):
    installed(h, extra=("--prerelease",))
    seen = []

    class Spy(FakeClient):
        def latest_release(self, source, prereleases=False):
            seen.append(prereleases)
            return super().latest_release(source, prereleases)

    update(h, Spy(release_=release2()))
    assert seen == [True]


def test_rate_limit_stops_the_run_instead_of_hammering_the_api(h):
    installed(h)
    h.add(source="o/Other", extra=("--name", "other"))
    h.add(source="o/Third", extra=("--name", "third"))

    class Limited(FakeClient):
        def repo_info(self, source):
            self.calls.append(("repo_info", source))
            raise github.RateLimited("12:00:00Z")

    client = Limited(release_=release2())
    console = Script(["y"])
    args = cli.build_parser().parse_args(["update", "--quarantine", "0"])
    code = cli.cmd_update(args, client, console, download=h.download(NEW_IMAGE), now=T0, extract=h.extract,
                          extract_ok=lambda: True)
    assert code == 1 and len(client.calls) == 1
    assert "other: not checked (rate limited)" in console.text and "third: not checked (rate limited)" in console.text


def test_add_records_portals_and_opt_ins(h):
    c = h.add(extra=("--allow", "portals", "--portal", "OpenURI", "--portal", "OpenURI"))
    p = manifest.load(store.manifest_path("app")).permissions
    assert p.portals and p.portal_interfaces == ("OpenURI",)
    assert "OpenURI portal is privileged" in c.text


def test_add_portal_needs_portals_and_refuses_flatpak(h):
    with pytest.raises(Abort, match="needs --allow portals"):
        h.add(extra=("--portal", "OpenURI"))
    with pytest.raises(Abort, match="refused"):
        h.add(extra=("--allow", "portals", "--portal", "Flatpak"))
    assert not store.manifest_path("app").exists()


def test_perms_add_and_remove_portal_interfaces(h):
    path = installed(h, extra=("--allow", "portals"))

    def perms(*argv):
        c = Script()
        cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", "--yes", *argv]), c)
        return c

    c = perms("--add-portal", "Screenshot")
    assert manifest.load(path).permissions.portal_interfaces == ("Screenshot",) and "privileged" in c.text
    perms("--rm-portal", "Screenshot")
    assert manifest.load(path).permissions.portal_interfaces == ()
    with pytest.raises(Abort, match="not allowed"):
        perms("--rm-portal", "Screenshot")
    perms("--add-portal", "Camera")
    perms("--deny", "portals")  # turning portals off drops the opt-ins with it
    p = manifest.load(path).permissions
    assert not p.portals and p.portal_interfaces == ()


def test_perms_add_portal_without_portals_is_refused(h):
    installed(h)
    with pytest.raises(Abort, match="needs portals"):
        cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", "--yes", "--add-portal", "Camera"]), Script())


def tier4_client(**kw):
    return FakeClient(release_=release2(sha="", **kw))


def test_tier4_candidate_is_hashed_when_first_seen(h):
    installed(h, client=FakeClient(release_=release(asset(sha=""))))
    code, c = update(h, tier4_client())
    assert code == 0 and NEW_SHA in c.text
    assert updater.load_pending("app")["sha256"] == NEW_SHA
    assert len(h.downloads) == 2 and list(store.staging_root().iterdir()) == []  # the add, and the hash-only download
    update(h, tier4_client(), now=T0 + timedelta(days=3))
    assert len(h.downloads) == 2  # recorded once


def test_tier4_hash_is_optional_and_a_refusal_is_warned_about(h):
    installed(h, client=FakeClient(release_=release(asset(sha=""))))
    _code, c = update(h, tier4_client(), answers=("n",))
    assert "will not be detected" in c.text and "sha256" not in (updater.load_pending("app") or {})
    assert len(h.downloads) == 1


def test_tier4_asset_swapped_during_quarantine_is_blocked_and_restarts_the_clock(h):
    path = installed(h, client=FakeClient(release_=release(asset(sha=""))))
    update(h, tier4_client())
    swapped = NEW_IMAGE[:-1] + b"X"  # same size: only the content differs
    code, c = update(h, tier4_client(), now=T0 + timedelta(days=8), download=h.download(swapped))
    assert code == 1 and "CHANGED DURING QUARANTINE" in c.text and "updated" not in c.text
    assert manifest.load(path).version == "v1.0" and store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    p = updater.load_pending("app")
    assert p["first_seen"] == "2026-10-25T00:00:00Z" and p["sha256"] == hashlib.sha256(swapped).hexdigest()
    assert list(store.staging_root().iterdir()) == []


def test_tier4_unchanged_asset_installs_after_the_quarantine(h):
    path = installed(h, client=FakeClient(release_=release(asset(sha=""))))
    update(h, tier4_client())
    _code, c = update(h, tier4_client(), answers=("y", "y"), now=T0 + timedelta(days=7))
    assert "updated app" in c.text and manifest.load(path).sha256 == NEW_SHA


@pytest.mark.parametrize("bad", ['{"key": "k", "tag": "t", "first_seen": "2026-10-17T00:00:00Z", "sha256": "zz"}',
                                 '{"key": "k", "tag": "t", "first_seen": "2026-10-17T00:00:00Z", "extra": "x"}'])
def test_malformed_pending_is_ignored(h, bad):
    installed(h)
    updater.pending_path("app").write_text(bad)
    assert updater.load_pending("app") is None


# -- pasta is needed for network without network_host ------------------------------------------


@pytest.fixture
def no_pasta(monkeypatch):
    from appjail import jail
    monkeypatch.setattr(jail, "find_pasta", lambda: None)


def test_add_refuses_network_without_pasta_before_any_request(h, no_pasta):
    with pytest.raises(Abort, match="passt"):
        h.add(extra=("--allow", "network"))
    assert h.downloads == [] and not store.manifest_path("app").exists() and not store.app_dir("app").exists()


def test_add_with_network_host_or_without_network_needs_no_pasta(h, no_pasta):
    h.add(extra=("--allow", "network_host"))
    p = manifest.load(store.manifest_path("app")).permissions
    assert p.network and p.network_host
    h.add(extra=("--name", "offline"))


def test_perms_refuses_to_grant_network_without_pasta_but_not_other_changes(h, no_pasta):
    installed(h)
    with pytest.raises(Abort, match="passt"):
        perms(h, "--allow", "network")
    assert not manifest.load(store.manifest_path("app")).permissions.network
    perms(h, "--deny", "gpu")
    perms(h, "--allow", "network_host")
    assert manifest.load(store.manifest_path("app")).permissions.network_host
    perms(h, "--deny", "audio")  # an app already granted network_host is not blocked by other edits
