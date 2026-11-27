# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A file and folder chooser in the window's own theme (Tk's stock one on X11 ignores it).

It lists one folder at a time: folders first, then files, optionally only those matching a pattern. Names are shown
cleaned of control characters; the path returned is the real one. Choosing a file is the consent to use it, as with
any chooser: nothing here opens or reads a file."""

import base64
import fnmatch
import os
import stat
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .. import textsafe
from . import dialogs, icons

MAX_ENTRIES = 5000  # a folder with more is listed in part, and says so
ALL = ("All files", "*")
_last = {"dir": None}  # the folder of the last choice, for this session


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def listing(folder, hidden=False, pattern="*", directories_only=False, limit=MAX_ENTRIES):
    """([(name, is_dir, size, mtime)], truncated) of a folder: folders first, each group by name, case-insensitive.
    Raises OSError when the folder cannot be read."""
    entries, truncated = [], False
    with os.scandir(folder) as it:
        for entry in it:
            if not hidden and entry.name.startswith("."):
                continue
            try:
                st = entry.stat()  # follows links: a link to a folder is a folder
            except OSError:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            if not is_dir and (directories_only or not fnmatch.fnmatch(entry.name.lower(), pattern.lower())):
                continue
            if len(entries) >= limit:
                truncated = True
                break
            entries.append((entry.name, is_dir, st.st_size, st.st_mtime))
    entries.sort(key=lambda e: (not e[1], e[0].lower()))
    return entries, truncated


def places(home=None):
    """(label, path) of the usual starting points that exist."""
    home = Path(home or Path.home())
    found = [("Home", home)]
    for name in ("Desktop", "Documents", "Downloads", "Applications"):
        if (home / name).is_dir():
            found.append((name, home / name))
    found.append(("Computer", Path("/")))
    return found


class Chooser:
    """A modal chooser; `result` is the chosen path (str) or None. directory=True chooses a folder."""

    def __init__(self, parent, title, directory=False, patterns=(), start=None):
        self.directory = directory
        self.patterns = [*patterns, ALL] if not directory else [ALL]
        self.result = None
        self.top = top = dialogs._modal(parent, title)
        scale = max(float(parent.tk.call("tk", "scaling")) / (96 / 72), 1.0)
        px = lambda n: max(round(n * scale), 1)
        self.images = {"dir": self._image(icons.folder(px(18), px(6))), "file": self._image(icons.document(px(18), px(6)))}
        frame = ttk.Frame(top, padding=px(14))
        frame.pack(fill="both", expand=True)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, px(10)))
        ttk.Button(bar, text="↑ Up", command=self.up).pack(side="left")
        self.path = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.path)
        entry.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
        entry.bind("<Return>", lambda _e: self.typed())
        bottom = ttk.Frame(frame)  # packed before the list: a small window shrinks the list, not the buttons
        bottom.pack(side="bottom", fill="x", pady=(px(10), 0))
        side = ttk.Frame(frame)
        side.pack(side="left", fill="y", padx=(0, px(12)))
        self.place = tk.StringVar()
        for label, path in places():
            ttk.Radiobutton(side, text=label, value=str(path), variable=self.place, style="Seg.TRadiobutton",
                            command=lambda p=path: self.go(p)).pack(fill="x", pady=(0, px(3)))
        holder = ttk.Frame(frame, style="Card.TFrame", padding=px(3))
        holder.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(holder, columns=("size", "modified"), selectmode="browse", height=14)
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.heading("size", text="Size", anchor="e")
        self.tree.heading("modified", text="Modified", anchor="w")
        self.tree.column("#0", width=px(320), minwidth=px(160))
        self.tree.column("size", width=px(80), anchor="e", stretch=False)
        self.tree.column("modified", width=px(130), stretch=False)
        scroll = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=dialogs.autohide_pack(scroll, self.tree, side="right", fill="y"))
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.activate())
        self.tree.bind("<Return>", lambda _e: self.activate())
        self.tree.bind("<BackSpace>", lambda _e: self.up())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.selected())
        self.hidden = tk.BooleanVar()
        ttk.Checkbutton(bottom, text="Hidden files", variable=self.hidden, command=self.refresh).pack(side="left")
        self.pattern = tk.StringVar(value=self.patterns[0][0])
        if len(self.patterns) > 1:
            box = ttk.Combobox(bottom, textvariable=self.pattern, values=[p[0] for p in self.patterns], state="readonly", width=18)
            box.pack(side="left", padx=(px(12), 0))
            box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.note = ttk.Label(bottom, style="Small.TLabel")
        self.note.pack(side="left", padx=(px(12), 0))
        self.ok = ttk.Button(bottom, text="Choose this folder" if directory else "Open", style="Accent.TButton", command=self.accept)
        self.ok.pack(side="right")
        ttk.Button(bottom, text="Cancel", command=top.destroy).pack(side="right", padx=(0, px(6)))
        top.bind("<Escape>", lambda _e: top.destroy())
        self.names = {}
        start = Path(start or _last["dir"] or Path.home())
        self.go(start if start.is_dir() else Path.home())
        dialogs._wait(top, self.tree)

    def _image(self, png):
        return tk.PhotoImage(master=self.top, data=base64.b64encode(png))

    def go(self, folder):
        self.folder = Path(folder)
        self.place.set(str(self.folder))
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.names = {}
        self.path.set(str(self.folder))
        pattern = dict(self.patterns)[self.pattern.get()]
        try:
            entries, truncated = listing(self.folder, self.hidden.get(), pattern, self.directory)
        except OSError as e:
            self.note.configure(text=textsafe.clean(f"cannot open: {e.strerror or e}", 120))
            return
        self.note.configure(text=f"the first {MAX_ENTRIES} entries" if truncated else "")
        for i, (name, is_dir, size, mtime) in enumerate(entries):
            iid = str(i)
            self.names[iid] = (name, is_dir)
            self.tree.insert("", "end", iid=iid, text=textsafe.clean(name, 200), image=self.images["dir" if is_dir else "file"],
                             values=("" if is_dir else human_size(size), time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))))
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
        self.selected()

    def selected(self):
        sel = self.tree.selection()
        name, is_dir = self.names.get(sel[0], (None, False)) if sel else (None, False)
        if not self.directory:
            self.ok.configure(state="normal" if name is not None and not is_dir else "disabled")

    def up(self):
        if self.folder.parent != self.folder:
            child = self.folder.name
            self.go(self.folder.parent)
            for iid, (name, _d) in self.names.items():
                if name == child:
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
                    break

    def activate(self):
        sel = self.tree.selection()
        if not sel:
            return
        name, is_dir = self.names[sel[0]]
        if is_dir:
            self.go(self.folder / name)
        else:
            self.finish(self.folder / name)

    def typed(self):
        path = Path(os.path.expanduser(self.path.get().strip()))
        if not path.is_absolute():
            path = self.folder / path
        if path.is_dir():
            self.go(path)
        elif path.is_file() and not self.directory:
            self.finish(path)
        else:
            self.note.configure(text="no such folder" if self.directory else "no such file or folder")

    def accept(self):
        if self.directory:  # the folder shown; double-click opens a subfolder first
            self.finish(self.folder)
        else:
            self.activate()

    def finish(self, path):
        self.result = str(path)
        _last["dir"] = str(Path(path).parent if not self.directory else path)
        self.top.destroy()


def choose_file(parent, title, patterns=()):
    """A file chosen in the themed chooser, or None. patterns: [(label, glob)] offered before "All files"."""
    return Chooser(parent, title, patterns=patterns).result


def choose_folder(parent, title):
    return Chooser(parent, title, directory=True).result
