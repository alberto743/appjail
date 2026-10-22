# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

from datetime import timedelta

import pytest

from appjail import appimage, cli, cmd_addimage, manifest, store, updater

from .helpers import (
    FAKE_APPIMAGE,
    NEW_IMAGE,
    NEW_SHA,
    NOW,
    SHA,
    T0,
    FakeClient,
    Script,
    UrlServer,
    install_file,
    install_url,
    installed,
    update,
)


def run(h, server, *, days=7, now=T0, answers=("y",), extra=()):
    return update(h, None, answers=answers, days=days, now=now, extra=extra, **server.kw)


def mf():
    return manifest.load(store.manifest_path("app"))


# -- url: nothing changed ---------------------------------------------------------------------


def test_unchanged_url_is_a_304_and_downloads_nothing(h):
    server = UrlServer()
    install_url(h, server)
    code, c = run(h, server)
    assert code == 0 and "up to date" in c.text
    assert server.downloads == 0 and server.checks == [('"e1"', "Tue, 20 Oct 2026 08:00:00 GMT")]


def test_same_content_with_new_validators_is_up_to_date_and_refreshes_them(h):
    server = UrlServer()
    install_url(h, server)
    server.etag = '"e2"'
    _code, c = run(h, server)
    assert "up to date" in c.text and server.downloads == 0
    assert mf().fingerprint.etag == '"e2"'
    run(h, server)
    assert server.checks[-1][0] == '"e2"'


# -- url: a new candidate and the quarantine ------------------------------------------------------


def candidate(h, **kw):
    server = UrlServer()
    install_url(h, server, *kw.get("add", ()))
    server.content, server.etag = NEW_IMAGE, '"e2"'
    return server


def test_changed_file_is_downloaded_once_and_waits_out_the_quarantine(h):
    server = candidate(h)
    code, c = run(h, server)
    assert code == 0 and server.downloads == 1
    assert "quarantine" in c.text and "2026-10-24T00:00:00Z" in c.text
    assert mf().sha256 == SHA  # nothing installed
    pending = updater.load_pending("app")
    assert pending["sha256"] == NEW_SHA and pending["etag"] == '"e2"' and pending["first_seen"] == "2026-10-17T00:00:00Z"
    assert updater.pending_image("app").read_bytes() == NEW_IMAGE


def test_later_runs_ask_the_server_for_the_candidate_and_download_nothing(h):
    server = candidate(h)
    run(h, server)
    _code, c = run(h, server, now=T0 + timedelta(days=3))
    assert server.downloads == 1 and "still the same file" in c.text
    assert server.checks[-1][0] == '"e2"'  # validators of the candidate, not of the installed file
    assert updater.load_pending("app")["first_seen"] == "2026-10-17T00:00:00Z"


def test_install_after_quarantine_uses_the_stored_candidate(h):
    server = candidate(h)
    run(h, server)
    code, c = run(h, server, now=T0 + timedelta(days=7))
    assert code == 0 and server.downloads == 1 and "updated app" in c.text
    m = mf()
    assert (m.sha256, m.evidence_tier, m.version) == (NEW_SHA, 5, f"sha256:{NEW_SHA[:12]}")
    assert m.fingerprint.etag == '"e2"' and m.published_at == "2026-10-24T00:00:00Z"
    assert store.appimage_path("app").read_bytes() == NEW_IMAGE
    assert store.root_marker("app").read_text().strip() == NEW_SHA
    assert updater.load_pending("app") is None and not updater.pending_image("app").exists()
    code, c = run(h, server, now=T0 + timedelta(days=8))
    assert "up to date" in c.text


def test_verify_downloads_again_and_compares(h):
    server = candidate(h)
    run(h, server)
    _code, c = run(h, server, now=T0 + timedelta(days=7), extra=("--verify",), answers=("y", "y"))
    assert server.downloads == 2 and "updated app" in c.text


def test_verify_catches_a_swap_with_the_same_validators(h):
    server = candidate(h)
    run(h, server)
    server.content = NEW_IMAGE[:-1] + b"X"  # same etag, different bytes
    code, c = run(h, server, now=T0 + timedelta(days=7), extra=("--verify",))
    assert code == 0 and server.downloads == 2 and "CHANGED DURING QUARANTINE" in c.text and "waiting" not in c.text
    assert mf().sha256 == SHA
    assert updater.load_pending("app")["first_seen"] == "2026-10-24T00:00:00Z"
    assert updater.pending_image("app").read_bytes() == NEW_IMAGE[:-1] + b"X"


def test_the_server_changing_again_restarts_the_clock(h):
    server = candidate(h)
    run(h, server)
    server.content, server.etag = NEW_IMAGE + b"more", '"e3"'
    _code, c = run(h, server, now=T0 + timedelta(days=3))
    assert "CHANGED DURING QUARANTINE" in c.text and server.downloads == 2
    assert updater.load_pending("app")["first_seen"] == "2026-10-20T00:00:00Z"
    assert mf().sha256 == SHA


