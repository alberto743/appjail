# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Run an installed app: verify the pin, make sure the tree matches it, start the jail."""

import contextlib
import json
import os
import select
import shutil
import signal
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from . import (
    appimage,
    audiojail,
    audiomode,
    dbusproxy,
    grants,
    history,
    jail,
    landlock,
    manifest,
    portal,
    runtimejail,
    seccomp,
    store,
    wayland,
)
from .errors import RunError
from .jail import PASTA_SECCOMP_FD

# More descriptors the pasta wrapper opens for bwrap (single digits: dash redirects accept no more; see jail.net_wrap).
PASTA_STATUS_FD, PASTA_BLOCK_FD = 8, 7


def _passwd(uid, gid):
    return (f"root:x:0:0:root:/root:/usr/sbin/nologin\napp:x:{uid}:{gid}:app:{runtimejail.APP_HOME}:/bin/sh\n",
            f"root:x:0:\napp:x:{gid}:\n")


def _warner(say, warn):
    """How to warn: the console's `warn`, or through `say` with the same prefix when the caller has no console."""
    return warn or (lambda text: say(f"! warning: {text}"))


def prepare(name, extract=appimage.extract, say=print, warn=None):
    """Return (manifest, root, home, etc_dir) ready for launch.

    Refuses to run when the stored AppImage no longer matches the pinned sha256. Re-extracts
    when the tree is missing or was made from a different file.
    """
    mpath = store.manifest_path(manifest.check_name(name))
    if not mpath.exists():
        raise RunError(f"unknown app '{name}'")
    m = manifest.load(mpath)
    image = store.appimage_path(name)
    if not image.is_file():
        raise RunError(f"{image} is missing")
    digest = store.sha256_file(image)
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
            _warner(say, warn)(f"the extracted tree of {name} is missing its record or was modified; extracting it again from the verified image")
    if not valid:
        say(f"Extracting {name} (no valid extracted tree)…")
        appimage.remove_tree(root)
        try:
            extract(image, root, False)
        except appimage.EXTRACT_ERRORS as e:
            raise RunError(f"cannot extract {name}: {e}") from e
        store.atomic_write(marker, digest + "\n")
        store.atomic_write(tree_mark, appimage.tree_digest(root) + "\n")
    home, etc = store.home_path(name), store.etc_path(name)
    for d in (home, etc):
        store.make_private(d)
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


def _wait_group(proc):
    """Wait for the app's process group; forward SIGINT, SIGTERM and SIGHUP to the whole group and leave nothing behind.

    Needed because killing pasta alone (or appjail) does not stop the jail it started: bwrap's --die-with-parent does
    not follow pasta's namespace helper, so an app with `network` would keep running, unsupervised, after its launcher.
    """
    def forward(signum, _frame):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signum)
    try:
        old = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    except ValueError:  # not the main thread: no handlers, the group is still cleaned up below
        old = {}
    try:
        return proc.wait()
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def _run_app(argv, filter_fd=None, pipes=None, instance=None, grant_fds=()):
    """Start the jail, publish its init pid for the portal, then let the app run; return its exit status.

    filter_fd: the seccomp memfd bwrap inherits; None behind pasta, which closes inherited descriptors (the filter
    then reaches bwrap through a file, see jail.net_wrap). grant_fds: the granted paths bwrap binds; empty behind pasta.
    """
    env = {"PATH": "/usr/bin:/bin"}
    keep = (*grant_fds, *(() if filter_fd is None else (filter_fd,)))
    if instance is None:
        return _wait_group(subprocess.Popen(argv, env=env, pass_fds=keep, start_new_session=True))
    proc = subprocess.Popen(argv, env=env, start_new_session=True,
                            pass_fds=(*keep, *(pipes.fds[n] for n in ("status_w", "block_r") if n in pipes.fds)))
    try:
        pipes.close("status_w")
        pipes.close("block_r")
        ready, _, _ = select.select([pipes["status_r"]], [], [], STATUS_TIMEOUT)
        line = b""
        if ready:
            with os.fdopen(os.dup(pipes["status_r"]), "rb") as status:
                line = status.readline()
        try:
            pid = json.loads(line)["child-pid"]
        except (ValueError, KeyError, TypeError):
            raise RunError("the jail did not report its process id") from None
        instance.child_started(pid)
        pipes.close("block_w")  # the app starts now
        return _wait_group(proc)
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def _open_grants(stack, perms, extra_dirs, extra_files, extra_args, say):
    """Open the app's grants with those of this run (`--dir`, `--file`): (permissions, Grants, the app's arguments)."""
    if extra_dirs:
        perms = replace(perms, dirs=grants.merge_dirs(perms.dirs, extra_dirs))
        say("Temporary access for this run: " + ", ".join(extra_dirs))
    opened = stack.enter_context(runtimejail.Grants(perms.dirs, extra_files, Path.home()))
    if opened.file_dests:
        say("Temporary file access for this run: " + ", ".join(opened.file_dests))
        extra_args = [*extra_args, *opened.file_dests]
    return perms, opened, extra_args


