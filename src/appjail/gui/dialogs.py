# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Modal dialogs: the answers to a command's prompts, an options form, and the permissions editor."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..manifest import DISPLAYS
from ..permargs import PERMISSION_FLAGS


def _modal(parent, title):
    top = tk.Toplevel(parent)
    top.title(title)
    top.transient(parent)
    top.resizable(True, True)
    return top


def _wait(top, focus=None):
    """Centre the dialog over its parent (there may be no window manager to place it), then block until it closes."""
    top.update_idletasks()
    parent = top.master.winfo_toplevel()
    w, h = top.winfo_reqwidth(), top.winfo_reqheight()
    x = parent.winfo_rootx() + max((parent.winfo_width() - w) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - h) // 3, 0)
    x = min(x, max(top.winfo_screenwidth() - w, 0))
    y = min(y, max(top.winfo_screenheight() - h, 0))
    top.geometry(f"+{x}+{y}")
    top.grab_set()
    if focus is not None:  # a modal dialog takes the keyboard, so Return/Escape act on it at once
        focus.focus_force()
    top.wait_window()


def _review_box(frame, lines):
    """What the command printed so far, so an answer is given with the facts in front of the user."""
    holder = ttk.Frame(frame)
    holder.pack(fill="both", expand=True, pady=(0, 8))
    text = tk.Text(holder, width=100, height=min(len(lines) + 3, 22), wrap="word")
    scroll = ttk.Scrollbar(holder, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.insert("1.0", "\n".join(lines))
    text.configure(state="disabled")
    scroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.see("end")


def answer(parent, request):
    """Show a Request and reply to it. Closing the dialog cancels (None)."""
    result = {"value": None}
    top = _modal(parent, "appjail")
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    if request.review:
        _review_box(frame, request.review)
    ttk.Label(frame, text=request.prompt, wraplength=700, justify="left").pack(anchor="w", pady=(0, 8))
    buttons = ttk.Frame(frame)

    def done(value):
        result["value"] = value
        top.destroy()

    if request.kind == "ask":
        var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=var, width=60)
        entry.pack(fill="x")
        first = entry
        entry.bind("<Return>", lambda _e: done(var.get()))
        ttk.Button(buttons, text="OK", command=lambda: done(var.get())).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=lambda: done(None)).pack(side="right", padx=6)
    elif request.kind == "confirm":
        yes = ttk.Button(buttons, text="Yes", command=lambda: done(True))
        no = ttk.Button(buttons, text="No", command=lambda: done(False))
        no.pack(side="right")
        yes.pack(side="right", padx=6)
        first = yes if request.default else no
        for button in (yes, no):  # Return presses the focused button, as in any dialog
            button.bind("<Return>", lambda e: e.widget.invoke())
    else:  # choose
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True)
        box = tk.Listbox(holder, height=min(len(request.options), 12), width=80, exportselection=False)
        scroll = ttk.Scrollbar(holder, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        for o in request.options:
            box.insert("end", o)
        scroll.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        first = box

        def pick(_e=None):
            sel = box.curselection()
            if sel:
                done(int(sel[0]))
        box.bind("<Double-Button-1>", pick)
        box.bind("<Return>", pick)
        ttk.Button(buttons, text="OK", command=pick).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=lambda: done(None)).pack(side="right", padx=6)
    buttons.pack(fill="x", pady=(10, 0))
    top.protocol("WM_DELETE_WINDOW", lambda: done(None))
    top.bind("<Escape>", lambda _e: done(None))
    _wait(top, first)
    request.reply(result["value"])


class ListEditor(ttk.LabelFrame):
    """A list of strings with add and remove. browse="dir" or "file" adds a chooser; for directories a box makes the entry writable."""

    def __init__(self, parent, title, values, hint="", browse=None, height=3):
        super().__init__(parent, text=title, padding=6)
        self.browse = browse
        holder = ttk.Frame(self)  # long names and paths scroll sideways, a long list scrolls down
        holder.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.box = tk.Listbox(holder, height=height, width=16, exportselection=False, selectmode="extended")
        down = ttk.Scrollbar(holder, command=self.box.yview)
        across = ttk.Scrollbar(holder, orient="horizontal", command=self.box.xview)
        self.box.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        for v in values:
            self.box.insert("end", v)
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        self.box.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.var = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self.var, width=10)
        entry.grid(row=1, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self.add())
        ttk.Button(self, text="Add", width=6, command=self.add).grid(row=1, column=1)
        self.writable = tk.BooleanVar()
        row = ttk.Frame(self)
        row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left")
        if browse:
            ttk.Button(row, text="Browse…", command=self.choose).pack(side="left", padx=4)
        below = 3
        if browse == "dir":  # on its own line: a narrow column must not push it out of sight
            ttk.Checkbutton(self, text="writable (:rw)", variable=self.writable).grid(
                row=below, column=0, columnspan=3, sticky="w")
            below += 1
        if hint:
            ttk.Label(self, text=hint, foreground="gray40").grid(row=below, column=0, columnspan=3, sticky="w")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def choose(self):
        path = filedialog.askdirectory(parent=self, title="Directory") if self.browse == "dir" else \
            filedialog.askopenfilename(parent=self, title="File")
        if path:
            self.var.set(path + (":rw" if self.writable.get() else ""))
            self.add()

    def add(self):
        v = self.var.get().strip()
        if v and v not in self.values(flush=False):
            self.box.insert("end", v)
        self.var.set("")

    def remove(self):
        for i in reversed(self.box.curselection()):
            self.box.delete(i)

    def values(self, flush=True):
        if flush:
            self.add()  # text left in the entry counts: nobody expects it to be dropped silently
        return tuple(self.box.get(0, "end"))


