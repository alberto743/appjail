# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Manifest schema, strict parser and writer (TOML).

A manifest is declarative data only: where an app comes from, what was pinned and
what the jail may do. Unknown keys and malformed values are errors, never ignored.
"""

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .grants import (
    check_dbus_name,
    check_dbus_own,
    check_dir,
    check_portal_interface,
)
from .valid import ManifestError, boolean, match, str_list, string

SCHEMA_VERSION = 1

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# GitHub owners are alphanumeric/hyphen; repos may also hold "_" and "." but are never "." or "..".
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}")
SOURCE_KINDS = ("github", "url", "file")
MAX_URL = 2048
FILE_NAME_RE = re.compile(r"[^/\x00-\x1f\x7f]{1,255}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PUBLISHED_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

TIERS = (1, 2, 3, 4, 5)
DISPLAYS = ("wayland", "xwayland")

TOP_KEYS = {
    "schema", "name", "source", "asset_pattern", "version", "sha256",
    "evidence_tier", "published_at", "owner_id", "channel", "fingerprint", "permissions",
}
FINGERPRINT_KEYS = {"size", "etag", "last_modified", "chunks"}
CHANNELS = ("stable", "prerelease", "pinned")
BOOL_PERMS = ("network", "network_host", "audio", "gpu", "portals", "userns")
PERM_KEYS = {"network", "network_host", "audio", "gpu", "display", "dbus_filter", "dbus_own", "portals", "portal_interfaces", "userns", "dirs"}


@dataclass(frozen=True)
class Permissions:
    """Everything is denied unless granted."""
    network: bool = False  # outbound only, in a private pasta namespace (no host loopback)
    network_host: bool = False  # with network: the host's own network namespace, loopback services included
    audio: bool = False
    gpu: bool = False
    display: str = "wayland"
    dbus_filter: tuple = ()  # session-bus names the app may talk to
    dbus_own: tuple = ()  # session-bus names the app may own (and talk to): MPRIS players, single-instance names
    portals: bool = False
    portal_interfaces: tuple = ()  # opt-in portal interfaces beyond the safe set (see PORTAL_OPT_IN)
    userns: bool = False  # nested user namespaces and mounts (Electron/Chromium sandboxes, nested bwrap)
    dirs: tuple = ()  # "path" (read-only) or "path:rw"; absolute or starting with "~/"


@dataclass(frozen=True)
class Manifest:
    name: str
    source: str  # kind-prefixed: "github:owner/repo", "url:https://...", "file:BASENAME"
    version: str
    sha256: str
    evidence_tier: int
    published_at: str  # UTC, YYYY-MM-DDTHH:MM:SSZ
    asset_pattern: str = None  # github only: fnmatch pattern for the release asset name
    fingerprint: "Fingerprint" = None  # url only: cheap "has it changed" evidence (see DESIGN.md)
    owner_id: int = None  # GitHub account id of the owner; pins the account, not just the name
    channel: str = "stable"  # which releases `update` follows: stable, prerelease, or pinned (never)
    permissions: Permissions = field(default_factory=Permissions)

    @property
    def kind(self):
        return self.source.partition(":")[0]

    @property
    def target(self):
        """What follows the kind prefix: owner/repo, the URL or the file's base name."""
        return self.source.partition(":")[2]


@dataclass(frozen=True)
class Fingerprint:
    """What the server said about the file at install time, and a hash of a few fixed windows of it."""
    size: int
    chunks: str  # sha256 hex of the sampled windows
    etag: str = None
    last_modified: str = None


def github_source(full_name):
    return f"github:{full_name}"


def _unknown(table, allowed, where):
    extra = sorted(set(table) - allowed)
    if extra:
        raise ManifestError(f"unknown key(s) in {where}: {', '.join(map(str, extra))}")


def _portal_consistency(p):
    if p.portal_interfaces and not p.portals:
        raise ManifestError("permissions.portal_interfaces needs portals = true")


def _network_consistency(p):
    if p.network_host and not p.network:
        raise ManifestError("permissions.network_host needs network = true")


