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
import tarfile
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
    sha256: str  # of the downloaded file
    purpose: str
    member: str = None  # path of the executable inside a .tar.gz download
    exe_size: int = None  # size and sha256 of that executable (what is hashed before every use)
    exe_sha256: str = None


# mhx/dwarfs v0.15.8, static multi-call binary (dwarfsextract is one of its tools). Not packaged in
# Debian 13, trixie-backports or sid (checked 2026-10-18). GitHub's own digest for the asset is the same.
TOOLS = {
    "dwarfs": Tool(
        "dwarfs",
        "https://github.com/mhx/dwarfs/releases/download/v0.15.8/dwarfs-universal-small-0.15.8-Linux-x86_64",
        2195148, "d29734ed51547f5a5e1c92ede3ea0f2e003902f5c58df10d5e060c87b4e07e69",
        "extracting DwarFS AppImages"),
    # GitHub CLI v2.102.0: used only for `gh attestation verify --bundle` (Sigstore verification), inside a
    # jail, on bundles bjail fetched itself. Not packaged in Debian 13 in a usable version.
    "gh": Tool(
        "gh",
        "https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_linux_amd64.tar.gz",
        15319960, "bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386",
        "verifying build attestations (evidence tier 1)",
        member="gh_2.102.0_linux_amd64/bin/gh", exe_size=42086560,
        exe_sha256="7469124f706944133d6a169691dd1c6c3511b12e85878d255e044e2948df4c9b"),
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
    t = TOOLS[name]
    return "ok" if _hash(p) == (t.exe_sha256 or t.sha256) else "corrupt"


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


def _unpack(tool, archive, stage):
    """Pull the one pinned executable out of the verified tarball; nothing else is written."""
    out = stage / (tool.name + ".exe")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember(tool.member)
            if not member.isreg() or member.size != tool.exe_size:
                raise ToolError(f"the {tool.name} archive does not contain the expected executable")
            src = tar.extractfile(member)
            with open(out, "xb") as f:
                shutil.copyfileobj(src, f)
    except (tarfile.TarError, KeyError, OSError) as e:
        raise ToolError(f"cannot unpack the {tool.name} archive: {e}") from e
    if _hash(out) != tool.exe_sha256:
        raise ToolError(f"the unpacked {tool.name} does not match its pinned sha256; nothing was kept")
    return out


def install(name, download=jail.download):
    """Download the tool in the network-only jail and keep it only if size and sha256 match the pins."""
    tool = TOOLS[name]
    stage = store.staging_root() / secrets.token_hex(8)
    stage.mkdir(parents=True, mode=0o700)
    try:
        staged = download(tool.url, stage, name, tool.size)
        if staged.stat().st_size != tool.size or _hash(staged) != tool.sha256:
            raise ToolError(f"the downloaded {name} does not match its pinned size and sha256; nothing was kept")
        if tool.member:
            staged = _unpack(tool, staged, stage)
        os.chmod(staged, 0o700)
        dest = path(name)
        dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.replace(staged, dest)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return path(name)
