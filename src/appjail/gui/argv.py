# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Form state to argv lists for the CLI. No tkinter here: the parser stays the one place that validates options."""

from ..catalog import INSTALLABLE
from ..permargs import PERMISSION_FLAGS


def _repeat(flag, values):
    return [part for v in values for part in (flag, v)]


def add_argv(form):
    """`appjail add ...` from the Add form (a dict; empty values are left out).

    form["kind"] is "github", "url" or "file"; form["source"] is the owner/repo, URL or path.
    """
    kind, source = form.get("kind", "github"), form.get("source", "").strip()
    argv = ["add"]
    if kind == "github":
        argv.append(source)
        if form.get("tag"):
            argv += ["--tag", form["tag"].strip()]
        if form.get("prerelease"):
            argv.append("--prerelease")
    else:
        argv += ["--url" if kind == "url" else "--file", source]
        if form.get("sha256"):
            argv += ["--sha256", form["sha256"].strip()]
        if kind == "url" and form.get("max_size"):
            argv += ["--max-size", str(form["max_size"]).strip()]
    if form.get("name"):
        argv += ["--name", form["name"].strip()]
    argv += _repeat("--dir", form.get("dirs", ()))
    argv += _repeat("--dbus", form.get("dbus", ()))
    argv += _repeat("--dbus-own", form.get("dbus_own", ()))
    argv += _repeat("--portal", form.get("portals", ()))
    argv += _repeat("--allow", [f for f in form.get("allow", ()) if f not in ("audio", "gpu")])
    if "audio" not in form.get("allow", ("audio",)):
        argv.append("--no-audio")
    if "gpu" not in form.get("allow", ("gpu",)):
        argv.append("--no-gpu")
    if form.get("display") and form["display"] != "wayland":
        argv += ["--display", form["display"]]
    if form.get("desktop"):
        argv.append("--desktop")
        if form.get("mime_all"):
            argv.append("--mime-all")
        argv += _repeat("--mime", form.get("mime", ()))
        if form.get("rw"):
            argv.append("--rw")
    return argv


def defers_menu_entry(form):
    """True when the menu entry waits for a follow-up `desktop NAME`: wanted, but no file types chosen yet.

    The types an app declares are only known once it is installed; `desktop` then lists them and asks.
    """
    return bool(form.get("desktop") and not form.get("mime_all") and not form.get("mime"))


def add_followup(before, after, rw=False):
    """The `desktop NAME` that follows a successful add: the one new app between the two name collections, else None."""
    new = set(after) - set(before)
    return desktop_argv(next(iter(new)), rw=rw) if len(new) == 1 else None


def perms_argv(name, old, new):
    """`appjail perms NAME ...` for the difference between two permission states.

    A state is a dict: the boolean flags by name, "display", and the tuples "dirs", "dbus_filter", "dbus_own",
    "portal_interfaces". The command shows the before/after review and asks; the option that skips the question is never added here.
    """
    argv = ["perms", name]
    for flag in PERMISSION_FLAGS:
        if new.get(flag) and not old.get(flag):
            argv += ["--allow", flag]
        elif old.get(flag) and not new.get(flag):
            argv += ["--deny", flag]
    if new.get("display") != old.get("display"):
        argv += ["--display", new["display"]]
    for key, add, rm in (("dirs", "--add-dir", "--rm-dir"), ("dbus_filter", "--add-dbus", "--rm-dbus"),
                         ("dbus_own", "--add-dbus-own", "--rm-dbus-own"),
                         ("portal_interfaces", "--add-portal", "--rm-portal")):
        before, after = tuple(old.get(key, ())), tuple(new.get(key, ()))
        removed = [v for v in before if v not in after]
        if key == "dirs":
            removed = [v.rpartition(":")[0] if v.endswith((":ro", ":rw")) else v for v in removed]
        argv += _repeat(rm, removed)
        argv += _repeat(add, [v for v in after if v not in before])
    return argv


def add_target(source):
    """(kind, target) for the Add form from a catalog `kind:target` source, or None when `add` cannot install it."""
    kind, _, target = source.partition(":")
    if kind not in INSTALLABLE or not target:
        return None
    return kind, target


def update_argv(app=None, prerelease=False, channel=None, quarantine=None, file=None, sha256=None, verify=False):
    argv = ["update"]
    if app:
        argv.append(app)
    if prerelease:
        argv.append("--prerelease")
    if channel:
        argv += ["--channel", channel]
    if quarantine not in (None, ""):
        argv += ["--quarantine", str(quarantine).strip()]
    if file:
        argv += ["--file", file]
    if sha256:
        argv += ["--sha256", sha256.strip()]
    if verify:
        argv.append("--verify")
    return argv


def run_argv(app, dirs=(), files=()):
    """`run` with grants for this run only (the manifest is unchanged)."""
    return ["run", app, *_repeat("--dir", dirs), *_repeat("--file", files)]


def desktop_argv(app=None, mime=(), mime_all=False, rw=False, remove=False, prune=False, show=False):
    argv = ["desktop"]
    if app:
        argv.append(app)
    if remove:
        argv.append("--remove")
    if prune:
        argv.append("--prune")
    if show:
        argv.append("--show")
    if mime_all:
        argv.append("--mime-all")
    argv += _repeat("--mime", mime)
    if rw:
        argv.append("--rw")
    return argv


def portals_argv(app, revoke=(), revoke_all=False):
    """`portals APP`: a listing, or the revocations; the command asks before revoking."""
    return ["portals", app, *_repeat("--revoke", revoke), *(["--revoke-all"] if revoke_all else [])]


def history_argv(app=None, limit=None):
    return ["history", *([app] if app else []), *(["--limit", str(limit)] if limit else [])]
