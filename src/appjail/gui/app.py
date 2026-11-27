# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The main window: a sidebar with one page per area of the CLI, and one shared output pane. Every action ends in a CLI
command."""

import base64
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .. import cli, manifest, textsafe, tools
from ..catalog import IndexProblem
from ..permargs import PERMISSION_FLAGS
from . import apps, argv, dialogs, files, icons, theme, worker
from .dialogs import autohide_pack as autohide

POLL_MS = 60
DARK_WAIT = 0.25  # seconds the window waits for the desktop's dark-mode setting before starting light
KEEP = "(unchanged)"
PAGES = (("apps", "Apps"), ("add", "Add"), ("search", "Search"), ("tools", "Tools"))
LIST_ICON, CARD_ICON = 32, 64  # sides of an app's icon in the list and in the detail pane, at 96 dpi
# how a line of output is coloured: (tag, prefix)
LOG_TAGS = (("cmd", "$ appjail"), ("err", "error:"), ("warn", "! warning:"), ("note", "note:"), ("ok", "-- exit status 0 --"),
            ("err", "-- exit status"), ("err", "cancelled"))


class Scrolled(ttk.Frame):
    """A frame whose `body` scrolls vertically when it is given less height than the body asks for, and only then.
    The frame asks for the body's whole size, so a window that has room shows everything."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.canvas.palette_bg = "bg"
        bar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=autohide(bar, self.canvas, side="right", fill="y", padx=(6, 0)))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.fit())
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        for widget in (self, self.body):
            widget.bind("<Enter>", lambda _e: self._wheel(True), add="+")
            widget.bind("<Leave>", lambda _e: self._wheel(False), add="+")

    def fit(self):
        self.canvas.configure(width=self.body.winfo_reqwidth(), height=self.body.winfo_reqheight(),
                              scrollregion=(0, 0, self.body.winfo_reqwidth(), self.body.winfo_reqheight()))

    def _wheel(self, inside):
        if inside:
            self.bind_all("<Button-4>", lambda _e: self._scroll(-1))
            self.bind_all("<Button-5>", lambda _e: self._scroll(1))
            self.bind_all("<MouseWheel>", lambda e: self._scroll(-1 if e.delta > 0 else 1))
        else:
            under = self.winfo_containing(*self.winfo_pointerxy())
            if under is not None and str(under).startswith(str(self)):
                return  # the pointer moved onto a widget inside the frame
            for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                self.unbind_all(sequence)

    def _scroll(self, step):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(step, "units")

    def see(self, widget):
        """Scroll so that `widget`, somewhere in the body, is in view."""
        self.update_idletasks()
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        total = max(self.body.winfo_reqheight(), 1)
        view = self.canvas.winfo_height()
        first = self.canvas.yview()[0] * total
        if top < first or top + widget.winfo_height() > first + view:
            self.canvas.yview_moveto(max(min(top - 8, total - view), 0) / total)


