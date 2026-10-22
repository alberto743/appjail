# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Turning command-line permission options into manifest permissions, and describing them."""

import os
from pathlib import Path

from . import jail, manifest
from .console import Abort

PERMISSION_FLAGS = manifest.BOOL_PERMS


def show_permissions(console, perms):
    """The permission summary of an install, with the warnings for grants that deserve one."""
    console.out("Permissions: " + granted_summary(perms))
    warn_sensitive_dbus(console, perms.dbus_filter)
    warn_owned_dbus(console, perms.dbus_own)
    warn_privileged_portals(console, perms.portal_interfaces)


def dirs_from_args(specs, home=None, cwd=None):
    """Canonical, existing directories for --dir options."""
    home, cwd = home or Path.home(), cwd or Path.cwd()
    out = []
    for spec in specs:
        try:
            entry = manifest.normalize_dir(spec, home, cwd)
        except manifest.ManifestError as e:
            raise Abort(f"--dir {spec}: {e}") from e
        host = Path(home) / entry[2:] if entry.startswith("~/") else Path(entry)
        if not Path(str(host).removesuffix(":rw")).is_dir():
            raise Abort(f"--dir {spec}: not a directory")
        out.append(entry)
    return tuple(out)


def files_from_args(specs, cwd=None):
    """Absolute, existing regular files for --file options (PATH or PATH:rw); symlinks are resolved at launch."""
    cwd = Path(cwd or Path.cwd())
    out = []
    for spec in specs:
        path, mode = manifest.split_file_mode(spec)
        full = Path(os.path.normpath(cwd / path))
        if not full.is_file():
            raise Abort(f"--file {spec}: not a regular file")
        out.append(f"{full}:rw" if mode else str(full))
    return tuple(out)


def dbus_from_args(names, current=(), check=manifest.check_dbus_name, flag="--dbus"):
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
    return dbus_from_args(names, current, manifest.check_portal_interface, "--portal")


def warn_privileged_portals(console, names):
    for n in names:
        console.warn(f"the {n} portal is privileged: it can act outside the jail (the desktop asks you each time, "
                     "but the app can trigger the request)")


def warn_sensitive_dbus(console, names):
    for n in names:
        if n.startswith(manifest.DBUS_SENSITIVE):
            console.warn(f"{n} gives access to stored secrets (passwords, keys)")


def warn_owned_dbus(console, names):
    for n in names:
        console.warn(f"{n}: the app may own this session-bus name (be the service behind it) and talk to it")


def require_pasta(perms):
    """An app with network (and not network_host) runs behind pasta and is refused without it: say so when the
    permission is granted, not at the first launch."""
    if perms.network and not perms.network_host and not jail.find_pasta():
        raise Abort("network access runs the app in a private network namespace made by pasta, which is not installed "
                    "(package passt, e.g. `apt install passt`). Install it, or use --allow network_host to give the "
                    "app the host's own network, localhost services included.")


def permissions_from_args(args):
    allowed = set(args.allow)
    if args.portal and "portals" not in allowed:
        raise Abort("--portal needs --allow portals")
    return manifest.Permissions(
        portal_interfaces=portals_from_args(args.portal),
        dirs=dirs_from_args(args.dir), dbus_filter=dbus_from_args(args.dbus),
        dbus_own=dbus_from_args(args.dbus_own, check=manifest.check_dbus_own, flag="--dbus-own"),
        network="network" in allowed or "network_host" in allowed, network_host="network_host" in allowed,
        portals="portals" in allowed, userns="userns" in allowed,
        audio=not args.no_audio, gpu=not args.no_gpu,
        display=args.display,
    )


def granted_summary(p):
    """`key=value` for every permission that is granted, comma-separated (empty when nothing is)."""
    return ", ".join(f"{k}={v}" for k, v in vars(p).items() if v not in ((), False))


def describe_permissions(p):
    return ", ".join([f"{k}={getattr(p, k)}" for k in PERMISSION_FLAGS] + [f"display={p.display}"]
                     + [f"dir={d}" for d in p.dirs] + [f"dbus={n}" for n in p.dbus_filter] + [f"dbus-own={n}" for n in p.dbus_own] + [f"portal={n}" for n in p.portal_interfaces]) or "none"
