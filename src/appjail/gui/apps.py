# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The installed apps as data for the Apps tab (read from the manifests, like `appjail list`). No tkinter."""

import os

from .. import index, manifest, portal, store, textsafe, updater
from ..cmd_apps import list_line
from ..cmd_desktop import file_type_state
from ..cmd_portals import names_for
from ..jail import RunError
from ..permargs import PERMISSION_FLAGS


def permission_state(p):
    """A Permissions as the dict argv.perms_argv compares."""
    state = {k: getattr(p, k) for k in PERMISSION_FLAGS}
    state.update(display=p.display, display_size=p.display_size, dirs=tuple(p.dirs), dbus_filter=tuple(p.dbus_filter), dbus_own=tuple(p.dbus_own),
                 portal_interfaces=tuple(p.portal_interfaces))
    return state


def load_permissions(name):
    return permission_state(manifest.load(store.manifest_path(name)).permissions)


def detail(name):
    """The full `list` line of an app (directories, D-Bus names, portals, channel), for the line under the table."""
    try:
        line = list_line(name, manifest.load(store.manifest_path(name)))
        offered, _ignored, registered, _rw, has_entry = file_types(name)
        if has_entry:
            line += f"; file types: {len(registered)} registered of {len(offered)} offered"
        return textsafe.clean(line, 1000)
    except (manifest.ManifestError, OSError) as e:
        return textsafe.clean(f"{name}: unreadable manifest ({e})", 300)


def file_types(name):
    """(offered, ignored, registered, rw, has_entry) of an app's menu entry, cleaned; ([], [], [], False, False) when unreadable."""
    try:
        offered, ignored, registered, rw, has_entry = file_type_state(name)
    except (OSError, ValueError):
        return [], [], [], False, False
    def clean(items):
        return [textsafe.clean(m, 130) for m in items]

    return clean(offered), clean(ignored), clean(registered), rw, has_entry


def rows():
    """(name, version, source, tier, summary, note) per installed app; an unreadable manifest gives a note instead."""
    result = []
    for name in updater.installed():
        try:
            m = manifest.load(store.manifest_path(name))
        except (manifest.ManifestError, OSError) as e:
            result.append((name, "", "", "", "", textsafe.clean(f"unreadable manifest ({e})", 120)))
            continue
        p = m.permissions
        summary = ", ".join([k for k in PERMISSION_FLAGS if getattr(p, k)] + [f"display={p.display}"]
                            + [f"portal:{i}" for i in p.portal_interfaces])
        pending = updater.load_pending(name)
        note = f"update seen: {pending['tag']}" if pending else ""
        if m.channel != "stable":
            note = (f"channel {m.channel}; " + note).rstrip("; ")
        result.append(tuple(textsafe.clean(str(v), 120) for v in (name, m.version, m.source, m.evidence_tier, summary, note)))
    return result


def portal_grants(name, host_env=None):
    """What the Portals dialog shows: (header lines, [(document id, line)]). The header has the interfaces granted in
    the manifest and the count of document grants of the permission store (or why they cannot be read)."""
    host_env = dict(os.environ if host_env is None else host_env)
    try:
        interfaces = manifest.load(store.manifest_path(name)).permissions.portal_interfaces
    except (manifest.ManifestError, OSError) as e:
        return [textsafe.clean(f"unreadable manifest ({e})", 300)], []
    header = ["Portal interfaces: " + (", ".join(interfaces) if interfaces else "none beyond the defaults")]
    app = portal.app_id(name)
    try:
        granted = portal.granted_documents(app, host_env)
    except RunError as e:
        return header + [textsafe.clean(f"Document grants: unavailable ({e})", 300)], []
    header.append(f"Document grants: {len(granted)}")
    return header, [(doc, textsafe.clean(f"{doc}  [{', '.join(perms)}]  {', '.join(names_for(doc, app, host_env))}", 300))
                    for doc, perms in granted.items()]


def search_hits(words, limit, show_all):
    """(hits, total, catalogs searched) like `appjail search`; texts cleaned. Raises catalog.IndexProblem."""
    hits, total, searched = index.search(words.split(), limit=10 ** 9 if show_all or not limit else limit)
    clean = [index.Hit(*(textsafe.clean(v, 300) for v in (h.name, h.description, h.source, h.note, h.catalog))) for h in hits]
    return clean, total, searched
