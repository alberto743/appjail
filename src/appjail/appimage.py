# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""AppImage inspection, jailed extraction and validation of the extracted tree."""

import hashlib
import os
import shutil
import stat
import struct
from pathlib import Path

from . import jail
from .textsafe import clean

ELF_MAGIC = b"\x7fELF"
MAX_EXTRACTED_BYTES = 4 * 1024 ** 3
MAX_EXTRACTED_ENTRIES = 500_000
MAX_SYMLINK_HOPS = 40
UNSQUASHFS = "/usr/bin/unsquashfs"


class NotAnAppImage(Exception):
    pass


class UnsupportedImage(Exception):
    """A valid image appjail does not handle (DwarFS, unknown filesystem)."""


class UnsafeTree(Exception):
    """The extracted tree violates a rule (escaping links, special files, no entry point)."""


class ExtractError(Exception):
    pass


# What a caller of extract() or locate_fs() has to handle (jail failures are JailError and are separate).
EXTRACT_ERRORS = (UnsupportedImage, ExtractError, UnsafeTree)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root):
    """sha256 over every path, type, permission bits, file content and link target of a tree.

    Nothing is followed: a symlink contributes its target text only. Detects any later change
    to the extracted tree, including added, removed or re-linked entries.
    """
    h = hashlib.sha256()
    root = str(root)
    stack = [""]
    while stack:
        rel = stack.pop()
        with os.scandir(os.path.join(root, rel)) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            path = os.path.join(rel, e.name)
            st = e.stat(follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                h.update(f"L {path}\0{os.readlink(e.path)}\0".encode("utf-8", "surrogateescape"))
            elif stat.S_ISDIR(st.st_mode):
                h.update(f"D {path}\0{stat.S_IMODE(st.st_mode):o}\0".encode("utf-8", "surrogateescape"))
                stack.append(path)
            else:
                h.update(f"F {path}\0{stat.S_IMODE(st.st_mode):o}\0{st.st_size}\0".encode("utf-8", "surrogateescape"))
                if stat.S_ISREG(st.st_mode):
                    fd = os.open(e.path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 20), b""):
                            h.update(chunk)
    return h.hexdigest()


def appimage_type(path):
    """Return 2 for a type-2 AppImage; raise NotAnAppImage otherwise (type 1 is unsupported)."""
    with open(path, "rb") as f:
        head = f.read(11)
    if len(head) < 11 or head[:4] != ELF_MAGIC:
        raise NotAnAppImage("not an ELF executable")
    if head[8:10] != b"AI":
        raise NotAnAppImage("no AppImage marker (not an AppImage)")
    if head[10] == 2:
        return 2
    raise NotAnAppImage(f"AppImage type {head[10]} is not supported (only type 2)")