class App:
    def __init__(self, root, dark=None):
        self.root = root
        root.title(f"appjail {cli.version_string()}")
        # width caps are in pixels for a 96 dpi screen; Tk's scaling follows the real one, and so do the fonts
        self.scale = max(float(root.tk.call("tk", "scaling")) / (96 / 72), 1.0)
        self.calls = queue.Queue()  # (function, result, error) of work done off the Tk thread, run by _poll
        asked = {}
        if dark is None:  # the portal usually answers at once; a slow one must not hold the window back
            probe = threading.Thread(target=lambda: asked.setdefault("dark", theme.prefers_dark()), daemon=True)
            probe.start()
            probe.join(DARK_WAIT)
            if probe.is_alive():
                self._when_done(probe, lambda: asked.get("dark"))
        self.theme = theme.Theme(root, asked.get("dark", False) if dark is None else dark, self.scale)
        font = tkfont.nametofont("TkDefaultFont")
        # ttk keeps a fixed row height: on a larger font the rows would overlap and cut the text
        ttk.Style().configure("Treeview", rowheight=font.metrics("linespace") + self.px(10))
        ttk.Style().configure("Apps.Treeview", rowheight=max(font.metrics("linespace"), self.px(LIST_ICON)) + self.px(12),
                              padding=(self.px(6), self.px(2)))
        self.events = queue.Queue()
        self.icon_events = queue.Queue()
        self.background = []  # event queues of detached children (run, open)
        self.busy = False
        self.names_before_add = None  # (names, rw) while an add waits for its file-types follow-up
        self.search_seq = 0  # the newest search; the results of an older one are dropped
        self.portals_pending = False
        self.narrow = False  # below 900 pixels: the action groups lose their names, the list narrows
        self.images = {}  # PhotoImages by key; Tk forgets an image nobody holds
        self.icon_keys = {}  # app name: the icon_key its images were made from
        self.status = tk.StringVar(value="ready")
        self.logo = self._photo("logo", icons.logo(self.px(30)))
        root.iconphoto(True, self._photo("logo:window", icons.logo(64)))
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self._build_sidebar()
        main = ttk.Frame(root)
        main.grid(row=0, column=1, sticky="nsew")
        bar = ttk.Frame(main, padding=(self.px(16), self.px(6)))  # packed first, at the bottom: a small window shrinks the panes, never the status line
        bar.pack(side="bottom", fill="x")
        ttk.Frame(main, style="Rule.TFrame", height=1).pack(side="bottom", fill="x")
        self.paned = ttk.PanedWindow(main, orient="vertical")
        self.paned.pack(fill="both", expand=True)
        self.content = ttk.Frame(self.paned)
        self.paned.add(self.content, weight=4)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.pages = {}
        self._build_apps_page()
        self._build_add_page()
        self._build_search_page()
        self._build_tools_page()
        self.log_frame = self._build_log(self.paned)
        self.log_shown = False
        self.status_label = ttk.Label(bar, textvariable=self.status, style="Muted.TLabel")
        self.status_label.pack(side="left")
        self.output_button = ttk.Button(bar, text="Show output", command=self.toggle_log)
        self.output_button.pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=self.px(160))
        self.show("apps")
        self.refresh()
        self._fit_window()
        self.polling = root.after(POLL_MS, self._poll)
        root.bind("<Destroy>", self._closed, add="+")

    def px(self, n):
        return self.theme.px(n)

    def off_thread(self, work, done):
        """Run work() on a thread, then done(result, error) on the Tk thread (from _poll)."""
        def run():
            try:
                self.calls.put((done, work(), None))
            except Exception as e:  # noqa: BLE001  (handed to done, which decides)
                self.calls.put((done, None, e))
        threading.Thread(target=run, daemon=True).start()

    def _when_done(self, probe, answer):
        """The desktop answered the dark-mode question late: follow it once the window is up."""
        def wait():
            probe.join()
            return answer()
        def follow(dark, _error):
            if dark and not self.theme.dark:
                self.dark.set(True)
                self.toggle_dark()
        self.off_thread(wait, follow)

    def _photo(self, key, png):
        image = self.images.get(key)
        data = base64.b64encode(png)
        if image is None:
            image = self.images[key] = tk.PhotoImage(master=self.root, data=data)
        else:
            image.configure(data=data)
        return image

    # --- frame: sidebar, pages, output ------------------------------------------------------------------------------

    def _build_sidebar(self):
        side = ttk.Frame(self.root, style="Side.TFrame", padding=(self.px(12), self.px(16)))
        side.grid(row=0, column=0, sticky="ns")
        brand = ttk.Frame(side, style="Side.TFrame")
        brand.pack(fill="x", pady=(0, self.px(18)))
        ttk.Label(brand, image=self.logo, style="Side.TLabel").pack(side="left")
        ttk.Label(brand, text="appjail", style="Brand.TLabel").pack(side="left", padx=(self.px(8), 0))
        self.page = tk.StringVar(value="apps")
        self.nav = {}
        for key, text in PAGES:
            self.nav[key] = ttk.Radiobutton(side, text=text, value=key, variable=self.page, style="Nav.TRadiobutton",
                                            command=lambda k=key: self.show(k))
            self.nav[key].pack(fill="x", pady=1)
        version = cli.version_string()
        if version != "unknown":  # a source tree has none to show (the title says so)
            ttk.Label(side, text=f"version {version}", style="SideSmall.TLabel").pack(side="bottom", anchor="w", pady=(self.px(8), 0))
        self.dark = tk.BooleanVar(value=self.theme.dark)
        ttk.Checkbutton(side, text="Dark", variable=self.dark, style="Switch.TCheckbutton",
                        command=self.toggle_dark).pack(side="bottom", anchor="w")

    def _page(self, key, title, subtitle):
        """A page in the content area, with its title; returns (page, header) so the page can add buttons to the header."""
        page = ttk.Frame(self.content, padding=(self.px(20), self.px(16), self.px(20), self.px(12)))
        self.pages[key] = page
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, self.px(12)))
        words = ttk.Frame(header)
        words.pack(side="left", fill="x", expand=True)
        ttk.Label(words, text=title, style="Title.TLabel").pack(anchor="w")
        subtitle_label = ttk.Label(words, text=subtitle, style="Muted.TLabel")
        subtitle_label.pack(anchor="w")
        page.subtitle = subtitle_label
        return page, header

    def show(self, key):
        """Bring a page to the front (the sidebar's buttons and Add this app… use it)."""
        self.page.set(key)
        for name, page in self.pages.items():
            if name == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()

    def toggle_dark(self):
        self.theme.apply(self.dark.get())
        self._tag_log()
        self._show_detail()

    def _build_log(self, parent):
        frame = ttk.Frame(parent, padding=(self.px(20), self.px(8), self.px(20), self.px(8)))
        head = ttk.Frame(frame)
        head.pack(fill="x", pady=(0, self.px(6)))
        ttk.Label(head, text="Output", style="Strong.TLabel").pack(side="left")
        ttk.Button(head, text="Clear", command=self.clear_log).pack(side="right")
        holder = ttk.Frame(frame, style="Card.TFrame", padding=self.px(2))
        holder.pack(fill="both", expand=True)
        self.log = tk.Text(holder, height=8, wrap="word", state="disabled", font=self.theme.fonts["mono"],
                           padx=self.px(10), pady=self.px(8), relief="flat")
        self.log.palette_bg = "log"
        self.log.retag = lambda _p: self._tag_log()
        scroll = ttk.Scrollbar(holder, command=self.log.yview)
        self.log.configure(yscrollcommand=autohide(scroll, self.log, side="right", fill="y"))
        self.log.pack(fill="both", expand=True)
        self.theme.recolor(self.log)
        self._tag_log()
        return frame

    def _tag_log(self):
        p = self.theme.p
        self.log.configure(background=p["log"])
        self.log.tag_configure("cmd", foreground=p["accent"], font=self.theme.fonts["mono"])
        self.log.tag_configure("err", foreground=p["danger"])
        self.log.tag_configure("warn", foreground=p["warn"])
        self.log.tag_configure("note", foreground=p["muted"])
        self.log.tag_configure("ok", foreground=p["ok"])

    def toggle_log(self, show=None):
        show = not self.log_shown if show is None else show
        if show and not self.log_shown:
            self.paned.add(self.log_frame, weight=1)
        elif not show and self.log_shown:
            self.paned.forget(self.log_frame)
        self.log_shown = show
        self.output_button.configure(text="Hide output" if show else "Show output")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def say(self, text):
        self.log.configure(state="normal")
        for line in textsafe.clean(text).split("\n"):
            tag = next((t for t, prefix in LOG_TAGS if line.startswith(prefix)), ())
            self.log.insert("end", line + "\n", tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    def run(self, command, label=None):
        """Run a CLI command in-process (it may prompt). One at a time."""
        if self.busy:
            self.status.set("busy: wait for the running command to finish")
            self.root.bell()
            return
        self.busy = True
        self.toggle_log(True)
        self.say(f"$ appjail {' '.join(command)}")
        self.status.set(label or f"running: {command[0]}")
        self.progress.pack(side="right", padx=self.px(12))
        self.progress.start(12)
        worker.run_command(command, self.events)

    def launch(self, command):
        """Start an app (run, open) as a detached process; it may run alongside other commands."""
        events = queue.Queue()
        self.background.append(events)
        self.toggle_log(True)
        self.say(f"$ appjail {' '.join(command)}")
        worker.spawn_detached(command, events)

    def _poll(self):
        """Hand what the threads produced to the window. It always schedules its next round, even when a step fails:
        a window that stopped polling would look alive and never show a command's output again."""
        try:
            self._drain(self.events, foreground=True)
            for q in list(self.background):
                if self._drain(q, foreground=False):
                    self.background.remove(q)
            self._take_icons()
            while True:
                try:
                    done, result, error = self.calls.get_nowait()
                except queue.Empty:
                    break
                done(result, error)
        finally:
            if self.polling is not None:  # None once the window is closing
                self.polling = self.root.after(POLL_MS, self._poll)

    def _closed(self, event):
        """The window is going: stop polling (Tk would report the pending call on a destroyed window)."""
        if event.widget is self.root and getattr(self, "polling", None):
            self.root.after_cancel(self.polling)
            self.polling = None

    def report(self, what, error):
        """A failure of work done in the background, shown where a command's would be."""
        self.say(textsafe.clean(f"error: {what}: {error}"))
        self.status.set(f"{what} failed")

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

    # --- icons ------------------------------------------------------------------------------------------------------

    def icon(self, name, side):
        """The app's icon at `side` (LIST_ICON or CARD_ICON): its own once loaded, a stand-in until then or without one."""
        own = self.images.get(f"app:{name}:{side}")
        if own is not None:
            return own
        key = f"stand-in:{name}:{side}"
        margin = self.px(10) if side == LIST_ICON else 0  # space between the icon and the name in the list
        return self.images.get(key) or self._photo(key, icons.stand_in(name, self.px(side), margin))

    def _load_icons(self, names):
        """Decode the icons that changed on a thread (a large icon takes a moment in Python); _take_icons shows them."""
        todo = []
        for name in names:
            key = apps.icon_key(name)
            if key != self.icon_keys.get(name):
                self.icon_keys[name] = key
                for side in (LIST_ICON, CARD_ICON):
                    self.images.pop(f"app:{name}:{side}", None)
                if key is not None:
                    todo.append((name, key))
        if todo:
            sides, margins = (self.px(LIST_ICON), self.px(CARD_ICON)), {self.px(LIST_ICON): self.px(10)}
            threading.Thread(target=lambda: [self.icon_events.put((name, key, apps.icon_pngs(key, sides, margins))) for name, key in todo],
                             daemon=True).start()

    def _take_icons(self):
        changed = False
        while True:
            try:
                name, key, pngs = self.icon_events.get_nowait()
            except queue.Empty:
                break
            if pngs is None or self.icon_keys.get(name) != key:
                continue
            for side in (LIST_ICON, CARD_ICON):
                self._photo(f"app:{name}:{side}", pngs[self.px(side)])
            changed = True
            if self.tree.exists(name):
                self.tree.item(name, image=self.icon(name, LIST_ICON))
        if changed:
            self._show_detail()

    # --- Apps -------------------------------------------------------------------------------------------------------

    def refresh(self):
        self.rows = apps.rows()
        self._load_icons([row[0] for row in self.rows])
        count = len(self.rows)
        self.pages["apps"].subtitle.configure(text=f"{count} installed, each in its own jail" if count else "Nothing installed yet")
        self._fill_list()

    def _fill_list(self):
        """The list shows the apps whose name or source contains the filter text; the selection is kept when shown."""
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.filter_text().lower()
        shown = [row for row in self.rows if query in row[0].lower() or query in row[2].lower()]
        for row in shown:
            self.tree.insert("", "end", iid=row[0], text=row[0], image=self.icon(row[0], LIST_ICON), values=row[1:])
        self._fit_columns()
        keep = [k for k in keep if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)
        elif shown:
            self.tree.selection_set(shown[0][0])
        if self.rows and not shown:
            self.no_match.place(relx=0.5, rely=0.3, anchor="center")
        else:
            self.no_match.place_forget()
        self._show_detail()

    def filter_text(self):
        return self.filter.get().strip()

    def _fit_window(self):
        """Start at the size the layout asks for (the tallest page), so no button is hidden by default."""
        self.root.update_idletasks()
        self.add_scroll.fit()
        self.root.update_idletasks()
        # every page computes the size it asks for, shown or not; the window asks for the shown one's, plus the frame
        shown = self.pages[self.page.get()]
        req_w = self.root.winfo_reqwidth() - shown.winfo_reqwidth() + max(p.winfo_reqwidth() for p in self.pages.values())
        req_h = self.root.winfo_reqheight() - shown.winfo_reqheight() + max(p.winfo_reqheight() for p in self.pages.values())
        width = min(max(req_w, int(1100 * self.scale)), self.root.winfo_screenwidth() - 40)
        height = min(req_h + 16, self.root.winfo_screenheight() - 80)
        self.root.minsize(min(req_w, width), min(req_h, height))
        self.root.geometry(f"{width}x{height}")

    def _fit_columns(self):
        """The name column is as wide as the longest name, within a cap."""
        font = tkfont.nametofont("TkDefaultFont")
        names = [self.tree.item(k, "text") for k in self.tree.get_children()]
        width = max([font.measure("Installed apps"), *(font.measure(n) for n in names)]) + self.px(LIST_ICON) + self.px(40)
        cap = 170 if self.narrow else 300  # a narrow window gives the room to the actions
        # not stretchable: Tk 9 fits a stretchable column to the width the list has, which is what the column asked for
        self.tree.column("#0", width=min(width, int(cap * self.scale)), minwidth=self.px(120), stretch=False)

    def _show_detail(self):
        """Fill the detail pane for the selected app (or the empty state)."""
        sel = self.tree.selection()
        for child in self.card_body.winfo_children():
            child.destroy()
        has_app = bool(sel)
        for button in self.app_buttons:
            button.configure(state="normal" if has_app else "disabled")
        if not has_app:
            empty = not self.rows
            self.card_icon.configure(image=self.logo if empty else "")
            self.card_title.configure(text="No apps yet" if empty else "Select an app")
            self.card_subtitle.configure(text="Add one from GitHub, a URL or a file, or find one in the catalogs." if empty else "")
            if empty:
                row = ttk.Frame(self.card_body)
                row.pack(anchor="w", pady=(self.px(12), 0))
                ttk.Button(row, text="Add an app", style="Accent.TButton", command=lambda: self.show("add")).pack(side="left")
                ttk.Button(row, text="Search the catalogs", command=lambda: self.show("search")).pack(side="left", padx=self.px(8))
            self._detail_text([])
            return
        info = apps.card(sel[0])
        self.card_icon.configure(image=self.icon(sel[0], CARD_ICON))
        self.card_title.configure(text=info["name"])
        self.card_subtitle.configure(text=info["error"] or info["subtitle"])
        chips = ttk.Frame(self.card_body)
        chips.pack(fill="x", pady=(self.px(10), 0))
        for kind, text in info["badges"]:
            ttk.Label(chips, text=text, style="Warn.TLabel" if kind == "warn" else "Plain.TLabel").pack(side="left", padx=(0, self.px(6)))
        self._detail_text(info["grants"], info["lines"])

    def _detail_text(self, grants, lines=()):
        """The grants as chips that wrap with the pane, then what else the app is granted, one line each."""
        t = self.detail
        t.configure(state="normal")
        t.delete("1.0", "end")
        if self.tree.selection():
            t.insert("end", "Granted\n", "head")
            for flag in grants:
                t.window_create("end", window=ttk.Label(t, text=flag, style="Chip.TLabel"), padx=self.px(2), pady=self.px(3))
                t.insert("end", " ", "chips")
            if not grants:
                t.insert("end", "nothing beyond the defaults", "muted")
            t.insert("end", "\n" + "".join(f"\n{line}" for line in lines))
            # the flags are also plain text (hidden), so the pane reads and searches as the `list --long` line does
            t.insert("end", "\n" + " ".join(grants), "hidden")
        t.configure(state="disabled")
        self.root.after_idle(self._fit_detail)

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            dialogs.notice(self.root, "Select an app first.")
            return None
        return sel[0]

    def _build_apps_page(self):
        page, header = self._page("apps", "Apps", "")
        ttk.Button(header, text="Update all", command=lambda: self.run(argv.update_argv())).pack(side="right")
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side="right", padx=self.px(8))
        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        # the list: icon and name; the rest is in the detail pane
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, self.px(14)))
        self.filter = tk.StringVar()
        self.filter_entry = dialogs.HintEntry(left, "Filter apps  (Ctrl+F)", textvariable=self.filter, width=12)
        self.filter_entry.pack(fill="x", pady=(0, self.px(8)))
        self.filter.trace_add("write", lambda *_: self._fill_list())
        self.filter_entry.bind("<Escape>", lambda _e: (self.filter.set(""), self.tree.focus_set()))
        self.filter_entry.bind("<Down>", lambda _e: self.tree.focus_set())
        self.root.bind("<Control-f>", lambda _e: (self.show("apps"), self.filter_entry.focus_set()))
        holder = ttk.Frame(left, style="Card.TFrame", padding=self.px(4))
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(holder, columns=("version", "source", "tier", "permissions", "note"), displaycolumns=(),
                                 show="tree", selectmode="browse", style="Apps.Treeview", height=7)
        self.no_match = ttk.Label(holder, text="No app matches", style="Muted.TLabel")
        self.rows = []
        scroll = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=autohide(scroll, self.tree, side="right", fill="y"))
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())
        self.tree.bind("<Double-1>", lambda _e: self._for_app(lambda a: self.launch(argv.run_argv(a))))
        self.tree.bind("<Return>", lambda _e: self._for_app(lambda a: self.launch(argv.run_argv(a))))
        # the detail pane: who the app is, what it is granted, and what can be done with it; it scrolls when the window
        # is too short for it (a small screen), so no button is ever cut off
        card = ttk.Frame(body, style="Card.TFrame", padding=(self.px(18), self.px(14), self.px(8), self.px(14)))
        card.grid(row=0, column=1, sticky="nsew")
        self.card_scroll = Scrolled(card)
        self.card_scroll.pack(fill="both", expand=True)
        inside = self.card_scroll.body
        top = ttk.Frame(inside)
        top.pack(fill="x")
        self.card_icon = ttk.Label(top)
        self.card_icon.pack(side="left", padx=(0, self.px(14)))
        words = ttk.Frame(top)
        words.pack(side="left", fill="x", expand=True)
        self.card_title = ttk.Label(words, style="Title.TLabel")
        self.card_title.pack(anchor="w")
        self.card_subtitle = dialogs.WrapLabel(words, style="Muted.TLabel")
        self.card_subtitle.pack(fill="x")
        self.card_body = ttk.Frame(inside)
        self.card_body.pack(fill="x")
        self.detail = tk.Text(inside, height=4, width=36, wrap="word", state="disabled", relief="flat", cursor="arrow",
                              padx=0, pady=self.px(8), font="TkDefaultFont")
        self.detail.palette_bg = "bg"
        self.detail.retag = lambda p: self._tag_detail(p)
        self._tag_detail(self.theme.p)
        self.detail.pack(fill="x")
        self.detail.bind("<Configure>", lambda _e: self._fit_detail())

        def on(action):
            return lambda: self._for_app(action)

        self.app_buttons, self.group_labels = [], []
        groups = (
            (None, (("Run", on(lambda a: self.launch(argv.run_argv(a))), "Accent.TButton"), ("Run with…", on(self._run_with), None),
                    ("Open file…", on(self._open_file), None))),
            ("Access", (("Permissions…", on(self._permissions), None), ("Portals…", on(self._portals), None))),
            ("Menu", (("Menu entry…", on(self._menu_entry), None), ("File types", on(lambda a: self.run(argv.desktop_argv(a, show=True))), None),
                      ("Remove menu entry", on(lambda a: self.run(argv.desktop_argv(a, remove=True))), None))),
            ("Updates", (("Update", on(lambda a: self.run(argv.update_argv(a))), None), ("Update…", on(self._update_options), None),
                         ("History", on(lambda a: self.run(argv.history_argv(a))), None))),
            ("Remove", (("Reset app", on(lambda a: self.run(["reset", a])), "Danger.TButton"),
                        ("Remove app", on(lambda a: self.run(["remove", a])), "Danger.TButton"))))
        actions = ttk.Frame(inside)
        actions.pack(fill="x", pady=(self.px(4), 0))
        for row, (title, buttons) in enumerate(groups):
            label = ttk.Label(actions, text=title or "", style="Small.TLabel")
            label.grid(row=row, column=0, sticky="w", padx=(0, self.px(12)))
            self.group_labels.append(label)
            line = dialogs.Flow(actions)
            line.grid(row=row, column=1, sticky="ew", pady=self.px(3))
            for text, action, style in buttons:
                button = line.add(ttk.Button(line, text=text, command=action, **({"style": style} if style else {})))
                self.app_buttons.append(button)
        actions.columnconfigure(1, weight=1)
        # a narrow window drops the group names, so two or three buttons still fit on a row
        self.root.bind("<Configure>", lambda e: e.widget is self.root and self._narrow(e.width), add="+")

    def _narrow(self, width):
        narrow = width < int(900 * self.scale)
        if narrow != self.narrow:
            self.narrow = narrow
            self._fit_columns()
        for label in self.group_labels:
            if narrow and label.winfo_manager():
                label.grid_remove()
            elif not narrow and not label.winfo_manager():
                label.grid()

    def _fit_detail(self):
        """The text is as tall as its lines (it sits in a pane that scrolls), never taller."""
        pixels = self.detail.count("1.0", "end", "ypixels")  # the chips' line is taller than a line of text
        pixels = pixels[0] if isinstance(pixels, tuple) else pixels or 0
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        height = max(-(-pixels // line), 1)
        if int(self.detail.cget("height")) != height:
            self.detail.configure(height=height)

    def _tag_detail(self, p):
        self.detail.tag_configure("head", font=self.theme.fonts["strong"], spacing1=self.px(4), spacing3=self.px(4))
        self.detail.tag_configure("muted", foreground=p["muted"])
        self.detail.tag_configure("hidden", elide=True)
        self.detail.configure(foreground=p["muted"], background=p["bg"])

    def _for_app(self, action):
        app = self.selected()
        if app:
            action(app)

    def _run_with(self, app):
        got = dialogs.options_dialog(
            self.root, f"Run {app} with extra access", (
                ("list", "dirs", "Directories for this run", {"hint": "read-only unless writable; the manifest is unchanged", "browse": "dir"}),
                ("list", "files", "Files for this run", {"hint": "PATH or PATH:rw; the app gets their in-jail path", "browse": "file"})),
            "Granted for this run only.", ok="Run")
        if got:
            self.launch(argv.run_argv(app, got["dirs"], got["files"]))

    def _update_options(self, app):
        got = dialogs.options_dialog(
            self.root, f"Update {app}", (
                ("check", "prerelease", "Follow pre-releases for this run"),
                ("combo", "channel", "Channel from now on (GitHub apps)", (KEEP, *manifest.CHANNELS)),
                ("text", "quarantine", "Quarantine days (default 7)"),
                ("text", "file", "New AppImage (file apps)"),
                ("text", "sha256", "sha256 of the new content"),
                ("check", "verify", "URL apps: verify after the quarantine"),
                ("text", "pattern", "Asset pattern, from now on (GitHub apps)"),
                ("check", "private", "URL apps: follow redirects to private addresses (the LAN, loopback); only for a server of your own")),
            "The update shows its review and asks before installing.")
        if got:
            self.run(argv.update_argv(app, got["prerelease"], None if got["channel"] == KEEP else got["channel"], got["quarantine"], got["file"], got["sha256"], got["verify"],
                                          got["pattern"], got["private"]))

    def _portals(self, app):
        """The grants are read from the session bus on a thread (a slow bus must not freeze the window)."""
        if self.portals_pending:
            return
        self.portals_pending = True
        self.status.set("reading the portal grants…")

        def done(result, error):
            self.portals_pending = False
            if error is not None:
                self.report("reading the portal grants", error)
                return
            self.status.set("ready")
            self._portals_dialog(app, *result)
        self.off_thread(lambda: apps.portal_grants(app), done)

    def _portals_dialog(self, app, header, grants):
        ids = {line: doc for doc, line in grants}
        fields = [("choice", "revoke", "Document grants to revoke",
                   {"items": list(ids), "width": 80, "hint": "select none to only list the grants"})] if grants else []
        got = dialogs.options_dialog(
            self.root, f"Portal grants of {app}", (*fields, ("check", "all", "Revoke every grant")),
            "\n".join(header) + "\n\nThe command lists the grants and asks before revoking.", ok="Go")
        if got:
            self.run(argv.portals_argv(app, [ids[line] for line in got.get("revoke", ())], got["all"]))

    def _menu_entry(self, app):
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

    def _open_file(self, app):
        path = files.choose_file(self.root, f"Open with {app}")
        if not path:
            return
        got = dialogs.options_dialog(
            self.root, f"Open with {app}", (("check", "rw", "Let the app change this file"),),
            f"{textsafe.clean(path)}\n\nThe file is bound alone into the jail, read-only unless you tick the box.", ok="Open")
        if got:
            self.launch(argv.open_argv(app, path, got["rw"]))

    def _permissions(self, app):
        try:
            old = apps.load_permissions(app)
        except (manifest.ManifestError, OSError) as e:
            dialogs.notice(self.root, textsafe.clean(f"cannot read the manifest: {e}"), error=True)
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

    def _build_add_page(self):
        page, _header = self._page("add", "Add an app", "The command shows what it will install and asks before anything is written.")
        self.add_page = page
        gap = self.px(10)
        bottom = ttk.Frame(page)  # packed first: the main action stays visible in a small window
        bottom.pack(side="bottom", fill="x", pady=(gap, 0))
        # the form scrolls only when the window is shorter than it asks (a small screen)
        self.add_scroll = Scrolled(page)
        self.add_scroll.pack(fill="both", expand=True)
        body = self.add_scroll.body
        source = ttk.LabelFrame(body, text="Source")
        source.pack(fill="x")
        top = ttk.Frame(source)
        top.pack(fill="x")
        self.kind = tk.StringVar(value="github")
        kinds = ttk.Frame(top)
        kinds.grid(row=0, column=0, columnspan=2, sticky="w")
        for value, text in (("github", "GitHub owner/repo"), ("url", "https URL"), ("file", "Local file")):
            ttk.Radiobutton(kinds, text=text, value=value, variable=self.kind).pack(side="left", padx=(0, self.px(16)))
        self.source = tk.StringVar()
        ttk.Entry(top, textvariable=self.source, width=30).grid(row=1, column=0, sticky="ew", pady=(self.px(6), 0))
        ttk.Button(top, text="Browse…", command=self._browse).grid(row=1, column=1, padx=(self.px(8), 0), pady=(self.px(6), 0))
        top.columnconfigure(0, weight=1)
        self.text, self.entries = {}, {}
        opts = dialogs.Flow(source, gap=gap, uniform=True)  # four fields in a row, or two, or one: as the width allows
        opts.pack(fill="x", pady=(self.px(8), 0))
        for key, label in (("name", "Local name"), ("tag", "Release tag (GitHub)"), ("sha256", "sha256 (url/file)"),
                           ("max_size", "Max MiB (url)")):
            cell = ttk.Frame(opts)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            self.text[key] = tk.StringVar()
            self.entries[key] = ttk.Entry(cell, textvariable=self.text[key], width=18)
            self.entries[key].pack(anchor="w", pady=(self.px(2), 0))
            opts.add(cell)
        self.prerelease = tk.BooleanVar()
        self.private_redirects = tk.BooleanVar()
        self.checks = {}
        choices = dialogs.Flow(source, gap=self.px(18))
        choices.pack(fill="x", pady=(self.px(6), 0))
        self.checks["Allow pre-releases"] = choices.add(ttk.Checkbutton(choices, text="Allow pre-releases (GitHub)", variable=self.prerelease))
        self.private_check = choices.add(ttk.Checkbutton(choices, text="Follow redirects to private addresses (URL)",
                                                         variable=self.private_redirects))
        dialogs.WrapLabel(source, text="Private addresses (the LAN, loopback) are refused by default; follow them only for a server of your own.",
                          style="Small.TLabel").pack(fill="x")
        self.kind.trace_add("write", lambda *_: self._kind_changed())
        self.flag = {}
        grants = ttk.LabelFrame(body, text="Permissions")
        grants.pack(fill="x", pady=(gap, 0))
        flags_row = dialogs.Flow(grants, gap=gap, uniform=True)  # in columns, as many as fit
        flags_row.pack(fill="x")
        for flag in PERMISSION_FLAGS:
            self.flag[flag] = tk.BooleanVar(value=False)
            flags_row.add(ttk.Checkbutton(flags_row, text=flag, variable=self.flag[flag]))
        self.audio_mode = tk.StringVar(value=manifest.DEFAULT_AUDIO_MODE)
        self.display = tk.StringVar(value="wayland")
        self.display_size = tk.StringVar(value=manifest.DEFAULT_DISPLAY_SIZE)
        self.limits = {key: tk.StringVar() for key in manifest.LIMIT_KEYS}
        # two rows, each wrapping on its own: how the app is shown and heard, then its limits
        for fields in ((("Audio mode", lambda p: ttk.Combobox(p, textvariable=self.audio_mode, values=manifest.AUDIO_MODES, state="readonly", width=9)),
                        ("Display", lambda p: ttk.Combobox(p, textvariable=self.display, values=manifest.DISPLAYS, state="readonly", width=16)),
                        ("Window size", lambda p: ttk.Entry(p, textvariable=self.display_size, width=10))),
                       (("Memory limit", lambda p: ttk.Entry(p, textvariable=self.limits["memory_max"], width=7)),
                        ("CPU limit", lambda p: ttk.Entry(p, textvariable=self.limits["cpu_quota"], width=7)),
                        ("Process limit", lambda p: ttk.Entry(p, textvariable=self.limits["tasks_max"], width=7)))):
            row = dialogs.Flow(grants, gap=self.px(18))
            row.pack(fill="x", pady=(self.px(8), 0))
            for label, make in fields:
                pair = ttk.Frame(row)
                ttk.Label(pair, text=label, style="Muted.TLabel").pack(side="left", padx=(0, self.px(6)))
                make(pair).pack(side="left")
                row.add(pair)
        dialogs.WrapLabel(grants, text="Window size: for the rootful Xwayland display. Limits: 2G, 200%, 512; empty for none.",
                          style="Small.TLabel").pack(fill="x", pady=(self.px(4), 0))
        # the lists, one at a time beside a column of segments; each segment counts its entries, so none is forgotten
        access = ttk.LabelFrame(body, text="Access")
        access.pack(fill="x", pady=(gap, 0))

        def lister(title, hint="", browse=None):
            return lambda parent, changed: dialogs.ListEditor(parent, title, (), hint, browse=browse, bare=True, on_change=changed)
        self.access_lists = dialogs.Segmented(access, (
            ("dirs", "Directories", lister("Directories", "PATH or PATH:rw", browse="dir")),
            ("dbus", "D-Bus names (talk)", lister("D-Bus names (talk)")),
            ("dbus_own", "D-Bus names (own)", lister("D-Bus names (own)")),
            ("portals", "Privileged portals",
             lambda parent, changed: dialogs.PortalChecks(parent, "Privileged portals", (), "needs the portals permission",
                                                          wrap=int(360 * self.scale), height=int(96 * self.scale), bare=True,
                                                          on_change=changed)),
            ("schemes", "URL schemes", lister("URL schemes", "gemini; links of these open the app"))))
        self.access_lists.pack(fill="both", expand=True)
        self.editors, self.segments, self.access = self.access_lists.editors, self.access_lists.segments, self.access_lists.current
        self._show_access = self.access_lists.show
        self.desktop = tk.BooleanVar()
        self.mime_all = tk.BooleanVar()
        self.mime = tk.StringVar()
        self.rw = tk.BooleanVar()
        ttk.Button(bottom, text="Add…", style="Accent.TButton", command=self._add).pack(side="right", anchor="n", padx=(gap, 0))
        menu = dialogs.Flow(bottom, gap=gap)  # wraps on a narrow window; the Add… button stays at the right
        menu.pack(side="left", fill="x", expand=True)
        for var, text in ((self.desktop, "Create menu entry"), (self.mime_all, "All file types"), (self.rw, "Files writable")):
            self.checks[text] = menu.add(ttk.Checkbutton(menu, text=text, variable=var))
        types = ttk.Frame(menu)
        ttk.Label(types, text="File types", style="Muted.TLabel").pack(side="left", padx=(0, self.px(6)))
        ttk.Entry(types, textvariable=self.mime, width=14).pack(side="left")
        menu.add(types)
        self._kind_changed()

    def _kind_changed(self):
        """Options that do not apply to the chosen source are greyed out, as the CLI refuses them."""
        kind = self.kind.get()
        for key, applies in (("tag", kind == "github"), ("sha256", kind != "github"), ("max_size", kind == "url")):
            self.entries[key].configure(state="normal" if applies else "disabled")
        self.checks["Allow pre-releases"].configure(state="normal" if kind == "github" else "disabled")
        self.private_check.configure(state="normal" if kind == "url" else "disabled")

    def _browse(self):
        path = files.choose_file(self.root, "Choose an AppImage", patterns=[("AppImages", "*.appimage")])
        if path:
            self.kind.set("file")
            self.source.set(path)

    def _add(self):
        form = {k: v.get() for k, v in self.text.items()}
        form.update(kind=self.kind.get(), source=self.source.get(), prerelease=self.prerelease.get(),
                    allow=[f for f, v in self.flag.items() if v.get()], audio_mode=self.audio_mode.get(), display=self.display.get(), display_size=self.display_size.get().strip(),
                    **{k: v.get().strip() for k, v in self.limits.items()},
                    desktop=self.desktop.get(), mime_all=self.mime_all.get(),
                    mime=self.mime.get().replace(",", " ").split(), rw=self.rw.get())
        form.update({k: ed.values() for k, ed in self.editors.items()})
        form["allow_private_redirects"] = self.private_redirects.get()
        if not form["source"].strip():
            dialogs.notice(self.root, "Give a source first.")
            return
        if argv.defers_menu_entry(form):  # `desktop NAME` follows the install and offers the types the app declares
            form["desktop"] = False
            self.names_before_add = ([r[0] for r in apps.rows()], self.rw.get())
        self.run(argv.add_argv(form), "adding")  # the command shows its review and asks before installing

    # --- Search and index -------------------------------------------------------------------------------------------

    def _build_search_page(self):
        page, _header = self._page("search", "Search", "A hit is only a suggestion: check the owner and repository before adding.")
        gap = self.px(10)
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.keywords = tk.StringVar()
        entry = dialogs.HintEntry(row, "Keywords, such as: gemini browser", textvariable=self.keywords, width=16)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._search())
        ttk.Button(row, text="Search", style="Accent.TButton", command=self._search).pack(side="left", padx=(self.px(8), 0))
        self.limit = tk.StringVar(value="20")
        ttk.Label(row, text="Limit", style="Muted.TLabel").pack(side="left", padx=(self.px(16), self.px(6)))
        ttk.Entry(row, textvariable=self.limit, width=5).pack(side="left")
        self.show_all = tk.BooleanVar()
        ttk.Checkbutton(row, text="All", variable=self.show_all).pack(side="left", padx=(gap, 0))
        self.hits = []
        # rarely needed, so closed until asked for; packed before the results: they shrink, the buttons stay
        self.catalogs = dialogs.Expander(page, "Catalogs")
        self.catalogs.pack(side="bottom", fill="x", pady=(gap, 0))
        idx = self.catalogs.body
        results = ttk.Frame(page, style="Card.TFrame", padding=self.px(4))
        results.pack(fill="both", expand=True, pady=(gap, 0))
        self.hit_tree = ttk.Treeview(results, columns=("name", "description", "source", "catalog"), show="headings",
                                     selectmode="browse", height=6)
        for c, w in (("name", 150), ("description", 320), ("source", 200), ("catalog", 80)):
            self.hit_tree.heading(c, text=c.title(), anchor="w")
            self.hit_tree.column(c, width=int(w * self.scale), minwidth=40)
        bar = ttk.Scrollbar(results, command=self.hit_tree.yview)
        self.hit_tree.configure(yscrollcommand=autohide(bar, self.hit_tree, side="right", fill="y"))
        self.hit_tree.pack(fill="both", expand=True)
        self.hit_tree.bind("<<TreeviewSelect>>", lambda _e: self._hit_selected())
        self.hit_tree.bind("<Double-1>", lambda _e: self._use_hit())
        use = ttk.Frame(page)
        use.pack(fill="x", pady=(self.px(8), 0), before=self.catalogs)
        self.use_hit = ttk.Button(use, text="Add this app…", command=self._use_hit, state="disabled")
        self.use_hit.pack(side="right", anchor="n")
        dialogs.WrapLabel(use, text="Copies the hit into the Add page; nothing is installed until you confirm there.",
                          style="Small.TLabel").pack(side="left", fill="x", expand=True)
        fields = dialogs.Flow(idx, gap=gap)
        fields.pack(fill="x")
        self.source_name = tk.StringVar()
        self.index_commit = tk.StringVar()
        for label, var, width, hint in (("Source name", self.source_name, 22, "optional for Update and Rollback"),
                                        ("appjail-db commit", self.index_commit, 42, "40 hex digits, for Update; empty: the latest")):
            pair = ttk.Frame(fields)
            ttk.Label(pair, text=label, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Entry(pair, textvariable=var, width=width).grid(row=1, column=0, sticky="w", pady=(2, 0))
            ttk.Label(pair, text=hint, style="Small.TLabel").grid(row=2, column=0, sticky="w")
            fields.add(pair)
        self.index_private = tk.BooleanVar()
        ttk.Checkbutton(idx, text="Follow redirects to private addresses (Update, Add from URL)",
                        variable=self.index_private).pack(anchor="w", pady=(self.px(6), 0))
        ttk.Label(idx, text="Only for a server of your own: the LAN and loopback are refused by default.",
                  style="Small.TLabel").pack(anchor="w")
        buttons = dialogs.Flow(idx)
        buttons.pack(fill="x", pady=(self.px(8), 0))
        for text, action, style in (("Status", lambda: self.run(["index", "status"]), None),
                                    ("Update", lambda: self._index("update"), None),
                                    ("Rollback", lambda: self._index("rollback"), None),
                                    ("Add from URL…", lambda: self._index_add("--url"), None),
                                    ("Add from file…", lambda: self._index_add("--file"), None),
                                    ("Remove source", self._index_remove, "Danger.TButton")):
            buttons.add(ttk.Button(buttons, text=text, command=action, **({"style": style} if style else {})))

    def _search(self):
        """Search the catalogs on a thread (reading a catalog takes a moment); a newer search replaces an older one."""
        words = self.keywords.get().strip()
        if not words:
            return
        limit = self.limit.get().strip()
        if limit and not (limit.isdigit() and int(limit) > 0):
            dialogs.notice(self.root, "The limit must be a positive number (or empty for every match).", error=True)
            return
        self.hit_tree.delete(*self.hit_tree.get_children())
        self.hits = []
        self._hit_selected()
        self.search_seq += 1
        seq = self.search_seq
        self.status.set("searching the catalogs…")
        show_all = self.show_all.get()
        self.off_thread(lambda: apps.search_hits(words, int(limit) if limit.isdigit() else None, show_all),
                        lambda result, error: self._show_hits(seq, words, result, error))

    def _show_hits(self, seq, words, result, error):
        if seq != self.search_seq:
            return  # a newer search is running
        self.say(f"$ appjail search {words}")
        if isinstance(error, IndexProblem):  # no index yet, no keyword: said as the command says it
            self.say(f"error: {error}")
            self.status.set(f"search: {error}")
            return
        if error is not None:
            self.report("search", error)
            return
        hits, total, searched = result
        summary = f"{total} match(es) in {', '.join(searched)}" + (f", showing {len(hits)}" if len(hits) < total else "")
        self.say(summary)
        self.status.set(summary)
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
            dialogs.notice(self.root, f"{hit.name}: appjail cannot install this source ({hit.note or hit.source or 'none given'}).")
            return
        self.kind.set(target[0])
        self.source.set(target[1])
        for key in ("name", "tag", "sha256", "max_size"):
            self.text[key].set("")
        self.private_redirects.set(False)  # a suggestion never carries the risky choice
        self.show("add")

    def _index(self, sub):
        name = self.source_name.get().strip()
        self.run(argv.index_argv(sub, name, self.index_commit.get(), self.index_private.get()))

    def _index_add(self, flag):
        name = self.source_name.get().strip()
        if not name:
            dialogs.notice(self.root, "Type a name for the new source first.")
            return
        if flag == "--file":
            where = files.choose_file(self.root, "Choose a catalog", patterns=[("Catalogs (JSON)", "*.json")])
        else:
            where = dialogs.ask_text(self.root, "Add a catalog", "https URL of the catalog:", ok="Add")
        if where:
            self.run(argv.index_add_argv(name, flag, where, self.index_private.get()))

    def _index_remove(self):
        name = self.source_name.get().strip()
        if name:
            self.run(["index", "remove", name])
        else:
            dialogs.notice(self.root, "Type the source name first.")

    # --- Tools ------------------------------------------------------------------------------------------------------

    def _build_tools_page(self):
        page, _header = self._page("tools", "Tools", "Helper binaries and commands that concern every app.")
        helpers = ttk.LabelFrame(page, text="Helper binaries")
        helpers.pack(fill="x")
        ttk.Label(helpers, text="Pinned in appjail's source and verified before use.", style="Small.TLabel").pack(anchor="w", pady=(0, self.px(8)))
        row = ttk.Frame(helpers)
        row.pack(fill="x")
        ttk.Button(row, text="Status", command=lambda: self.run(["tools", "status"])).pack(side="left")
        self.tool = tk.StringVar(value=min(tools.TOOLS))
        ttk.Combobox(row, textvariable=self.tool, values=sorted(tools.TOOLS), state="readonly", width=16).pack(side="left", padx=(self.px(16), self.px(6)))
        ttk.Button(row, text="Install…", command=lambda: self.run(["tools", "install", self.tool.get()])).pack(side="left")
        other = ttk.LabelFrame(page, text="Other commands")
        other.pack(fill="x", pady=(self.px(12), 0))
        row = dialogs.Flow(other)
        row.pack(fill="x")
        for text, command in (("Version", ["version"]), ("List apps", ["list"]), ("History (all apps)", argv.history_argv()),
                              ("Prune stale menu entries", argv.desktop_argv(prune=True))):
            row.add(ttk.Button(row, text=text, command=lambda c=command: self.run(c)))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