def test_reverting_to_the_installed_file_clears_the_candidate(h):
    server = candidate(h)
    run(h, server)
    server.content, server.etag = FAKE_APPIMAGE, '"e9"'
    _code, c = run(h, server, now=T0 + timedelta(days=2))
    assert "up to date" in c.text and updater.load_pending("app") is None
    assert not updater.pending_image("app").exists()


def test_quarantine_zero_installs_after_confirmation(h):
    server = candidate(h)
    _code, c = run(h, server, days=0, answers=("y", "y"))
    assert "updated app" in c.text and mf().sha256 == NEW_SHA
    assert "quarantine shortened" in c.text


def test_declining_the_download_changes_nothing(h):
    server = candidate(h)
    _code, _c = run(h, server, answers=("n",))
    assert server.downloads == 0 and updater.load_pending("app") is None and mf().sha256 == SHA


def test_a_missing_stored_candidate_is_dropped_and_fetched_again(h):
    server = candidate(h)
    run(h, server)
    updater.pending_image("app").unlink()
    _code, _c = run(h, server, now=T0 + timedelta(days=1))
    assert server.downloads == 2 and updater.pending_image("app").exists()


def test_a_corrupted_stored_candidate_is_refused(h):
    server = candidate(h)
    run(h, server)
    updater.pending_image("app").write_bytes(b"corrupt")
    code, c = run(h, server, now=T0 + timedelta(days=7))
    assert code == 1 and "does not match its recorded hash" in c.text and mf().sha256 == SHA


def test_http_hop_during_an_update_download_needs_confirmation(h):
    server = candidate(h)
    server.http_hop = True
    code, c = run(h, server, answers=("y", "n"))
    assert code == 1 and "plain http" in c.text and updater.load_pending("app") is None


# -- url: no range requests -------------------------------------------------------------------


def test_without_range_support_a_full_download_decides(h):
    server = UrlServer(ranges=False, etag=None)
    install_url(h, server)
    _code, c = run(h, server)
    assert server.downloads == 1 and "same content" in c.text
    server.content = NEW_IMAGE
    _code, c = run(h, server)
    assert server.downloads == 2 and "quarantine" in c.text


def test_without_range_support_waiting_runs_cost_nothing_and_the_end_compares(h):
    server = UrlServer(ranges=False, etag=None)
    install_url(h, server)
    server.content = NEW_IMAGE
    run(h, server)
    _code, c = run(h, server, now=T0 + timedelta(days=2))
    assert server.downloads == 1 and "cannot be asked cheaply" in c.text
    _code, c = run(h, server, now=T0 + timedelta(days=7), answers=("y", "y"))
    assert server.downloads == 2 and "updated app" in c.text


# -- tiers ----------------------------------------------------------------------------------------


def test_tier4_url_app_refuses_new_content_without_a_hash(h):
    server = UrlServer()
    install_url(h, server, "--sha256", SHA)
    assert mf().evidence_tier == 4
    server.content, server.etag = NEW_IMAGE, '"e2"'
    code, c = run(h, server)
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text and server.downloads == 0 and updater.load_pending("app") is None


def test_tier4_url_app_keeps_tier4_with_the_new_hash(h):
    server = UrlServer()
    install_url(h, server, "--sha256", SHA)
    server.content, server.etag = NEW_IMAGE, '"e2"'
    run(h, server, extra=("--sha256", NEW_SHA))
    _code, _c = run(h, server, now=T0 + timedelta(days=7), extra=("--sha256", NEW_SHA))
    assert mf().evidence_tier == 4 and mf().sha256 == NEW_SHA


def test_wrong_hash_on_update_downloads_but_installs_nothing(h):
    server = UrlServer()
    install_url(h, server, "--sha256", SHA)
    server.content, server.etag = NEW_IMAGE, '"e2"'
    code, c = run(h, server, extra=("--sha256", "0" * 64))
    assert code == 1 and "sha256 mismatch" in c.text and updater.load_pending("app") is None and mf().sha256 == SHA


def test_tier5_app_earns_tier4_with_the_candidates_hash(h):
    server = UrlServer()
    install_url(h, server)
    server.content, server.etag = NEW_IMAGE, '"e2"'
    run(h, server)
    _code, c = run(h, server, now=T0 + timedelta(days=7), extra=("--sha256", NEW_SHA))
    assert mf().evidence_tier == 4 and "tier 5 -> 4" in c.text


