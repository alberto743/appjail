# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The local index: the registered sources and, for each, the current and the previous catalog.

Layout under `~/.local/share/appjail/index/`:
    sources.json          the sources added with `index add` (the built-in `am` is implicit)
    <name>/current.json   the catalog `search` reads
    <name>/previous.json  the one before it, for `index rollback`
    <name>/state.json     sha256, revision and update time of both
Only the current and the previous catalog are kept. The index only feeds `search`; installed apps never depend on it.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

from . import catalog, store
from .catalog import IndexProblem

BUILTIN = "am"
SOURCE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
KINDS = ("am", "url", "file")


@dataclass(frozen=True)
class Source:
    name: str
    kind: str  # am | url | file
    location: str = ""  # the URL, or the file's base name (a file source is a copy: update re-reads the path given)


@dataclass(frozen=True)
class Diff:
    added: tuple
    removed: tuple
    owner_changed: tuple  # (name, old owner/repo, new owner/repo)
    source_changed: tuple


def base():
    return store.data_dir() / "index"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def check_name(name):
    if not SOURCE_RE.fullmatch(name or "!"):
        raise IndexProblem(f"a source name is 1-32 characters of {SOURCE_RE.pattern}: {name!r}")
    return name


# -- registered sources ---------------------------------------------------------------------------


def sources():
    """Every source, the built-in `am` first, then the added ones by name."""
    found = {BUILTIN: Source(BUILTIN, "am")}
    try:
        data = json.loads((base() / "sources.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return found
    except (OSError, ValueError) as e:
        raise IndexProblem(f"cannot read the registered index sources: {e}") from e
    raw = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise IndexProblem("the registered index sources are malformed")
    for name in sorted(raw):
        spec = raw[name]
        if (not SOURCE_RE.fullmatch(name) or name == BUILTIN or not isinstance(spec, dict)
                or spec.get("kind") not in ("url", "file") or not isinstance(spec.get("location"), str)):
            raise IndexProblem(f"the registered index source {name!r} is malformed")
        found[name] = Source(name, spec["kind"], spec["location"])
    return found


def get(name):
    try:
        return sources()[name]
    except KeyError:
        raise IndexProblem(f"unknown index source '{name}' (see `appjail index status`)") from None


def _save_sources(found):
    extra = {n: {"kind": s.kind, "location": s.location} for n, s in found.items() if n != BUILTIN}
    _write(base() / "sources.json", json.dumps({"sources": extra}, indent=1, sort_keys=True) + "\n")


def register(source):
    found = sources()
    check_name(source.name)
    if source.name in found:
        raise IndexProblem(f"index source '{source.name}' already exists")
    found[source.name] = source
    _save_sources(found)


def unregister(name):
    found = sources()
    if name == BUILTIN:
        raise IndexProblem("the built-in source cannot be removed")
    if name not in found:
        raise IndexProblem(f"unknown index source '{name}'")
    del found[name]
    _save_sources(found)
    shutil.rmtree(base() / name, ignore_errors=True)


# -- snapshots ------------------------------------------------------------------------------------


def _state(name):
    try:
        data = json.loads((base() / name / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"current": None, "previous": None}
    except (OSError, ValueError) as e:
        raise IndexProblem(f"cannot read the state of index source '{name}': {e}") from e
    ok = isinstance(data, dict) and all(
        data.get(k) is None or (isinstance(data.get(k), dict) and all(isinstance(v, str) for v in data[k].values()))
        for k in ("current", "previous"))
    if not ok:
        raise IndexProblem(f"the state of index source '{name}' is malformed")
    return {"current": data.get("current"), "previous": data.get("previous")}


def current(name):
    """{"sha256", "revision", "updated"} of the current catalog, or None when the source has none yet."""
    return _state(name)["current"]


def previous(name):
    return _state(name)["previous"]


def load(name, which="current"):
    """The Catalog of a source (current or previous), or None when it has none."""
    path = base() / name / f"{which}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise IndexProblem(f"cannot read {path}: {e}") from e
    return catalog.parse(text)


def loaded():
    """[(source, Catalog)] for every source that has a current catalog."""
    out = []
    for source in sources().values():
        cat = load(source.name)
        if cat is not None:
            out.append((source, cat))
    return out


def install(name, text, now=None):
    """Make the catalog `text` (already validated by the caller) the current one, keeping the old one for rollback.
    Returns False when it is byte for byte the current catalog."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    state = _state(name)
    if state["current"] and state["current"]["sha256"] == digest:
        return False
    cat = catalog.parse(text)
    directory = base() / name
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state["current"]:
        os.replace(directory / "current.json", directory / "previous.json")
    _write(directory / "current.json", text)
    entry = {"sha256": digest, "revision": cat.revision, "updated": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    _write(directory / "state.json", json.dumps({"current": entry, "previous": state["current"]}, indent=1) + "\n")
    return True


def rollback(name):
    """Swap the current and previous catalogs (so it can be undone). Returns (from entry, to entry)."""
    state = _state(name)
    directory = base() / name
    if not state["previous"] or not (directory / "previous.json").is_file():
        raise IndexProblem(f"index source '{name}' has no previous catalog to roll back to")
    tmp = directory / "swap.json"
    os.replace(directory / "current.json", tmp)
    os.replace(directory / "previous.json", directory / "current.json")
    os.replace(tmp, directory / "previous.json")
    _write(directory / "state.json", json.dumps({"current": state["previous"], "previous": state["current"]}, indent=1) + "\n")
    return state["current"], state["previous"]


# -- review ---------------------------------------------------------------------------------------


def _owner(source):
    return source.split("/", 1)[0].lower()


def diff(old, new):
    """Compare two catalogs: apps added or removed and changed GitHub sources."""
    a, b = catalog.by_name(old), catalog.by_name(new)
    owner_changed, source_changed = [], []
    for name in sorted(a.keys() & b.keys()):
        x, y = a[name].source, b[name].source
        if x == y:
            continue
        if x and y and _owner(x) != _owner(y):
            owner_changed.append((name, x, y))
        else:
            source_changed.append((name, x or "(none)", y or "(none)"))
    return Diff(tuple(sorted(b.keys() - a.keys())), tuple(sorted(a.keys() - b.keys())),
                tuple(owner_changed), tuple(source_changed))
