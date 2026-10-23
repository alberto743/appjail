# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The installed apps as data for the Apps tab (read from the manifests, like `appjail list`). No tkinter."""

from .. import manifest, store, textsafe, updater
from ..cmd_apps import list_line
from ..permargs import PERMISSION_FLAGS


def permission_state(p):
    """A Permissions as the dict argv.perms_argv compares."""
    state = {k: getattr(p, k) for k in PERMISSION_FLAGS}
    state.update(display=p.display, dirs=tuple(p.dirs), dbus_filter=tuple(p.dbus_filter), dbus_own=tuple(p.dbus_own),
                 portal_interfaces=tuple(p.portal_interfaces))
    return state


def load_permissions(name):
    return permission_state(manifest.load(store.manifest_path(name)).permissions)


def detail(name):
    """The full `list` line of an app (directories, D-Bus names, portals, channel), for the line under the table."""
    try:
        return textsafe.clean(list_line(name, manifest.load(store.manifest_path(name))), 1000)
    except (manifest.ManifestError, OSError) as e:
        return textsafe.clean(f"{name}: unreadable manifest ({e})", 300)


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
        summary = ", ".join([k for k in PERMISSION_FLAGS if getattr(p, k)] + [f"display={p.display}"])
        pending = updater.load_pending(name)
        note = f"update seen: {pending['tag']}" if pending else ""
        if m.channel != "stable":
            note = (f"channel {m.channel}; " + note).rstrip("; ")
        result.append(tuple(textsafe.clean(str(v), 120) for v in (name, m.version, m.source, m.evidence_tier, summary, note)))
    return result
