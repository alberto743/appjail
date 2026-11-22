# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Turning command-line permission options into manifest permissions, and describing them."""

import os
from pathlib import Path

from . import grants, jail, landlock, manifest
from .console import ARROW, Abort
from .valid import cpu_quota, display_size, memory_max, tasks_max

PERMISSION_FLAGS = manifest.BOOL_PERMS


def show_permissions(console, perms):
    """The permission summary of an install, with the warnings for grants that deserve one."""
    console.kv("Permissions", granted_summary(perms))
    warn_new_grants(console, manifest.Permissions(), perms)


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


def schemes_from_args(names, current=(), flag="--scheme"):
    """Validated URL schemes (given in any case, stored in lower case) merged into the current list (order kept)."""
    out = list(current)
    for name in names:
        try:
            grants.check_scheme(name.lower())
        except manifest.ManifestError as e:
            raise Abort(f"{flag} {name}: {e}") from e
        if name.lower() not in out:
            out.append(name.lower())
    if len(out) > grants.MAX_SCHEMES:
        raise Abort(f"{flag}: at most {grants.MAX_SCHEMES} schemes")
    return tuple(out)


def warn_new_schemes(console, names):
    for n in names:
        console.warn(f"{n}: a {n}: link opened anywhere on your desktop will start this app with that link, "
                     "and the app keeps a relay running inside its jail to receive links while it runs")


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


RISKY_GRANTS = (("network", "network access (outbound only, off the host's loopback)"),
                ("network_host", "the host's own network, including services bound to localhost"), ("portals", "portals"),
                ("mic", "access to the microphone"), ("camera", "access to the camera (the video capture devices)"),
                ("userns", "nested user namespaces (weakens the kernel-level isolation: needed by Electron/Chromium sandboxes)"),
                ("full_wayland", ("running on a compositor whose Wayland socket for the app still lists privileged interfaces "
                                  "(the app may then capture the screen, inject input, read the clipboard without focus or control "
                                  "other windows, depending on the compositor); a socket that lists none is unaffected")),
                ("raw_terminal", ("your terminal as it is: what the app prints is not cleaned, so it can set your clipboard or "
                                  "window title, rewrite the screen and make the terminal type replies into your input, and it "
                                  "can read what you type in that terminal")),
                ("devel", ("tracing and debugging: the app can trace its own processes (ptrace) and run them at fixed "
                           "addresses; it cannot reach processes outside its jail, and the filter still applies to what "
                           "it traces")))


def warn_new_grants(console, old, new):
    """A warning for each risky grant in new that old did not have (old is all-denied for an install)."""
    for risky, text in RISKY_GRANTS:
        if getattr(new, risky) and not getattr(old, risky):
            console.warn(f"this grants {text}")
    if new.audio and new.audio_mode == "pulse" and not new.mic and not (old.audio and old.audio_mode == "pulse"):
        console.warn("audio in pulse mode uses the host's Pulse socket, which also lets the app record from the microphone; "
                     "that cannot be denied in this mode, and the server can be told to create files and listeners in your name "
                     "and, if it is PulseAudio itself, to load the app's own code (appjail refuses the socket then)")
    warn_sensitive_dbus(console, [n for n in new.dbus_filter if n not in old.dbus_filter])
    warn_owned_dbus(console, [n for n in new.dbus_own if n not in old.dbus_own])
    warn_privileged_portals(console, [n for n in new.portal_interfaces if n not in old.portal_interfaces])
    warn_new_schemes(console, [n for n in new.schemes if n not in old.schemes])


def require_network_isolation(perms):
    """Refuse a network grant that cannot be isolated, at grant time: pasta for `network`, Landlock for `network_host`."""
    if perms.network_host and not landlock.available():
        raise Abort(landlock.NEEDED_FOR_NETWORK_HOST)
    if perms.pasta and not jail.find_pasta():
        raise Abort("network access runs the app in a private network namespace made by pasta, which is not installed "
                    "(package passt). Install it, or use --allow network_host to give the "
                    "app the host's own network, localhost services included.")


