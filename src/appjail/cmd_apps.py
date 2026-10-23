# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail tools`, `history`, `list`, `remove` and `perms`."""

import os
from dataclasses import replace
from pathlib import Path

from . import (
    appimage,
    desktop,
    grants,
    history,
    jail,
    manifest,
    portal,
    store,
    tools,
    updater,
)
from .cmd_desktop import forget
from .console import Abort
from .permargs import (
    PERMISSION_FLAGS,
    dbus_from_args,
    describe_permissions,
    dirs_from_args,
    portals_from_args,
    require_pasta,
    warn_owned_dbus,
    warn_privileged_portals,
    warn_sensitive_dbus,
)


def cmd_tools(args, console, download=jail.download):
    names = sorted(tools.TOOLS)
    if args.tools_command == "status":
        for n in names:
            console.out(f"{n}: {tools.status(n)}  ({tools.TOOLS[n].purpose})")
        return
    tool = tools.TOOLS[args.tool]
    console.out(f"{tool.name}: {tool.url}")
    console.out(f"  size {tool.size} bytes, sha256 {tool.sha256} (pinned in appjail's source)")
    if not console.confirm("Download it in a network-only jail and keep it only if it matches?"):
        raise Abort("cancelled")
    try:
        tools.install(args.tool, download)
    except tools.ToolError as e:
        raise Abort(str(e)) from e
    console.out(f"Installed {tool.name}.")


def cmd_history(args, console):
    if args.app and not manifest.NAME_RE.fullmatch(args.app):
        raise Abort("invalid app name")
    lines = history.log(args.app, args.limit)
    if not lines:
        console.out("No recorded history (git is missing, or the config directory is part of your own repository).")
    for line in lines:
        console.out(line)


def list_line(name, m):
    """The one line `list` prints for an app."""
    p = m.permissions
    granted = [k for k in PERMISSION_FLAGS if getattr(p, k)] + [f"display={p.display}"]
    pending = updater.load_pending(name)
    return (f"{name}  {m.version}  {m.source}  tier {m.evidence_tier}  [{', '.join(granted)}]"
            + (f"  dirs: {', '.join(p.dirs)}" if p.dirs else "")
            + (f"  dbus: {', '.join(p.dbus_filter)}" if p.dbus_filter else "")
            + (f"  dbus-own: {', '.join(p.dbus_own)}" if p.dbus_own else "")
            + (f"  portals: {', '.join(p.portal_interfaces)}" if p.portal_interfaces else "")
            + (f"  channel: {m.channel}" if m.channel != "stable" else "")
            + (f"  (update seen: {pending['tag']})" if pending else ""))


def cmd_list(console):
    names = updater.installed()
    if not names:
        console.out("No apps installed.")
    for app, path in desktop.dangling():
        console.out(f"note: menu entry of the missing app '{app}': {path} (`appjail desktop --prune` deletes it)")
    for name in names:
        try:
            m = manifest.load(store.manifest_path(name))
        except (manifest.ManifestError, OSError) as e:
            console.out(f"{name}: unreadable manifest ({e})")
            continue
        console.out(list_line(name, m))


def revoke_portal_grants(name, mpath, console):
    """Drop the app's document-portal grants; only worth a note when the app had portals and the store is unreachable."""
    app = portal.app_id(name)
    try:
        portal.revoke_documents(app, os.environ, portal.granted_documents(app, os.environ))
    except jail.RunError as e:
        try:
            had_portals = manifest.load(mpath).permissions.portals
        except (manifest.ManifestError, OSError):
            had_portals = False
        if had_portals:
            console.out(f"note: document-portal grants were not revoked ({e}); see `appjail portals`")


def cmd_remove(args, console):
    name = args.app
    if not manifest.NAME_RE.fullmatch(name):
        raise Abort("invalid app name")
    mpath, adir = store.manifest_path(name), store.app_dir(name)
    if not mpath.exists() and not adir.exists():
        raise Abort(f"unknown app '{name}'")
    console.out(f"This deletes the manifest and the app's files, including its private home (its settings and data): {adir}")
    if not args.yes and not console.confirm(f"Remove {name}?"):
        raise Abort("cancelled")
    revoke_portal_grants(name, mpath, console)
    appimage.remove_tree(adir)
    mpath.unlink(missing_ok=True)
    history.record(f"remove {name}")
    console.out(f"Removed {name}.")
    forget(name, console)


