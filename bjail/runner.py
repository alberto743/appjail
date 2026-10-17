# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run an installed app: verify the pin, make sure the tree matches it, start the jail."""

import os
import subprocess
from pathlib import Path

from . import appimage, jail, manifest, store
from .jail import RunError


def _passwd(uid, gid):
    return (f"root:x:0:0:root:/root:/usr/sbin/nologin\napp:x:{uid}:{gid}:app:{jail.APP_HOME}:/bin/sh\n",
            f"root:x:0:\napp:x:{gid}:\n")


def prepare(name, extract=appimage.extract, say=print):
    """Return (manifest, root, home, etc_dir) ready for launch.

    Refuses to run when the stored AppImage no longer matches the pinned sha256. Re-extracts
    when the tree is missing or was made from a different file.
    """
    mpath = store.manifest_path(name)
    if not mpath.exists():
        raise RunError(f"unknown app '{name}'")
    m = manifest.load(mpath)
    image = store.appimage_path(name)
    if not image.is_file():
        raise RunError(f"{image} is missing")
    digest = appimage.sha256_file(image)
    if digest != m.sha256:
        raise RunError(f"{name}: the stored AppImage does not match the pinned sha256 "
                       f"(pinned {m.sha256[:16]}…, found {digest[:16]}…); refusing to run")
    root, marker = store.root_path(name), store.root_marker(name)
    if not (root.is_dir() and marker.is_file() and marker.read_text().strip() == digest):
        say(f"Extracting {name} (no valid extracted tree)…")
        appimage.remove_tree(root)
        try:
            extract(image, root, False)
        except (appimage.UnsupportedImage, appimage.ExtractError, appimage.UnsafeTree) as e:
            raise RunError(f"cannot extract {name}: {e}") from e
        marker.write_text(digest + "\n")
    home, etc = store.home_path(name), store.etc_path(name)
    for d in (home, etc):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    passwd, group = _passwd(os.getuid(), os.getgid())
    (etc / "passwd").write_text(passwd)
    (etc / "group").write_text(group)
    return m, root, home, etc


def launch(name, extra_args=(), host_env=None, extract=appimage.extract, say=print, runner=None):
    """Start the app in its jail and return its exit status."""
    m, root, home, etc = prepare(name, extract, say)
    env = dict(os.environ if host_env is None else host_env)
    args = jail.runtime_args(
        root=root, home=home, etc_dir=etc, perms=m.permissions, uid=os.getuid(), host_env=env,
        command=[f"{jail.APP_DIR}/AppRun", *extra_args], host_home=Path.home())
    argv = [jail.find_bwrap(), *args]
    run = runner or (lambda a: subprocess.call(a, env={"PATH": "/usr/bin:/bin"}))
    return run(argv)
