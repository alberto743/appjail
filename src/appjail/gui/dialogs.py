# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Modal dialogs: the answers to a command's prompts, an options form, and the permissions editor."""

import tkinter as tk
from tkinter import ttk

from ..grants import PORTAL_DESCRIPTIONS, PORTAL_OPT_IN
from ..manifest import AUDIO_MODES, DEFAULT_AUDIO_MODE, DEFAULT_DISPLAY_SIZE, DISPLAYS
from ..permargs import PERMISSION_FLAGS

LIMIT_LABELS = (("memory_max", "memory limit (2G, 50%)"), ("cpu_quota", "CPU limit (200% = 2 CPUs)"), ("tasks_max", "process limit (512, 20%)"))


def autohide_pack(bar, widget, **pack):
    """A scroll command that shows the scroll bar (packed beside `widget`) only while there is something to scroll."""
    def set_(lo, hi):
        bar.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            bar.pack_forget()
        elif not bar.winfo_manager():
            bar.pack(before=widget, **pack)
    return set_


class HintEntry(ttk.Entry):
    """An entry that shows a muted hint while it is empty (a label over it; the text variable holds only what is typed)."""

    def __init__(self, parent, hint, textvariable, **options):
        super().__init__(parent, textvariable=textvariable, **options)
        self.hint = ttk.Label(self, text=hint, style="Hint.TLabel", cursor="xterm")
        self.hint.bind("<Button-1>", lambda _e: self.focus_set())
        textvariable.trace_add("write", lambda *_: self._update(textvariable))
        self._update(textvariable)

    def _update(self, var):
        if var.get():
            self.hint.place_forget()
        else:
            self.hint.place(x=8, rely=0.5, anchor="w")


def notice(parent, text, error=False, title="appjail"):
    """A message with one OK button, in the window's theme (Tk's own message box ignores it)."""
    top = _modal(parent, title)
    frame = ttk.Frame(top, padding=16)
    frame.pack(fill="both", expand=True)
    if error:
        ttk.Label(frame, text="Something went wrong", style="ErrorHeading.TLabel").pack(anchor="w", pady=(0, 4))
    ttk.Label(frame, text=text, wraplength=460, justify="left").pack(anchor="w")
    ok = ttk.Button(frame, text="OK", style="Accent.TButton", command=top.destroy)
    ok.pack(anchor="e", pady=(14, 0))
    for key in ("<Return>", "<Escape>", "<KP_Enter>"):
        top.bind(key, lambda _e: top.destroy())
    _wait(top, ok)


def ask_text(parent, title, prompt, ok="OK"):
    """One line of text, or None when cancelled."""
    result = {"value": None}
    top = _modal(parent, title)
    frame = ttk.Frame(top, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=prompt, wraplength=460, justify="left").pack(anchor="w", pady=(0, 6))
    var = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=var, width=52)
    entry.pack(fill="x")

    def done(value):
        result["value"] = value
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))
    ttk.Button(buttons, text=ok, style="Accent.TButton", command=lambda: done(var.get())).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=lambda: done(None)).pack(side="right", padx=6)
    entry.bind("<Return>", lambda _e: done(var.get()))
    top.bind("<Escape>", lambda _e: done(None))
    _wait(top, entry)
    return result["value"]


def _modal(parent, title):
    top = tk.Toplevel(parent)
    top.title(title)
    top.transient(parent)
    top.resizable(True, True)
    top.configure(highlightthickness=1)  # an edge where no window manager draws one
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
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=lambda: done(var.get())).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=lambda: done(None)).pack(side="right", padx=6)
    elif request.kind == "confirm":
        yes = ttk.Button(buttons, text="Yes", command=lambda: done(True))
        no = ttk.Button(buttons, text="No", command=lambda: done(False))
        no.pack(side="right")
        yes.pack(side="right", padx=6)
        first = yes if request.default else no
        first.configure(style="Accent.TButton")  # the default answer is the one that stands out
        for button in (yes, no):  # Return presses the focused button, as in any dialog
            button.bind("<Return>", lambda e: e.widget.invoke())
    else:  # choose
        box = _scrolled_listbox(frame, request.options, height=min(len(request.options), 12), width=80)
        first = box

        def pick(_e=None):
            sel = box.curselection()
            if sel:
                done(int(sel[0]))
        box.bind("<Double-Button-1>", pick)
        box.bind("<Return>", pick)
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=pick).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=lambda: done(None)).pack(side="right", padx=6)
    buttons.pack(fill="x", pady=(10, 0))
    top.protocol("WM_DELETE_WINDOW", lambda: done(None))
    top.bind("<Escape>", lambda _e: done(None))
    _wait(top, first)
    request.reply(result["value"])


