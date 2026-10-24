# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail search` and `appjail index add|remove|update|rollback|status`."""

import hashlib
import shutil
from urllib.parse import urlsplit

from . import catalog, github, index, indexstore, jail, manifest, store
from .catalog import IndexProblem
from .console import Abort, human_size
from .imagesrc import regular_file


def add_hint(source):
    kind, _, target = source.partition(":")
    if kind not in catalog.INSTALLABLE:
        return "(no resolver for this forge yet: appjail add cannot install it)"
    if kind == "github":
        return f"->  appjail add {target}"
    return f"->  appjail add --url {target}"


def cmd_search(args, console):
    hits, total, searched = index.search(args.keywords, limit=args.limit if not args.all else 10 ** 9)
    many = len(searched) > 1
    console.out(f"{total} match(es) in {', '.join(searched)}" + (f", showing {len(hits)}" if len(hits) < total else ""))
    for h in hits:
        console.out(f"{h.name}: {h.description}" + (f"   [{h.catalog}]" if many else ""))
        if h.source:
            console.out(f"    source {h.source}   {add_hint(h.source)}")
        if h.note:
            console.out(f"    ({h.note})")
    if hits:
        console.out("A hit is only a suggestion: check the owner and repository yourself before `appjail add`.")


# -- getting a catalog from a source --------------------------------------------------------------


def read_catalog_file(path):
    """The text of a local catalog file (regular, size-capped, UTF-8)."""
    try:
        real, st = regular_file(path)
    except Abort as e:
        raise IndexProblem(str(e).replace("--file ", "")) from e
    if st.st_size > catalog.MAX_BYTES:
        raise IndexProblem("the catalog file is too large")
    try:
        return real.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise IndexProblem(f"cannot read the catalog file: {e}") from e


def download_catalog(url, download_url, console):
    try:
        stage = store.new_staging_dir()
    except OSError as e:
        raise IndexProblem(f"cannot prepare a download directory: {e}") from e
    try:
        path, info = download_url(url, stage, "catalog.json", catalog.MAX_BYTES)
        if info["http_hop"]:
            console.warn("a redirect went through plain http: anyone on the path could have changed the catalog")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise IndexProblem(f"cannot read the downloaded catalog as UTF-8 text: {e}") from e
    except jail.JailError as e:
        raise IndexProblem(str(e)) from e
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def fetch_repo(source, args, console, client, download_url):
    """The catalog of a GitHub repository at one commit: the latest unless --commit names one. Returns (text, commit);
    the download is of that commit's file, so the commit is exactly what the review and the state record."""
    try:
        commit = client.head_commit(source.location) if args.commit == "HEAD" else args.commit
    except github.GitHubError as e:
        raise IndexProblem(str(e)) from e
    console.out(f"Fetching {source.location} at {commit[:12]} in a network-only jail…")
    url = f"https://raw.githubusercontent.com/{source.location}/{commit}/{indexstore.CATALOG_FILE}"
    return download_catalog(url, download_url, console), commit


def fetch_text(source, args, console, client, download_url):
    """(validated catalog text, commit or "") of a source."""
    commit = ""
    if source.kind == "repo":
        text, commit = fetch_repo(source, args, console, client, download_url)
    elif source.kind == "url":
        console.out(f"Fetching {source.location} in a network-only jail…")
        text = download_catalog(source.location, download_url, console)
    else:
        text = read_catalog_file(source.location)
    return catalog.dumps(catalog.parse(text)), commit  # what is stored is what was validated


# -- reviewing and accepting it -------------------------------------------------------------------


