# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The main window: one tab per area of the CLI, one shared log. Every action ends in a CLI command."""

import queue
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from .. import cli, manifest, textsafe, tools
from ..catalog import IndexProblem
from ..permargs import PERMISSION_FLAGS
from . import apps, argv, dialogs, worker

POLL_MS = 60
KEEP = "(unchanged)"


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"appjail {cli.version_string()}")
        # width caps are in pixels for a 96 dpi screen; Tk's scaling follows the real one, and so do the fonts
        self.scale = max(float(root.tk.call("tk", "scaling")) / (96 / 72), 1.0)
        font = tkfont.nametofont("TkDefaultFont")
        # ttk keeps a fixed row height: on a larger font the rows would overlap and cut the text
        ttk.Style().configure("Treeview", rowheight=font.metrics("linespace") + 6)
        self.events = worker.new_events()
        self.background = []  # event queues of detached children (run, open)
        self.busy = False
        self.names_before_add = None  # (names, rw) while an add waits for its file-types follow-up
        self.status = tk.StringVar(value="ready")
        bar = ttk.Frame(root)  # packed first, at the bottom: a small window shrinks the panes, never the status line
        bar.pack(side="bottom", fill="x")
        paned = ttk.PanedWindow(root, orient="vertical")
        paned.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=4)
        self._build_apps_tab()
        self._build_add_tab()
        self._build_search_tab()
        self._build_tools_tab()
        paned.add(self._build_log(paned), weight=1)
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear output", command=self.clear_log).pack(side="right", padx=6)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.refresh()
        self._fit_window()
        root.after(POLL_MS, self._poll)

    # --- plumbing ---------------------------------------------------------------------------------------------------

    def _build_log(self, parent):
        frame = ttk.LabelFrame(parent, text="Output", padding=4)
        self.log = tk.Text(frame, height=6, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        return frame

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def say(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", textsafe.clean(text) + "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def run(self, command, label=None):
        """Run a CLI command in-process (it may prompt). One at a time."""
        if self.busy:
            self.status.set("busy: wait for the running command to finish")
            self.root.bell()
            return
        self.busy = True
        self.say(f"$ appjail {' '.join(command)}")
        self.status.set(label or f"running: {command[0]}")
        self.progress.pack(side="right", padx=6, pady=2)
        self.progress.start(12)
        worker.run_command(command, self.events)

    def launch(self, command):
        """Start an app (run, open) as a detached process; it may run alongside other commands."""
        events = worker.new_events()
        self.background.append(events)
        self.say(f"$ appjail {' '.join(command)}")
        worker.spawn_detached(command, events)

    def _poll(self):
        self._drain(self.events, foreground=True)
        for q in list(self.background):
            if self._drain(q, foreground=False):
                self.background.remove(q)
        self.root.after(POLL_MS, self._poll)

    def _drain(self, q, foreground):
        finished = False
        while True:
            try:
                kind, payload = q.get_nowait()
            except queue.Empty:
                return finished
            if kind == "out":
                self.say(payload)
            elif kind == "ask":
                dialogs.answer(self.root, payload)
            elif kind == "done":
                finished = True
                self.say(f"-- exit status {payload} --")
                if foreground:
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    self.status.set("ready" if payload == 0 else f"last command ended with status {payload}")
                    self.refresh()
                    pending, self.names_before_add = self.names_before_add, None
                    if pending is not None and payload == 0:
                        followup = argv.add_followup(pending[0], [r[0] for r in apps.rows()], pending[1])
                        if followup:
                            self.run(followup)

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in apps.rows():
            self.tree.insert("", "end", iid=row[0], values=row)
        self._fit_columns()
        keep = [k for k in keep if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)
        self._show_detail()

    def _fit_window(self):
        """Start at the size the layout asks for (the notebook wants its tallest tab), so no button is hidden by default."""
        self.root.update_idletasks()
        width = min(max(self.root.winfo_reqwidth(), int(1000 * self.scale)), self.root.winfo_screenwidth() - 40)
        height = min(self.root.winfo_reqheight() + 16, self.root.winfo_screenheight() - 80)
        self.root.minsize(min(self.root.winfo_reqwidth(), width), min(self.root.winfo_reqheight(), height))
        self.root.geometry(f"{width}x{height}")

    def _fit_columns(self):
        """Each column is as wide as its longest cell (real versions and sources are long), within a cap."""
        font = tkfont.nametofont("TkDefaultFont")
        caps = {c: int(w * self.scale) for c, w in (("name", 300), ("version", 300), ("source", 380), ("tier", 60), ("permissions", 700), ("note", 320))}
        for i, c in enumerate(self.tree["columns"]):
            cells = [self.tree.set(k, c) for k in self.tree.get_children()]
            width = max([font.measure(c.title()), *(font.measure(t) for t in cells)]) + 24
            self.tree.column(c, width=min(width, caps[c]), minwidth=40)

    def _show_detail(self):
        sel = self.tree.selection()
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", apps.detail(sel[0]) if sel else "")
        self.detail.configure(state="disabled")

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("appjail", "Select an app first.", parent=self.root)
            return None
        return sel[0]

    # --- Apps -------------------------------------------------------------------------------------------------------

    def _build_apps_tab(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Apps")
        cols = ("name", "version", "source", "tier", "permissions", "note")
        rows = 8
        # the table asks for a fixed size: its columns can be wider than the window (it scrolls), which must not widen the window
        holder = ttk.Frame(tab, width=int(640 * self.scale), height=(rows + 2) * (tkfont.nametofont("TkDefaultFont").metrics("linespace") + 6) + 16)
        holder.pack_propagate(False)
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(holder, columns=cols, show="headings", selectmode="browse", height=rows)
        scroll = ttk.Scrollbar(holder, command=self.tree.yview)
        across = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=60, stretch=c == "note")  # the empty column gives way first
        across.pack(side="bottom", fill="x")  # a wide table scrolls; nothing is cut off for good
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # the cells can be too narrow: the selected app's whole `list` line is shown here, scrolling when it is long
        box = ttk.Frame(tab)
        box.pack(fill="x", pady=(4, 0))
        self.detail = tk.Text(box, height=3, wrap="word", state="disabled", relief="flat", background=ttk.Style().lookup("TFrame", "background"))
        bar = ttk.Scrollbar(box, command=self.detail.yview)
        self.detail.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.detail.pack(side="left", fill="x", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(6, 0))
        def on(action):
            return lambda: self._for_app(action)

        for i, (text, action) in enumerate((
                ("Refresh", self.refresh), ("Run", on(lambda a: self.launch(argv.run_argv(a)))), ("Run with…", self._run_with),
                ("Open file…", self._open_file), ("Permissions…", self._permissions),
                ("Update", on(lambda a: self.run(argv.update_argv(a)))), ("Update…", self._update_options),
                ("Update all", lambda: self.run(argv.update_argv())), ("Portals…", self._portals),
                ("History", on(lambda a: self.run(argv.history_argv(a)))),
                ("Menu entry…", self._menu_entry), ("File types", on(lambda a: self.run(argv.desktop_argv(a, show=True)))),
                ("Remove menu entry", on(lambda a: self.run(argv.desktop_argv(a, remove=True)))),
                ("Remove app", on(lambda a: self.run(["remove", a]))))):
            ttk.Button(buttons, text=text, command=action).grid(row=i // 5, column=i % 5, sticky="ew", padx=2, pady=2)
        for c in range(5):
            buttons.columnconfigure(c, weight=1)

    def _for_app(self, action):
        app = self.selected()
        if app:
            action(app)

    def _run_with(self):
        app = self.selected()
        if not app:
            return
        got = dialogs.options_dialog(
            self.root, f"Run {app} with extra access", (
                ("list", "dirs", "Directories for this run", {"hint": "read-only unless writable; the manifest is unchanged", "browse": "dir"}),
                ("list", "files", "Files for this run", {"hint": "PATH or PATH:rw; the app gets their in-jail path", "browse": "file"})),
            "Granted for this run only.", ok="Run")
        if got:
            self.launch(argv.run_argv(app, got["dirs"], got["files"]))

    def _update_options(self):
        app = self.selected()
        if not app:
            return
        got = dialogs.options_dialog(
            self.root, f"Update {app}", (
                ("check", "prerelease", "Follow pre-releases for this run"),
                ("combo", "channel", "Channel from now on", (KEEP, *manifest.CHANNELS)),
                ("text", "quarantine", "Quarantine days (default 7)"),
                ("text", "file", "New AppImage (file apps)"),
                ("text", "sha256", "sha256 of the new content"),
                ("check", "verify", "URL apps: verify after the quarantine")),
            "The update shows its review and asks before installing.")
        if got:
            self.run(argv.update_argv(app, got["prerelease"], None if got["channel"] == KEEP else got["channel"], got["quarantine"], got["file"], got["sha256"], got["verify"]))

    def _portals(self):
        app = self.selected()
        if not app:
            return
        header, grants = apps.portal_grants(app)
        ids = {line: doc for doc, line in grants}
        fields = [("choice", "revoke", "Document grants to revoke",
                   {"items": list(ids), "width": 80, "hint": "select none to only list the grants"})] if grants else []
        got = dialogs.options_dialog(
            self.root, f"Portal grants of {app}", (*fields, ("check", "all", "Revoke every grant")),
            "\n".join(header) + "\n\nThe command lists the grants and asks before revoking.", ok="Go")
        if got:
            self.run(argv.portals_argv(app, [ids[line] for line in got.get("revoke", ())], got["all"]))

    def _menu_entry(self):
        app = self.selected()
        if not app:
            return
        offered, ignored, registered, _rw, _has_entry = apps.file_types(app)
        hint = "highlighted: registered now; click to select or deselect" if registered else "select the types to register; none selected: the command asks"
        if ignored:
            hint += "\nNot offered (refused by appjail): " + ", ".join(ignored)
        fields = [("check", "mime_all", "Offer every file type the app declares"),
                  ("check", "rw", "Opened files are writable (default: read-only)")]
        if offered:
            fields.insert(0, ("choice", "mime", "File types the app offers", {"items": offered, "selected": registered, "hint": hint}))
        else:
            fields.insert(0, ("list", "mime", "File types to offer", {"hint": "the app declares none that appjail accepts"}))

        def check(values):  # no --mime means "keep the current types" for an entry that has some
            if registered and not values["mime"] and not values["mime_all"]:
                return "Select at least one type, or use Remove menu entry and create the entry again without types."
            return None

        got = dialogs.options_dialog(self.root, f"Menu entry of {app}", tuple(fields),
                                     "Creates or refreshes the entry; the command shows what it will register and asks.", validate=check)
        if got:
            self.run(argv.desktop_argv(app, got["mime"], got["mime_all"], got["rw"]))

    def _open_file(self):
        app = self.selected()
        if not app:
            return
        path = filedialog.askopenfilename(parent=self.root, title=f"Open with {app}")
        if path:  # choosing the file is the consent; it is bound read-only, like the menu entry
            self.launch(["open", app, "--", path])

    def _permissions(self):
        app = self.selected()
        if not app:
            return
        try:
            old = apps.load_permissions(app)
        except (manifest.ManifestError, OSError) as e:
            messagebox.showerror("appjail", textsafe.clean(f"cannot read the manifest: {e}"), parent=self.root)
            return
        new = dialogs.permissions_editor(self.root, app, old)
        if new is None:
            return
        command = argv.perms_argv(app, old, new)
        if len(command) == 2:
            self.say(f"{app}: no changes")
            return
        self.run(command)  # prints before/after and asks; the answer is the user's

    # --- Add --------------------------------------------------------------------------------------------------------

    def _build_add_tab(self):
        tab = self.add_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Add")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        self.kind = tk.StringVar(value="github")
        for i, (value, text) in enumerate((("github", "GitHub owner/repo"), ("url", "https URL"), ("file", "Local file"))):
            ttk.Radiobutton(top, text=text, value=value, variable=self.kind).grid(row=0, column=i, sticky="w", padx=4)
        self.source = tk.StringVar()
        ttk.Entry(top, textvariable=self.source, width=60).grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
        ttk.Button(top, text="Browse…", command=self._browse).grid(row=1, column=3)
        self.text, self.entries = {}, {}
        opts = ttk.Frame(tab)
        opts.pack(fill="x", pady=4)
        for i, (key, label) in enumerate((("name", "Local name"), ("tag", "Release tag (GitHub)"),
                                          ("sha256", "sha256 (url/file)"), ("max_size", "Max MiB (url)"))):
            ttk.Label(opts, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="e", padx=4, pady=2)
            self.text[key] = tk.StringVar()
            self.entries[key] = ttk.Entry(opts, textvariable=self.text[key], width=24)
            self.entries[key].grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w")
        self.kind.trace_add("write", lambda *_: self._kind_changed())
        self.flag = {}
        grants = ttk.LabelFrame(tab, text="Permissions", padding=6)
        grants.pack(fill="x", pady=4)
        for flag in ("audio", "gpu", *[f for f in PERMISSION_FLAGS if f not in ("audio", "gpu")]):
            self.flag[flag] = tk.BooleanVar(value=flag in ("audio", "gpu"))
            ttk.Checkbutton(grants, text=flag, variable=self.flag[flag]).pack(side="left", padx=4)
        self.display = tk.StringVar(value="wayland")
        ttk.Combobox(grants, textvariable=self.display, values=manifest.DISPLAYS, state="readonly", width=16).pack(side="left", padx=8)
        self.display_size = tk.StringVar(value=manifest.DEFAULT_DISPLAY_SIZE)
        ttk.Entry(grants, textvariable=self.display_size, width=10).pack(side="left")
        extra = ttk.Frame(tab)
        extra.pack(fill="both", expand=True)
        self.editors = {}
        for i, (key, title, hint) in enumerate((("dirs", "Directories", "PATH or PATH:rw"), ("dbus", "D-Bus names (talk)", ""),
                                                ("dbus_own", "D-Bus names (own)", ""), ("portals", "Privileged portals", "needs portals"))):
            self.editors[key] = dialogs.ListEditor(extra, title, (), hint, browse="dir" if key == "dirs" else None)
            self.editors[key].grid(row=0, column=i, sticky="nsew", padx=3)
            extra.columnconfigure(i, weight=1)
        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", pady=(4, 6), before=extra)  # the main action stays visible in a small window
        self.prerelease = tk.BooleanVar()
        self.desktop = tk.BooleanVar()
        self.mime_all = tk.BooleanVar()
        self.mime = tk.StringVar()
        self.rw = tk.BooleanVar()
        self.checks = {}
        for var, text in ((self.prerelease, "Allow pre-releases"), (self.desktop, "Create menu entry"),
                          (self.mime_all, "All file types"), (self.rw, "Files writable")):
            self.checks[text] = ttk.Checkbutton(bottom, text=text, variable=var)
            self.checks[text].pack(side="left", padx=4)
        ttk.Label(bottom, text="File types:").pack(side="left", padx=(12, 2))
        ttk.Entry(bottom, textvariable=self.mime, width=16).pack(side="left")
        ttk.Button(bottom, text="Add…", command=self._add).pack(side="right")
        self._kind_changed()

    def _kind_changed(self):
        """Options that do not apply to the chosen source are greyed out, as the CLI refuses them."""
        kind = self.kind.get()
        for key, applies in (("tag", kind == "github"), ("sha256", kind != "github"), ("max_size", kind == "url")):
            self.entries[key].configure(state="normal" if applies else "disabled")
        self.checks["Allow pre-releases"].configure(state="normal" if kind == "github" else "disabled")

    def _browse(self):
        path = filedialog.askopenfilename(parent=self.root, title="AppImage")
        if path:
            self.kind.set("file")
            self.source.set(path)

    def _add(self):
        form = {k: v.get() for k, v in self.text.items()}
        form.update(kind=self.kind.get(), source=self.source.get(), prerelease=self.prerelease.get(),
                    allow=[f for f, v in self.flag.items() if v.get()], display=self.display.get(), display_size=self.display_size.get().strip(),
                    desktop=self.desktop.get(), mime_all=self.mime_all.get(),
                    mime=self.mime.get().replace(",", " ").split(), rw=self.rw.get())
        form.update({k: ed.values() for k, ed in self.editors.items()})
        if not form["source"].strip():
            messagebox.showinfo("appjail", "Give a source first.", parent=self.root)
            return
        if argv.defers_menu_entry(form):  # `desktop NAME` follows the install and offers the types the app declares
            form["desktop"] = False
            self.names_before_add = ([r[0] for r in apps.rows()], self.rw.get())
        self.run(argv.add_argv(form), "adding")  # the command shows its review and asks before installing

    # --- Search and index -------------------------------------------------------------------------------------------

    def _build_search_tab(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Search")
        row = ttk.Frame(tab)
        row.pack(fill="x")
        self.keywords = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.keywords, width=50)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda _e: self._search())
        self.limit = tk.StringVar(value="20")
        ttk.Label(row, text="limit").pack(side="left")
        ttk.Entry(row, textvariable=self.limit, width=5).pack(side="left", padx=4)
        self.show_all = tk.BooleanVar()
        ttk.Checkbutton(row, text="all", variable=self.show_all).pack(side="left")
        ttk.Button(row, text="Search", command=self._search).pack(side="left", padx=6)
        self.use_hit = ttk.Button(row, text="Add this app…", command=self._use_hit, state="disabled")
        self.use_hit.pack(side="left")
        self.hits = []
        results = ttk.Frame(tab)
        results.pack(fill="both", expand=True, pady=(6, 0))
        self.hit_tree = ttk.Treeview(results, columns=("name", "description", "source", "catalog"), show="headings",
                                     selectmode="browse", height=6)
        for c, w in (("name", 160), ("description", 420), ("source", 300), ("catalog", 90)):
            self.hit_tree.heading(c, text=c.title())
            self.hit_tree.column(c, width=int(w * self.scale), minwidth=40)
        bar = ttk.Scrollbar(results, command=self.hit_tree.yview)
        self.hit_tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.hit_tree.pack(fill="both", expand=True)
        self.hit_tree.bind("<<TreeviewSelect>>", lambda _e: self._hit_selected())
        self.hit_tree.bind("<Double-1>", lambda _e: self._use_hit())
        ttk.Label(tab, text="A hit is only a suggestion: check the owner and repository before adding.",
                  foreground="gray40").pack(anchor="w")
        idx = ttk.LabelFrame(tab, text="Catalogs", padding=6)
        idx.pack(fill="x", pady=10)
        name_row = ttk.Frame(idx)
        name_row.pack(fill="x")
        self.source_name = tk.StringVar()
        ttk.Label(name_row, text="Source name").pack(side="left", padx=4)
        ttk.Entry(name_row, textvariable=self.source_name, width=24).pack(side="left")
        ttk.Label(name_row, text="(optional for update and rollback)", foreground="gray40").pack(side="left", padx=6)
        buttons = ttk.Frame(idx)
        buttons.pack(fill="x", pady=(6, 0))
        for text, action in (("Status", lambda: self.run(["index", "status"])),
                             ("Update", lambda: self._index("update")),
                             ("Rollback", lambda: self._index("rollback")),
                             ("Add from URL…", lambda: self._index_add("--url")),
                             ("Add from file…", lambda: self._index_add("--file")),
                             ("Remove source", self._index_remove)):
            ttk.Button(buttons, text=text, command=action).pack(side="left", padx=2)

    def _search(self):
        words = self.keywords.get().strip()
        if not words:
            return
        limit = self.limit.get().strip()
        self.hit_tree.delete(*self.hit_tree.get_children())
        self.hits = []
        self._hit_selected()
        self.say(f"$ appjail search {words}")
        try:
            hits, total, searched = apps.search_hits(words, int(limit) if limit.isdigit() else None, self.show_all.get())
        except IndexProblem as e:
            self.say(f"error: {e}")
            return
        self.say(f"{total} match(es) in {', '.join(searched)}" + (f", showing {len(hits)}" if len(hits) < total else ""))
        self.hits = hits
        for i, h in enumerate(hits):
            description = h.description + (f" ({h.note})" if h.note else "")
            self.hit_tree.insert("", "end", iid=str(i), values=(h.name, description, h.source, h.catalog))

    def _selected_hit(self):
        sel = self.hit_tree.selection()
        return self.hits[int(sel[0])] if sel else None

    def _hit_selected(self):
        hit = self._selected_hit()
        self.use_hit.configure(state="normal" if hit and argv.add_target(hit.source) else "disabled")

    def _use_hit(self):
        """Copy the selected hit into the Add form and show it. Nothing is installed: Add… still reviews and asks."""
        hit = self._selected_hit()
        if hit is None:
            return
        target = argv.add_target(hit.source)
        if target is None:
            messagebox.showinfo("appjail", f"{hit.name}: appjail cannot install this source ({hit.note or hit.source or 'none given'}).",
                                parent=self.root)
            return
        self.kind.set(target[0])
        self.source.set(target[1])
        for key in ("name", "tag", "sha256", "max_size"):
            self.text[key].set("")
        self.notebook.select(self.add_tab)

    def _index(self, sub):
        name = self.source_name.get().strip()
        self.run(["index", sub, *([name] if name else [])])

    def _index_add(self, flag):
        name = self.source_name.get().strip()
        if not name:
            messagebox.showinfo("appjail", "Type a name for the new source first.", parent=self.root)
            return
        if flag == "--file":
            where = filedialog.askopenfilename(parent=self.root, title="Catalog file")
        else:
            where = simpledialog.askstring("appjail", "https URL of the catalog:", parent=self.root)
        if where:
            self.run(["index", "add", name, flag, where])

    def _index_remove(self):
        name = self.source_name.get().strip()
        if name:
            self.run(["index", "remove", name])
        else:
            messagebox.showinfo("appjail", "Type the source name first.", parent=self.root)

    # --- Tools ------------------------------------------------------------------------------------------------------

    def _build_tools_tab(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Tools")
        helpers = ttk.LabelFrame(tab, text="Helper binaries (pinned in appjail's source)", padding=6)
        helpers.pack(fill="x", pady=(0, 8))
        ttk.Button(helpers, text="Status", command=lambda: self.run(["tools", "status"])).pack(side="left", padx=2)
        self.tool = tk.StringVar(value=min(tools.TOOLS))
        ttk.Combobox(helpers, textvariable=self.tool, values=sorted(tools.TOOLS), state="readonly", width=16).pack(side="left", padx=6)
        ttk.Button(helpers, text="Install…", command=lambda: self.run(["tools", "install", self.tool.get()])).pack(side="left")
        other = ttk.LabelFrame(tab, text="Other commands", padding=6)
        other.pack(fill="x")
        for text, command in (("Version", ["version"]), ("List apps", ["list"]), ("History (all apps)", argv.history_argv()),
                              ("Prune stale menu entries", argv.desktop_argv(prune=True))):
            ttk.Button(other, text=text, command=lambda c=command: self.run(c)).pack(side="left", padx=2)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
