# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json
import os
from datetime import datetime, timezone

import pytest

from appjail import github
from appjail.github import Client, GitHubError, NotFound, RateLimited

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
        status, hdrs, body = self.routes[url[len(github.API):]]
        return status, hdrs, json.dumps(body).encode()


def client(routes, token=""):
    fake = Fake(routes)
    return Client(token=token, fetch=fake), fake


# -- repo info ---------------------------------------------------------------------------


def test_repo_info():
    c, _ = client({"/repos/o/r": (200, {}, REPO), "/users/o": (200, {}, USER)})
    info = c.repo_info("o/r")
    assert (info.owner, info.owner_id, info.stars, info.fork, info.archived) == ("o", 42, 1234, False, False)
    assert info.owner_created_at == "2015-01-02T03:04:05Z"
    assert info.description == "A nice app"
    assert not info.renamed


def test_fork_and_rename_flagged():
    repo = dict(REPO, full_name="new/r", fork=True, parent={"full_name": "up/r"})
    c, _ = client({"/repos/o/r": (200, {}, repo), "/users/o": (200, {}, USER)})
    info = c.repo_info("o/r")
    assert info.renamed
    assert (info.fork, info.parent) == (True, "up/r")


def test_case_difference_is_not_a_rename():
    c, _ = client({"/repos/O/R": (200, {}, REPO), "/users/o": (200, {}, USER)})
    assert not c.repo_info("O/R").renamed


@pytest.mark.parametrize("bad", ["o", "o/r/x", "../x", "o/..", "https://github.com/o/r"])
def test_bad_source_rejected_before_any_request(bad):
    c, fake = client({})
    with pytest.raises(GitHubError):
        c.repo_info(bad)
    assert fake.calls == []


def test_not_found():
    c, _ = client({"/repos/o/r": (404, {}, {})})
    with pytest.raises(NotFound):
        c.repo_info("o/r")


def test_rate_limit():
    c, _ = client({"/repos/o/r": (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {})})
    with pytest.raises(RateLimited, match="GITHUB_TOKEN"):
        c.repo_info("o/r")


def test_other_http_error():
    c, _ = client({"/repos/o/r": (500, {}, {})})
    with pytest.raises(GitHubError, match="HTTP 500"):
        c.repo_info("o/r")


# -- transport ---------------------------------------------------------------------------


def test_token_never_follows_a_foreign_redirect():
    calls = []

    def fetch(url, headers, timeout, max_bytes):
        calls.append((url, headers))
        return 301, {"location": "https://evil.example/x"}, b""

    with pytest.raises(GitHubError, match="redirect"):
        Client(token="secret", fetch=fetch).repo_info("o/r")
    assert len(calls) == 1
    assert calls[0][1]["Authorization"] == "Bearer secret"


def test_same_host_redirect_followed():
    seen = []

    def fetch(url, headers, timeout, max_bytes):
        seen.append(url)
        if url.endswith("/repos/o/r"):
            return 301, {"location": "https://api.github.com/repositories/9"}, b""
        if url.endswith("/repositories/9"):
            return 200, {}, json.dumps(dict(REPO, full_name="new/r")).encode()
        return 200, {}, json.dumps(USER).encode()

    assert Client(token="", fetch=fetch).repo_info("o/r").renamed
    assert len(seen) == 3


def test_no_token_means_no_auth_header():
    c, fake = client({"/repos/o/r": (200, {}, REPO), "/users/o": (200, {}, USER)})
    c.repo_info("o/r")
    assert all("Authorization" not in h for _, h in fake.calls)


def test_invalid_json():
    def fetch(url, headers, timeout, max_bytes):
        return 200, {}, b"<html>"

    with pytest.raises(GitHubError, match="invalid JSON"):
        Client(token="", fetch=fetch).repo_info("o/r")


# -- releases ----------------------------------------------------------------------------


def test_latest_release_and_digest():
    assets = [asset("App-1.2.3-x86_64.AppImage"), asset("App-1.2.3-x86_64.AppImage.zsync", digest=None),
              asset("other", digest="md5:abc"), asset("short", digest="sha256:abc")]
    c, _ = client({"/repos/o/r/releases/latest": (200, {}, release_json(assets))})
    rel = c.latest_release("o/r")
    assert (rel.tag, rel.published_at) == ("v1.2.3", "2026-09-30T02:40:02Z")
    by_name = {a.name: a.sha256 for a in rel.assets}
    assert by_name["App-1.2.3-x86_64.AppImage"] == SHA
    assert by_name["App-1.2.3-x86_64.AppImage.zsync"] == ""
    assert by_name["other"] == ""
    assert by_name["short"] == ""


def test_digest_parsing():
    assert github.parse_digest("sha256:" + "A" * 64) == "a" * 64
    assert github.parse_digest(None) == ""


