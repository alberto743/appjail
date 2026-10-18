# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Pinned helper binaries that bjail cannot get from the distribution.

Each tool is identified here, in reviewed source, by URL, size and sha256: bjail never decides at
run time what to fetch or trust. `install` downloads it in the network-only jail and refuses any
mismatch; `require` re-hashes the file before every use and only ever runs it inside the extraction
jail. Updating a tool means changing these constants in a reviewed commit.
"""

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import jail, store


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    url: str
    size: int
    sha256: str
    purpose: str


# mhx/dwarfs v0.15.8, static multi-call binary (dwarfsextract is one of its tools). Not packaged in
# Debian 13, trixie-backports or sid (checked 2026-10-18). GitHub's own digest for the asset is the same.
TOOLS = {
    "dwarfs": Tool(
        "dwarfs",
        "https://github.com/mhx/dwarfs/releases/download/v0.15.8/dwarfs-universal-small-0.15.8-Linux-x86_64",
        2195148, "d29734ed51547f5a5e1c92ede3ea0f2e003902f5c58df10d5e060c87b4e07e69",
        "extracting DwarFS AppImages"),
}


def path(name):
    return store.tools_dir() / name


def _hash(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def status(name):
    """'missing', 'ok' or 'corrupt' for an installed tool."""
    p = path(name)
    if not p.is_file():
        return "missing"
    return "ok" if _hash(p) == TOOLS[name].sha256 else "corrupt"


def require(name):
    """Path of the verified tool, or ToolError telling the user what to do."""
    state = status(name)
    if state == "missing":
        raise ToolError(f"the {name} helper is not installed (needed for {TOOLS[name].purpose}); "
                        f"run `bjail tools install {name}`")
    if state == "corrupt":
        raise ToolError(f"the installed {name} helper does not match its pinned sha256; "
                        f"run `bjail tools install {name}` again")
    return path(name)


def install(name, download=jail.download):
    """Download the tool in the network-only jail and keep it only if size and sha256 match the pins."""
    tool = TOOLS[name]
    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged = download(tool.url, stage, name, tool.size)
        if staged.stat().st_size != tool.size or _hash(staged) != tool.sha256:
            raise ToolError(f"the downloaded {name} does not match its pinned size and sha256; nothing was kept")
        os.chmod(staged, 0o700)
        dest = path(name)
        dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.replace(staged, dest)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return path(name)
