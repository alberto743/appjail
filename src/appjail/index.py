# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Search over the catalogs of the local index. A hit only suggests a GitHub owner/repo: it never installs."""

from dataclasses import dataclass

from . import indexstore
from .catalog import IndexProblem


@dataclass(frozen=True)
class Hit:
    name: str
    description: str
    source: str  # GitHub owner/repo suggested by the catalog, or ""
    note: str  # why there is no usable source, or a flag such as "repackager"
    catalog: str  # the name of the index source it came from


def _rank(app, words):
    name, desc = app.name.lower(), app.description.lower()
    if not all(w in name or w in desc for w in words):
        return None
    phrase = " ".join(words)
    if name == phrase:
        tier = 0
    elif name.startswith(words[0]):
        tier = 1
    elif all(w in name for w in words):
        tier = 2
    elif any(w in name for w in words):
        tier = 3
    else:
        tier = 4
    return tier, name


def search(keywords, limit=20):
    """Return (hits, total matches, catalogs searched) for the keywords, best first, over every source with a
    catalog. Raises when there is no index or no keyword."""
    searched = indexstore.loaded()
    if not searched:
        raise IndexProblem("no local index; run `appjail index update` first")
    words = [w.lower() for w in keywords if w.strip()]
    if not words:
        raise IndexProblem("give at least one keyword")
    ranked = sorted((r, source.name, app) for source, cat in searched for app in cat.apps
                    if (r := _rank(app, words)) is not None)
    hits = [Hit(app.name, app.description, app.source, app.note, catalog_name) for _, catalog_name, app in ranked[:limit]]
    return hits, len(ranked), [s.name for s, _ in searched]