def _permissions(table):
    if not isinstance(table, dict):
        raise ManifestError("permissions must be a table")
    _unknown(table, PERM_KEYS, "[permissions]")
    # Only the shape is settled here (lists of strings); validate() checks every value.
    perms = {key: table[key] for key in (*BOOL_PERMS, "display") if key in table}
    for key in ("dbus_filter", "dbus_own", "portal_interfaces", "dirs"):
        if key in table:
            perms[key] = tuple(str_list(table[key], f"permissions.{key}"))
    return Permissions(**perms)


def _published_at(value):
    match(value, PUBLISHED_RE, "published_at")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ManifestError(f"published_at is not a valid date: {value!r}") from e
    return value


def check_url(url):
    """An https URL without credentials or fragment, as `add --url` and a `url:` source accept."""
    string(url, "url", MAX_URL)
    if any(c.isspace() for c in url):
        raise ManifestError("the url contains whitespace")
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises on a bad port
    except ValueError as e:
        raise ManifestError(f"invalid url: {url!r}") from e
    if parts.scheme != "https" or not parts.hostname:
        raise ManifestError(f"the url must be https with a host: {url!r}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ManifestError("the url must not contain credentials")
    if parts.fragment:
        raise ManifestError("the url must not have a fragment")
    return url


def _source(m):
    string(m.source, "source", MAX_URL + 8)
    kind, sep, target = m.source.partition(":")
    if not sep or kind not in SOURCE_KINDS:
        raise ManifestError(f"source must start with one of {', '.join(k + ':' for k in SOURCE_KINDS)}: {m.source!r}")
    if kind == "github":
        match(target, REPO_RE, "source")
        string(m.asset_pattern, "asset_pattern")
        if "/" in m.asset_pattern:
            raise ManifestError("asset_pattern must not contain '/'")
    else:
        if m.asset_pattern is not None:
            raise ManifestError("asset_pattern applies to a github source only")
        if kind == "url":
            check_url(target)
        elif not FILE_NAME_RE.fullmatch(target) or target in (".", ".."):
            raise ManifestError(f"a file source is a base name, never a path: {target!r}")
    if kind == "url" and m.fingerprint is None:
        raise ManifestError("a url source needs a fingerprint")
    if m.fingerprint is not None:
        if kind != "url":
            raise ManifestError("fingerprint applies to a url source only")
        f = m.fingerprint
        if type(f.size) is not int or f.size < 1:
            raise ManifestError("fingerprint.size must be a positive integer")
        match(f.chunks, SHA256_RE, "fingerprint.chunks")
        for key in ("etag", "last_modified"):
            if getattr(f, key) is not None:
                string(getattr(f, key), f"fingerprint.{key}")


def _fingerprint(table):
    if not isinstance(table, dict):
        raise ManifestError("fingerprint must be a table")
    _unknown(table, FINGERPRINT_KEYS, "fingerprint")
    missing = sorted({"size", "chunks"} - set(table))
    if missing:
        raise ManifestError(f"fingerprint is missing: {', '.join(missing)}")
    return Fingerprint(**table)


def validate(m):
    """Return m after checking every field; raise ManifestError otherwise."""
    match(m.name, NAME_RE, "name")
    _source(m)
    string(m.version, "version", 128)
    match(m.sha256, SHA256_RE, "sha256")
    if type(m.evidence_tier) is not int or m.evidence_tier not in TIERS:
        raise ManifestError(f"evidence_tier must be one of {TIERS}")
    if m.kind != "github" and m.evidence_tier not in (4, 5):
        raise ManifestError("an app from a url or a file is tier 4 (sha256 confirmed) or tier 5 (trust on first use)")
    _published_at(m.published_at)
    if m.owner_id is not None and (type(m.owner_id) is not int or m.owner_id < 1):
        raise ManifestError("owner_id must be a positive integer")
    if m.owner_id is not None and m.kind != "github":
        raise ManifestError("owner_id applies to a github source only")
    if m.channel not in CHANNELS:
        raise ManifestError(f"channel must be one of {', '.join(CHANNELS)}")
    p = m.permissions
    for key in BOOL_PERMS:
        boolean(getattr(p, key), f"permissions.{key}")
    if p.display not in DISPLAYS:
        raise ManifestError(f"permissions.display must be one of {', '.join(DISPLAYS)}")
    for n in p.dbus_filter:
        check_dbus_name(n)
    for n in p.dbus_own:
        check_dbus_own(n)
    for n in p.portal_interfaces:
        check_portal_interface(n)
    _portal_consistency(p)
    _network_consistency(p)
    for d in p.dirs:
        check_dir(string(d, "permissions.dirs entry"))
    return m


def loads(text):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"invalid TOML: {e}") from e
    _unknown(data, TOP_KEYS, "manifest")
    if data.get("schema") != SCHEMA_VERSION:
        raise ManifestError(f"schema must be {SCHEMA_VERSION}")
    missing = sorted(TOP_KEYS - {"permissions", "owner_id", "channel", "schema", "asset_pattern", "fingerprint"} - set(data))
    if missing:
        raise ManifestError(f"missing key(s): {', '.join(missing)}")
    if str(data["source"]).startswith("github:") and "asset_pattern" not in data:
        raise ManifestError("missing key(s): asset_pattern")
    return validate(Manifest(
        name=data["name"], source=data["source"], asset_pattern=data.get("asset_pattern"),
        version=data["version"], sha256=data["sha256"], evidence_tier=data["evidence_tier"],
        published_at=data["published_at"], owner_id=data.get("owner_id"), channel=data.get("channel", "stable"),
        fingerprint=_fingerprint(data["fingerprint"]) if "fingerprint" in data else None,
        permissions=_permissions(data.get("permissions", {})),
    ))


