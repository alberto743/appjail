# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
import unittest
from datetime import datetime, timezone

from bjail import github
from bjail.github import Client, GitHubError, NotFound, RateLimited

SHA = "a" * 64
SHA2 = "b" * 64


def asset(name, digest=f"sha256:{SHA}", repo="o/r", tag="v1.2.3", size=10, url=None):
    return {"name": name, "size": size, "digest": digest,
            "browser_download_url": url or f"https://github.com/{repo}/releases/download/{tag}/{name}"}


def release_json(assets, tag="v1.2.3", prerelease=False, draft=False):
    return {"tag_name": tag, "published_at": "2026-09-30T02:40:02Z", "prerelease": prerelease,
            "draft": draft, "html_url": f"https://github.com/o/r/releases/tag/{tag}", "assets": assets}


REPO = {"full_name": "o/r", "owner": {"login": "o", "id": 42, "type": "User"}, "stargazers_count": 1234,
        "fork": False, "archived": False, "description": "A \x1b[31mnice\x1b[0m app",
        "html_url": "https://github.com/o/r"}
USER = {"created_at": "2015-01-02T03:04:05Z"}


class Fake:
    """Scripted transport: path -> (status, headers, JSON-able body)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers, timeout, max_bytes):
        self.calls.append((url, dict(headers)))
        path = url[len(github.API):]
        status, hdrs, body = self.routes[path]
        return status, hdrs, json.dumps(body).encode()


def client(routes, token=""):
    fake = Fake(routes)
    return Client(token=token, fetch=fake), fake


class RepoInfoTests(unittest.TestCase):
    def test_repo_info(self):
        c, fake = client({"/repos/o/r": (200, {}, REPO), "/users/o": (200, {}, USER)})
        info = c.repo_info("o/r")
        self.assertEqual((info.owner, info.owner_id, info.stars, info.fork, info.archived), ("o", 42, 1234, False, False))
        self.assertEqual(info.owner_created_at, "2015-01-02T03:04:05Z")
        self.assertEqual(info.description, "A nice app")
        self.assertFalse(info.renamed)

    def test_fork_and_rename_flagged(self):
        repo = dict(REPO, full_name="new/r", fork=True, parent={"full_name": "up/r"})
        c, _ = client({"/repos/o/r": (200, {}, repo), "/users/o": (200, {}, USER)})
        info = c.repo_info("o/r")
        self.assertTrue(info.renamed)
        self.assertEqual((info.fork, info.parent), (True, "up/r"))

    def test_case_difference_is_not_a_rename(self):
        c, _ = client({"/repos/O/R": (200, {}, REPO), "/users/o": (200, {}, USER)})
        self.assertFalse(c.repo_info("O/R").renamed)

    def test_bad_source_rejected_before_any_request(self):
        c, fake = client({})
        for bad in ("o", "o/r/x", "../x", "o/..", "https://github.com/o/r"):
            with self.assertRaises(GitHubError):
                c.repo_info(bad)
        self.assertEqual(fake.calls, [])

    def test_not_found(self):
        c, _ = client({"/repos/o/r": (404, {}, {})})
        with self.assertRaises(NotFound):
            c.repo_info("o/r")

    def test_rate_limit(self):
        c, _ = client({"/repos/o/r": (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {})})
        with self.assertRaisesRegex(RateLimited, "GITHUB_TOKEN"):
            c.repo_info("o/r")

    def test_other_http_error(self):
        c, _ = client({"/repos/o/r": (500, {}, {})})
        with self.assertRaisesRegex(GitHubError, "HTTP 500"):
            c.repo_info("o/r")


class TransportTests(unittest.TestCase):
    def test_token_sent_only_to_api_and_never_on_foreign_redirect(self):
        calls = []

        def fetch(url, headers, timeout, max_bytes):
            calls.append((url, headers))
            return 301, {"location": "https://evil.example/x"}, b""

        with self.assertRaisesRegex(GitHubError, "redirect"):
            Client(token="secret", fetch=fetch).repo_info("o/r")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")

    def test_same_host_redirect_followed(self):
        seen = []

        def fetch(url, headers, timeout, max_bytes):
            seen.append(url)
            if url.endswith("/repos/o/r"):
                return 301, {"location": "https://api.github.com/repositories/9"}, b""
            if url.endswith("/repositories/9"):
                return 200, {}, json.dumps(dict(REPO, full_name="new/r")).encode()
            return 200, {}, json.dumps(USER).encode()

        info = Client(token="", fetch=fetch).repo_info("o/r")
        self.assertTrue(info.renamed)
        self.assertEqual(len(seen), 3)

    def test_no_token_no_auth_header(self):
        c, fake = client({"/repos/o/r": (200, {}, REPO), "/users/o": (200, {}, USER)})
        c.repo_info("o/r")
        self.assertTrue(all("Authorization" not in h for _, h in fake.calls))

    def test_invalid_json(self):
        def fetch(url, headers, timeout, max_bytes):
            return 200, {}, b"<html>"

        with self.assertRaisesRegex(GitHubError, "invalid JSON"):
            Client(token="", fetch=fetch).repo_info("o/r")


class ReleaseTests(unittest.TestCase):
    def test_latest_release_and_digest(self):
        assets = [asset("App-1.2.3-x86_64.AppImage"), asset("App-1.2.3-x86_64.AppImage.zsync", digest=None),
                  asset("other", digest="md5:abc"), asset("short", digest="sha256:abc")]
        c, _ = client({"/repos/o/r/releases/latest": (200, {}, release_json(assets))})
        rel = c.latest_release("o/r")
        self.assertEqual((rel.tag, rel.published_at), ("v1.2.3", "2026-09-30T02:40:02Z"))
        by_name = {a.name: a.sha256 for a in rel.assets}
        self.assertEqual(by_name["App-1.2.3-x86_64.AppImage"], SHA)
        self.assertEqual(by_name["App-1.2.3-x86_64.AppImage.zsync"], "")
        self.assertEqual(by_name["other"], "")
        self.assertEqual(by_name["short"], "")

    def test_digest_uppercase_normalised(self):
        self.assertEqual(github.parse_digest("sha256:" + "A" * 64), "a" * 64)
        self.assertEqual(github.parse_digest(None), "")

    def test_assets_with_foreign_urls_or_odd_names_dropped(self):
        assets = [asset("good.AppImage"),
                  asset("evil.AppImage", url="https://evil.example/o/r/releases/download/v1/evil.AppImage"),
                  asset("other.AppImage", url="https://github.com/x/y/releases/download/v1/other.AppImage"),
                  asset("a\x1b[2Jb.AppImage"), asset("../x.AppImage")]
        c, _ = client({"/repos/o/r/releases/latest": (200, {}, release_json(assets))})
        self.assertEqual([a.name for a in c.latest_release("o/r").assets], ["good.AppImage"])

    def test_prerelease_listing_skips_drafts(self):
        listing = [release_json([asset("d.AppImage")], tag="v3", draft=True),
                   release_json([asset("p.AppImage", tag="v2-rc1")], tag="v2-rc1", prerelease=True)]
        c, _ = client({"/repos/o/r/releases?per_page=30": (200, {}, listing)})
        rel = c.latest_release("o/r", prereleases=True)
        self.assertEqual((rel.tag, rel.prerelease), ("v2-rc1", True))

    def test_bad_timestamp_rejected(self):
        bad = release_json([])
        bad["published_at"] = "yesterday"
        c, _ = client({"/repos/o/r/releases/latest": (200, {}, bad)})
        with self.assertRaises(GitHubError):
            c.latest_release("o/r")


class AssetSelectionTests(unittest.TestCase):
    def rel(self, *names):
        return github.Release("v1.2.3", "2026-09-30T02:40:02Z", False, "", tuple(
            github.Asset(n, 1, "", "https://github.com/o/r/releases/download/v1.2.3/" + n) for n in names))

    def names(self, *names, **kw):
        return [a.name for a in github.appimage_candidates(self.rel(*names), **kw)]

    def test_filters_arch_and_suffix(self):
        got = self.names("A-x86_64.AppImage", "A-aarch64.AppImage", "A-armhf.AppImage", "A-i386.AppImage",
                         "A-x86_64.AppImage.zsync", "A.tar.gz", "A-amd64.deb")
        self.assertEqual(got, ["A-x86_64.AppImage"])

    def test_untagged_fallback_and_tagged_priority(self):
        self.assertEqual(self.names("A.AppImage", "A-arm64.AppImage"), ["A.AppImage"])
        self.assertEqual(self.names("A.AppImage", "A-x86_64.AppImage"), ["A-x86_64.AppImage"])

    def test_multiple_candidates_returned_for_user_choice(self):
        self.assertEqual(len(self.names("A-x86_64.AppImage", "B-amd64.AppImage")), 2)

    def test_case_insensitive_suffix(self):
        self.assertEqual(self.names("A-x86_64.appimage"), ["A-x86_64.appimage"])

    def test_none(self):
        self.assertEqual(self.names("A.tar.gz"), [])

    def test_pattern(self):
        self.assertEqual(github.suggest_pattern("App-1.2.3-x86_64.AppImage", "v1.2.3"), "App-*-x86_64.AppImage")
        self.assertEqual(github.suggest_pattern("App-v1.2.3.AppImage", "v1.2.3"), "App-*.AppImage")
        self.assertEqual(github.suggest_pattern("App.AppImage", "v1.2.3"), "App.AppImage")
        rel = self.rel("App-1.2.3-x86_64.AppImage", "App-1.2.3-aarch64.AppImage")
        self.assertEqual([a.name for a in github.match_assets(rel, "App-*-x86_64.AppImage")], ["App-1.2.3-x86_64.AppImage"])


class AttestationTests(unittest.TestCase):
    def test_present(self):
        c, fake = client({f"/repos/o/r/attestations/sha256:{SHA}": (200, {}, {"attestations": [{"repository_id": 1}]})})
        self.assertTrue(c.has_attestation("o/r", SHA))

    def test_absent(self):
        c, _ = client({f"/repos/o/r/attestations/sha256:{SHA}": (200, {}, {"attestations": []}),
                       f"/repos/o/r/attestations/sha256:{SHA2}": (404, {}, {})})
        self.assertFalse(c.has_attestation("o/r", SHA))
        self.assertFalse(c.has_attestation("o/r", SHA2))

    def test_invalid_digest(self):
        c, fake = client({})
        with self.assertRaises(GitHubError):
            c.has_attestation("o/r", "../..")
        self.assertEqual(fake.calls, [])


class AgeTests(unittest.TestCase):
    def test_age_days(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.assertEqual(github.age_days("2026-09-30T02:40:02Z", now), 16)


@unittest.skipUnless(os.environ.get("BJAIL_LIVE") == "1", "set BJAIL_LIVE=1 for the live metadata check")
class LiveTests(unittest.TestCase):
    """Metadata-only queries against cli/cli (user-approved). Downloads nothing."""

    def test_cli_cli(self):
        c = Client()
        info = c.repo_info("cli/cli")
        self.assertEqual(info.owner, "cli")
        rel = c.latest_release("cli/cli")
        self.assertTrue(rel.assets and all(a.sha256 for a in rel.assets))
        a = next(a for a in rel.assets if a.name.endswith("_linux_amd64.tar.gz"))
        self.assertTrue(c.has_attestation("cli/cli", a.sha256))


if __name__ == "__main__":
    unittest.main()