def autohide_grid(bar):
    """A scroll command that shows the (gridded) scroll bar only while there is something to scroll."""
    def set_(lo, hi):
        bar.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            bar.grid_remove()
        else:
            bar.grid()
    return set_


def _scrolled_listbox(parent, items, **options):
    """A Listbox of strings with a vertical scrollbar, packed into its own frame in `parent`."""
    holder = ttk.Frame(parent)
    holder.pack(fill="both", expand=True)
    box = tk.Listbox(holder, exportselection=False, **options)
    scroll = ttk.Scrollbar(holder, command=box.yview)
    box.configure(yscrollcommand=scroll.set)
    for item in items:
        box.insert("end", item)
    scroll.pack(side="right", fill="y")
    box.pack(side="left", fill="both", expand=True)
    return box


class ListEditor(ttk.LabelFrame):
    """A list of strings with add and remove. browse="dir" or "file" adds a chooser; for directories a box makes the entry writable.
    bare=True draws no frame or title and puts the controls beside the list (the Add page's Access card); on_change() is
    called when the list changes."""

    def __init__(self, parent, title, values, hint="", browse=None, height=3, bare=False, on_change=None):
        super().__init__(parent, text="" if bare else title, padding=0 if bare else 6, **({"style": "Bare.TLabelframe"} if bare else {}))
        self.title, self.browse, self.on_change = title, browse, on_change
        holder = ttk.Frame(self)  # long names and paths scroll sideways, a long list scrolls down
        self.box = tk.Listbox(holder, height=height, width=16, exportselection=False, selectmode="extended")
        down = ttk.Scrollbar(holder, command=self.box.yview)
        across = ttk.Scrollbar(holder, orient="horizontal", command=self.box.xview)
        self.box.configure(yscrollcommand=autohide_grid(down), xscrollcommand=autohide_grid(across))
        for v in values:
            self.box.insert("end", v)
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        self.box.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        if bare:
            holder.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            controls, first = ttk.Frame(self), 0
            controls.grid(row=0, column=1, sticky="nw")
        else:
            holder.grid(row=0, column=0, columnspan=3, sticky="nsew")
            controls, first = self, 1
        self.var = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self.var, width=22 if bare else 10)
        entry.grid(row=first, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self.add())
        ttk.Button(controls, text="Add", width=6, command=self.add).grid(row=first, column=1, padx=(4, 0))
        self.writable = tk.BooleanVar()
        row = ttk.Frame(controls)
        row.grid(row=first + 1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left")
        if browse:
            ttk.Button(row, text="Browse…", command=self.choose).pack(side="left", padx=4)
        below = first + 2
        if browse == "dir":  # on its own line: a narrow column must not push it out of sight
            ttk.Checkbutton(controls, text="writable (:rw)", variable=self.writable).grid(
                row=below, column=0, columnspan=3, sticky="w")
            below += 1
        if hint:
            ttk.Label(controls, text=hint, style="Small.TLabel").grid(row=below, column=0, columnspan=3, sticky="w")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def choose(self):
        from . import files  # here: files builds on this module
        path = files.choose_folder(self, "Choose a folder") if self.browse == "dir" else files.choose_file(self, "Choose a file")
        if path:
            self.var.set(path + (":rw" if self.writable.get() else ""))
            self.add()

    def add(self):
        v = self.var.get().strip()
        if v and v not in self.values(flush=False):
            self.box.insert("end", v)
            self._changed()
        self.var.set("")

    def remove(self):
        for i in reversed(self.box.curselection()):
            self.box.delete(i)
        self._changed()

    def _changed(self):
        if self.on_change:
            self.on_change()

    def values(self, flush=True):
        if flush:
            self.add()  # text left in the entry counts: nobody expects it to be dropped silently
        return tuple(self.box.get(0, "end"))


class PortalChecks(ttk.LabelFrame):
    """One check box for each opt-in portal, with what it lets the app do beside it; values() are the checked names.
    bare and on_change as for ListEditor."""

    def __init__(self, parent, title, selected=(), hint="", wrap=260, height=150, bare=False, on_change=None):
        super().__init__(parent, text="" if bare else title, padding=0 if bare else 6, **({"style": "Bare.TLabelframe"} if bare else {}))
        self.title = title
        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, height=height, width=wrap + 160, highlightthickness=0)
        scroll = ttk.Scrollbar(holder, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.checks = {}
        for row, name in enumerate(PORTAL_OPT_IN):
            self.checks[name] = tk.BooleanVar(value=name in selected)
            ttk.Checkbutton(inner, text=name, variable=self.checks[name], command=on_change).grid(row=row, column=0, sticky="nw")
            ttk.Label(inner, text=PORTAL_DESCRIPTIONS[name], style="Small.TLabel", wraplength=wrap,
                      justify="left").grid(row=row, column=1, sticky="w", padx=(6, 0), pady=1)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        canvas.bind("<Button-4>", lambda _e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda _e: canvas.yview_scroll(1, "units"))
        if hint:
            ttk.Label(self, text=hint, style="Small.TLabel").pack(anchor="w", pady=(4, 0))

    def values(self):
        return tuple(name for name in PORTAL_OPT_IN if self.checks[name].get())


class ChoiceList(ttk.LabelFrame):
    """A fixed list of strings to select (extra: {"items": [...], "selected": [...], "hint": ...}); values() are the selected ones."""

    def __init__(self, parent, title, items=(), selected=(), hint="", width=16):
        super().__init__(parent, text=title, padding=6)
        self.box = _scrolled_listbox(self, items, height=max(2, min(len(items), 8)), width=width, selectmode="multiple")
        for i, item in enumerate(items):
            if item in selected:
                self.box.selection_set(i)
        if hint:
            ttk.Label(self, text=hint, style="Small.TLabel", wraplength=480, justify="left").pack(anchor="w", pady=(4, 0))

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
            notice(top, problem, error=True)
            return
        result["value"] = value
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text=ok, style="Accent.TButton", command=accept).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=6)
    top.bind("<Escape>", lambda _e: top.destroy())
    _wait(top)
    return result["value"]


