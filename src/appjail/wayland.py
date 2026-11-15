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

# What an app's Wayland socket may list. Every global is in one of two tables, or it is unknown. A global is classified by
# what it gives the app, not by whether refusing it would refuse a common desktop (docs/decisions/desktop/wayland-allowlist.md):
#
# 1. Can it act on, or observe, other apps, the screen, input in general or the user's activity beyond the app's own focus?
#    PRIVILEGED. An app whose socket lists one is refused unless it has full_wayland.
# 2. Does it hand over a host resource that a permission gates, or reach a service the app could not otherwise reach?
#    Allowed only as an accepted limit (basis LIMIT in RATIONALE), when the cost is bounded, with what ends the exception.
# 3. Otherwise it acts on the app's own surfaces, buffers or settings, on input while it has the focus, behind a token, or
#    only describes the hardware: ALLOWED, with the reason in RATIONALE.
#
# Anything else is unknown (a compositor that was not measured, or a new protocol in one that was) and is refused like a
#   privileged global: appjail cannot say what it allows. tests/test_wayland.py checks that every measured name is in one
#   of the tables, so new measurements have to be classified.
PRIVILEGED = {
    "capture": ("zwlr_screencopy_manager_v1", "ext_image_copy_capture_manager_v1", "zwlr_export_dmabuf_manager_v1",
                "hyprland_toplevel_export_manager_v1", "zkde_screencast_unstable_v1", "weston_capture_v1"),
    "input": ("zwlr_virtual_pointer_manager_v1", "zwp_virtual_keyboard_manager_v1", "zwp_input_method_manager_v2",
              "zwp_input_method_v1", "zwp_input_panel_v1", "org_kde_kwin_fake_input", "zwlr_input_inhibit_manager_v1",
              "hyprland_global_shortcuts_manager_v1", "zwf_shell_manager_v2", "ext_transient_seat_manager_v1",
              "hyprland_focus_grab_manager_v1"),
    "clipboard": ("zwlr_data_control_manager_v1", "ext_data_control_manager_v1"),
    "windows": ("zwlr_foreign_toplevel_manager_v1", "ext_foreign_toplevel_list_v1", "org_kde_plasma_window_management",
                "zwlr_layer_shell_v1", "org_kde_plasma_shell", "weston_desktop_shell", "zwlr_output_manager_v1",
                "zwlr_output_power_manager_v1", "zwlr_gamma_control_manager_v1", "kde_output_management_v2",
                "kde_output_management_v1", "ext_session_lock_manager_v1", "ext_workspace_manager_v1",
                "zcosmic_workspace_manager_v1", "hyprland_toplevel_mapping_manager_v1", "hyprland_ctm_control_manager_v1",
                "hyprland_lock_notifier_v1", "kde_lockscreen_overlay_v1", "org_kde_plasma_activation_feedback",
                "org_kde_kwin_appmenu_manager", "xapp_shell_v1"),
    "desktop": ("org_kde_kwin_dpms_manager", "kde_external_brightness_v1", "org_kde_plasma_virtual_desktop_management",
                "kde_screen_edge_manager_v1", "org_kde_kwin_keystate"),
}
OWN, FOCUS, TOKEN, FACTS, LIMIT = "own", "focus", "token", "facts", "limit"
BASIS = {
    OWN: "acts only on the client's own surfaces, buffers or settings",
    FOCUS: "acts only while the client has the focus, or on an input serial it was given",
    TOKEN: "needs a token or handle that another client or the compositor handed over",
    FACTS: "describes the hardware, the outputs or the settings; changes nothing",
    LIMIT: "accepted limit, decided (docs/decisions/desktop/wayland-allowlist.md)",
}
# Where the protocol was read. The first two are the XML shipped by the distributions (read in the Fedora 45 guest); "core" is
# wayland.xml; the others are the definition and the compositor's own code in the source package of the version measured
# (the Debian and Ubuntu source packages, Fedora's source RPM), and for wl_drm and gtk_shell1 the live behaviour too.
# UNREAD is a name appjail only knows from the compositors that list it; tests/test_wayland.py allows none.
READ_WP, READ_PLASMA, READ_CORE, UNREAD = "wayland-protocols", "plasma-wayland-protocols", "core", "unread"
READ_GTK = "gtk-shell.xml, gtk-primary-selection.xml, gtk-text-input.xml (Mutter 48.7, Muffin 6.4.1 sources)"
READ_MESA = "wayland-drm.xml (Mesa 26.1.6, KWin 6.3.6) and live on KWin and Hyprland"
READ_HYPRLAND = "hyprland-surface-v1.xml (hyprland-protocols 0.7.1) and Hyprland 0.55.2 source"
READ_FROG = "frog-color-management-v1.xml (KWin 6.3.6)"

