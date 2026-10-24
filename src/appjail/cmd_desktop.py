# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail desktop`: the menu entry of an app, and the hooks `add`, `update` and `remove` call."""

from . import desktop, manifest, store
from .console import Abort


def _check(name):
    if not manifest.NAME_RE.fullmatch(name or "!"):
        raise Abort("invalid app name")
    if not store.manifest_path(name).is_file():
        raise Abort(f"unknown app '{name}'")
    if not store.root_path(name).is_dir():
        raise Abort(f"'{name}' has no extracted tree; run it once (`appjail run {name}`) and retry")


def _select(console, declared, args, current, yes):
    """The MIME types to register: --mime-all, --mime TYPE, the current selection on a refresh, else ask."""
    if args.mime_all:
        return list(declared)
    if args.mime:
        unknown = [m for m in args.mime if m not in declared]
        if unknown:
            raise Abort(f"not offered by the app (or refused by appjail): {', '.join(unknown)}")
        return list(dict.fromkeys(args.mime))
    if current is not None:
        return [m for m in current if m in declared]
    if not declared or yes:
        return []
    mode = "read-write; an app that saves by renaming a new file will fail" if args.rw else "read-only"
    console.out(f"The app offers these file types (opening one of them hands that single file to the app, {mode}):")
    for i, m in enumerate(declared, 1):
        console.out(f"  {i}. {m}")
    answer = console.ask("Register: numbers separated by commas, 'all', or empty for none: ")
    if not answer:
        return []
    if answer == "all":
        return list(declared)
    picks = [p.strip() for p in answer.split(",")]
    if not all(p.isdigit() and 1 <= int(p) <= len(declared) for p in picks):
        raise Abort("invalid selection")
    return [declared[int(p) - 1] for p in dict.fromkeys(picks)]


def install_entry(name, console, args, yes=False, ask=True):
    """Show what the entry will say, ask, then write it. `args` carries mime, mime_all and rw."""
    _check(name)
    root = store.root_path(name)
    fields = desktop.read_app_desktop(root)
    declared, ignored = desktop.split_mimes(fields.get("MimeType"))
    state = desktop.installed_state(name)
    mimes = _select(console, declared, args, state[0] if state else None, yes or not ask)
    rw = bool(args.rw) or bool(state and state[1] and not args.mime and not args.mime_all)
    shown = desktop.display_fields(fields, name)
    console.out(f"Menu entry : {shown['Name']} (appjail) -> {' '.join(desktop.launcher_argv())} {'open' if mimes else 'run'} {name}")
    console.out("File types : " + (", ".join(mimes) + (" (read-write)" if rw else " (read-only)") if mimes else "none (launcher only)"))
    if ignored:
        console.out("Not offered: " + ", ".join(ignored))
    if rw and mimes:
        console.warn("read-write: the app may change the opened file, but an app that saves by writing a new file and renaming it will fail")
    if ask and not yes and not console.confirm("Write the menu entry?", default=True):
        raise Abort("cancelled")
    try:
        path, size, note = desktop.install(name, root, mimes, rw)
    except desktop.DesktopError as e:
        raise Abort(str(e)) from e
    console.out(f"Entry      : {path}")
    console.out("Icon       : " + (f"{size} PNG" if size else "none"))
    if note:
        console.out(f"note: {note}")
    if not desktop.refresh_cache() and mimes:
        console.out("note: update-desktop-database (desktop-file-utils) is not installed; the file types may appear after the next login")


def cmd_desktop(args, console):
    if args.prune:
        gone = desktop.dangling()
        for app, path in gone:
            desktop.remove(app)
            console.out(f"Removed the entry of the missing app '{app}': {path}")
        console.out("" if gone else "No dangling menu entries.")
        return
    name = args.app
    if not name:
        raise Abort("name an app, or use --prune")
    if args.remove:
        if not manifest.NAME_RE.fullmatch(name):
            raise Abort("invalid app name")
        console.out(f"Removed the menu entry of {name}." if desktop.remove(name) else f"{name} has no menu entry.")
        return
    install_entry(name, console, args, yes=args.yes)


def refresh_after_update(name, console):
    """`update` replaced the tree: regenerate an existing entry, keeping the chosen types the app still offers."""
    state = desktop.installed_state(name)
    if state is None:
        return
    mimes, rw = state
    declared, _ = desktop.split_mimes(desktop.read_app_desktop(store.root_path(name)).get("MimeType"))
    kept = [m for m in mimes if m in declared]
    try:
        desktop.install(name, store.root_path(name), kept, rw)
    except desktop.DesktopError as e:
        console.out(f"  menu entry not refreshed: {e}")
        return
    if dropped := [m for m in mimes if m not in declared]:
        console.out(f"  menu entry: no longer offered by the app: {', '.join(dropped)}")
    if new := [m for m in declared if m not in mimes]:
        console.out(f"  menu entry: new file types offered: {', '.join(new)} (`appjail desktop {name} --mime TYPE` to register)")


def forget(name, console):
    """`remove` deletes the app: its entry and icons go with it."""
    if desktop.remove(name):
        console.out("Removed the menu entry.")
        if desktop.mimeapps_mentions(name):
            console.out(f"note: your mimeapps.list still names appjail-{name}.desktop; desktops ignore a missing entry, "
                        "you can delete the line")
