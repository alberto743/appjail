# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""GitHub release resolver: repo review data, latest release, AppImage assets, evidence.

Only api.github.com is queried here and only JSON is parsed; nothing is downloaded or
executed. The transport is injectable so tests never touch the network. A token is read
from GITHUB_TOKEN and sent to api.github.com only (redirects are followed by hand and
refused when they leave that host).
"""

import fnmatch
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from . import manifest, snappy, textsafe

API = "https://api.github.com"
MAX_BODY = 8 * 1024 * 1024
MAX_BUNDLE = 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 20

TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
X86_64_TOKENS = ("x86_64", "x86-64", "amd64", "x64")
OTHER_ARCH_RE = re.compile(r"aarch64|arm64|armhf|armv7|armv6|(?<![a-z0-9])arm(?![a-z0-9])|i[3-6]86|ppc64|riscv|s390x", re.IGNORECASE)


class GitHubError(Exception):
    pass


class NotFound(GitHubError):
    pass


class RateLimited(GitHubError):
    def __init__(self, reset=None):
        self.reset = reset
        super().__init__("GitHub API rate limit reached" + (f" (resets at {reset})" if reset else "")
                         + "; set GITHUB_TOKEN to raise the limit")


@dataclass(frozen=True)
class RepoInfo:
    full_name: str  # canonical name reported by GitHub
    owner: str
    owner_id: int
    owner_type: str
    owner_created_at: str
    stars: int
    fork: bool
    parent: str  # "owner/repo" of the fork parent, or ""
    archived: bool
    description: str
    html_url: str
    renamed: bool  # canonical name differs from the requested one (rename or transfer)


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str  # lowercase hex from the GitHub digest, or "" when GitHub gave none
    url: str  # browser_download_url, validated to belong to the repo's releases


@dataclass(frozen=True)
class Release:
    tag: str
    published_at: str
    prerelease: bool
    html_url: str
    assets: tuple


def _urllib_fetch(url, headers, timeout, max_bytes):
    """Single GET without following redirects. Returns (status, headers, body)."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        resp = e
    with resp:
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise GitHubError("response too large")
        return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body


class Client:
    def __init__(self, token=None, fetch=_urllib_fetch):
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._fetch = fetch

    def _get(self, path, ok=(200,)):
        url = API + path
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "appjail",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        for _ in range(MAX_REDIRECTS + 1):
            status, hdrs, body = self._fetch(url, headers, TIMEOUT, MAX_BODY)
            if status in (301, 302, 307, 308):
                url = urllib.parse.urljoin(url, hdrs.get("location", ""))
                if not url.startswith(API + "/"):
                    raise GitHubError("refusing redirect away from api.github.com")
                continue
            break
        else:
            raise GitHubError("too many redirects")
        if status in ok:
            try:
                return json.loads(body)
            except ValueError as e:
                raise GitHubError("GitHub returned invalid JSON") from e
        if status == 404:
            raise NotFound(path)
        if status in (403, 429) and hdrs.get("x-ratelimit-remaining") == "0":
            reset = hdrs.get("x-ratelimit-reset", "")
            try:
                reset = datetime.fromtimestamp(int(reset), UTC).strftime("%H:%M:%SZ")
            except ValueError:
                reset = None
            raise RateLimited(reset)
        raise GitHubError(f"GitHub API returned HTTP {status} for {path}")

    # -- resolver ---------------------------------------------------------------

    def repo_info(self, source):
        _check_source(source)
        repo = self._get(f"/repos/{source}")
        owner = repo["owner"]
        user = self._get(f"/users/{owner['login']}")
        parent = (repo.get("parent") or {}).get("full_name", "") if repo.get("fork") else ""
        return RepoInfo(
            full_name=repo["full_name"],
            owner=owner["login"],
            owner_id=int(owner["id"]),
            owner_type=owner.get("type", ""),
            owner_created_at=_timestamp(user.get("created_at")),
            stars=int(repo.get("stargazers_count", 0)),
            fork=bool(repo.get("fork")),
            parent=parent,
            archived=bool(repo.get("archived")),
            description=textsafe.clean(repo.get("description") or "", 300),
            html_url=repo["html_url"],
            renamed=repo["full_name"].lower() != source.lower(),
        )

    def head_commit(self, source, ref="HEAD"):
        """The full commit SHA that `ref` (default: the default branch) points to in `source`."""
        _check_source(source)
        sha = self._get(f"/repos/{source}/commits/{ref}").get("sha")
        if not isinstance(sha, str) or not COMMIT_RE.fullmatch(sha):
            raise GitHubError("GitHub returned no usable commit")
        return sha

    def latest_release(self, source, prereleases=False):
        _check_source(source)
        if prereleases:
            releases = [r for r in self._get(f"/repos/{source}/releases?per_page=30") if not r.get("draft")]
            if not releases:
                raise NotFound(f"no releases for {source}")
            data = releases[0]
        else:
            data = self._get(f"/repos/{source}/releases/latest")
        return _release(source, data)

    def release_by_tag(self, source, tag):
        _check_source(source)
        if not TAG_RE.fullmatch(tag or ""):
            raise GitHubError(f"not a valid release tag: {textsafe.clean(tag, 60)!r}")
        return _release(source, self._get(f"/repos/{source}/releases/tags/{urllib.parse.quote(tag)}"))

    def _attestations(self, source, sha256):
        """The attestation records GitHub lists for this digest (a list; empty when there are none)."""
        _check_source(source)
        if not manifest.SHA256_RE.fullmatch(sha256):
            raise GitHubError("invalid sha256")
        try:
            data = self._get(f"/repos/{source}/attestations/sha256:{sha256}")
        except NotFound:
            return []
        return data.get("attestations") or []

    def has_attestation(self, source, sha256):
        """True if GitHub holds at least one attestation for this digest (existence only)."""
        return bool(self._attestations(source, sha256))

    def attestation_bundles(self, source, sha256, limit=5):
        """Sigstore bundles (parsed JSON objects) GitHub holds for this digest, to be verified elsewhere.

        The listing comes from api.github.com; each bundle is a short-lived signed blob URL on
        blob.core.windows.net (fetched without credentials, size-capped) and is Snappy-compressed.
        Nothing here is trusted: the bundles only become evidence after `appjail.attest` verifies them.
        """
        out = []
        for item in self._attestations(source, sha256)[:limit]:
            bundle = item.get("bundle") if isinstance(item, dict) else None
            url = item.get("bundle_url") if isinstance(item, dict) else None
            if bundle is None and isinstance(url, str):
                host = urllib.parse.urlsplit(url)
                if host.scheme != "https" or not (host.hostname or "").endswith(".blob.core.windows.net"):
                    raise GitHubError("attestation bundle URL is not on the expected storage host")
                status, _, body = self._fetch(url, {"User-Agent": "appjail"}, TIMEOUT, MAX_BUNDLE)
                if status != 200:
                    raise GitHubError(f"attestation bundle download failed (HTTP {status})")
                try:
                    bundle = json.loads(body)
                except ValueError:
                    try:
                        bundle = json.loads(snappy.decompress(body, MAX_BUNDLE * 4))
                    except (snappy.SnappyError, ValueError) as e:
                        raise GitHubError("attestation bundle is not valid JSON") from e
            if isinstance(bundle, dict):
                out.append(bundle)
        return out


