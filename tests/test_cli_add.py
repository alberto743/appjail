# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from bjail import cli, github, manifest, store
from bjail.cli import Abort

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
FAKE_APPIMAGE = b"\x7fELF\x02\x01\x01\x00AI\x02" + b"payload" * 10
SHA = __import__("hashlib").sha256(FAKE_APPIMAGE).hexdigest()


def info(**kw):
    base = dict(full_name="o/App", owner="o", owner_id=42, owner_type="User", owner_created_at="2015-01-02T03:04:05Z",
                stars=500, fork=False, parent="", archived=False, description="An app",
                html_url="https://github.com/o/App", renamed=False)
    base.update(kw)
    return github.RepoInfo(**base)


def asset(name="App-1.0-x86_64.AppImage", sha=SHA, size=len(FAKE_APPIMAGE)):
    return github.Asset(name, size, sha, f"https://github.com/o/App/releases/download/v1.0/{name}")


def release(*assets):
    return github.Release("v1.0", "2026-09-30T02:40:02Z", False, "https://github.com/o/App/releases/tag/v1.0", tuple(assets))


class FakeClient:
    def __init__(self, info_=None, release_=None, attestation=True):
        self._info, self._release, self._att = info_ or info(), release_ or release(asset()), attestation
        self.calls = []

    def repo_info(self, source):
        self.calls.append(("repo_info", source))
        return self._info

    def latest_release(self, source, prereleases=False):
        self.calls.append(("latest_release", source))
        return self._release

    def has_attestation(self, source, sha):
        return self._att