# Every global an app's socket may list without full_wayland, with why: (basis, where its protocol was read, note).
# The basis answers the rule in docs/decisions/desktop/wayland-allowlist.md; tests/test_wayland.py checks the table is complete.
RATIONALE = {
    # core, xdg and stable or staging client protocols
    "wl_compositor": (OWN, READ_CORE, "creates the client's surfaces"),
    "wl_subcompositor": (OWN, READ_CORE, "sub-surfaces of the client's own surfaces"),
    "wl_shm": (OWN, READ_CORE, "the client's own shared-memory buffers"),
    "wl_seat": (FOCUS, READ_CORE, "input goes to the focused client only"),
    "wl_output": (FACTS, READ_CORE, "geometry, make, model and scale of the outputs"),
    "wl_data_device_manager": (FOCUS, READ_CORE, "selection and drag-and-drop reach the focused client; reading the clipboard needs a paste"),
    "wl_drm": (OWN, READ_MESA, "Mesa's buffer sharing: the device name, and buffers the client makes from its own dmabuf; a buffer by flink name is refused (KWin, Hyprland, tried)"),
    "wl_fixes": (OWN, READ_CORE, "destroys the client's own registry"),
    "xdg_wm_base": (OWN, READ_WP, "makes the client's surfaces windows"),
    "xdg_wm_dialog_v1": (OWN, READ_WP, "marks the client's own dialog modal"),
    "xdg_activation_v1": (TOKEN, READ_WP, "needs a serial of the client or a token it was handed; the compositor may ignore it"),
    "xdg_system_bell_v1": (OWN, READ_WP, "rings the system bell"),
    "xdg_toplevel_drag_manager_v1": (FOCUS, READ_WP, "attaches the client's window to a drag it started"),
    "xdg_toplevel_icon_manager_v1": (OWN, READ_WP, "the icon of the client's own window"),
    "xdg_toplevel_tag_manager_v1": (OWN, READ_WP, "a tag and description of the client's own window"),
    "zxdg_decoration_manager_v1": (OWN, READ_WP, "the decoration mode of the client's own window"),
    "zxdg_output_manager_v1": (FACTS, READ_WP, "names and logical layout of the outputs"),
    "zxdg_exporter_v1": (TOKEN, READ_WP, "gives out a handle to the client's own window"),
    "zxdg_exporter_v2": (TOKEN, READ_WP, "gives out a handle to the client's own window"),
    "zxdg_importer_v1": (TOKEN, READ_WP, "needs a handle another client exported"),
    "zxdg_importer_v2": (TOKEN, READ_WP, "needs a handle another client exported"),
    "xwayland_shell_v1": (OWN, READ_WP, "pairs the client's surface with an X11 window; compositors hide it from clients but Xwayland"),
    "wp_viewporter": (OWN, READ_WP, "crops and scales the client's own surface"),
    "wp_presentation": (FACTS, READ_WP, "timing of the client's own frames"),
    "wp_single_pixel_buffer_manager_v1": (OWN, READ_WP, "a buffer of the client"),
    "wp_fractional_scale_manager_v1": (FACTS, READ_WP, "the preferred scale of the client's own surface"),
    "wp_cursor_shape_manager_v1": (FOCUS, READ_WP, "the cursor shape while the client has the pointer"),
    "wp_tearing_control_manager_v1": (OWN, READ_WP, "a hint about the client's own surface"),
    "wp_content_type_manager_v1": (OWN, READ_WP, "a hint about the client's own surface"),
    "wp_alpha_modifier_v1": (OWN, READ_WP, "the opacity of the client's own surface"),
    "wp_fifo_manager_v1": (OWN, READ_WP, "presentation order of the client's own commits"),
    "wp_commit_timing_manager_v1": (OWN, READ_WP, "timing of the client's own commits"),
    "wp_color_manager_v1": (LIMIT, READ_WP, "colour of the client's own surface, and the colour profile (ICC) of the outputs: a hardware fingerprint"),
    "wp_color_representation_manager_v1": (OWN, READ_WP, "how the client's own buffer is interpreted"),
    "wp_linux_drm_syncobj_manager_v1": (OWN, READ_WP, "synchronisation of the client's own buffers"),
    "wp_pointer_warp_v1": (FOCUS, READ_WP, "moves the pointer within the client's focused surface, on a serial"),
    "wp_drm_lease_device_v1": (LIMIT, READ_WP, ("sends the client an unprivileged DRM file descriptor (a render node on GNOME) without the "
                                                "gpu permission; leasing a display needs an output the desktop does not use")),
    "wp_security_context_manager_v1": (OWN, READ_WP, "can only make another socket that is more restricted"),
    "zwp_linux_dmabuf_v1": (OWN, READ_WP, "the client's own GPU buffers; feedback names the device, it does not open it"),
    "zwp_linux_explicit_synchronization_v1": (OWN, READ_WP, "synchronisation of the client's own buffers"),
    "zwp_primary_selection_device_manager_v1": (FOCUS, READ_WP, "the primary selection reaches the focused client"),
    "zwp_relative_pointer_manager_v1": (FOCUS, READ_WP, "relative motion while the client has the pointer"),
    "zwp_pointer_constraints_v1": (FOCUS, READ_WP, "locks or confines the pointer while the client has the focus"),
    "zwp_pointer_gestures_v1": (FOCUS, READ_WP, "gestures on the client's focused surface"),
    "zwp_tablet_manager_v2": (FOCUS, READ_WP, "tablet input while the client has the focus"),
    "zwp_idle_inhibit_manager_v1": (LIMIT, READ_WP, "keeps the screen from blanking or locking while the client's surface is visible"),
    "zwp_input_timestamps_manager_v1": (FOCUS, READ_WP, "timestamps of the input the client receives"),
    "zwp_keyboard_shortcuts_inhibit_manager_v1": (FOCUS, READ_WP, "receives the desktop's shortcuts while focused"),
    "zwp_text_input_manager_v1": (FOCUS, READ_WP, "the input method of the focused client"),
    "zwp_text_input_manager_v2": (FOCUS, READ_PLASMA, "the input method of the focused client"),
    "zwp_text_input_manager_v3": (FOCUS, READ_WP, "the input method of the focused client"),
    "ext_idle_notifier_v1": (LIMIT, READ_WP, "tells whether the user is idle: a privacy signal, no request acts on anything"),
    "ext_output_image_capture_source_manager_v1": (OWN, READ_WP, "names an output as a capture source; capturing needs the copy manager, which is privileged"),
    "ext_foreign_toplevel_image_capture_source_manager_v1": (OWN, READ_WP, "names a window as a capture source; capturing needs the copy manager, which is privileged"),
    # older versions of the above, which Muffin lists: the deprecated core shell and the unstable xdg shell (own windows),
    # and GTK's own primary selection and text input (the focused client's selection and input method, as the zwp_ ones)
    "wl_shell": (OWN, READ_CORE, "the deprecated shell: the client's own windows"),
    "zxdg_shell_v6": (OWN, READ_WP, "the unstable xdg shell: the client's own windows"),
    "gtk_primary_selection_device_manager": (FOCUS, READ_GTK, "GTK's own version of the primary selection: only the client with the keyboard focus receives the offer"),
    "gtk_text_input_manager": (FOCUS, READ_GTK, "GTK's own version of text input: enable, disable and surrounding text of the focused client"),
    # compositor extras
    "gtk_shell1": (LIMIT, READ_GTK, "own windows, but any client can take the keyboard focus (present, or notify_launch and request_focus, with no token) and GNOME Shell calls a D-Bus name the client picks"),
    "hyprland_surface_manager_v1": (OWN, READ_HYPRLAND, "opacity and visible region of the client's own surface (set_opacity, set_visible_region)"),
    "frog_color_management_factory_v1": (OWN, READ_FROG, "colour management of the client's own surface; the preferred metadata is a fact about its output"),
    "org_kde_kwin_idle": (LIMIT, READ_PLASMA, "idle notification; simulate_user_activity resets the idle timer, as an idle inhibitor already can"),
    "org_kde_kwin_server_decoration_manager": (OWN, READ_PLASMA, "the decoration mode of the client's own window"),
    "org_kde_kwin_server_decoration_palette_manager": (OWN, READ_PLASMA, "the title-bar colours of the client's own window"),
    "org_kde_kwin_shadow_manager": (OWN, READ_PLASMA, "the shadow of the client's own surface"),
    "kde_output_device_v2": (LIMIT, READ_PLASMA, "describes the outputs, with their EDID and serial numbers: a hardware fingerprint"),
    "kde_output_order_v1": (FACTS, READ_PLASMA, "the order of the outputs; events only"),
    # new in Fedora 45
    "ext_background_effect_manager_v1": (OWN, READ_WP, "blur behind the client's own translucent surface"),
    "xdg_session_manager_v1": (TOKEN, READ_WP, "the client's own toplevels, restored through a session token the compositor makes"),
    "kde_output_device_registry_v2": (LIMIT, READ_PLASMA, "the list of outputs, as kde_output_device_v2 describes them"),
}
ALLOWED = frozenset(RATIONALE)
UNKNOWN = "unknown"
CAPABILITY = {
    "capture": "capture the screen",
    "input": "type or click for other apps, or take over the keyboard",
    "clipboard": "read and replace the clipboard without having the focus",
    "windows": "see or control other apps' windows, see which apps start, change the screen layout or the lock screen, or make the "
               "shell call a D-Bus service or open an icon file of the app's choosing",
    "desktop": "switch the screens off, change their brightness, the virtual desktops or the screen edges, or read the "
               "lock keys",
    UNKNOWN: "do something appjail has not checked: these interfaces are not known to it",
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
    """{kind: [interface, ...]} of the globals among these names that an app may not have without full_wayland: the
    privileged ones by what they allow (see PRIVILEGED), and under UNKNOWN those in neither list (see ALLOWED)."""
    found = {}
    for name in sorted(names):
        if name in PRIVILEGED_BY_NAME:
            found.setdefault(PRIVILEGED_BY_NAME[name], []).append(name)
        elif name not in ALLOWED:
            found.setdefault(UNKNOWN, []).append(name)
    return found


def describe(found):
    """What the privileged globals of `privileged()` would let an app do, as one sentence fragment."""
    return "; ".join(f"{', '.join(names)} (could {CAPABILITY[kind]})"
                     for kind, names in sorted(found.items(), key=lambda item: item[0] == UNKNOWN))


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
