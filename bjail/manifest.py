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

SCHEMA_VERSION = 1

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# GitHub owners are alphanumeric/hyphen; repos may also hold "_" and "." but are never "." or "..".
SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PUBLISHED_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
DBUS_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+(\.\*)?")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

TIERS = (1, 2, 3, 4, 5)
DISPLAYS = ("wayland", "xwayland")

TOP_KEYS = {
    "schema", "name", "source", "asset_pattern", "version", "sha256",
    "evidence_tier", "published_at", "permissions",
}
PERM_KEYS = {"network", "audio", "gpu", "display", "dbus_filter", "portals", "dirs"}


class ManifestError(ValueError):
    """The manifest is malformed or violates the schema."""


@dataclass(frozen=True)
class Permissions:
    """Everything is denied unless granted."""
    network: bool = False
    audio: bool = False
    gpu: bool = False
    display: str = "wayland"
    dbus_filter: tuple = ()
    portals: bool = False
    dirs: tuple = ()  # "path" (read-only) or "path:rw"; absolute or starting with "~/"


@dataclass(frozen=True)
class Manifest:
    name: str
    source: str  # GitHub "owner/repo"
    asset_pattern: str  # fnmatch pattern for the release asset name
    version: str
    sha256: str
    evidence_tier: int
    published_at: str  # UTC, YYYY-MM-DDTHH:MM:SSZ
    permissions: Permissions = field(default_factory=Permissions)


def _text(value, what, max_len=256):
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{what} must be a non-empty string")
    if len(value) > max_len or CONTROL_RE.search(value):
        raise ManifestError(f"{what} is too long or contains control characters")
    return value


def _match(value, regex, what):
    _text(value, what)
    if not regex.fullmatch(value):
        raise ManifestError(f"{what} has an invalid format: {value!r}")
    return value


def _bool(value, what):
    if not isinstance(value, bool):
        raise ManifestError(f"{what} must be true or false")
    return value


def _str_list(value, what):
    if not isinstance(value, list):
        raise ManifestError(f"{what} must be a list of strings")
    return [_text(v, f"{what} entry") for v in value]


def _check_dir(entry):
    path, _, mode = entry.partition(":")
    if mode not in ("", "ro", "rw"):
        raise ManifestError(f"dirs entry {entry!r}: mode must be ro or rw")
    if not (path.startswith("/") or path.startswith("~/")):
        raise ManifestError(f"dirs entry {entry!r}: path must be absolute or start with ~/")
    if path in ("/", "~/") or ".." in path.split("/"):
        raise ManifestError(f"dirs entry {entry!r}: path is too broad or contains '..'")
    return entry


def _unknown(table, allowed, where):
    extra = sorted(set(table) - allowed)
    if extra:
        raise ManifestError(f"unknown key(s) in {where}: {', '.join(map(str, extra))}")


def _permissions(table):
    if not isinstance(table, dict):
        raise ManifestError("permissions must be a table")
    _unknown(table, PERM_KEYS, "[permissions]")
    perms = {}
    for key in ("network", "audio", "gpu", "portals"):
        if key in table:
            perms[key] = _bool(table[key], f"permissions.{key}")
    if "display" in table:
        if table["display"] not in DISPLAYS:
            raise ManifestError(f"permissions.display must be one of {', '.join(DISPLAYS)}")
        perms["display"] = table["display"]
    if "dbus_filter" in table:
        names = _str_list(table["dbus_filter"], "permissions.dbus_filter")
        for n in names:
            _match(n, DBUS_NAME_RE, "permissions.dbus_filter entry")
        perms["dbus_filter"] = tuple(names)
    if "dirs" in table:
        perms["dirs"] = tuple(_check_dir(d) for d in _str_list(table["dirs"], "permissions.dirs"))
    return Permissions(**perms)


def _published_at(value):
    _match(value, PUBLISHED_RE, "published_at")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ManifestError(f"published_at is not a valid date: {value!r}") from e
    return value


def validate(m):
    """Return m after checking every field; raise ManifestError otherwise."""
    _match(m.name, NAME_RE, "name")
    _match(m.source, SOURCE_RE, "source")
    _text(m.asset_pattern, "asset_pattern")
    if "/" in m.asset_pattern:
        raise ManifestError("asset_pattern must not contain '/'")
    _text(m.version, "version", 128)
    _match(m.sha256, SHA256_RE, "sha256")
    if type(m.evidence_tier) is not int or m.evidence_tier not in TIERS:
        raise ManifestError(f"evidence_tier must be one of {TIERS}")
    _published_at(m.published_at)
    p = m.permissions
    for key in ("network", "audio", "gpu", "portals"):
        _bool(getattr(p, key), f"permissions.{key}")
    if p.display not in DISPLAYS:
        raise ManifestError(f"permissions.display must be one of {', '.join(DISPLAYS)}")
    for n in p.dbus_filter:
        _match(n, DBUS_NAME_RE, "permissions.dbus_filter entry")
    for d in p.dirs:
        _check_dir(_text(d, "permissions.dirs entry"))
    return m


def loads(text):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"invalid TOML: {e}") from e
    _unknown(data, TOP_KEYS, "manifest")
    if data.get("schema") != SCHEMA_VERSION:
        raise ManifestError(f"schema must be {SCHEMA_VERSION}")
    missing = sorted(TOP_KEYS - {"permissions"} - {"schema"} - set(data))
    if missing:
        raise ManifestError(f"missing key(s): {', '.join(missing)}")
    return validate(Manifest(
        name=data["name"], source=data["source"], asset_pattern=data["asset_pattern"],
        version=data["version"], sha256=data["sha256"], evidence_tier=data["evidence_tier"],
        published_at=data["published_at"], permissions=_permissions(data.get("permissions", {})),
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


def dumps(m):
    """Deterministic TOML for a validated manifest."""
    validate(m)
    p = m.permissions
    lines = [
        f"schema = {SCHEMA_VERSION}",
        f"name = {_quote(m.name)}",
        f"source = {_quote(m.source)}",
        f"asset_pattern = {_quote(m.asset_pattern)}",
        f"version = {_quote(m.version)}",
        f"sha256 = {_quote(m.sha256)}",
        f"evidence_tier = {m.evidence_tier}",
        f"published_at = {_quote(m.published_at)}",
        "",
        "[permissions]",
        f"network = {str(p.network).lower()}",
        f"audio = {str(p.audio).lower()}",
        f"gpu = {str(p.gpu).lower()}",
        f"display = {_quote(p.display)}",
        f"dbus_filter = {_array(p.dbus_filter)}",
        f"portals = {str(p.portals).lower()}",
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