class Segmented(ttk.Frame):
    """Several editors in the space of one: a column of segments (each with its entry count) beside the editor shown.
    items: (key, title, make(parent, on_change)) where make builds a bare ListEditor or PortalChecks."""

    def __init__(self, parent, items, start=None):
        super().__init__(parent)
        column = ttk.Frame(self)
        column.pack(side="left", fill="y", padx=(0, 12))
        holder = ttk.Frame(self)
        holder.pack(side="left", fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.current = tk.StringVar(value=start or items[0][0])
        self.editors, self.segments = {}, {}
        for key, title, make in items:
            self.editors[key] = make(holder, lambda k=key: self.count(k))
            self.segments[key] = ttk.Radiobutton(column, text=title, value=key, variable=self.current, style="Seg.TRadiobutton",
                                                 command=self.show)
            self.segments[key].pack(fill="x", pady=(0, 3))
            self.count(key)
        self.show()

    def show(self):
        for key, editor in self.editors.items():
            if key == self.current.get():
                editor.grid(row=0, column=0, sticky="nsew")
            else:
                editor.grid_remove()

    def count(self, key):
        editor = self.editors[key]
        n = len(editor.values() if isinstance(editor, PortalChecks) else editor.values(flush=False))
        self.segments[key].configure(text=editor.title + (f"  {n}" if n else ""))


class Flow(ttk.Frame):
    """A row of widgets that wraps onto more rows when it is narrower than they are, instead of cutting them off.
    Make each widget with this frame as its parent, then add() it in order."""

    def __init__(self, parent, gap=6, uniform=False, **options):
        super().__init__(parent, **options)
        self.gap, self.items, self.uniform = gap, [], uniform  # uniform: every cell as wide as the widest, in columns
        self.bind("<Configure>", lambda e: self._place(e.width))

    def add(self, widget):
        self.items.append(widget)
        self.after_idle(lambda: self._place(self.winfo_width()))
        return widget

    def _place(self, width):
        shown = [w for w in self.items if not getattr(w, "flow_hidden", False)]
        if not shown:
            return
        widest = max(w.winfo_reqwidth() for w in shown)
        width = max(width, widest) if width > 1 else sum(w.winfo_reqwidth() + self.gap for w in shown)
        x = y = row = 0
        for w in shown:
            wd, ht = (widest if self.uniform else w.winfo_reqwidth()), w.winfo_reqheight()
            if x and x + wd > width:
                x, y, row = 0, y + row + self.gap // 2, 0
            w.place(x=x, y=y)
            x += wd + self.gap
            row = max(row, ht)
        # ask for the widest widget (so the row never forces the window wider) and the height the rows take
        self.configure(width=widest, height=y + row)


class Expander(ttk.Frame):
    """A titled section that opens and closes; `body` holds its content."""

    def __init__(self, parent, title, opened=False):
        super().__init__(parent)
        self.title = title
        self.opened = tk.BooleanVar(value=opened)
        self.header = ttk.Checkbutton(self, text=title, variable=self.opened, style="Expander.TCheckbutton", command=self._toggle)
        self.header.pack(anchor="w")
        self.body = ttk.LabelFrame(self, style="Bare.TLabelframe")
        self._toggle()

    def _toggle(self):
        self.header.configure(text=("▾  " if self.opened.get() else "▸  ") + self.title)
        if self.opened.get():
            self.body.pack(fill="both", expand=True, pady=(6, 0))
        else:
            self.body.pack_forget()

    def open(self, value=True):
        self.opened.set(value)
        self._toggle()


def permissions_editor(parent, name, state):
    """Edit an app's permissions. Returns the new state dict (same shape as the argument) or None when cancelled.

    Applying only builds the `appjail perms` command; the command prints the before/after review and asks.
    """
    top = _modal(parent, f"Permissions of {name}")
    frame = ttk.Frame(top, padding=14)
    frame.pack(fill="both", expand=True)
    flags = {}
    box = ttk.LabelFrame(frame, text="Permissions")
    box.pack(fill="x")
    grid = ttk.Frame(box)
    grid.pack(fill="x")
    per_row = 4
    for i, flag in enumerate(PERMISSION_FLAGS):
        flags[flag] = tk.BooleanVar(value=bool(state.get(flag)))
        ttk.Checkbutton(grid, text=flag, variable=flags[flag]).grid(row=i // per_row, column=i % per_row, sticky="w", padx=(0, 10))
    for c in range(per_row):
        grid.columnconfigure(c, weight=1, uniform="flag")
    modes = Flow(box, gap=8)
    modes.pack(fill="x", pady=(8, 0))
    audio_mode = tk.StringVar(value=state.get("audio_mode", DEFAULT_AUDIO_MODE))
    display = tk.StringVar(value=state.get("display", "wayland"))
    size = tk.StringVar(value=state.get("display_size", DEFAULT_DISPLAY_SIZE))
    limit_vars = {key: tk.StringVar(value=state.get(key, "")) for key, _label in LIMIT_LABELS}
    for label, make in (("Audio mode", lambda p: ttk.Combobox(p, textvariable=audio_mode, values=AUDIO_MODES, state="readonly", width=9)),
                        ("Display", lambda p: ttk.Combobox(p, textvariable=display, values=DISPLAYS, state="readonly", width=16)),
                        ("Window size (rootful)", lambda p: ttk.Entry(p, textvariable=size, width=10))):
        pair = ttk.Frame(modes)
        ttk.Label(pair, text=label, style="Muted.TLabel").pack(side="left", padx=(0, 6))
        make(pair).pack(side="left", padx=(0, 10))
        modes.add(pair)
    limits = Flow(box, gap=8)
    limits.pack(fill="x", pady=(6, 0))
    for key, label in (("memory_max", "Memory limit"), ("cpu_quota", "CPU limit"), ("tasks_max", "Process limit")):
        pair = ttk.Frame(limits)
        ttk.Label(pair, text=label, style="Muted.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(pair, textvariable=limit_vars[key], width=7).pack(side="left", padx=(0, 10))
        limits.add(pair)
    ttk.Label(box, text="Limits: 2G or 50% of memory, 200% = 2 CPUs, 512 processes; empty for none.",
              style="Small.TLabel").pack(anchor="w", pady=(4, 0))
    access = ttk.LabelFrame(frame, text="Access")
    access.pack(fill="both", expand=True, pady=(10, 0))

    def lister(title, key, hint="", browse=None):
        return lambda parent, changed: ListEditor(parent, title, state.get(key, ()), hint, browse=browse, height=4, bare=True,
                                                  on_change=changed)
    lists = Segmented(access, (
        ("dirs", "Directories", lister("Directories", "dirs", "PATH or PATH:rw", browse="dir")),
        ("dbus_filter", "D-Bus names (talk)", lister("D-Bus names (talk)", "dbus_filter")),
        ("dbus_own", "D-Bus names (own)", lister("D-Bus names (own)", "dbus_own")),
        ("portal_interfaces", "Privileged portals",
         lambda parent, changed: PortalChecks(parent, "Privileged portals", state.get("portal_interfaces", ()), "needs the portals permission",
                                              wrap=240, height=110, bare=True, on_change=changed)),
        ("schemes", "URL schemes", lister("URL schemes", "schemes", "gemini; links of these open the app")),
        ("env", "Environment", lister("Environment", "env", "NAME=VALUE; plain text, no secrets"))))
    lists.pack(fill="both", expand=True)
    editors = lists.editors
    result = {"value": None}

    def apply():
        new = {k: v.get() for k, v in flags.items()}
        new["audio_mode"] = audio_mode.get()
        new["display"] = display.get()
        new["display_size"] = size.get().strip()
        new.update({k: v.get().strip() for k, v in limit_vars.items()})
        new.update({k: ed.values() for k, ed in editors.items()})
        result["value"] = new
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="Review changes…", style="Accent.TButton", command=apply).pack(side="right")
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=6)
    ttk.Label(buttons, text="The command shows what changes and asks.", style="Small.TLabel").pack(side="left")
    top.bind("<Escape>", lambda _e: top.destroy())
    _wait(top)
    return result["value"]
