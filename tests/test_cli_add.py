# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from bjail import appimage, cli, github, manifest, store
from bjail.cli import Abort

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
FAKE_APPIMAGE = b"\x7fELF\x02\x01\x01\x00AI\x02" + b"payload" * 10
SHA = hashlib.sha256(FAKE_APPIMAGE).hexdigest()


def info(**kw):
    base = dict(full_name="o/App", owner="o", owner_id=42, owner_type="User", owner_created_at="2015-01-02T03:04:05Z",
                stars=500, fork=False, parent="", archived=False, description="An app",
                html_url="https://github.com/o/App", renamed=False)
    base.update(kw)
    return github.RepoInfo(**base)


def asset(name="App-1.0-x86_64.AppImage", sha=SHA, size=len(FAKE_APPIMAGE)):
    return github.Asset(name, size, sha, f"https://github.com/o/App/releases/download/v1.0/{name}")


def release(*assets, tag="v1.0"):
    return github.Release(tag, "2026-09-30T02:40:02Z", False, f"https://github.com/o/App/releases/tag/{tag}", tuple(assets))


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


@pytest.fixture
def h(tmp_path, monkeypatch):
    monkeypatch.setenv("BJAIL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BJAIL_CONFIG_DIR", str(tmp_path / "config"))
    return Harness()


# -- success paths -----------------------------------------------------------------------


def test_success_with_digest(h):
    console = h.add()
    m = manifest.load(store.manifest_path("app"))
    assert (m.source, m.version, m.sha256, m.evidence_tier, m.owner_id) == ("o/App", "v1.0", SHA, 3, 42)
    assert m.asset_pattern == "App-*-x86_64.AppImage"
    assert store.appimage_path("app").read_bytes() == FAKE_APPIMAGE
    assert store.appimage_path("app").stat().st_mode & 0o777 == 0o600
    assert h.downloads[0][0] == asset().url
    assert list(store.staging_root().iterdir()) == []
    assert "attestation: present, cannot be verified" in console.text


def test_extraction_runs_on_stored_file_and_marks_source_hash(h):
    h.add()
    assert h.extractions[0] == (store.appimage_path("app"), store.root_path("app"), False)
    assert store.root_marker("app").read_text().strip() == SHA
    assert store.tree_marker("app").read_text().strip() == appimage.tree_digest(store.root_path("app"))


def test_default_permissions_are_minimal(h):
    h.add()
    p = manifest.load(store.manifest_path("app")).permissions
    assert (p.network, p.audio, p.gpu, p.portals, p.display, p.dirs) == (False, True, True, False, "wayland", ())


def test_permission_flags(h):
    h.add(extra=["--allow", "network", "--no-audio", "--display", "xwayland"])
    p = manifest.load(store.manifest_path("app")).permissions
    assert (p.network, p.audio, p.gpu, p.display) == (True, False, True, "xwayland")


def test_no_digest_is_tier4_with_warning(h):
    console = h.add(client=FakeClient(release_=release(asset(sha=""))))
    assert manifest.load(store.manifest_path("app")).evidence_tier == 4
    assert "trust on first use" in console.text


def test_tag_selects_that_release(h):
    client = FakeClient(release_=release(asset(), tag="v0.9"))
    h.add(client=client, extra=["--tag", "v0.9"])
    assert ("release_by_tag", "o/App", "v0.9") in client.calls
    assert not any(c[0] == "latest_release" for c in client.calls)
    assert manifest.load(store.manifest_path("app")).version == "v0.9"


def test_dir_option_is_stored_canonically(h, tmp_path, monkeypatch):
    home = tmp_path / "fakehome"
    (home / "Docs").mkdir(parents=True)
    (tmp_path / "shared").mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    h.add(extra=["--dir", str(home / "Docs"), "--dir", f"{tmp_path / 'shared'}:rw"])
    assert manifest.load(store.manifest_path("app")).permissions.dirs == ("~/Docs", f"{tmp_path / 'shared'}:rw")


@pytest.mark.parametrize("spec", ["/definitely/not/here", "/", "~/", "relative-missing"])
def test_bad_dir_option_aborts_before_any_network(h, spec):
    client = FakeClient()
    with pytest.raises(Abort, match="--dir"):
        h.add(client=client, extra=["--dir", spec])
    assert client.calls == []


# -- failure paths leave nothing behind --------------------------------------------------


def test_digest_mismatch_aborts_and_cleans(h):
    with pytest.raises(Abort, match="sha256 mismatch"):
        h.add(client=FakeClient(release_=release(asset(sha="0" * 64))))
    h.assert_nothing_installed()


