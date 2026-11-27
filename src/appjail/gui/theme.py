# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The window's look: two palettes (light and dark) on ttk's `clam` theme, with rounded buttons, fields, cards, check
boxes and switches drawn by gui/icons.py. Whether to start dark is read from the desktop's appearance setting."""

import base64
import os
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .. import portal
from ..errors import RunError
from . import icons

LIGHT = {
    "bg": "#ffffff", "side": "#f1f5f9", "border": "#e2e8f0", "line": "#cbd5e1", "text": "#0f172a", "muted": "#64748b",
    "accent": "#0369a1", "accent_hover": "#075985", "accent_pressed": "#0c4a6e", "accent_fg": "#ffffff",
    "soft": "#e0f2fe", "soft_fg": "#075985", "button": "#ffffff", "button_hover": "#f1f5f9", "button_pressed": "#e2e8f0",
    "danger": "#b42318", "danger_soft": "#fee4e2", "warn": "#b54708", "warn_soft": "#fef0c7", "ok": "#067647",
    "field": "#ffffff", "disabled": "#94a3b8", "log": "#f8fafc",
}
DARK = {
    "bg": "#111827", "side": "#0b0f19", "border": "#263041", "line": "#334155", "text": "#e5e7eb", "muted": "#94a3b8",
    "accent": "#38bdf8", "accent_hover": "#7dd3fc", "accent_pressed": "#0ea5e9", "accent_fg": "#082f49",
    "soft": "#0c3350", "soft_fg": "#7dd3fc", "button": "#1a2232", "button_hover": "#222c3f", "button_pressed": "#2a3650",
    "danger": "#f97066", "danger_soft": "#3a1a1a", "warn": "#fdb022", "warn_soft": "#3a2a0a", "ok": "#47cd89",
    "field": "#0d1320", "disabled": "#4b5563", "log": "#0b0f19",
}

PORTAL_DESKTOP = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")


def parse_color_scheme(reply):
    """True for "prefer dark" in a dbus-send reply to Settings.ReadOne(org.freedesktop.appearance, color-scheme)."""
    found = re.findall(r"\buint32 (\d+)", reply or "")
    return bool(found) and found[-1] == "1"


def prefers_dark(host_env=None):
    """The desktop's colour-scheme preference, read from the settings portal; light when it cannot be read."""
    try:
        reply = portal.bus_call(dict(os.environ if host_env is None else host_env), *PORTAL_DESKTOP,
                                "org.freedesktop.portal.Settings.ReadOne", "string:org.freedesktop.appearance",
                                "string:color-scheme", timeout=1.0)
    except RunError:
        return False
    return parse_color_scheme(reply)