def load(path):
    return loads(Path(path).read_text(encoding="utf-8"))


def _quote(s):
    out = ['"']
    for ch in s:
        if ch == '"' or ch == "\\":
            out.append("\\" + ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _array(items):
    return "[" + ", ".join(_quote(i) for i in items) + "]"


def _fingerprint_line(f):
    parts = [f"size = {f.size}", f"chunks = {_quote(f.chunks)}"]
    if f.etag is not None:
        parts.append(f"etag = {_quote(f.etag)}")
    if f.last_modified is not None:
        parts.append(f"last_modified = {_quote(f.last_modified)}")
    return "fingerprint = { " + ", ".join(parts) + " }"


def dumps(m):
    """Deterministic TOML for a validated manifest."""
    validate(m)
    p = m.permissions
    lines = [
        f"schema = {SCHEMA_VERSION}",
        f"name = {_quote(m.name)}",
        f"source = {_quote(m.source)}",
        *([f"asset_pattern = {_quote(m.asset_pattern)}"] if m.asset_pattern is not None else []),
        f"version = {_quote(m.version)}",
        f"sha256 = {_quote(m.sha256)}",
        f"evidence_tier = {m.evidence_tier}",
        f"published_at = {_quote(m.published_at)}",
        *([f"owner_id = {m.owner_id}"] if m.owner_id is not None else []),
        *([f"channel = {_quote(m.channel)}"] if m.channel != "stable" else []),
        *([_fingerprint_line(m.fingerprint)] if m.fingerprint is not None else []),
        "",
        "[permissions]",
        f"network = {str(p.network).lower()}",
        *(["network_host = true"] if p.network_host else []),
        f"audio = {str(p.audio).lower()}",
        f"gpu = {str(p.gpu).lower()}",
        f"display = {_quote(p.display)}",
        f"dbus_filter = {_array(p.dbus_filter)}",
        f"dbus_own = {_array(p.dbus_own)}",
        f"portals = {str(p.portals).lower()}",
        f"portal_interfaces = {_array(p.portal_interfaces)}",
        f"userns = {str(p.userns).lower()}",
        f"dirs = {_array(p.dirs)}",
        "",
    ]
    return "\n".join(lines)


def dump(path, m):
    """Write atomically (temp file in the same directory, then rename)."""
    path = Path(path)
    text = dumps(m)
    tmp = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