def permissions_from_args(args):
    allowed = set(args.allow)
    if args.portal and "portals" not in allowed:
        raise Abort("--portal needs --allow portals")
    try:
        display_size(args.display_size, "--display-size")
        for value, check, flag in ((args.memory_max, memory_max, "--memory-max"), (args.cpu_quota, cpu_quota, "--cpu-quota"),
                                   (args.tasks_max, tasks_max, "--tasks-max")):
            if value:
                check(value, flag)
    except manifest.ManifestError as e:
        raise Abort(str(e)) from e
    return manifest.Permissions(
        portal_interfaces=portals_from_args(args.portal), schemes=schemes_from_args(args.scheme),
        dirs=dirs_from_args(args.dir), dbus_filter=dbus_from_args(args.dbus),
        dbus_own=dbus_from_args(args.dbus_own, check=grants.check_dbus_own, flag="--dbus-own"),
        network="network" in allowed or "network_host" in allowed, network_host="network_host" in allowed,
        portals="portals" in allowed, userns="userns" in allowed, linger="linger" in allowed,
        full_wayland="full_wayland" in allowed, raw_terminal="raw_terminal" in allowed, devel="devel" in allowed,
        audio="audio" in allowed or "mic" in allowed, mic="mic" in allowed, audio_mode=args.audio_mode,
        gpu="gpu" in allowed, camera="camera" in allowed,
        display=args.display, display_size=args.display_size,
        memory_max=args.memory_max, cpu_quota=args.cpu_quota, tasks_max=args.tasks_max,
    )


def granted_summary(p):
    """What an app is granted on one line: `grants: audio, gpu; display: wayland; dirs: ...`."""
    return "; ".join(f"{label}: {text}" for label, text in permission_lines(p))


def permission_lines(p):
    """What an app is granted, one (label, text) per line: the flags and the display always, the lists when not empty."""
    display = p.display + (f" {p.display_size}" if p.rootful else "")
    lines = [("grants", ", ".join(k for k in PERMISSION_FLAGS if getattr(p, k)) or "none"), ("display", display)]
    if p.audio:
        lines.append(("audio-mode", p.audio_mode))
    for label, value in (("memory-max", p.memory_max), ("cpu-quota", p.cpu_quota), ("tasks-max", p.tasks_max)):
        if value:
            lines.append((label, value))
    for label, values in (("dirs", p.dirs), ("dbus", p.dbus_filter), ("dbus-own", p.dbus_own), ("portals", p.portal_interfaces),
                          ("schemes", p.schemes)):
        if values:
            lines.append((label, ", ".join(values)))
    return lines


def permission_changes(old, new):
    """What differs between two Permissions, as (label, text) lines: `no → yes` for a value, `+ x` / `- x` for a list."""
    lines = []
    for k in PERMISSION_FLAGS:
        if getattr(old, k) != getattr(new, k):
            lines.append((k, f"{'yes' if getattr(old, k) else 'no'} {ARROW} {'yes' if getattr(new, k) else 'no'}"))
    for k in ("audio_mode", "display", "display_size", *manifest.LIMIT_KEYS):
        if getattr(old, k) != getattr(new, k):
            lines.append((k.replace("_", "-"), f"{getattr(old, k) or 'none'} {ARROW} {getattr(new, k) or 'none'}"))
    for label, a, b in (("dirs", old.dirs, new.dirs), ("dbus", old.dbus_filter, new.dbus_filter),
                        ("dbus-own", old.dbus_own, new.dbus_own), ("portals", old.portal_interfaces, new.portal_interfaces),
                        ("schemes", old.schemes, new.schemes)):
        lines += [(label, f"+ {x}") for x in b if x not in a] + [(label, f"- {x}") for x in a if x not in b]
    return lines


def env_from_args(current, set_specs, unset_names):
    """The [env] pairs after --unset-env and --set-env (NAME=VALUE), sorted by name."""
    env = dict(current)
    for name in unset_names:
        if name not in env:
            raise Abort(f"--unset-env {name}: not set")
        del env[name]
    for spec in set_specs:
        key, eq, value = spec.partition("=")
        if not eq:
            raise Abort(f"--set-env {spec}: expected NAME=VALUE")
        try:
            grants.check_env(key, value)
        except manifest.ManifestError as e:
            raise Abort(f"--set-env {key}: {e}") from e
        env[key] = value
    return tuple(sorted(env.items()))


def env_lines(env):
    """The (label, text) lines `perms` and `list --long` print for [env]; the values are the user's own, shown as set."""
    return [("env", ", ".join(f"{k}={v}" for k, v in env))] if env else []


def env_changes(old, new):
    """(label, text) lines for what differs between two [env] tables."""
    a, b = dict(old), dict(new)
    return ([("env", f"+ {k}={v}") for k, v in b.items() if k not in a]
            + [("env", f"{k}: {a[k]} {ARROW} {v}") for k, v in b.items() if k in a and a[k] != v]
            + [("env", f"- {k}") for k in a if k not in b])