def test_tier5_app_earns_tier4_when_the_hash_matches_the_installed_file(h):
    server = UrlServer()
    install_url(h, server)
    code, _c = run(h, server, extra=("--sha256", SHA))
    assert code == 0 and mf().evidence_tier == 4 and server.checks == [] and server.downloads == 0
    code, _c = run(h, server, extra=("--sha256", SHA))  # already tier 4: nothing to do
    assert mf().evidence_tier == 4


# -- file: ----------------------------------------------------------------------------------------


@pytest.fixture
def file_app(h, tmp_path):
    old = tmp_path / "old.AppImage"
    old.write_bytes(FAKE_APPIMAGE)
    new = tmp_path / "new.AppImage"
    new.write_bytes(NEW_IMAGE)
    return h, old, new


def test_plain_update_of_a_file_app_has_nothing_to_check(file_app):
    h, old, _new = file_app
    install_file(h, old)
    code, c = update(h, None)
    assert code == 0 and "no source to check" in c.text and "--file PATH" in c.text


def test_update_file_replaces_the_image_and_keeps_the_home(file_app):
    h, old, new = file_app
    install_file(h, old)
    (store.home_path("app")).mkdir(parents=True)
    (store.home_path("app") / "settings").write_text("keep")
    code, c = update(h, None, extra=("--file", str(new)))
    assert code == 0 and "updated app" in c.text
    m = mf()
    assert (m.source, m.sha256, m.evidence_tier) == ("file:new.AppImage", NEW_SHA, 5)
    assert store.appimage_path("app").read_bytes() == NEW_IMAGE
    assert (store.home_path("app") / "settings").read_text() == "keep"
    assert new.read_bytes() == NEW_IMAGE


def test_update_file_declined_changes_nothing(file_app):
    h, old, new = file_app
    install_file(h, old)
    _code, _c = update(h, None, answers=("n",), extra=("--file", str(new)))
    assert mf().sha256 == SHA and store.appimage_path("app").read_bytes() == FAKE_APPIMAGE


def test_update_file_with_the_installed_file_does_nothing(file_app):
    h, old, _new = file_app
    install_file(h, old)
    _code, c = update(h, None, extra=("--file", str(old)))
    assert "installed file already" in c.text


def test_tier4_file_app_refuses_a_new_file_without_a_hash(file_app):
    h, old, new = file_app
    install_file(h, old, "--sha256", SHA)
    code, c = update(h, None, extra=("--file", str(new)))
    assert code == 1 and "EVIDENCE DOWNGRADE" in c.text and mf().sha256 == SHA
    code, c = update(h, None, extra=("--file", str(new), "--sha256", NEW_SHA))
    assert code == 0 and mf().evidence_tier == 4 and mf().sha256 == NEW_SHA


def test_tier5_file_app_earns_tier4_with_its_own_hash(file_app):
    h, old, _new = file_app
    install_file(h, old)
    _code, _c = update(h, None, extra=("--sha256", SHA))
    assert mf().evidence_tier == 4


def test_update_file_with_a_wrong_hash_installs_nothing(file_app):
    h, old, new = file_app
    install_file(h, old)
    code, c = update(h, None, extra=("--file", str(new), "--sha256", "0" * 64))
    assert code == 1 and "sha256 mismatch" in c.text and mf().sha256 == SHA


def test_extraction_failure_restores_the_previous_version(file_app):
    h, old, new = file_app
    install_file(h, old)

    def broken(*a, **k):
        raise appimage.ExtractError("boom")
    code, _c = update(h, None, extra=("--file", str(new)), extract=broken)
    assert code == 1 and mf().sha256 == SHA and store.appimage_path("app").read_bytes() == FAKE_APPIMAGE


# -- wrong combinations ---------------------------------------------------------------------------


def test_file_option_needs_a_file_app(h, tmp_path):
    server = UrlServer()
    install_url(h, server)
    f = tmp_path / "x.AppImage"
    f.write_bytes(NEW_IMAGE)
    code, c = update(h, None, extra=("--file", str(f)), **server.kw)
    assert code == 1 and "applies to an app installed from a file" in c.text


def test_file_and_sha256_do_not_apply_to_github_apps(h):
    installed(h)
    code, c = update(h, FakeClient(), extra=("--sha256", SHA))
    assert code == 1 and "apply to apps installed from a file or a URL" in c.text


def test_all_apps_run_checks_mixed_kinds(h, tmp_path):
    server = UrlServer()
    install_url(h, server)
    old = tmp_path / "f.AppImage"
    old.write_bytes(FAKE_APPIMAGE)
    cmd_addimage.cmd_add_file(cli.build_parser().parse_args(["add", "--file", str(old), "--name", "other"]), Script(["y"]),
                              extract=h.extract, extract_ok=lambda: True, now=NOW)
    code, c = update(h, None, app=None, **server.kw)
    assert code == 0 and "app: current" in c.text and "other: current" in c.text
