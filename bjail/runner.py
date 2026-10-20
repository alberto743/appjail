# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run an installed app: verify the pin, make sure the tree matches it, start the jail."""

import json
import os
import select
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import contextlib

from . import appimage, dbusproxy, history, jail, manifest, portal, seccomp, store, wayland
from .jail import RunError

# Descriptors the pasta wrapper opens for bwrap (single digits: dash redirects accept no more; see jail.net_wrap).
PASTA_SECCOMP_FD, PASTA_STATUS_FD, PASTA_BLOCK_FD = 9, 8, 7


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


STATUS_TIMEOUT = 10.0


class Pipes:
    """The two pipes of a portal launch (bwrap status out, start gate in); each end is closed exactly once."""

    def __init__(self, fifo_dir=None):
        """With fifo_dir the ends are named FIFOs for a bwrap behind pasta (which closes inherited descriptors):
        only the parent's ends exist here, opened read-write so the opens inside the namespace never block."""
        self.fds = {}
        self.paths = {}
        if fifo_dir is None:
            self.fds["status_r"], self.fds["status_w"] = os.pipe()
            self.fds["block_r"], self.fds["block_w"] = os.pipe()
            return
        for name, key in (("status", "status_r"), ("block", "block_w")):
            self.paths[name] = os.path.join(fifo_dir, name)
            os.mkfifo(self.paths[name], 0o600)
            self.fds[key] = os.open(self.paths[name], os.O_RDWR)

    def __getitem__(self, name):
        return self.fds[name]

    def close(self, name):
        fd = self.fds.pop(name, None)
        if fd is not None:
            os.close(fd)

    def close_all(self):
        for name in list(self.fds):
            self.close(name)


def _run_app(argv, filter_fd, pipes=None, instance=None):
    """Start the jail, publish its init pid for the portal, then let the app run; return its exit status."""
    env = {"PATH": "/usr/bin:/bin"}
    if instance is None:
        return subprocess.call(argv, env=env, pass_fds=(filter_fd,))
    proc = subprocess.Popen(argv, env=env, pass_fds=(filter_fd, *(pipes.fds[n] for n in ("status_w", "block_r") if n in pipes.fds)))
    try:
        pipes.close("status_w")
        pipes.close("block_r")
        ready, _, _ = select.select([pipes["status_r"]], [], [], STATUS_TIMEOUT)
        line = b""
        if ready:
            line = os.fdopen(os.dup(pipes["status_r"]), "rb").readline()
        try:
            pid = json.loads(line)["child-pid"]
        except (ValueError, KeyError, TypeError):
            raise RunError("the jail did not report its process id") from None
        instance.child_started(pid)
        pipes.close("block_w")  # the app starts now
        return proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def launch(name, extra_args=(), host_env=None, extract=appimage.extract, say=print, runner=None,
           extra_dirs=(), extra_files=(), proxy=dbusproxy.Proxy, restricted=wayland.RestrictedSocket):
    """Start the app in its jail and return its exit status."""
    m, root, home, etc = prepare(name, extract, say)
    if history.modified(name):
        say(f"Warning: the manifest of {name} was changed outside bjail since its last recorded change "
            f"(see `bjail history {name}` and the config directory's git log).")
    perms = m.permissions
    if extra_dirs:
        perms = replace(perms, dirs=manifest.merge_dirs(perms.dirs, extra_dirs))
        say("Temporary access for this run: " + ", ".join(extra_dirs))
    file_dests = jail.file_binds(extra_files, Path.home())[1] if extra_files else []
    if file_dests:
        say("Temporary file access for this run: " + ", ".join(file_dests))
        extra_args = [*extra_args, *file_dests]
    env = dict(os.environ if host_env is None else host_env)
    in_pasta = perms.network and not perms.network_host
    with contextlib.ExitStack() as stack:
        filter_fd = seccomp.open_fd(perms.userns)
        stack.callback(os.close, filter_fd)
        filter_file = None
        if in_pasta:
            fd, filter_file = tempfile.mkstemp(prefix="bjail-seccomp-", dir=env.get("XDG_RUNTIME_DIR") or None)
            stack.callback(os.unlink, filter_file)
            with os.fdopen(fd, "wb") as f:
                f.write(seccomp.program(perms.userns))
        instance = docs = None
        if perms.portals:
            rt = env.get("XDG_RUNTIME_DIR", "")
            if not rt:
                raise RunError("portals need XDG_RUNTIME_DIR")
            app = portal.app_id(name)
            docs = portal.doc_dir(rt, app, env)
            instance = stack.enter_context(portal.Instance(rt, app, perms.network))
        bus = None
        if dbusproxy.needed(perms):
            bus = stack.enter_context(proxy(perms, env, identity=instance.info) if instance else proxy(perms, env))
        wl_sock = stack.enter_context(restricted(env, app_id=name))
        if wl_sock is None:
            say("Warning: the compositor does not offer wp_security_context_v1, so this app gets the full "
                "Wayland socket (it may be able to capture the screen or inject input where the compositor allows it).")
        fifo_dir = tempfile.mkdtemp(prefix="bjail-pipes-", dir=env.get("XDG_RUNTIME_DIR") or None) if instance and in_pasta else None
        if fifo_dir:
            stack.callback(shutil.rmtree, fifo_dir, ignore_errors=True)
        pipes = Pipes(fifo_dir) if instance else None
        if pipes:
            stack.callback(pipes.close_all)
        args = jail.runtime_args(
            root=root, home=home, etc_dir=etc, perms=perms, uid=os.getuid(), host_env=env,
            command=[f"{jail.APP_DIR}/AppRun", *extra_args], host_home=Path.home(), dbus_socket=bus,
            wayland_socket=wl_sock, seccomp_fd=PASTA_SECCOMP_FD if in_pasta else filter_fd, portal_docs=docs, status_fd=pipes and (PASTA_STATUS_FD if in_pasta else pipes["status_w"]),
            block_fd=pipes and (PASTA_BLOCK_FD if in_pasta else pipes["block_r"]), files=extra_files)
        argv = [jail.find_bwrap(), *args]
        if perms.network and not perms.network_host:
            argv = jail.net_wrap(argv, required=True, fd_files={
                PASTA_SECCOMP_FD: filter_file,
                **({PASTA_STATUS_FD: (">", pipes.paths["status"]), PASTA_BLOCK_FD: ("<", pipes.paths["block"])} if pipes else {})})
        if runner:
            return runner(argv)
        return _run_app(argv, filter_fd, pipes, instance)
