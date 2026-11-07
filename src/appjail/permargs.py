# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Turning command-line permission options into manifest permissions, and describing them."""

import os
from pathlib import Path

from . import grants, jail, landlock, manifest
from .console import ARROW, Abort
from .valid import display_size

PERMISSION_FLAGS = manifest.BOOL_PERMS


def show_permissions(console, perms):
    """The permission summary of an install, with the warnings for grants that deserve one."""
    console.kv("Permissions", granted_summary(perms))
    warn_sensitive_dbus(console, perms.dbus_filter)
    warn_owned_dbus(console, perms.dbus_own)
    warn_privileged_portals(console, perms.portal_interfaces)


def dirs_from_args(specs, home=None, cwd=None):
    """Canonical, existing directories for --dir options."""
    home, cwd = home or Path.home(), cwd or Path.cwd()
    out = []
    for spec in specs:
        try:
            entry = grants.normalize_dir(spec, home, cwd)
        except manifest.ManifestError as e:
            raise Abort(f"--dir {spec}: {e}") from e
        host = Path(home) / entry[2:] if entry.startswith("~/") else Path(entry)
        if not Path(str(host).removesuffix(":rw")).is_dir():
            raise Abort(f"--dir {spec}: not a directory")
        out.append(entry)
    return tuple(out)


def files_from_args(specs, cwd=None):
    """Absolute, existing regular files for --file options (PATH, PATH:ro or PATH:rw), each with an explicit mode so a
    file named like a suffix is never re-split later; what the path really names is checked at launch."""
    cwd = Path(cwd or Path.cwd())
    out = []
    for spec in specs:
        path, mode = grants.split_file_mode(spec)
        full = Path(os.path.normpath(cwd / path))
        if not full.is_file():
            raise Abort(f"--file {spec}: not a regular file")
        out.append(f"{full}:{'rw' if mode else 'ro'}")
    return tuple(out)


def dbus_from_args(names, current=(), check=grants.check_dbus_name, flag="--dbus"):
    """Validated dbus_filter (or dbus_own) names merged into the current list (order kept, no duplicates)."""
    out = list(current)
    for name in names:
        try:
            check(name)
        except manifest.ManifestError as e:
            raise Abort(f"{flag} {name}: {e}") from e
        if name not in out:
            out.append(name)
    return tuple(out)


def portals_from_args(names, current=()):
    """Validated opt-in portal interfaces merged into the current list (order kept, no duplicates)."""
    return dbus_from_args(names, current, grants.check_portal_interface, "--portal")


def warn_privileged_portals(console, names):
    for n in names:
        console.warn(f"the {n} portal is privileged: it can act outside the jail (the desktop asks you each time, "
                     "but the app can trigger the request)")


def warn_sensitive_dbus(console, names):
    for n in names:
        if n.startswith(grants.DBUS_SENSITIVE):
            console.warn(f"{n} gives access to stored secrets (passwords, keys)")


def warn_owned_dbus(console, names):
    for n in names:
        console.warn(f"{n}: the app may own this session-bus name (be the service behind it) and talk to it")


def require_network_isolation(perms):
    """Refuse a network grant that cannot be isolated, at grant time: pasta for `network`, Landlock for `network_host`."""
    if perms.network_host and not landlock.available():
        raise Abort(landlock.NEEDED_FOR_NETWORK_HOST)
    if perms.pasta and not jail.find_pasta():
        raise Abort("network access runs the app in a private network namespace made by pasta, which is not installed "
                    "(package passt, e.g. `apt install passt`). Install it, or use --allow network_host to give the "
                    "app the host's own network, localhost services included.")


def permissions_from_args(args):
    allowed = set(args.allow)
    if args.portal and "portals" not in allowed:
        raise Abort("--portal needs --allow portals")
    try:
        display_size(args.display_size, "--display-size")
    except manifest.ManifestError as e:
        raise Abort(str(e)) from e
    return manifest.Permissions(
        portal_interfaces=portals_from_args(args.portal),
        dirs=dirs_from_args(args.dir), dbus_filter=dbus_from_args(args.dbus),
        dbus_own=dbus_from_args(args.dbus_own, check=grants.check_dbus_own, flag="--dbus-own"),
        network="network" in allowed or "network_host" in allowed, network_host="network_host" in allowed,
        portals="portals" in allowed, userns="userns" in allowed, linger="linger" in allowed,
        audio="audio" in allowed, gpu="gpu" in allowed, camera="camera" in allowed,
        display=args.display, display_size=args.display_size,
    )


def granted_summary(p):
    """What an app is granted on one line: `grants: audio, gpu; display: wayland; dirs: ...`."""
    return "; ".join(f"{label}: {text}" for label, text in permission_lines(p))


def permission_lines(p):
    """What an app is granted, one (label, text) per line: the flags and the display always, the lists when not empty."""
    display = p.display + (f" {p.display_size}" if p.rootful else "")
    lines = [("grants", ", ".join(k for k in PERMISSION_FLAGS if getattr(p, k)) or "none"), ("display", display)]
    for label, values in (("dirs", p.dirs), ("dbus", p.dbus_filter), ("dbus-own", p.dbus_own), ("portals", p.portal_interfaces)):
        if values:
            lines.append((label, ", ".join(values)))
    return lines


def permission_changes(old, new):
    """What differs between two Permissions, as (label, text) lines: `no → yes` for a value, `+ x` / `- x` for a list."""
    lines = []
    for k in PERMISSION_FLAGS:
        if getattr(old, k) != getattr(new, k):
            lines.append((k, f"{'yes' if getattr(old, k) else 'no'} {ARROW} {'yes' if getattr(new, k) else 'no'}"))
    for k in ("display", "display_size"):
        if getattr(old, k) != getattr(new, k):
            lines.append((k.replace("_", "-"), f"{getattr(old, k)} {ARROW} {getattr(new, k)}"))
    for label, a, b in (("dirs", old.dirs, new.dirs), ("dbus", old.dbus_filter, new.dbus_filter),
                        ("dbus-own", old.dbus_own, new.dbus_own), ("portals", old.portal_interfaces, new.portal_interfaces)):
        lines += [(label, f"+ {x}") for x in b if x not in a] + [(label, f"- {x}") for x in a if x not in b]
    return lines