class ChoiceList(ttk.LabelFrame):
    """A fixed list of strings to select (extra: {"items": [...], "selected": [...], "hint": ...}); values() are the selected ones."""

    def __init__(self, parent, title, items=(), selected=(), hint="", width=16):
        super().__init__(parent, text=title, padding=6)
        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        self.box = tk.Listbox(holder, height=max(2, min(len(items), 8)), width=width, exportselection=False, selectmode="multiple")
        bar = ttk.Scrollbar(holder, command=self.box.yview)
        self.box.configure(yscrollcommand=bar.set)
        for i, item in enumerate(items):
            self.box.insert("end", item)
            if item in selected:
                self.box.selection_set(i)
        bar.pack(side="right", fill="y")
        self.box.pack(side="left", fill="both", expand=True)
        if hint:
            ttk.Label(self, text=hint, foreground="gray40", wraplength=480, justify="left").pack(anchor="w", pady=(4, 0))

    def values(self):
        return tuple(self.box.get(i) for i in self.box.curselection())


def options_dialog(parent, title, fields, intro="", ok="Continue", validate=None):
    """A small form. fields: (kind, key, label[, extra]) with kind "check", "text", "combo" (extra: values), "list"
    (extra: {"hint":..., "browse":...}) or "choice" (extra: {"items":..., "selected":..., "hint":...}). validate(values)
    returns an error text to keep the form open. Returns {key: value} or None when cancelled."""
    top = _modal(parent, title)
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    if intro:
        ttk.Label(frame, text=intro, wraplength=520, justify="left").pack(anchor="w", pady=(0, 8))
    widgets = {}
    for kind, key, label, *extra in fields:
        extra = extra[0] if extra else None
        if kind == "check":
            widgets[key] = tk.BooleanVar()
            ttk.Checkbutton(frame, text=label, variable=widgets[key]).pack(anchor="w", pady=2)
        elif kind == "list":
            widgets[key] = ListEditor(frame, label, (), **(extra or {}))
            widgets[key].pack(fill="x", pady=4)
        elif kind == "choice":
            widgets[key] = ChoiceList(frame, label, **(extra or {}))
            widgets[key].pack(fill="x", pady=4)
        else:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=24, anchor="w").pack(side="left")
            widgets[key] = tk.StringVar(value=(extra[0] if kind == "combo" else ""))
            if kind == "combo":
                ttk.Combobox(row, textvariable=widgets[key], values=extra, state="readonly", width=18).pack(side="left")
            else:
                ttk.Entry(row, textvariable=widgets[key], width=36).pack(side="left", fill="x", expand=True)
    result = {"value": None}

    def accept():
        value = {k: (w.values() if isinstance(w, (ListEditor, ChoiceList)) else w.get()) for k, w in widgets.items()}
        problem = validate(value) if validate else None
        if problem:
            messagebox.showerror("appjail", problem, parent=top)
            return
        result["value"] = value
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text=ok, command=accept).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=6)
    top.bind("<Escape>", lambda _e: top.destroy())
    _wait(top)
    return result["value"]


def permissions_editor(parent, name, state):
    """Edit an app's permissions. Returns the new state dict (same shape as the argument) or None when cancelled.

    Applying only builds the `appjail perms` command; the command prints the before/after review and asks.
    """
    top = _modal(parent, f"Permissions of {name}")
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    flags = {}
    box = ttk.LabelFrame(frame, text="Permissions", padding=6)
    box.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
    for flag in PERMISSION_FLAGS:
        flags[flag] = tk.BooleanVar(value=bool(state.get(flag)))
        ttk.Checkbutton(box, text=flag, variable=flags[flag]).pack(anchor="w")
    display = tk.StringVar(value=state.get("display", "wayland"))
    ttk.Label(box, text="display").pack(anchor="w", pady=(6, 0))
    ttk.Combobox(box, textvariable=display, values=DISPLAYS, state="readonly", width=16).pack(anchor="w")
    size = tk.StringVar(value=state.get("display_size", "1280x800"))
    ttk.Label(box, text="window size (xwayland-rootful)").pack(anchor="w", pady=(6, 0))
    ttk.Entry(box, textvariable=size, width=12).pack(anchor="w")
    lists = ttk.Frame(frame)
    lists.grid(row=0, column=1, sticky="nsew")
    editors = {
        "dirs": ListEditor(lists, "Directories", state.get("dirs", ()), "PATH or PATH:rw", browse="dir", height=5),
        "dbus_filter": ListEditor(lists, "D-Bus names (talk)", state.get("dbus_filter", ())),
        "dbus_own": ListEditor(lists, "D-Bus names (own)", state.get("dbus_own", ())),
        "portal_interfaces": ListEditor(lists, "Privileged portals", state.get("portal_interfaces", ()), "needs portals"),
    }
    for i, ed in enumerate(editors.values()):
        ed.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(0, weight=1)
    result = {"value": None}

    def apply():
        new = {k: v.get() for k, v in flags.items()}
        new["display"] = display.get()
        new["display_size"] = size.get().strip()
        new.update({k: ed.values() for k, ed in editors.items()})
        result["value"] = new
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(buttons, text="Review changes…", command=apply).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=6)
    top.bind("<Escape>", lambda _e: top.destroy())
    _wait(top)
    return result["value"]
