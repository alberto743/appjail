# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""`appjail open NAME -- FILE...`: what the menu entry runs to open files with an app.

Each file is bound alone (read-only unless --rw) for that run, like `run --file`. The menu has no terminal, so a refusal
is also shown as a notification when notify-send exists.
"""

import os
import shutil
import subprocess
from pathlib import Path

from . import desktop, manifest, runner, store
from .console import Abort
from .textsafe import clean


def file_spec(path, rw):
    """A --file entry for a path from the file manager; the mode is always explicit so a name ending in :rw stays read-only."""
    return f"{os.path.normpath(Path.cwd() / path)}:{'rw' if rw else 'ro'}"


def notify(text):
    tool = shutil.which("notify-send")
    if tool:
        subprocess.run([tool, "--app-name=appjail", "appjail", clean(text, 300)], capture_output=True, check=False, timeout=10)


def cmd_open(args, files, console):
    name = args.app
    try:
        if not manifest.NAME_RE.fullmatch(name):
            raise Abort("invalid app name")
        if not store.manifest_path(name).is_file():
            if desktop.marker_of(desktop.entry_path(name)) == name:
                desktop.remove(name)
                raise Abort(f"'{name}' was removed; its leftover menu entry has been deleted")
            raise Abort(f"unknown app '{name}'")
        specs = []
        for f in files:
            if "://" in f.split("/")[0]:
                raise Abort(f"not a local file: {clean(f, 100)}")
            if not Path(f).is_file():
                raise Abort(f"not a regular file: {clean(f, 100)}")
            specs.append(file_spec(f, args.rw))
        return runner.launch(name, [], say=console.out, extra_files=tuple(specs))
    except (Abort, runner.jail.RunError, runner.jail.JailError) as e:
        notify(str(e))
        raise
