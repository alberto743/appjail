# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`bjail search` and `bjail index update`."""

import secrets
import shutil

from . import index, indexsync, store
from .console import Abort


def cmd_search(args, console):
    hits, total = index.search(args.keywords, limit=args.limit if not args.all else 10 ** 9)
    commit = index.pinned_commit()
    console.out(f"{total} match(es)" + (f" in the AM index at {commit[:12]}" if commit else "")
                + (f", showing {len(hits)}" if len(hits) < total else ""))
    for h in hits:
        console.out(f"{h.name}: {h.description}")
        if h.source:
            console.out(f"    source {h.source}   ->  bjail add {h.source}")
        if h.note:
            console.out(f"    ({h.note})")
    if hits:
        console.out("A hit is only a suggestion: check the owner and repository yourself before `bjail add`.")


def cmd_index_update(args, console, fetch=indexsync.fetch):
    base = store.data_dir() / "index"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = base / f"work-{secrets.token_hex(6)}"
    work.mkdir(mode=0o700)
    try:
        console.out(f"Fetching the AM index ({args.commit}) in a network-only jail…")
        got = fetch(work, args.commit)
        if got.commit == indexsync.current():
            console.out(f"The index is already at {got.commit[:12]}.")
            return
        staged = base / f"staged-{got.commit[:12]}"
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(mode=0o700)
        try:
            copied, skipped = indexsync.collect(got.tree, staged)
            console.out(f"Fetched commit {got.commit}: {copied} install scripts"
                        + (f", {skipped} odd file names skipped" if skipped else "")
                        + (", signature header present (not verified)" if got.signed else ", unsigned"))
            old = indexsync.current()
            if old and indexsync.snapshot_path(old).is_dir():
                d = indexsync.diff(indexsync.snapshot_path(old), staged)
                show_index_diff(console, old, d)
            else:
                console.out("There is no previous index to compare with.")
            if not console.confirm("Accept this snapshot as the current index?"):
                raise Abort("cancelled; the index is unchanged")
            indexsync.install(staged, got.commit, got.signed)
        finally:
            shutil.rmtree(staged, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    console.out(f"Index pinned at {got.commit[:12]}. Previous: {(indexsync.previous() or 'none')[:12]}.")


def cmd_index_rollback(console):
    a, b = indexsync.rollback()
    console.out(f"Index rolled back from {a[:12]} to {b[:12]}.")


def cmd_index_status(console):
    cur, prev = indexsync.current(), indexsync.previous()
    console.out(f"Pinned: {cur or 'no index yet'}" + (f"; previous: {prev}" if prev else ""))


def show_index_diff(console, old, d):
    console.out(f"Changes since {old[:12]}: {len(d.added)} apps added, {len(d.removed)} removed, "
                f"{len(d.owner_changed)} owner changes, {len(d.source_changed)} other source changes")
    for label, names in (("added", d.added), ("removed", d.removed)):
        if names:
            console.out(f"  {label}: " + ", ".join(names[:15]) + (f", … (+{len(names) - 15})" if len(names) > 15 else ""))
    for name, a, b in d.owner_changed:
        console.warn(f"OWNER CHANGE for {name}: {a} -> {b}. Check this before adding it.")
    for name, a, b in d.source_changed[:20]:
        console.out(f"  source changed: {name}: {a} -> {b}")
    if len(d.source_changed) > 20:
        console.out(f"  … and {len(d.source_changed) - 20} more source changes")
