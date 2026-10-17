# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Local snapshot of the AM (ivan-hc/AM) catalogue, used for search only.

Everything here is text parsing. AM scripts are never sourced or executed; their content is
read through a size cap, symlinks are refused, and every string shown to the user is cleaned of
terminal escape sequences. A search hit only suggests a GitHub owner/repo: it never installs.
"""

import os
import re
import stat
from dataclasses import dataclass

from . import manifest, store, textsafe

LIST_FILE = os.path.join("programs", "x86_64-appimages")
SCRIPT_DIR = os.path.join("programs", "x86_64")
MAX_LIST_BYTES = 8 * 1024 * 1024
MAX_SCRIPT_BYTES = 256 * 1024

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,80}")
# "◆ name : description" (the bullet, and anything before the name, is ignored)
LIST_RE = re.compile(r"^[^\w\s]{0,2}\s*([A-Za-z0-9][A-Za-z0-9._+-]{0,80}) : (.*)$")
# SITE="..." / SITE2='...' / SITE=bare, possibly several assignments on one line
SITE_RE = re.compile(r"""(?:^|[\s;])(SITE2?)=(?:"([^"\n]*)"|'([^'\n]*)'|([^\s"';#]*))""", re.M)
GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/([^/\s]+/[^/\s#?]+?)(?:\.git)?(?:/.*)?")


class IndexProblem(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    description: str


@dataclass(frozen=True)
class Hit:
    name: str
    description: str
    source: str  # GitHub owner/repo suggested by the index, or ""
    note: str  # why there is no usable source, or a flag such as "repackager"


def tree_path():
    """Directory holding the checked-out snapshot (programs/... below it)."""
    return store.data_dir() / "index" / "tree"


def pinned_commit():
    try:
        return (store.data_dir() / "index" / "PINNED").read_text().split()[0]
    except (OSError, IndexError):
        return ""


def read_text(path, limit):
    """Read a regular, non-symlink file as text (invalid bytes replaced), at most limit bytes."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit).decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def parse_list(text):
    """Entries from the AM list file; lines that do not match are skipped."""
    entries = []
    for raw in text.splitlines():
        m = LIST_RE.match(textsafe.clean(raw, 600))
        if m:
            entries.append(Entry(m.group(1), m.group(2).strip()))
    return entries


def parse_sites(text):
    """(SITE, SITE2) as first assigned in the script text; '' when absent. Nothing is evaluated."""
    found = {}
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for m in SITE_RE.finditer(code):
        found.setdefault(m.group(1), next(g for g in m.groups()[1:] if g is not None))
    return found.get("SITE", ""), found.get("SITE2", "")


def classify(site):
    """(owner/repo, note) for a SITE value."""
    if not site:
        return "", "no source in the index"
    if manifest.SOURCE_RE.fullmatch(site):
        return site, ""
    m = GITHUB_URL_RE.fullmatch(site)
    if m and manifest.SOURCE_RE.fullmatch(m.group(1)):
        return m.group(1), ""
    return "", "resolve manually: " + textsafe.clean(site, 100)


def lookup(root, entry):
    script = read_text(os.path.join(root, SCRIPT_DIR, entry.name), MAX_SCRIPT_BYTES)
    if script is None:
        return Hit(entry.name, entry.description, "", "no install script in the index")
    site, site2 = parse_sites(script)
    source, note = classify(site)
    if site2:
        repack, _ = classify(site2)
        extra = f"repackager {repack}" if repack else "repackager " + textsafe.clean(site2, 100)
        note = f"{note}; {extra}" if note else extra
    return Hit(entry.name, entry.description, source, note)


def _rank(entry, words):
    name, desc = entry.name.lower(), entry.description.lower()
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


def search(keywords, root=None, limit=20):
    """Return (hits, total matches) for the keywords, best first. Raises when there is no index."""
    root = str(root or tree_path())
    text = read_text(os.path.join(root, LIST_FILE), MAX_LIST_BYTES)
    if text is None:
        raise IndexProblem("no local index; run `bjail index update` first")
    words = [w.lower() for w in keywords if w.strip()]
    if not words:
        raise IndexProblem("give at least one keyword")
    ranked = sorted((r, e) for e in parse_list(text) if (r := _rank(e, words)) is not None)
    hits = [lookup(root, e) for _, e in ranked[:limit]]
    return hits, len(ranked)
