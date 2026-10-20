# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Fetch, review, pin and roll back the AM index snapshot.

git runs only inside a network-only jail, without hooks, filters, submodules or LFS, and fetches
only the two paths bjail reads. The host never runs git on the result: it copies plain regular
files out of the jail's work tree into a snapshot directory after strict checks. The index only
feeds `search`; installed apps never depend on it.
"""

import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from . import index, jail, store, textsafe

AM_URL = "https://github.com/ivan-hc/AM"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
MAX_WORK_BYTES = 1536 * 1024 ** 2
MAX_WORK_ENTRIES = 300_000
MAX_FILES = 30_000

GIT_SCRIPT = r"""set -eu
G="git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.attributesFile=/dev/null \
-c submodule.recurse=false -c advice.detachedHead=false -c gc.auto=0 \
-c protocol.allow=never -c protocol.https.allow=always"
$G init -q repo
cd repo
$G config core.repositoryformatversion 1
$G config extensions.partialclone origin
$G remote add origin "$2"
$G config remote.origin.promisor true
$G config remote.origin.partialclonefilter blob:none
$G sparse-checkout set --no-cone /programs/x86_64-appimages /programs/x86_64/
$G fetch -q --depth 1 --filter=blob:none --no-tags --no-recurse-submodules origin "$1"
$G checkout -q --detach FETCH_HEAD
echo "commit $($G rev-parse HEAD)"
if $G cat-file commit HEAD | sed '/^$/q' | grep -q '^gpgsig'; then echo "signed yes"; else echo "signed no"; fi
"""


class IndexRefused(Exception):
    """The fetched tree violates a rule; nothing is installed."""


@dataclass(frozen=True)
class Fetched:
    commit: str
    signed: bool  # a signature header is present; it is not verified
    tree: Path  # directory containing programs/...


@dataclass(frozen=True)
class Diff:
    added: tuple
    removed: tuple
    owner_changed: tuple  # (name, old owner/repo, new owner/repo)
    source_changed: tuple


def fetch(workdir, commit="HEAD", url=AM_URL, run=jail.run):
    """Fetch the requested commit (or the remote HEAD) into workdir inside the git jail."""
    if commit != "HEAD" and not COMMIT_RE.fullmatch(commit):
        raise IndexRefused("commit must be a 40-digit lowercase hex id or HEAD")
    cmd = ["/bin/sh", "-c", GIT_SCRIPT, "sh", commit, url]
    proc = run(jail.git_args(workdir, cmd), timeout=1200, watch=(workdir, MAX_WORK_BYTES, MAX_WORK_ENTRIES))
    if proc.returncode != 0:
        raise IndexRefused("git failed: " + textsafe.clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
    out = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if " " in line)
    if not COMMIT_RE.fullmatch(out.get("commit", "")):
        raise IndexRefused("could not determine the fetched commit")
    return Fetched(out["commit"], out.get("signed") == "yes", Path(workdir) / "repo")


def collect(src_root, dest):
    """Copy programs/{x86_64-appimages, x86_64/*} from an untrusted work tree into dest.

    Only regular files are accepted: a symlink, special file or unexpected directory refuses the
    whole snapshot. Odd file names are skipped and counted. Returns (files copied, names skipped).
    """
    src, dest = Path(src_root) / "programs", Path(dest) / "programs"
    list_src = src / "x86_64-appimages"
    scripts = src / "x86_64"
    for p in (list_src, scripts):
        if not p.exists() and not p.is_symlink():
            raise IndexRefused(f"missing {p.relative_to(Path(src_root))} in the fetched tree")

    def regular(path, limit):
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            raise IndexRefused(f"not a regular file: {textsafe.clean(os.path.relpath(path, src_root), 200)}")
        if st.st_size > limit:
            raise IndexRefused(f"unexpectedly large file: {textsafe.clean(os.path.relpath(path, src_root), 200)}")

    dest.mkdir(parents=True, mode=0o700)
    (dest / "x86_64").mkdir(mode=0o700)
    regular(list_src, index.MAX_LIST_BYTES)
    shutil.copyfile(list_src, dest / "x86_64-appimages", follow_symlinks=False)
    os.chmod(dest / "x86_64-appimages", 0o600)
    if not stat.S_ISDIR(os.lstat(scripts).st_mode):
        raise IndexRefused("programs/x86_64 is not a directory")
    copied = skipped = 0
    with os.scandir(scripts) as it:
        for entry in it:
            if copied + skipped >= MAX_FILES:
                raise IndexRefused("too many files in the index")
            if not index.NAME_RE.fullmatch(entry.name):
                skipped += 1
                continue
            regular(entry.path, index.MAX_SCRIPT_BYTES)
            shutil.copyfile(entry.path, dest / "x86_64" / entry.name, follow_symlinks=False)
            os.chmod(dest / "x86_64" / entry.name, 0o600)
            copied += 1
    if not index.parse_list(index.read_text(str(dest / "x86_64-appimages"), index.MAX_LIST_BYTES) or ""):
        raise IndexRefused("the fetched list contains no apps")
    return copied, skipped


def _owner(source):
    return source.split("/", 1)[0].lower()


def diff(old_root, new_root):
    """Compare two snapshots: apps added or removed and changed GitHub sources."""
    def entries(root):
        text = index.read_text(os.path.join(root, index.LIST_FILE), index.MAX_LIST_BYTES) or ""
        return {e.name: e for e in index.parse_list(text)}

    old, new = entries(old_root), entries(new_root)
    owner_changed, source_changed = [], []
    for name in sorted(old.keys() & new.keys()):
        a = index.lookup(str(old_root), old[name]).source
        b = index.lookup(str(new_root), new[name]).source
        if a == b:
            continue
        if a and b and _owner(a) != _owner(b):
            owner_changed.append((name, a, b))
        else:
            source_changed.append((name, a or "(none)", b or "(none)"))
    return Diff(tuple(sorted(new.keys() - old.keys())), tuple(sorted(old.keys() - new.keys())),
                tuple(owner_changed), tuple(source_changed))


# -- pinned state ---------------------------------------------------------------------------------


def _dir():
    return store.data_dir() / "index"


def _read(name):
    try:
        return (_dir() / name).read_text().split()[0]
    except (OSError, IndexError):
        return ""


def current():
    return index.pinned_commit()


def previous():
    return _read("PREVIOUS")


def snapshot_path(commit):
    return _dir() / "snapshots" / commit


def _point_tree_at(commit):
    link, tmp = _dir() / "tree", _dir() / "tree.new"
    tmp.unlink(missing_ok=True)
    os.symlink(os.path.join("snapshots", commit), tmp)
    os.replace(tmp, link)


def _write(name, text):
    tmp = _dir() / (name + ".new")
    tmp.write_text(text)
    tmp.chmod(0o600)
    os.replace(tmp, _dir() / name)


def install(staged, commit, signed=False):
    """Make the staged snapshot current, keeping the previous one for rollback."""
    _dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    (_dir() / "snapshots").mkdir(exist_ok=True, mode=0o700)
    old = current()
    target = snapshot_path(commit)
    if target.exists():
        shutil.rmtree(staged, ignore_errors=True)
    else:
        os.replace(staged, target)
    if old and old != commit:
        _write("PREVIOUS", old + "\n")
    _write("PINNED", f"{commit}\nsigned={'yes' if signed else 'no'}\n")
    _point_tree_at(commit)
    keep = {commit, previous(), current()} - {""}
    for p in (_dir() / "snapshots").iterdir():
        if p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)


def rollback():
    """Swap the current and previous snapshots. Returns (from commit, to commit)."""
    prev, cur = previous(), current()
    if not prev or not snapshot_path(prev).is_dir():
        raise IndexRefused("there is no previous index snapshot to roll back to")
    _write("PREVIOUS", cur + "\n")
    _write("PINNED", f"{prev}\nsigned=unknown\n")
    _point_tree_at(prev)
    return cur, prev
