# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run an installed app: verify the pin, make sure the tree matches it, start the jail."""

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import contextlib

from . import appimage, dbusproxy, jail, manifest, store, wayland
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
    tree_mark = store.tree_marker(name)
    valid = root.is_dir() and marker.is_file() and marker.read_text().strip() == digest
    if valid:
        try:
            valid = tree_mark.read_text().strip() == appimage.tree_digest(root)
        except OSError:
            valid = False
        if not valid:
            say(f"Warning: the extracted tree of {name} is missing its record or was modified; extracting it again from the verified image.")
    if not valid:
        say(f"Extracting {name} (no valid extracted tree)…")
        appimage.remove_tree(root)
        try:
            extract(image, root, False)
        except (appimage.UnsupportedImage, appimage.ExtractError, appimage.UnsafeTree) as e:
            raise RunError(f"cannot extract {name}: {e}") from e
        marker.write_text(digest + "\n")
        tree_mark.write_text(appimage.tree_digest(root) + "\n")
    home, etc = store.home_path(name), store.etc_path(name)
    for d in (home, etc):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    passwd, group = _passwd(os.getuid(), os.getgid())
    (etc / "passwd").write_text(passwd)
    (etc / "group").write_text(group)
    return m, root, home, etc


def launch(name, extra_args=(), host_env=None, extract=appimage.extract, say=print, runner=None,
           extra_dirs=(), proxy=dbusproxy.Proxy, restricted=wayland.RestrictedSocket):
    """Start the app in its jail and return its exit status."""
    m, root, home, etc = prepare(name, extract, say)
    perms = m.permissions
    if extra_dirs:
        perms = replace(perms, dirs=manifest.merge_dirs(perms.dirs, extra_dirs))
        say("Temporary access for this run: " + ", ".join(extra_dirs))
    env = dict(os.environ if host_env is None else host_env)
    run = runner or (lambda a: subprocess.call(a, env={"PATH": "/usr/bin:/bin"}))
    with contextlib.ExitStack() as stack:
        bus = stack.enter_context(proxy(perms, env)) if dbusproxy.needed(perms) else None
        wl_sock = stack.enter_context(restricted(env, app_id=name))
        if wl_sock is None:
            say("Warning: the compositor does not offer wp_security_context_v1, so this app gets the full "
                "Wayland socket (it may be able to capture the screen or inject input where the compositor allows it).")
        args = jail.runtime_args(
            root=root, home=home, etc_dir=etc, perms=perms, uid=os.getuid(), host_env=env,
            command=[f"{jail.APP_DIR}/AppRun", *extra_args], host_home=Path.home(), dbus_socket=bus, wayland_socket=wl_sock)
        return run([jail.find_bwrap(), *args])