def _seccomp_filter(stack, perms, env, in_pasta):
    """The seccomp filter as (lifeline, memfd, file): a file behind pasta, which closes inherited descriptors."""
    if not in_pasta:
        filter_fd = seccomp.open_fd(perms.userns)
        stack.callback(os.close, filter_fd)
        return None, filter_fd, None
    life = stack.enter_context(jail.Lifeline(env.get("XDG_RUNTIME_DIR")))
    fd, filter_file = tempfile.mkstemp(prefix="appjail-seccomp-", dir=env.get("XDG_RUNTIME_DIR") or None)
    stack.callback(os.unlink, filter_file)
    with os.fdopen(fd, "wb") as f:
        f.write(seccomp.program(perms.userns))
    return life, None, filter_file


def _portal_and_bus(stack, name, perms, env, proxy):
    """The portal instance and document directory, and the filtered bus socket, each only when the app needs it."""
    instance = docs = bus = None
    if perms.portals:
        rt = env.get("XDG_RUNTIME_DIR", "")
        if not rt:
            raise RunError("portals need XDG_RUNTIME_DIR")
        app = portal.app_id(name)
        docs = portal.doc_dir(rt, app, env)
        instance = stack.enter_context(portal.Instance(rt, app, perms.network))
    if dbusproxy.needed(perms):
        bus = stack.enter_context(proxy(perms, env, identity=instance.info) if instance else proxy(perms, env))
    return instance, docs, bus


def _status_pipes(stack, instance, env, in_pasta):
    """The pipes that report the jail's init pid to the portal (FIFOs behind pasta); None without a portal instance."""
    if not instance:
        return None
    fifo_dir = tempfile.mkdtemp(prefix="appjail-pipes-", dir=env.get("XDG_RUNTIME_DIR") or None) if in_pasta else None
    if fifo_dir:
        stack.callback(shutil.rmtree, fifo_dir, ignore_errors=True)
    pipes = Pipes(fifo_dir)
    stack.callback(pipes.close_all)
    return pipes


def _private_audio(stack, name, perms, env, warn):
    """(graph, backend): the app's private audio graph, started when `audio_mode = pipewire` can be used, else None.

    The backend is `pulse` when the app gets the host's Pulse socket and None otherwise; a warning says why when it is not
    what was asked.
    """
    backend, note = audiomode.resolve(perms, env)
    graph = None
    if backend == audiomode.PIPEWIRE:
        try:
            graph = stack.enter_context(audiojail.PrivateAudio(name, perms.mic, audiomode.host_pulse(env), env["XDG_RUNTIME_DIR"],
                                                               os.getuid(), os.getgid()))
        except audiojail.AudioUnavailable as e:
            pulse, refused = audiomode.usable_pulse(env)
            backend, note = audiomode.fallback(perms, str(e), pulse is not None, refused)
    if note:
        warn(note)
    return graph, backend