def review_and_install(source, text, console, now=None, commit=""):
    """Show what the new catalog is and how it differs from the current one; install it if the user agrees.
    Returns 'updated' or 'current'."""
    new = catalog.parse(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    now_entry = indexstore.current(source.name)
    if now_entry and now_entry["sha256"] == digest:
        console.out(f"{source.name}: already up to date ({len(new.apps)} apps).")
        return "current"
    console.out(f"{source.name}: {len(new.apps)} apps, {human_size(len(text.encode('utf-8')))}"
                + (f", revision {new.revision[:40]}" if new.revision else "") + (f", commit {commit[:12]}" if commit else "")
                + f", sha256 {digest[:16]}")
    old = indexstore.load(source.name)
    if old is not None:
        show_diff(console, now_entry.get("commit") or now_entry.get("revision") or "the current catalog",
                  indexstore.diff(old, new))
    else:
        console.out("There is no previous catalog to compare with.")
    if not console.confirm(f"Accept this catalog as the current one for '{source.name}'?"):
        raise Abort("cancelled; the index is unchanged")
    indexstore.install(source.name, text, now, digest, new, commit)
    return "updated"


def show_diff(console, since, d):
    console.out(f"Changes since {since[:12]}: {len(d.added)} apps added, {len(d.removed)} removed, "
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


# -- commands -------------------------------------------------------------------------------------


def cmd_index_update(args, console, client=None, download_url=jail.download_url, now=None):
    """Refresh one source or all of them; the status is 1 if any failed or was declined for a problem."""
    names = [args.name] if args.name else list(indexstore.sources())
    indexstore.sweep()
    if args.commit != "HEAD":
        if names != [indexstore.BUILTIN]:
            raise Abort(f"--commit applies to the built-in '{indexstore.BUILTIN}' source only "
                        f"(`appjail index update {indexstore.BUILTIN} --commit SHA`)")
        if not github.COMMIT_RE.fullmatch(args.commit):
            raise Abort("--commit must be 40 lowercase hexadecimal digits")
    client = client or github.Client()
    status = 0
    for name in names:
        source = indexstore.get(name)
        try:
            text, commit = fetch_text(source, args, console, client, download_url)
            review_and_install(source, text, console, now, commit)
        except (IndexProblem, Abort) as e:
            console.out(f"{name}: {e}")
            status = 1
    return status


def cmd_index_add(args, console, download_url=jail.download_url, now=None):
    name = indexstore.check_name(args.name)
    if name in indexstore.sources():
        raise Abort(f"index source '{name}' already exists")
    if args.url:
        try:
            url = manifest.check_url(args.url)
        except manifest.ManifestError as e:
            raise Abort(f"--url: {e}") from e
        source = indexstore.Source(name, "url", url)
        console.out(f"Catalog URL: {url} (host {urlsplit(url).hostname})")
    else:
        real, _ = regular_file(args.file)
        source = indexstore.Source(name, "file", str(real))
        console.out(f"Catalog file: {real}")
    console.warn("a catalog only suggests repositories; nothing in it is trusted or run")
    text, _ = fetch_text(source, args, console, None, download_url)
    review_and_install_new(source, text, console, now)


def review_and_install_new(source, text, console, now):
    """The first catalog of a new source: register the source only once the user accepted what it holds."""
    new = catalog.parse(text)
    console.out(f"{source.name}: {len(new.apps)} apps" + (f", revision {new.revision[:40]}" if new.revision else "")
                + (f", origin {new.origin}" if new.origin else ""))
    sample = [a.name for a in new.apps[:10]]
    console.out("  e.g. " + ", ".join(sample) + (", …" if len(new.apps) > 10 else ""))
    if not console.confirm(f"Add '{source.name}' as an index source?"):
        raise Abort("cancelled; nothing was added")
    indexstore.register(source)
    try:
        indexstore.install(source.name, text, now)
    except BaseException:
        indexstore.unregister(source.name)
        raise
    console.out(f"Added index source '{source.name}'. `appjail index update {source.name}` refreshes it.")


def cmd_index_remove(args, console):
    indexstore.get(args.name)
    if not console.confirm(f"Remove index source '{args.name}' and its catalogs?"):
        raise Abort("cancelled")
    indexstore.unregister(args.name)
    console.out(f"Removed index source '{args.name}'.")


def cmd_index_rollback(args, console):
    name = args.name or indexstore.BUILTIN
    indexstore.get(name)
    a, b = indexstore.rollback(name)
    console.out(f"Index source '{name}' rolled back from {a['sha256'][:12]} to {b['sha256'][:12]}.")


def cmd_index_status(console):
    for source in indexstore.sources().values():
        cur, prev = indexstore.current(source.name), indexstore.previous(source.name)
        where = f"github:{source.location}" if source.kind == "repo" else source.location
        console.out(f"{source.name} ({source.kind}: {where})")
        if cur:
            console.out(f"    current: {cur['sha256'][:12]}, revision {cur['revision'][:12] or '-'}, updated {cur['updated']}"
                        + (f", commit {cur['commit'][:12]}" if cur.get("commit") else "")
                        + (f"; previous: {prev['sha256'][:12]}" if prev else ""))
        else:
            console.out("    no catalog yet; run `appjail index update " + source.name + "`")