def without(names, remove, what):
    """names minus remove; Abort(what: ...) when something to remove is not in names."""
    missing = [n for n in remove if n not in names]
    if missing:
        raise Abort(f"{what}: " + ", ".join(missing))
    return tuple(n for n in names if n not in remove)


def flag_changes(args):
    """The boolean permissions and the display mode that --allow, --deny and --display change."""
    changes = {}
    for flag in sorted(set(args.allow) & set(args.deny)):
        raise Abort(f"{flag} cannot be both allowed and denied")
    for flag in args.allow:
        changes[flag] = True
    if changes.get("network_host"):
        changes["network"] = True
    for flag in args.deny:
        changes[flag] = False
    if changes.get("network") is False:
        changes["network_host"] = False
    if args.display:
        changes["display"] = args.display
    return changes


def dir_changes(args, dirs):
    """The directories after --rm-dir and --add-dir."""
    if args.rm_dir:
        drop = set()
        for spec in args.rm_dir:
            try:
                entry = grants.normalize_dir(spec, Path.home(), Path.cwd())
            except manifest.ManifestError as e:
                raise Abort(f"--rm-dir {spec}: {e}") from e
            drop.add(entry.partition(":")[0])
        missing = drop - {d.partition(":")[0] for d in dirs}
        if missing:
            raise Abort("not granted: " + ", ".join(sorted(missing)))
        dirs = tuple(d for d in dirs if d.partition(":")[0] not in drop)
    if args.add_dir:
        dirs = grants.merge_dirs(dirs, dirs_from_args(args.add_dir))
    return dirs


def bus_and_portal_changes(args, p, changes):
    """Add the changed D-Bus names and portal interfaces to `changes`."""
    bus = without(dbus_from_args(args.add_dbus, p.dbus_filter), args.rm_dbus, "not allowed")
    if bus != p.dbus_filter:
        changes["dbus_filter"] = bus
    own = dbus_from_args(args.add_dbus_own, p.dbus_own, grants.check_dbus_own, "--add-dbus-own")
    own = without(own, args.rm_dbus_own, "not owned")
    if own != p.dbus_own:
        changes["dbus_own"] = own
    portal_names = without(portals_from_args(args.add_portal, p.portal_interfaces), args.rm_portal, "not allowed")
    if changes.get("portals") is False:
        portal_names = ()
    if portal_names != p.portal_interfaces:
        changes["portal_interfaces"] = portal_names
    if portal_names and not changes.get("portals", p.portals):
        raise Abort("--add-portal needs portals to be allowed (--allow portals)")


RISKY_GRANTS = (("network", "network access (outbound only, off the host's loopback)"),
                ("network_host", "the host's own network, including services bound to localhost"), ("portals", "portals"),
                ("userns", "nested user namespaces (weakens the kernel-level isolation: needed by Electron/Chromium sandboxes)"))


def warn_new_grants(console, old, new):
    for risky, text in RISKY_GRANTS:
        if getattr(new, risky) and not getattr(old, risky):
            console.warn(f"this grants {text}")
    warn_sensitive_dbus(console, set(new.dbus_filter) - set(old.dbus_filter))
    warn_owned_dbus(console, set(new.dbus_own) - set(old.dbus_own))
    warn_privileged_portals(console, set(new.portal_interfaces) - set(old.portal_interfaces))


def cmd_perms(args, console):
    name = args.app
    if not manifest.NAME_RE.fullmatch(name) or not store.manifest_path(name).is_file():
        raise Abort(f"unknown app '{name}'")
    m = manifest.load(store.manifest_path(name))
    p = m.permissions
    changes = flag_changes(args)
    dirs = dir_changes(args, p.dirs)
    if dirs != p.dirs:
        changes["dirs"] = dirs
    bus_and_portal_changes(args, p, changes)
    if not changes:
        console.out(f"{name}: {describe_permissions(p)}")
        return
    new = replace(m, permissions=replace(p, **changes))
    manifest.validate(new)
    if new.permissions.network != p.network or new.permissions.network_host != p.network_host:
        require_pasta(new.permissions)
    console.out(f"{name} before: {describe_permissions(p)}")
    console.out(f"{name} after : {describe_permissions(new.permissions)}")
    warn_new_grants(console, p, new.permissions)
    if not args.yes and not console.confirm("Save these permissions?"):
        raise Abort("cancelled")
    manifest.dump(store.manifest_path(name), new)
    history.record(f"permissions {name}")
    console.out("Saved. The pinned release is unchanged.")