def test_assets_with_foreign_urls_or_odd_names_dropped():
    assets = [asset("good.AppImage"),
              asset("evil.AppImage", url="https://evil.example/o/r/releases/download/v1/evil.AppImage"),
              asset("other.AppImage", url="https://github.com/x/y/releases/download/v1/other.AppImage"),
              asset("a\x1b[2Jb.AppImage"), asset("../x.AppImage")]
    c, _ = client({"/repos/o/r/releases/latest": (200, {}, release_json(assets))})
    assert [a.name for a in c.latest_release("o/r").assets] == ["good.AppImage"]


def test_prerelease_listing_skips_drafts():
    listing = [release_json([asset("d.AppImage")], tag="v3", draft=True),
               release_json([asset("p.AppImage", tag="v2-rc1")], tag="v2-rc1", prerelease=True)]
    c, _ = client({"/repos/o/r/releases?per_page=30": (200, {}, listing)})
    rel = c.latest_release("o/r", prereleases=True)
    assert (rel.tag, rel.prerelease) == ("v2-rc1", True)


def test_bad_timestamp_rejected():
    bad = release_json([])
    bad["published_at"] = "yesterday"
    c, _ = client({"/repos/o/r/releases/latest": (200, {}, bad)})
    with pytest.raises(GitHubError):
        c.latest_release("o/r")


# -- asset selection ---------------------------------------------------------------------


def rel_with(*names):
    return github.Release("v1.2.3", "2026-09-30T02:40:02Z", False, "", tuple(
        github.Asset(n, 1, "", "https://github.com/o/r/releases/download/v1.2.3/" + n) for n in names))


def candidates(*names):
    return [a.name for a in github.appimage_candidates(rel_with(*names))]


def test_filters_arch_and_suffix():
    got = candidates("A-x86_64.AppImage", "A-aarch64.AppImage", "A-armhf.AppImage", "A-i386.AppImage",
                     "A-x86_64.AppImage.zsync", "A.tar.gz", "A-amd64.deb")
    assert got == ["A-x86_64.AppImage"]


def test_untagged_fallback_and_tagged_priority():
    assert candidates("A.AppImage", "A-arm64.AppImage") == ["A.AppImage"]
    assert candidates("A.AppImage", "A-x86_64.AppImage") == ["A-x86_64.AppImage"]


def test_multiple_candidates_returned_for_user_choice():
    assert len(candidates("A-x86_64.AppImage", "B-amd64.AppImage")) == 2


def test_suffix_is_case_insensitive():
    assert candidates("A-x86_64.appimage") == ["A-x86_64.appimage"]


def test_no_candidates():
    assert candidates("A.tar.gz") == []


def test_pattern_suggestion_and_matching():
    assert github.suggest_pattern("App-1.2.3-x86_64.AppImage", "v1.2.3") == "App-*-x86_64.AppImage"
    assert github.suggest_pattern("App-v1.2.3.AppImage", "v1.2.3") == "App-*.AppImage"
    assert github.suggest_pattern("App.AppImage", "v1.2.3") == "App.AppImage"
    rel = rel_with("App-1.2.3-x86_64.AppImage", "App-1.2.3-aarch64.AppImage")
    assert [a.name for a in github.match_assets(rel, "App-*-x86_64.AppImage")] == ["App-1.2.3-x86_64.AppImage"]


# -- attestations and age ----------------------------------------------------------------


def test_attestation_present():
    c, _ = client({f"/repos/o/r/attestations/sha256:{SHA}": (200, {}, {"attestations": [{"repository_id": 1}]})})
    assert c.has_attestation("o/r", SHA)


def test_attestation_absent():
    c, _ = client({f"/repos/o/r/attestations/sha256:{SHA}": (200, {}, {"attestations": []}),
                   f"/repos/o/r/attestations/sha256:{SHA2}": (404, {}, {})})
    assert not c.has_attestation("o/r", SHA)
    assert not c.has_attestation("o/r", SHA2)


def test_attestation_invalid_digest_makes_no_request():
    c, fake = client({})
    with pytest.raises(GitHubError):
        c.has_attestation("o/r", "../..")
    assert fake.calls == []


def test_age_days():
    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert github.age_days("2026-09-30T02:40:02Z", now) == 16


@pytest.mark.skipif(os.environ.get("APPJAIL_LIVE") != "1", reason="set APPJAIL_LIVE=1 for the live metadata check")
def test_live_cli_cli():
    """Metadata-only queries against cli/cli (user-approved). Downloads nothing."""
    c = Client()
    assert c.repo_info("cli/cli").owner == "cli"
    rel = c.latest_release("cli/cli")
    assert rel.assets and all(a.sha256 for a in rel.assets)
    a = next(a for a in rel.assets if a.name.endswith("_linux_amd64.tar.gz"))
    assert c.has_attestation("cli/cli", a.sha256)