def test_size_mismatch_aborts(h):
    with pytest.raises(Abort, match="size"):
        h.add(client=FakeClient(release_=release(asset(size=5))))
    h.assert_nothing_installed()


def test_not_an_appimage_aborts(h):
    data = b"#!/bin/sh\necho pwned\n" * 5
    with pytest.raises(Abort, match="not a usable AppImage"):
        h.add(client=FakeClient(release_=release(asset(sha="", size=len(data)))), download=h.download(data))
    h.assert_nothing_installed()


def test_extraction_failure_leaves_nothing(h):
    def bad(appimage_, dest, fallback=False):
        raise appimage.UnsupportedImage("DwarFS AppImages are not supported (only SquashFS)")

    with pytest.raises(Abort, match="DwarFS"):
        h.add(extract=bad)
    h.assert_nothing_installed()


def test_declined_downloads_nothing(h):
    with pytest.raises(Abort, match="cancelled"):
        h.add(answers=("n",))
    assert h.downloads == []
    assert not store.staging_root().exists()


def test_empty_answer_means_no(h):
    with pytest.raises(Abort):
        h.add(answers=("",))
    assert h.downloads == []


def test_existing_name_refused_before_network(h):
    h.add()
    client = FakeClient()
    with pytest.raises(Abort, match="already added"):
        h.add(client=client)
    assert client.calls == []


# -- choosing and warnings ---------------------------------------------------------------


def test_choose_between_candidates(h):
    a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
    h.add(client=FakeClient(release_=release(a, b)), answers=("2", "y"))
    assert h.downloads[0][0] == b.url


def test_invalid_choice_aborts(h):
    a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
    with pytest.raises(Abort, match="invalid choice"):
        h.add(client=FakeClient(release_=release(a, b)), answers=("9",))
    assert h.downloads == []


def test_no_candidates(h):
    other = github.Asset("App.tar.gz", 1, "", "https://github.com/o/App/releases/download/v1.0/App.tar.gz")
    with pytest.raises(Abort, match="no x86_64 AppImage"):
        h.add(client=FakeClient(release_=release(other)))


def test_renamed_repo_requires_confirmation_and_pins_canonical_name(h):
    renamed = info(full_name="new/App", renamed=True)
    console = h.add(client=FakeClient(info_=renamed), answers=("y", "y"))
    assert manifest.load(store.manifest_path("app")).source == "new/App"
    assert "renamed or transferred" in console.text
    with pytest.raises(Abort, match="cancelled"):
        h.add(client=FakeClient(info_=renamed), answers=("n",), extra=["--name", "other"])
    assert not store.manifest_path("other").exists()


def test_review_warnings(h):
    client = FakeClient(info_=info(fork=True, parent="up/App", archived=True, stars=1,
                                   owner_created_at="2026-10-01T00:00:00Z"))
    console = h.add(client=client)
    for text in ("fork of up/App", "archived", "very few stars", "16 days old"):
        assert text in console.text


def test_missing_unsquashfs_needs_consent_for_runtime_fallback(h):
    with pytest.raises(Abort, match="squashfs-tools"):
        h.add(answers=("n",), extract_ok=lambda: False)
    assert h.downloads == []  # asked before downloading anything
    console = h.add(answers=("y", "y"), extract_ok=lambda: False)  # fallback consent, then download
    assert h.extractions[-1][2] is True
    assert "unsquashfs is not installed" in console.text


# -- console and naming ------------------------------------------------------------------


def test_terminal_escapes_in_api_text_are_neutralised():
    out = []
    console = cli.Console()
    with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(a))):
        console.out("evil \x1b]0;pwn\x07 text")
        console.warn("a\x1b[2Jb")
    assert out == ["evil  text", "WARNING: ab"]


@pytest.mark.parametrize("repo,name", [("My_App.v2", "my_app.v2"), ("App Name!", "app-name-"), ("___", "")])
def test_default_names(repo, name):
    assert cli.default_name(repo) == name


def test_main_rejects_bad_source(h):
    console = Script()
    assert cli.main(["add", "https://github.com/o/r"], client=FakeClient(), console=console) == 1
    assert "owner/repo" in console.text


def test_files_from_args_makes_absolute_paths_and_keeps_the_mode(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert cli.files_from_args(["a.txt", "a.txt:rw", "a.txt:ro"], cwd=tmp_path) == (
        str(tmp_path / "a.txt"), f"{tmp_path / 'a.txt'}:rw", str(tmp_path / "a.txt"))


@pytest.mark.parametrize("spec", ["missing.txt", "."])
def test_files_from_args_rejects_non_files(tmp_path, spec):
    with pytest.raises(cli.Abort, match="not a regular file"):
        cli.files_from_args([spec], cwd=tmp_path)
