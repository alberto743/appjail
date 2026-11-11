# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A GTK 4 window that copies or pastes through the ordinary clipboard once it has keyboard focus (tests/compositors/clipboard.py).

    python3 clip_client.py copy|paste OUTFILE [TEXT]

OUTFILE gets one line per event: `active` (the window got keyboard focus), `copied`, `pasted:<text>`, `error:<why>`,
`no-focus` or `timeout`. The clipboard here is the core one (wl_data_device), the one an ordinary app uses.
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

mode, out = sys.argv[1], sys.argv[2]
text = sys.argv[3] if len(sys.argv) > 3 else ""
state = {"done": False, "active": False}


def log(line):
    with open(out, "a") as f:
        f.write(line + "\n")


def on_paste(clip, result, app):
    try:
        log("pasted:" + (clip.read_text_finish(result) or ""))
    except GLib.Error as e:
        log("error:" + e.message[:80])
    app.quit()


def on_active(window, _param, app):
    if not window.is_active() or state["done"]:
        return
    state["done"] = True
    state["active"] = True
    log("active")
    clip = window.get_clipboard()
    if mode == "copy":
        # a compositor may accept a new selection only with the serial of an input event: copy at the first key, or, when
        # the compositor offers no way to send one, after 3 s with whatever serial the toolkit has (that is what is tried)
        GLib.timeout_add_seconds(3, lambda: window.get_clipboard() and window_copy(window) or False)
    else:
        GLib.timeout_add(500, lambda: clip.read_text_async(None, on_paste, app) or False)


def window_copy(window):
    if not state.get("copied"):
        state["copied"] = True
        state["fallback"] = True
        window.get_clipboard().set(text)
        GLib.timeout_add(500, lambda: log("copied") or False)


def on_activate(app):
    window = Gtk.ApplicationWindow(application=app, title=f"clip-{mode}", default_width=200, default_height=100)
    window.connect("notify::is-active", on_active, app)
    if mode == "copy":
        keys = Gtk.EventControllerKey()

        def on_key(*_args):
            if not state.get("copied"):
                state["copied"] = True
                window.get_clipboard().set(text)
                GLib.timeout_add(500, lambda: log("copied") or False)
            return False

        keys.connect("key-pressed", on_key)
        window.add_controller(keys)
    window.present()

    def give_up():
        if not state["done"]:
            log("no-focus")
        elif mode == "paste":
            log("timeout")
        if mode == "paste" or not state["done"]:
            app.quit()
        return False

    GLib.timeout_add_seconds(36, give_up)


app = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
app.connect("activate", on_activate)
sys.exit(app.run([]))