def locate_fs(path):
    """(kind, offset) of the embedded filesystem: "squashfs" or "dwarfs", right after the ELF runtime."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(64)
        if len(head) < 64 or head[:4] != ELF_MAGIC or head[4] != 2 or head[5] != 1:
            raise UnsupportedImage("only 64-bit little-endian ELF runtimes are supported")
        shoff, = struct.unpack_from("<Q", head, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)
        offset = shoff + shentsize * shnum
        if not 64 <= offset < size:
            raise UnsupportedImage("cannot locate the embedded filesystem")
        f.seek(offset)
        magic = f.read(8)
    if magic[:4] == b"hsqs":
        return "squashfs", offset
    if magic[:6] == b"DWARFS":
        return "dwarfs", offset
    raise UnsupportedImage("unknown embedded filesystem")


def check_tree(root):
    """Validate an extracted tree and make it safe to handle. Never follows symlinks.

    Only regular files, directories and symlinks are allowed. Set-id and sticky bits are
    cleared and directories are made owner-accessible so the tree can always be removed.
    Sizes are apparent sizes, so sparse files cannot hide a huge tree. Returns (entries, bytes).
    """
    root = Path(root)
    count = total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        os.chmod(dirpath, (os.lstat(dirpath).st_mode & 0o777) | 0o700)
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            count += 1
            if stat.S_ISLNK(st.st_mode) or stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode):
                raise UnsafeTree(f"special file in image: {clean(os.path.relpath(p, root), 200)}")
            total += st.st_size
            if st.st_mode & 0o7000:
                os.chmod(p, st.st_mode & 0o777)
    if total > MAX_EXTRACTED_BYTES or count > MAX_EXTRACTED_ENTRIES:
        raise UnsafeTree("extracted tree is too large")
    return count, total


def resolve_entry(root, rel="AppRun", executable=True):
    """Resolve rel inside root as the jail would see it, refusing anything that leaves root.

    Relative symlinks are followed; absolute targets and '..' above the root are rejected.
    Returns the path of a regular file, which must be executable unless executable is False (icons, metadata).
    """
    root = os.path.realpath(root)
    parts = [p for p in rel.split("/") if p]
    resolved = []
    hops = 0
    while parts:
        part = parts.pop(0)
        if part == ".":
            continue
        if part == "..":
            if not resolved:
                raise UnsafeTree("entry point path escapes the image")
            resolved.pop()
            continue
        candidate = os.path.join(root, *resolved, part)
        try:
            st = os.lstat(candidate)
        except FileNotFoundError:
            raise UnsafeTree(f"{rel} not found in the image") from None
        if stat.S_ISLNK(st.st_mode):
            hops += 1
            target = os.readlink(candidate)
            if hops > MAX_SYMLINK_HOPS:
                raise UnsafeTree("too many symlinks resolving the entry point")
            if target.startswith("/"):
                raise UnsafeTree(f"{rel} resolves through an absolute symlink ({clean(target, 100)})")
            parts = [p for p in target.split("/") if p] + parts
        else:
            resolved.append(part)
    final = os.path.join(root, *resolved)
    st = os.lstat(final)
    if not stat.S_ISREG(st.st_mode) or (executable and not st.st_mode & 0o111):
        raise UnsafeTree(f"{rel} is not {'an executable ' if executable else 'a regular '}file")
    return final


def remove_tree(path):
    """Delete a tree that may contain read-only directories. Never follows symlinks."""
    path = str(path)
    for dirpath, _, _ in os.walk(path, followlinks=False):
        try:
            if stat.S_ISDIR(os.lstat(dirpath).st_mode):
                os.chmod(dirpath, 0o700)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)


def extract_dwarfs(appimage, dest, offset):
    """DwarFS image: extract with the pinned, hash-checked dwarfs-universal tool, inside the jail."""
    from . import tools
    try:
        tool = tools.require("dwarfs")
    except tools.ToolError as e:
        raise ExtractError(str(e)) from e
    dest = Path(dest)
    if dest.exists():
        raise ExtractError(f"{dest} already exists")
    work = dest.with_name(dest.name + ".tmp")
    remove_tree(work)
    work.mkdir(mode=0o700)
    try:
        (work / "root").mkdir()
        cmd = ["/dwarfs-tool", "--tool=dwarfsextract", "-i", "/app.AppImage", "-O", str(offset),
               "-o", "/out/root", "--skip-devices", "--skip-specials"]
        proc = _run_extraction(jail.extract_args(appimage, work, cmd, tools=((tool, "/dwarfs-tool"),)), work)
        if proc.returncode != 0:
            raise ExtractError("extraction failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
        tree = work / "root"
        stats = check_tree(tree)
        resolve_entry(tree, "AppRun")
        os.replace(tree, dest)
        return stats
    finally:
        remove_tree(work)


def _run_extraction(args, work):
    """Run an extraction jail, watching its output. Killing it for size and finding the finished tree too large
    are the same verdict, so both raise UnsafeTree whichever the watcher's poll happens to catch."""
    try:
        return jail.run(args, timeout=900, watch=(work, MAX_EXTRACTED_BYTES, MAX_EXTRACTED_ENTRIES))
    except jail.OutputTooLarge:
        raise UnsafeTree("extracted tree is too large") from None


def have_unsquashfs():
    return os.access(UNSQUASHFS, os.X_OK)


def extract(appimage, dest, runtime_fallback=False):
    """Extract appimage into dest (must not exist) inside a no-network jail, then validate it.

    Prefers unsquashfs on the filesystem offset, so the AppImage runtime never runs. With
    runtime_fallback the image's own --appimage-extract is run, still inside the jail.
    Returns (entries, bytes). On any failure dest is not left behind.
    """
    appimage, dest = Path(appimage), Path(dest)
    kind, offset = locate_fs(appimage)
    if kind == "dwarfs":
        return extract_dwarfs(appimage, dest, offset)
    if not have_unsquashfs() and not runtime_fallback:
        raise ExtractError("unsquashfs is not installed (apt install squashfs-tools)")
    if dest.exists():
        raise ExtractError(f"{dest} already exists")
    work = dest.with_name(dest.name + ".tmp")
    remove_tree(work)
    work.mkdir(mode=0o700)
    try:
        if have_unsquashfs():
            cmd = [UNSQUASHFS, "-no-progress", "-no-xattrs", "-p", "2", "-o", str(offset),
                   "-d", "/out/root", "/app.AppImage"]
            tree = work / "root"
        else:
            # The runtime must be executable inside the jail: use a private copy.
            copy = work / "app.AppImage"
            shutil.copyfile(appimage, copy)
            copy.chmod(0o700)
            cmd = ["/out/app.AppImage", "--appimage-extract"]
            tree = work / "squashfs-root"
        proc = _run_extraction(jail.extract_args(appimage, work, cmd), work)
        if proc.returncode != 0:
            raise ExtractError("extraction failed: " + clean(proc.stderr.strip() or f"exit {proc.returncode}", 400))
        if not tree.is_dir():
            raise ExtractError("extraction produced no files")
        stats = check_tree(tree)
        resolve_entry(tree, "AppRun")
        os.replace(tree, dest)
        return stats
    finally:
        remove_tree(work)
