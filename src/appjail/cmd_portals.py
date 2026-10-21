# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail portals`: list and revoke the files an app was granted through the document portal."""

import os
from pathlib import Path

from . import manifest, portal, store
from .console import Abort
from .jail import RunError


def names_for(doc, app, host_env):
    """File names the portal shows the app for this document (empty when the mount is not visible)."""
    rt = host_env.get("XDG_RUNTIME_DIR", "")
    try:
        return sorted(p.name for p in (Path(rt) / "doc" / "by-app" / app / doc).iterdir())
    except OSError:
        return []


def cmd_portals(args, console, host_env=None):
    host_env = dict(os.environ if host_env is None else host_env)
    name = args.app
    if not manifest.NAME_RE.fullmatch(name) or not store.manifest_path(name).is_file():
        raise Abort(f"unknown app '{name}'")
    app = portal.app_id(name)
    try:
        granted = portal.granted_documents(app, host_env)
    except RunError as e:
        raise Abort(str(e)) from e
    wanted = list(granted) if args.revoke_all else args.revoke
    for doc in wanted:
        if doc not in granted:
            raise Abort(f"{name} has no grant on document '{doc}'")
    if not wanted:
        console.out(f"{app}: {len(granted)} document grant(s)" + (" (--revoke ID or --revoke-all to remove)" if granted else ""))
        for doc, perms in granted.items():
            console.out(f"  {doc}  [{', '.join(perms)}]  {', '.join(names_for(doc, app, host_env))}")
        return
    console.out(f"This removes {name}'s access to {len(wanted)} document(s); the files themselves are not touched.")
    if not args.yes and not console.confirm("Revoke?"):
        raise Abort("cancelled")
    try:
        portal.revoke_documents(app, host_env, wanted)
    except RunError as e:
        raise Abort(str(e)) from e
    console.out(f"Revoked {len(wanted)} grant(s). The app may still list those files as recent; it can no longer open them.")