# -- parsing helpers -----------------------------------------------------------------


def _check_source(source):
    if not isinstance(source, str) or not manifest.REPO_RE.fullmatch(source):
        raise GitHubError(f"not a GitHub owner/repo: {textsafe.clean(source, 80)!r}")


def _timestamp(value):
    if not isinstance(value, str) or not manifest.PUBLISHED_RE.fullmatch(value):
        raise GitHubError(f"unexpected timestamp from GitHub: {textsafe.clean(value, 40)!r}")
    return value


def parse_digest(value):
    """sha256 hex from a GitHub 'sha256:<hex>' digest; '' for null or other algorithms."""
    if isinstance(value, str) and value.startswith("sha256:"):
        hexa = value[7:].lower()
        if manifest.SHA256_RE.fullmatch(hexa):
            return hexa
    return ""


def _release(source, data):
    prefix = f"https://github.com/{source}/releases/download/".lower()
    assets = []
    for a in data.get("assets", []):
        url = a.get("browser_download_url", "")
        name = a.get("name", "")
        # Names are shown to the user and become file names: keep only plain ones.
        if not isinstance(name, str) or not name or "/" in name or textsafe.clean(name) != name:
            continue
        if not isinstance(url, str) or not url.lower().startswith(prefix):
            continue
        assets.append(Asset(name=name, size=int(a.get("size", 0)), sha256=parse_digest(a.get("digest")), url=url))
    return Release(
        tag=textsafe.clean(data.get("tag_name", ""), 128),
        published_at=_timestamp(data.get("published_at")),
        prerelease=bool(data.get("prerelease")),
        html_url=data.get("html_url", ""),
        assets=tuple(assets),
    )


def appimage_candidates(release):
    """x86-64 AppImage assets (the only supported architecture). Explicitly tagged ones win; untagged are the fallback."""
    images = [a for a in release.assets
              if a.name.lower().endswith(".appimage") and not OTHER_ARCH_RE.search(a.name)]
    tagged = [a for a in images if any(t in a.name.lower() for t in X86_64_TOKENS)]
    return tagged or images


def match_assets(release, pattern):
    return [a for a in release.assets if fnmatch.fnmatchcase(a.name, pattern)]


def suggest_pattern(name, tag):
    """Turn an asset name into an fnmatch pattern by replacing the release version with '*'."""
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    for v in sorted({version, tag}, key=len, reverse=True):
        if v and v in name:
            return name.replace(v, "*")
    return name


def age_days(timestamp, now=None):
    now = now or datetime.now(UTC)
    then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (now - then).days
