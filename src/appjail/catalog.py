# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The catalog format: what `search` reads, whoever produced it (the AM converter, a file or a URL).

A catalog is one JSON document listing apps and, where known, where they come from: a kind-prefixed `source` that
follows the manifest's grammar (`github:owner/repo`, `gitlab:HOST/group/project`, `forgejo:HOST/owner/repo`,
`codeberg:owner/repo`, `url:https://...`). Only GitHub and URL sources can be installed today; the others are
suggestions for a later resolver. A catalog is untrusted data: parsing is strict and bounded, every text is stripped of terminal escape sequences, and nothing in
it is ever executed. A catalog only suggests; `appjail add` still asks for the repository. See README.md "Search".
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import manifest, textsafe
from .valid import ManifestError

FORMAT = "appjail-catalog"
VERSION = 1
MAX_BYTES = 16 * 1024 ** 2
MAX_APPS = 50_000
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,80}")
TOP_KEYS = {"format", "version", "origin", "revision", "apps"}
APP_KEYS = {"name", "description", "source", "note"}
DESCRIPTION_MAX = 300
SOURCE_MAX = 2048
NOTE_MAX = 200
LABEL_MAX = 300


class IndexProblem(Exception):
    """A catalog or index operation cannot proceed; the message says why."""


HOST_RE = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]")
SEGMENT_RE = re.compile(r"(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}")
CODEBERG_HOST = "codeberg.org"
KINDS = ("github", "gitlab", "forgejo", "codeberg", "url")
INSTALLABLE = ("github", "url")  # the kinds `appjail add` can resolve today


def _forge_path(target, minimum, maximum):
    parts = target.split("/")
    if not minimum <= len(parts) <= maximum or not all(SEGMENT_RE.fullmatch(p) for p in parts):
        raise ValueError(f"expected {minimum if minimum == maximum else f'{minimum} or more'} path segment(s) "
                         f"of letters, digits, '.', '_' and '-'")
    return "/".join(parts)


def _host_path(target, minimum, maximum):
    host, sep, path = target.partition("/")
    if not sep or not HOST_RE.fullmatch(host.lower()):
        raise ValueError("expected HOST/path with a DNS host name (no port, no credentials)")
    return f"{host.lower()}/{_forge_path(path, minimum, maximum)}"


def parse_source(value):
    """(kind, target) of a catalog `source`, normalized: `codeberg:` becomes `forgejo:codeberg.org/`, hosts are
    lowercased. ValueError says what is wrong. Nothing is contacted; syntax only."""
    kind, sep, target = value.partition(":")
    if not sep or kind not in KINDS:
        raise ValueError(f"must start with one of {', '.join(k + ':' for k in KINDS)}")
    if kind == "github":
        if not manifest.REPO_RE.fullmatch(target):
            raise ValueError("expected github:owner/repo")
    elif kind == "gitlab":
        target = _host_path(target, 2, 20)
    elif kind == "forgejo":
        target = _host_path(target, 2, 2)
    elif kind == "codeberg":
        kind, target = "forgejo", f"{CODEBERG_HOST}/{_forge_path(target, 2, 2)}"
    else:
        try:
            manifest.check_url(target)
        except ManifestError as e:
            raise ValueError(str(e)) from e
    return kind, target


def identity(source):
    """Who stands behind a normalized source, for spotting a change of owner: kind, host and owner, lowercase
    (`github:cli`, `gitlab:gitlab.com/group`, `forgejo:codeberg.org/user`, `url:example.org`)."""
    kind, _, target = source.partition(":")
    if kind == "url":
        return f"url:{(urlsplit(target).hostname or '').lower()}"
    if kind == "github":
        return f"github:{target.split('/', 1)[0].lower()}"
    host, _, path = target.partition("/")
    return f"{kind}:{host}/{path.split('/', 1)[0].lower()}"


@dataclass(frozen=True)
class App:
    name: str
    description: str = ""
    source: str = ""  # normalized "kind:target" (see parse_source), or "" when the catalog does not know one
    note: str = ""  # why there is no usable source, or a flag such as "repackager ..."


@dataclass(frozen=True)
class Catalog:
    apps: tuple
    origin: str = ""  # where it came from, for the user's eyes
    revision: str = ""  # a commit, a date, a version: whatever tells two states of the catalog apart


def _string(value, what, limit, required=False):
    if not isinstance(value, str):
        raise IndexProblem(f"{what} must be a string")
    cleaned = textsafe.clean(value, limit).strip()
    if required and not cleaned:
        raise IndexProblem(f"{what} must not be empty")
    return cleaned


def _app(raw, position):
    where = f"apps[{position}]"
    if not isinstance(raw, dict):
        raise IndexProblem(f"{where} must be an object")
    unknown = sorted(set(raw) - APP_KEYS)
    if unknown:
        raise IndexProblem(f"{where} has unknown key(s): {', '.join(map(str, unknown))}")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise IndexProblem(f"{where}: name must match {NAME_RE.pattern}")
    source = _string(raw.get("source", ""), f"{where}.source", SOURCE_MAX)
    if source:
        try:
            source = "{}:{}".format(*parse_source(source))
        except ValueError as e:
            raise IndexProblem(f"{where} ({name}): invalid source: {e} (other locations go in note)") from e
    return App(name, _string(raw.get("description", ""), f"{where}.description", DESCRIPTION_MAX), source,
               _string(raw.get("note", ""), f"{where}.note", NOTE_MAX))


def parse(text):
    """The Catalog in `text` (a JSON document); IndexProblem if it does not follow the format."""
    if len(text) > MAX_BYTES:
        raise IndexProblem("the catalog is too large")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:
        raise IndexProblem(f"the catalog is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise IndexProblem("the catalog must be a JSON object")
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise IndexProblem(f"unknown top-level key(s): {', '.join(map(str, unknown))}")
    if data.get("format") != FORMAT:
        raise IndexProblem(f'"format" must be "{FORMAT}"')
    if data.get("version") != VERSION or type(data.get("version")) is not int:
        raise IndexProblem(f'unsupported catalog version (this appjail reads version {VERSION})')
    raw_apps = data.get("apps")
    if not isinstance(raw_apps, list):
        raise IndexProblem('"apps" must be a list')
    if len(raw_apps) > MAX_APPS:
        raise IndexProblem(f"too many apps (more than {MAX_APPS})")
    apps = tuple(_app(raw, i) for i, raw in enumerate(raw_apps))
    seen = set()
    for app in apps:
        if app.name in seen:
            raise IndexProblem(f"duplicate app name: {app.name}")
        seen.add(app.name)
    return Catalog(apps, _string(data.get("origin", ""), "origin", LABEL_MAX), _string(data.get("revision", ""), "revision", LABEL_MAX))


def dumps(catalog):
    """The deterministic JSON text of a catalog (apps sorted by name)."""
    head = {"format": FORMAT, "version": VERSION}
    if catalog.origin:
        head["origin"] = catalog.origin
    if catalog.revision:
        head["revision"] = catalog.revision
    apps = []
    for app in sorted(catalog.apps, key=lambda a: a.name):
        entry = {"name": app.name}
        for key in ("description", "source", "note"):
            if getattr(app, key):
                entry[key] = getattr(app, key)
        apps.append(entry)
    return json.dumps({**head, "apps": apps}, ensure_ascii=False, indent=1) + "\n"


def by_name(catalog):
    return {app.name: app for app in catalog.apps}