def _check_wayland_socket(name, perms, restricted_socket, offered, warn):
    """Refuse the app (or warn, with `full_wayland`) when the socket it will get lists privileged globals or globals
    appjail does not know (`wayland.privileged`): the restricted socket when the compositor made one, else the
    compositor's own. What matters is what that socket lets a client do."""
    found = wayland.privileged(offered)
    if not found:
        return
    if restricted_socket is None:
        which = "the compositor does not offer wp_security_context_v1, so this app would get its own Wayland socket"
    else:
        which = "the restricted Wayland socket this compositor makes for this app"
    what = f"{which}, which lists {wayland.describe(found)}"
    if not perms.full_wayland:
        raise RunError(f"{what}. {name} is not allowed that. Run it on a compositor that hides them, or accept it with "
                       f"`appjail perms {name} --allow full_wayland`")
    warn(f"{what}, and full_wayland is granted, so the app runs with it")


def launch(name, extra_args=(), host_env=None, extract=appimage.extract, say=print, warn=None, runner=None,
           extra_dirs=(), extra_files=(), proxy=dbusproxy.Proxy, restricted=wayland.RestrictedSocket,
           registry=wayland.interfaces):
    """Start the app in its jail and return its exit status."""
    warn = _warner(say, warn)
    m, root, home, etc = prepare(name, extract, say, warn)
    if history.modified(name):
        warn(f"the manifest of {name} was changed outside appjail since its last recorded change "
             f"(see `appjail history {name}` and the config directory's git log)")
    env = dict(os.environ if host_env is None else host_env)
    scoped = landlock.available()
    with contextlib.ExitStack() as stack:
        perms, opened, extra_args = _open_grants(stack, m.permissions, extra_dirs, extra_files, extra_args, say)
        if perms.network_host and not scoped:
            raise RunError(landlock.NEEDED_FOR_NETWORK_HOST)
        wl_sock = stack.enter_context(restricted(env, app_id=name)) if perms.windowed else None
        if perms.windowed:
            _check_wayland_socket(name, perms, wl_sock, registry(env, wl_sock), warn)
        in_pasta = perms.pasta
        audio, audio_backend = _private_audio(stack, name, perms, env, warn)
        life, filter_fd, filter_file = _seccomp_filter(stack, perms, env, in_pasta)
        instance, docs, bus = _portal_and_bus(stack, name, perms, env, proxy)
        pipes = _status_pipes(stack, instance, env, in_pasta)
        args = runtimejail.runtime_args(
            root=root, home=home, etc_dir=etc, perms=perms, uid=os.getuid(), host_env=env,
            command=[f"{runtimejail.APP_DIR}/AppRun", *extra_args], dbus_socket=bus,
            wayland_socket=wl_sock, audio_sockets=audio and (audio.pipewire_socket, audio.pulse_socket),
            host_audio=audio_backend == audiomode.PULSE, seccomp_fd=PASTA_SECCOMP_FD if in_pasta else filter_fd, portal_docs=docs, status_fd=pipes and (PASTA_STATUS_FD if in_pasta else pipes["status_w"]),
            block_fd=pipes and (PASTA_BLOCK_FD if in_pasta else pipes["block_r"]), binds=opened.args(in_pasta))
        argv = [jail.find_bwrap(), *args]
        if in_pasta:
            argv = jail.net_wrap(opened.reopened(argv), required=True, lifeline=life.path, fd_files={
                PASTA_SECCOMP_FD: filter_file,
                **({PASTA_STATUS_FD: (">", pipes.paths["status"]), PASTA_BLOCK_FD: ("<", pipes.paths["block"])} if pipes else {})})
        if scoped and not in_pasta:  # pasta's private namespace already isolates abstract sockets, and pasta does not
            argv = landlock.wrap(argv)  # start its command under the no_new_privs that Landlock needs
        if runner:
            return runner(argv)
        return _run_app(argv, filter_fd, pipes, instance, () if in_pasta else opened.fds)
