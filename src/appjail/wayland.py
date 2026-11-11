# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Restricted Wayland socket for an app, through the `wp_security_context_v1` protocol, and what its registry offers.

The host compositor's own socket gives a client every protocol the compositor offers, including
screen capture and input injection where it has them. When the compositor implements the security
context protocol, appjail creates a listening socket, hands it to the compositor and tells it that
every client on that socket belongs to a sandbox; the compositor then hides its privileged
interfaces from those clients. Only the minimal part of the wire protocol needed here is spoken
(stdlib sockets, fd passing with SCM_RIGHTS); nothing from the compositor is interpreted beyond
the registry and error events.

What an app may do on the socket it gets is read from that socket's registry (`interfaces`, `privileged`), not inferred
from the compositor's name or from whether it offers the protocol: some compositors restrict the socket (sway, labwc,
Hyprland), some leave privileged globals visible on it (KWin), and some have none on their own socket (GNOME, which guards
the privileged operations on D-Bus). docs/compositor-assessment has the measurements.
"""

import array
import os
import shutil
import socket
import struct
import tempfile
import time
from pathlib import Path

from .errors import RunError

MANAGER = "wp_security_context_manager_v1"
SANDBOX_ENGINE = "appjail"
TIMEOUT = 5.0

# Globals that let a client act on more than its own windows, by what they allow. Measured on nine compositors; the
# listed ones are the ones those compositors offer, so a compositor with others is not covered by name. Left out on
# purpose: zwp_keyboard_shortcuts_inhibit_manager_v1 (an app asks for its shortcuts while it has focus; the only extra
# global GNOME shows) and the capture-*source* managers (they name a target; the copy manager is what captures).
PRIVILEGED = {
    "capture": ("zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1", "zwlr_export_dmabuf_manager_v1",
                "hyprland_toplevel_export_manager_v1", "zkde_screencast_unstable_v1", "weston_capture_v1"),
    "input": ("zwlr_virtual_pointer_manager_v1", "zwp_virtual_keyboard_manager_v1", "zwp_input_method_manager_v2",
              "zwp_input_method_v1", "zwp_input_panel_v1", "org_kde_kwin_fake_input", "zwlr_input_inhibit_manager_v1",
              "hyprland_global_shortcuts_manager_v1", "zwf_shell_manager_v2"),
    "clipboard": ("zwlr_data_control_manager_v1", "ext_data_control_manager_v1"),
    "windows": ("zwlr_foreign_toplevel_manager_v1", "ext_foreign_toplevel_list_v1", "org_kde_plasma_window_management",
                "zwlr_layer_shell_v1", "org_kde_plasma_shell", "weston_desktop_shell", "zwlr_output_manager_v1",
                "zwlr_output_power_manager_v1", "zwlr_gamma_control_manager_v1", "kde_output_management_v2",
                "kde_output_management_v1", "ext_session_lock_manager_v1", "ext_workspace_manager_v1"),
}
CAPABILITY = {
    "capture": "capture the screen",
    "input": "type or click for other apps, or take over the keyboard",
    "clipboard": "read and replace the clipboard without having the focus",
    "windows": "see or control other apps' windows, the screen layout or the lock screen",
}
PRIVILEGED_BY_NAME = {name: kind for kind, names in PRIVILEGED.items() for name in names}
CONNECT_ATTEMPTS = 6  # a compositor may start serving a socket it was just given a moment after it accepted it

DISPLAY_ID, REGISTRY_ID, CALLBACK_ID, MANAGER_ID, CONTEXT_ID = 1, 2, 3, 4, 5


def _string(text):
    raw = text.encode() + b"\0"
    return struct.pack("I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def _message(obj, opcode, payload=b""):
    return struct.pack("II", obj, ((8 + len(payload)) << 16) | opcode) + payload


def _send(sock, data, fds=()):
    anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
    sock.sendmsg([data], anc)


class Events:
    """Incremental reader of compositor events: (object id, opcode, payload) tuples."""

    def __init__(self, sock):
        self.sock, self.buf = sock, b""

    def read(self):
        while True:
            if len(self.buf) >= 8:
                obj, word = struct.unpack("II", self.buf[:8])
                size = word >> 16
                if size < 8:
                    raise RunError("Wayland compositor sent a malformed message")
                if len(self.buf) >= size:
                    msg, self.buf = self.buf[:size], self.buf[size:]
                    return obj, word & 0xFFFF, msg[8:]
            try:
                chunk = self.sock.recv(4096)
            except TimeoutError:
                raise RunError("Wayland compositor did not answer") from None
            if not chunk:
                raise RunError("Wayland compositor closed the connection")
            self.buf += chunk


def _read_string(payload, pos):
    (n,) = struct.unpack_from("I", payload, pos)
    text = payload[pos + 4:pos + 4 + max(n - 1, 0)].decode("utf-8", "replace")
    return text, pos + 4 + n + (-n % 4)


def _roundtrip(sock, events, on_event=None):
    """wl_display.sync, then read until its callback fires. Protocol errors raise RunError."""
    _send(sock, _message(DISPLAY_ID, 0, struct.pack("I", CALLBACK_ID)))
    while True:
        obj, opcode, payload = events.read()
        if obj == DISPLAY_ID and opcode == 0:  # error(object, code, message)
            _, code = struct.unpack_from("II", payload)
            text, _ = _read_string(payload, 8)
            raise RunError(f"Wayland protocol error {code}: {text}")
        if obj == CALLBACK_ID and opcode == 0:
            return
        if on_event:
            on_event(obj, opcode, payload)


def host_socket_path(host_env):
    rt, wl = host_env.get("XDG_RUNTIME_DIR", ""), host_env.get("WAYLAND_DISPLAY", "wayland-0")
    if not rt or not wl or "/" in wl:
        raise RunError("no usable Wayland session (XDG_RUNTIME_DIR / WAYLAND_DISPLAY)")
    path = Path(rt) / wl
    if not path.is_socket():
        raise RunError(f"Wayland socket not found: {path}")
    return path


def _collect(obj, opcode, payload, found):
    if obj == REGISTRY_ID and opcode == 0:
        (name,) = struct.unpack_from("I", payload)
        iface, pos = _read_string(payload, 4)
        (version,) = struct.unpack_from("I", payload, pos)
        found[iface] = (name, version)


def _list(sock):
    """Ask a connected socket for its registry: (events, {interface: (name, version)})."""
    sock.settimeout(TIMEOUT)
    events, found = Events(sock), {}
    _send(sock, _message(DISPLAY_ID, 1, struct.pack("I", REGISTRY_ID)))
    _roundtrip(sock, events, lambda *a: _collect(*a, found))
    return events, found


def read_registry(sock):
    """{interface: version} of the registry of a connected socket, such as a connection handed over as a file descriptor."""
    return {iface: version for iface, (_name, version) in sorted(_list(sock)[1].items())}


def _connect(host_env, path=None):
    """Connection with the registry listed: (socket, events, {interface: (name, version)}). The compositor's own socket,
    or the one at `path`."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(path or host_socket_path(host_env)))
        events, found = _list(sock)
    except BaseException:
        sock.close()
        raise
    return sock, events, found