class Script(cli.Console):
    """Console with scripted answers; records output instead of printing."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.lines = []

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


def args(**kw):
    ns = cli.build_parser().parse_args(["add", kw.pop("source", "o/App")] + kw.pop("extra", []))
    return ns


class AddTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"BJAIL_DATA_DIR": f"{self.tmp.name}/data", "BJAIL_CONFIG_DIR": f"{self.tmp.name}/config"})
        env.start()
        self.addCleanup(env.stop)
        self.downloads = []

    def fake_download(self, content=FAKE_APPIMAGE):
        def download(url, stage, filename, expected_size):
            self.downloads.append((url, expected_size))
            path = Path(stage) / filename
            path.write_bytes(content)
            return path
        return download

    def add(self, client=None, answers=("y",), extra=(), download=None, **kw):
        console = Script(answers)
        cli.cmd_add(args(extra=list(extra), **kw), client or FakeClient(), console,
                    download=download or self.fake_download(), now=NOW)
        return console

    def assert_nothing_installed(self, name="app"):
        self.assertFalse(store.manifest_path(name).exists())
        self.assertFalse(store.app_dir(name).exists())
        self.assertEqual(list(store.staging_root().iterdir()), [])

    def test_success_with_digest(self):
        console = self.add()
        m = manifest.load(store.manifest_path("app"))
        self.assertEqual((m.source, m.version, m.sha256, m.evidence_tier, m.owner_id), ("o/App", "v1.0", SHA, 3, 42))
        self.assertEqual(m.asset_pattern, "App-*-x86_64.AppImage")
        self.assertEqual(store.appimage_path("app").read_bytes(), FAKE_APPIMAGE)
        self.assertEqual(self.downloads[0][0], asset().url)
        self.assertEqual(store.appimage_path("app").stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(store.staging_root().iterdir()), [])
        self.assertIn("attestation: present (not verified)", console.text)

    def test_default_permissions_are_minimal(self):
        self.add()
        p = manifest.load(store.manifest_path("app")).permissions
        self.assertEqual((p.network, p.audio, p.gpu, p.portals, p.display), (False, True, True, False, "wayland"))

    def test_permission_flags(self):
        self.add(extra=["--allow", "network", "--no-audio", "--display", "xwayland"])
        p = manifest.load(store.manifest_path("app")).permissions
        self.assertEqual((p.network, p.audio, p.gpu, p.display), (True, False, True, "xwayland"))

    def test_no_digest_is_tier4_with_warning(self):
        client = FakeClient(release_=release(asset(sha="")))
        console = self.add(client=client)
        self.assertEqual(manifest.load(store.manifest_path("app")).evidence_tier, 4)
        self.assertIn("trust on first use", console.text)

    def test_digest_mismatch_aborts_and_cleans(self):
        client = FakeClient(release_=release(asset(sha="0" * 64)))
        with self.assertRaisesRegex(Abort, "sha256 mismatch"):
            self.add(client=client)
        self.assert_nothing_installed()

    def test_size_mismatch_aborts(self):
        with self.assertRaisesRegex(Abort, "size"):
            self.add(client=FakeClient(release_=release(asset(size=5))), download=self.fake_download())
        self.assert_nothing_installed()

    def test_not_an_appimage_aborts(self):
        data = b"#!/bin/sh\necho pwned\n" * 5
        client = FakeClient(release_=release(asset(sha="", size=len(data))))
        with self.assertRaisesRegex(Abort, "not a usable AppImage"):
            self.add(client=client, download=self.fake_download(data))
        self.assert_nothing_installed()

    def test_declined_downloads_nothing(self):
        with self.assertRaisesRegex(Abort, "cancelled"):
            self.add(answers=("n",))
        self.assertEqual(self.downloads, [])
        self.assertFalse(store.staging_root().exists())

    def test_empty_answer_means_no(self):
        with self.assertRaises(Abort):
            self.add(answers=("",))
        self.assertEqual(self.downloads, [])

    def test_existing_name_refused_before_network(self):
        self.add()
        client = FakeClient()
        with self.assertRaisesRegex(Abort, "already added"):
            self.add(client=client)
        self.assertEqual(client.calls, [])

    def test_choose_between_candidates(self):
        a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
        self.add(client=FakeClient(release_=release(a, b)), answers=("2", "y"))
        self.assertEqual(self.downloads[0][0], b.url)

    def test_invalid_choice_aborts(self):
        a, b = asset("A-x86_64.AppImage"), asset("B-x86_64.AppImage")
        with self.assertRaisesRegex(Abort, "invalid choice"):
            self.add(client=FakeClient(release_=release(a, b)), answers=("9",))
        self.assertEqual(self.downloads, [])

    def test_no_candidates(self):
        other = github.Asset("App.tar.gz", 1, "", "https://github.com/o/App/releases/download/v1.0/App.tar.gz")
        with self.assertRaisesRegex(Abort, "no x86_64 AppImage"):
            self.add(client=FakeClient(release_=release(other)))

    def test_renamed_repo_requires_confirmation_and_pins_canonical_name(self):
        client = FakeClient(info_=info(full_name="new/App", renamed=True))
        console = self.add(client=client, answers=("y", "y"))
        self.assertEqual(manifest.load(store.manifest_path("app")).source, "new/App")
        self.assertIn("renamed or transferred", console.text)
        with self.assertRaisesRegex(Abort, "cancelled"):
            self.add(client=FakeClient(info_=info(full_name="new/App", renamed=True)), answers=("n",),
                     extra=["--name", "other"])
        self.assertFalse(store.manifest_path("other").exists())

    def test_review_warnings(self):
        client = FakeClient(info_=info(fork=True, parent="up/App", archived=True, stars=1,
                                       owner_created_at="2026-10-01T00:00:00Z"))
        console = self.add(client=client)
        for text in ("fork of up/App", "archived", "very few stars", "16 days old"):
            self.assertIn(text, console.text)

    def test_terminal_escapes_in_api_text_are_neutralised(self):
        out = []
        console = cli.Console()
        with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(a))):
            console.out("evil \x1b]0;pwn\x07 text")
            console.warn("a\x1b[2Jb")
        self.assertEqual(out, ["evil  text", "WARNING: ab"])

    def test_names(self):
        self.assertEqual(cli.default_name("My_App.v2"), "my_app.v2")
        self.assertEqual(cli.default_name("App Name!"), "app-name-")
        self.assertEqual(cli.default_name("___"), "")

    def test_main_rejects_bad_source(self):
        console = Script()
        self.assertEqual(cli.main(["add", "https://github.com/o/r"], client=FakeClient(), console=console), 1)
        self.assertIn("owner/repo", console.text)


if __name__ == "__main__":
    unittest.main()