class Theme:
    """Applies a palette to the root and every widget; `toggle` switches palettes while the window is open."""

    def __init__(self, root, dark=False, scale=1.0):
        self.root, self.scale, self.dark = root, scale, dark
        self.images, self.element_images = {}, {}
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._fonts()
        self.apply(dark)

    @property
    def p(self):
        return DARK if self.dark else LIGHT

    def px(self, n):
        return max(round(n * self.scale), 1)

    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        families = set(tkfont.families(self.root))
        for family in ("Inter", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"):
            if family in families:
                for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
                    tkfont.nametofont(name).configure(family=family)
                break
        size = base.actual("size")  # negative: pixels; keep the user's size, only derive from it
        bigger = (lambda n: size - n) if size < 0 else (lambda n: size + round(n * 0.75))
        smaller = (lambda n: min(size + n, -8)) if size < 0 else (lambda n: max(size - round(n * 0.75), 7))
        family = base.actual("family")
        self.fonts = {
            "title": tkfont.Font(self.root, family=family, size=bigger(6), weight="bold"),
            "heading": tkfont.Font(self.root, family=family, size=bigger(2), weight="bold"),
            "strong": tkfont.Font(self.root, family=family, size=size, weight="bold"),
            "small": tkfont.Font(self.root, family=family, size=smaller(1)),
            "mono": tkfont.nametofont("TkFixedFont"),
        }

    def _image(self, key, png):
        image = tk.PhotoImage(master=self.root, data=base64.b64encode(png))
        self.images[key] = image
        return image

    def _element(self, name, specs, radius=8, size=(160, 48)):
        """A 9-slice image element from [(state, fill, border)], the first being the default. ttk cannot redefine an
        element, so on a later call (the other palette) the same images get new pixels.

        The image is drawn at about `size`, larger than any corner needs: Tk tiles the middle of the image across the
        widget and blends every tile through the X server, so a small middle makes each widget slow to draw. Its
        requested size stays that of the corners alone."""
        r = self.px(radius)
        least = r * 2 + 4
        width, height = max(self.px(size[0]), least), max(self.px(size[1]), least)
        pngs = [(state, icons.frame(width, height, r, fill, border, max(self.scale, 1.0))) for state, fill, border in specs]
        if name in self.element_images:
            for image, (_, png) in zip(self.element_images[name], pngs):
                image.configure(data=base64.b64encode(png))
            return
        images = [self._image(f"{name}:{state}", png) for state, png in pngs]
        self.element_images[name] = images
        self.style.element_create(name, "image", images[0], *[(state, image) for (state, _), image in zip(pngs[1:], images[1:])],
                                  border=r + 1, padding=self.px(3), width=least, height=least, sticky="nsew")

    def apply(self, dark):
        self.dark = dark
        p, s, px = self.p, self.style, self.px
        r = self.root
        r.configure(background=p["bg"])
        s.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["field"], bordercolor=p["line"],
                    lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["side"], selectbackground=p["soft"],
                    selectforeground=p["text"], insertcolor=p["text"], focuscolor=p["accent"], arrowcolor=p["muted"],
                    font="TkDefaultFont")
        # clam paints a widget's background lighter when hovered or disabled; behind the rounded images that shows as corners
        s.map(".", foreground=[("disabled", p["disabled"])],
              background=[("disabled", p["bg"]), ("pressed", p["bg"]), ("active", p["bg"]), ("selected", p["bg"])])
        for style in ("TButton", "TCheckbutton", "TRadiobutton"):  # clam maps these itself, ahead of "."
            s.map(style, background=[("disabled", p["bg"]), ("pressed", p["bg"]), ("active", p["bg"])])
        s.configure("Rule.TFrame", background=p["border"])
        s.layout("Bare.TLabelframe", [("Frame.border", {"sticky": "nsew"})])
        s.configure("Bare.TLabelframe", borderwidth=0, relief="flat")
        # buttons: secondary (default), accent, danger
        self._element("Rounded.button", [(None, p["button"], p["line"]), ("disabled", p["bg"], p["border"]),
                                         ("pressed", p["button_pressed"], p["line"]), ("active", p["button_hover"], p["line"]),
                                         ("focus", p["button"], p["accent"])])
        self._element("Accent.button", [(None, p["accent"], None), ("disabled", p["border"], None),
                                        ("pressed", p["accent_pressed"], None), ("active", p["accent_hover"], None),
                                        ("focus", p["accent"], p["accent_pressed"])])
        self._element("Danger.button", [(None, p["button"], p["line"]), ("disabled", p["bg"], p["border"]),
                                        ("pressed", p["danger_soft"], p["danger"]), ("active", p["danger_soft"], p["danger"]),
                                        ("focus", p["button"], p["danger"])])
        self._element("Nav.button", [(None, p["side"], None), ("selected", p["soft"], None), ("active", p["button_hover"], None),
                                     ("focus", p["side"], p["line"])])
        self._element("Seg.button", [(None, p["bg"], p["border"]), ("selected", p["soft"], p["soft"]), ("active", p["button_hover"], p["border"]),
                                     ("focus", p["bg"], p["accent"])], radius=7)
        self._element("Rounded.field", [(None, p["field"], p["line"]), ("disabled", p["bg"], p["border"]),
                                        ("focus", p["field"], p["accent"]), ("invalid", p["field"], p["danger"])], radius=6)
        self._element("Card.border", [(None, p["bg"], p["border"])], radius=10, size=(400, 300))
        self._element("Chip.border", [(None, p["soft"], None)], radius=9, size=(96, 24))
        self._element("Warn.border", [(None, p["warn_soft"], None)], radius=9, size=(96, 24))
        self._element("Plain.border", [(None, p["side"], None)], radius=9, size=(96, 24))
        thumb = [(None, p["line"], None), ("active", p["muted"], None), ("pressed", p["muted"], None)]
        self._element("Vertical.Thumb.pill", thumb, radius=4, size=(0, 120))  # as thin as the bar, long along it
        self._element("Horizontal.Thumb.pill", thumb, radius=4, size=(120, 0))
        self._indicators()
        pad = (px(12), px(3))
        button_layout = lambda element: [(element, {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})]
        for style, element in (("TButton", "Rounded.button"), ("Accent.TButton", "Accent.button"),
                               ("Danger.TButton", "Danger.button")):
            s.layout(style, button_layout(element))
            s.configure(style, padding=pad, anchor="center", relief="flat")
        s.map("TButton", foreground=[("disabled", p["disabled"])])
        s.map("Accent.TButton", foreground=[("disabled", p["disabled"]), ("!disabled", p["accent_fg"])])
        s.configure("Accent.TButton", font=self.fonts["strong"])
        s.map("Danger.TButton", foreground=[("disabled", p["disabled"]), ("!disabled", p["danger"])])
        # the sidebar: radio buttons that look like a list of pages
        s.layout("Nav.TRadiobutton", [("Nav.button", {"sticky": "nsew", "children": [
            ("Radiobutton.padding", {"sticky": "nsew", "children": [("Radiobutton.label", {"sticky": "w"})]})]})])
        s.configure("Nav.TRadiobutton", padding=(px(12), px(7)), background=p["side"], font=self.fonts["strong"], anchor="w")
        s.map("Nav.TRadiobutton", foreground=[("selected", p["soft_fg"]), ("!selected", p["muted"])],
              background=[("!disabled", p["side"])])
        # segments: one of several panes, on a page
        s.layout("Seg.TRadiobutton", [("Seg.button", {"sticky": "nsew", "children": [
            ("Radiobutton.padding", {"sticky": "nsew", "children": [("Radiobutton.label", {"sticky": "nsew"})]})]})])
        s.configure("Seg.TRadiobutton", padding=(px(10), px(2)), anchor="w")
        s.map("Seg.TRadiobutton", foreground=[("selected", p["soft_fg"]), ("!selected", p["muted"])])
        # fields
        s.layout("TEntry", [("Rounded.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
        s.configure("TEntry", padding=(px(6), px(2)), foreground=p["text"])
        s.map("TEntry", foreground=[("disabled", p["disabled"])])
        s.layout("TCombobox", [("Rounded.field", {"sticky": "nsew", "children": [
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]})]})])
        s.configure("TCombobox", padding=(px(6), px(1)), arrowsize=px(12), background=p["field"], foreground=p["text"],
                    arrowcolor=p["muted"], bordercolor=p["field"], lightcolor=p["field"], darkcolor=p["field"])
        s.map("TCombobox", fieldbackground=[("readonly", p["field"]), ("disabled", p["bg"])], background=[("!disabled", p["field"])],
              foreground=[("disabled", p["disabled"]), ("readonly", p["text"])], selectbackground=[("readonly", p["field"])],
              selectforeground=[("readonly", p["text"])], arrowcolor=[("disabled", p["disabled"])])
        r.option_add("*TCombobox*Listbox.background", p["field"])
        r.option_add("*TCombobox*Listbox.foreground", p["text"])
        r.option_add("*TCombobox*Listbox.selectBackground", p["soft"])
        r.option_add("*TCombobox*Listbox.selectForeground", p["text"])
        r.option_add("*TCombobox*Listbox.font", "TkDefaultFont")
        # check boxes, radio buttons, switches
        for kind in ("Checkbutton", "Radiobutton"):
            s.layout(f"T{kind}", [(f"{kind}.padding", {"sticky": "nsew", "children": [
                (f"Pretty.{kind.lower()}", {"side": "left", "sticky": ""}),
                (f"{kind}.focus", {"side": "left", "sticky": "w", "children": [(f"{kind}.label", {"sticky": "nsew"})]})]})])
            s.configure(f"T{kind}", padding=(px(2), px(3)), focuscolor=p["bg"])
        s.layout("Switch.TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
            ("Pretty.switch", {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "nsew"})]})])
        s.configure("Switch.TCheckbutton", padding=(px(2), px(4)), background=p["side"], foreground=p["muted"])
        s.map("Switch.TCheckbutton", background=[("!disabled", p["side"])])
        # labels
        s.configure("TLabel", background=p["bg"], foreground=p["text"])
        s.configure("Muted.TLabel", foreground=p["muted"])
        s.configure("Small.TLabel", foreground=p["muted"], font=self.fonts["small"])
        s.configure("Title.TLabel", font=self.fonts["title"])
        s.configure("Heading.TLabel", font=self.fonts["heading"])
        s.configure("Strong.TLabel", font=self.fonts["strong"])
        s.configure("ErrorHeading.TLabel", font=self.fonts["strong"], foreground=p["danger"])
        s.configure("Hint.TLabel", background=p["field"], foreground=p["muted"])
        s.configure("Side.TFrame", background=p["side"])
        s.configure("Side.TLabel", background=p["side"], foreground=p["muted"])
        s.configure("Brand.TLabel", background=p["side"], foreground=p["text"], font=self.fonts["heading"])
        s.configure("SideSmall.TLabel", background=p["side"], foreground=p["muted"], font=self.fonts["small"])
        for style, element, fg in (("Chip.TLabel", "Chip.border", p["soft_fg"]), ("Warn.TLabel", "Warn.border", p["warn"]),
                                   ("Plain.TLabel", "Plain.border", p["muted"])):
            s.layout(style, [(element, {"sticky": "nsew", "children": [
                ("Label.padding", {"sticky": "nsew", "children": [("Label.label", {"sticky": "nsew"})]})]})])
            s.configure(style, foreground=fg, padding=(px(9), px(2)), font=self.fonts["small"])
        # cards: frames and label frames with a rounded outline
        s.layout("Card.TFrame", [("Card.border", {"sticky": "nsew"})])
        s.configure("Card.TFrame", padding=px(12))
        s.layout("TLabelframe", [("Card.border", {"sticky": "nsew"})])
        s.configure("TLabelframe", padding=(px(10), px(4), px(10), px(8)), labelmargins=(px(10), 0, px(10), px(3)))
        s.configure("TLabelframe.Label", font=self.fonts["strong"], foreground=p["text"], background=p["bg"])
        s.configure("TPanedwindow", background=p["bg"])
        s.configure("Sash", sashthickness=px(6), gripcount=0, background=p["bg"], lightcolor=p["bg"], bordercolor=p["bg"])
        # lists and tables
        s.configure("Treeview", background=p["bg"], fieldbackground=p["bg"], foreground=p["text"], borderwidth=0, relief="flat", indent=0)
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nsew"})])
        s.map("Treeview", background=[("selected", p["soft"])], foreground=[("selected", p["soft_fg"])])
        s.configure("Treeview.Heading", background=p["bg"], foreground=p["muted"], relief="flat", borderwidth=0,
                    font=self.fonts["small"], padding=(px(6), px(4)), lightcolor=p["bg"], darkcolor=p["bg"], bordercolor=p["border"])
        s.map("Treeview.Heading", background=[("active", p["button_hover"])])
        # thin scroll bars with a rounded thumb, no arrows
        for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
            s.layout(f"{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
                (f"{orient}.Thumb.pill", {"expand": "1", "sticky": "nsew"})]})])
            s.configure(f"{orient}.TScrollbar", troughcolor=p["bg"], background=p["bg"], bordercolor=p["bg"],
                        lightcolor=p["bg"], darkcolor=p["bg"], arrowsize=px(9), gripcount=0)
        s.configure("Horizontal.TProgressbar", troughcolor=p["border"], background=p["accent"], bordercolor=p["border"],
                    lightcolor=p["accent"], darkcolor=p["accent"], thickness=px(4))
        # classic tk widgets (text panes, list boxes, canvases) take the palette from the option database when created
        # after this, and from recolor() when they already exist
        for pattern, value in (("*Text.background", p["field"]), ("*Text.foreground", p["text"]), ("*Text.insertBackground", p["text"]),
                               ("*Text.selectBackground", p["soft"]), ("*Text.selectForeground", p["text"]),
                               ("*Text.highlightThickness", 0), ("*Text.borderWidth", 0),
                               ("*Listbox.background", p["field"]), ("*Listbox.foreground", p["text"]),
                               ("*Listbox.selectBackground", p["soft"]), ("*Listbox.selectForeground", p["soft_fg"]),
                               ("*Listbox.highlightThickness", 1), ("*Listbox.highlightColor", p["accent"]),
                               ("*Listbox.highlightBackground", p["line"]), ("*Listbox.borderWidth", 0),
                               ("*Listbox.activeStyle", "none"), ("*Canvas.background", p["bg"]),
                               ("*Toplevel.background", p["bg"]), ("*Toplevel.highlightBackground", p["line"]),
                               ("*Toplevel.highlightColor", p["line"]), ("*Menu.background", p["field"]), ("*Menu.foreground", p["text"])):
            r.option_add(pattern, value)
        self.recolor(r)

    def _indicators(self):
        p, side, m = self.p, self.px(18), self.px(7)  # m: the space between an indicator and its label
        made = {
            "check": icons.check(side, p["field"], p["line"], margin=m),
            "check:on": icons.check(side, None, p["accent"], p["accent_fg"], margin=m),
            "check:disabled": icons.check(side, p["bg"], p["border"], margin=m),
            "check:disabled:on": icons.check(side, None, p["border"], p["disabled"], margin=m),
            "check:hover": icons.check(side, p["field"], p["accent"], margin=m),
            "radio": icons.radio(side, p["field"], p["line"], margin=m),
            "radio:on": icons.radio(side, None, p["accent"], p["accent_fg"], margin=m),
            "radio:disabled": icons.radio(side, p["bg"], p["border"], margin=m),
            "radio:disabled:on": icons.radio(side, None, p["border"], p["disabled"], margin=m),
            "radio:hover": icons.radio(side, p["field"], p["accent"], margin=m),
            "switch": icons.switch_off(self.px(20), p["line"], "#ffffff", m),
            "switch:on": icons.switch(self.px(20), p["accent"], "#ffffff", m),
        }
        if "Pretty.checkbutton" in self.style.element_names():
            for key, png in made.items():
                self.images[f"ind:{key}"].configure(data=base64.b64encode(png))
            return
        for key, png in made.items():
            self._image(f"ind:{key}", png)
        i = self.images
        for kind in ("check", "radio"):
            self.style.element_create(
                f"Pretty.{kind}button" if kind == "check" else "Pretty.radiobutton", "image", i[f"ind:{kind}"],
                ("disabled selected", i[f"ind:{kind}:disabled:on"]), ("disabled", i[f"ind:{kind}:disabled"]),
                ("selected", i[f"ind:{kind}:on"]), ("active", i[f"ind:{kind}:hover"]), sticky="")
        self.style.element_create("Pretty.switch", "image", i["ind:switch"], ("selected", i["ind:switch:on"]), sticky="")

    def recolor(self, widget):
        """Give the classic tk widgets under `widget` the palette (ttk widgets follow their styles)."""
        p = self.p
        stack = [widget]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            kind = w.winfo_class()
            try:
                if kind == "Text":
                    w.configure(background=p[getattr(w, "palette_bg", "field")], foreground=p["text"],
                                insertbackground=p["text"], selectbackground=p["soft"], selectforeground=p["text"])
                    if hasattr(w, "retag"):
                        w.retag(p)
                elif kind == "Listbox":
                    w.configure(background=p["field"], foreground=p["text"], selectbackground=p["soft"], selectforeground=p["soft_fg"],
                                highlightcolor=p["accent"], highlightbackground=p["line"])
                elif kind == "Canvas":
                    w.configure(background=p[getattr(w, "palette_bg", "bg")])
                elif kind in ("Toplevel", "Tk"):
                    w.configure(background=p["bg"])
            except tk.TclError:
                pass