def registry(host_env, path=None):
    """{interface: version} the registry of a socket lists: the compositor's own, or the restricted one at `path`, which is
    waited for a few seconds (a compositor may serve a socket it was just given a moment after accepting it)."""
    left = CONNECT_ATTEMPTS if path is not None else 1  # only a socket just handed to the compositor is waited for
    while True:
        left -= 1
        try:
            sock, _events, found = _connect(host_env, path)
        except (ConnectionRefusedError, RunError):
            if not left:
                raise
            time.sleep(0.5)
        else:
            sock.close()
            return {iface: version for iface, (_name, version) in sorted(found.items())}


def interfaces(host_env, path=None):
    """The interface names the registry of a socket lists (see `registry`)."""
    return set(registry(host_env, path))


def privileged(names):
    """{kind: [interface, ...]} of the privileged globals among these names (see PRIVILEGED)."""
    found = {}
    for name in sorted(names):
        if name in PRIVILEGED_BY_NAME:
            found.setdefault(PRIVILEGED_BY_NAME[name], []).append(name)
    return found


def describe(found):
    """What the privileged globals of `privileged()` would let an app do, as one sentence fragment."""
    return "; ".join(f"{', '.join(names)} (could {CAPABILITY[kind]})" for kind, names in found.items())


class RestrictedSocket:
    """Context manager: yields the path of a restricted socket, or None if the compositor lacks the protocol.

    The socket lives in a private directory under the host runtime dir. The compositor serves it
    until this object exits (the close pipe hangs up) and the directory is then removed.
    """

    def __init__(self, host_env, app_id="appjail", instance=None):
        self.host_env, self.app_id, self.instance = host_env, app_id, instance or str(os.getpid())
        self.dir = self.conn = self._close_w = None

    def __enter__(self):
        self.conn, events, offered = _connect(self.host_env)
        if MANAGER not in offered:
            self.__exit__()
            return None
        name, _version = offered[MANAGER]
        rt = self.host_env["XDG_RUNTIME_DIR"]
        self.dir = Path(tempfile.mkdtemp(prefix="appjail-wl-", dir=rt))
        try:
            path = self.dir / "wayland-0"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(str(path))
                listener.listen(16)
                close_r, self._close_w = os.pipe()
                try:
                    bind = struct.pack("I", name) + _string(MANAGER) + struct.pack("II", 1, MANAGER_ID)
                    _send(self.conn, _message(REGISTRY_ID, 0, bind))
                    _send(self.conn, _message(MANAGER_ID, 1, struct.pack("I", CONTEXT_ID)),
                          fds=(listener.fileno(), close_r))
                    for opcode, text in ((1, SANDBOX_ENGINE), (2, self.app_id), (3, self.instance)):
                        _send(self.conn, _message(CONTEXT_ID, opcode, _string(text)))
                    _send(self.conn, _message(CONTEXT_ID, 4))  # commit
                    _roundtrip(self.conn, events)
                finally:
                    os.close(close_r)
            finally:
                listener.close()
        except BaseException:
            self.__exit__()
            raise
        return str(path)

    def __exit__(self, *exc):
        if self._close_w is not None:
            os.close(self._close_w)
            self._close_w = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.dir is not None:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = None
