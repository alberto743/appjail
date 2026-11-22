# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail open NAME -- FILE_OR_LINK...`: what the menu entry runs to open files, and links of the granted schemes, with an app.

Each file is bound alone (read-only unless --rw) for that run, like `run --file`; a link is checked against the app's
`schemes` and passed on as one argument, or, when the app is already running and only links were given, written to its
relay (relay.py), so the running app receives it. A file cannot be: it is bound when a jail starts. The desktop may name a local file by its path or as a `file:` URL. The menu has
no terminal, so a refusal is also shown as a notification when notify-send exists.
"""

import contextlib
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import desktop, grants, manifest, relay, runner, store
from .console import Abort
from .errors import JailError, RunError
from .textsafe import clean


def file_spec(path, rw):
    """A --file entry for a path from the file manager; the mode is always explicit so a name ending in :rw stays read-only."""
    return f"{os.path.normpath(Path.cwd() / path)}:{'rw' if rw else 'ro'}"


# Notification servers that support body markup read a subset of HTML (<a href>, <img>, <b>): a file name could become a
# link or an image. Escaping would show "&lt;" on servers without markup, so the characters are dropped instead.
NO_MARKUP = str.maketrans("", "", "<>&")


def classify(arg, schemes):
    """("file", path) or ("link", link) for an argument from the desktop. An absolute path is a path; `file:` is a local
    file URL (no host but localhost); any other scheme must be one of the app's granted `schemes`, else it is refused."""
    if arg.startswith("/"):
        return "file", arg
    scheme, colon, rest = arg.partition(":")
    if colon and grants.SCHEME_RE.fullmatch(scheme.lower()):
        low = scheme.lower()
        if low == "file":
            parts = urlsplit(arg)
            if parts.netloc not in ("", "localhost") or not parts.path.startswith("/") or parts.query or parts.fragment:
                raise Abort(f"not a local file: {clean(arg, 100)}")
            return "file", unquote(parts.path)
        if low in schemes:
            try:
                return "link", grants.check_link(arg, schemes)
            except manifest.ManifestError as e:
                raise Abort(f"refused link: {e}") from e
        if rest.startswith("//"):
            raise Abort(f"not a local file, and this app is not granted the {clean(low, 40)} scheme: {clean(arg, 100)}")
    return "file", arg


def notify(text):
    tool = shutil.which("notify-send")
    if tool:
        body = clean(text, 300).translate(NO_MARKUP)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([tool, "--app-name=appjail", "appjail", body], capture_output=True, check=False, timeout=10)


def cmd_open(args, files, console):
    name = args.app
    try:
        manifest.check_name(name)
        if not store.manifest_path(name).is_file():
            if desktop.marker_of(desktop.entry_path(name)) == name:
                desktop.remove(name)
                raise Abort(f"'{name}' was removed; its leftover menu entry has been deleted")
            raise Abort(f"unknown app '{name}'")
        schemes = manifest.load(store.manifest_path(name)).permissions.schemes
        specs, links = [], []
        for f in files:
            kind, value = classify(f, schemes)
            if kind == "link":
                links.append(value)
                continue
            if not Path(value).is_file():
                raise Abort(f"not a regular file: {clean(value, 100)}")
            specs.append(file_spec(value, args.rw))
        if links and not specs and relay.send(name, links):
            console.out(f"Sent {len(links)} link{'s' * (len(links) > 1)} to the running {name}.")
            return 0
        return runner.launch(name, links, say=console.out, warn=console.warn, extra_files=tuple(specs))
    except (Abort, JailError, RunError, manifest.ManifestError) as e:
        notify(str(e))
        raise
