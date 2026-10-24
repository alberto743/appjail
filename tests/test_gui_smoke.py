# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Builds the real window under a virtual X server (Xvfb); skipped where tkinter or Xvfb is missing."""

import os
import shutil
import subprocess
import time

import pytest

tk = pytest.importorskip("tkinter")

from appjail.gui import app, dialogs
from appjail.gui.console import Request


@pytest.fixture(scope="module")
def display():
    """One X server for the module: stopping and restarting one on the same number races with its lock file."""
    if not shutil.which("Xvfb"):
        pytest.skip("Xvfb is not installed")
    num = f":{90 + os.getpid() % 500}"
    proc = subprocess.Popen(["Xvfb", num, "-screen", "0", "1024x768x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    old = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = num
    yield num
    proc.terminate()
    proc.wait()
    if old is None:
        os.environ.pop("DISPLAY", None)
    else:
        os.environ["DISPLAY"] = old


@pytest.fixture
def window(display, h):
    root = tk.Tk()
    yield app.App(root)
    root.destroy()


def pump(window, until, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        window.root.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError("timeout")


def test_list_runs_and_fills_the_log(window):
    window.run(["list"])
    pump(window, lambda: not window.busy)
    assert "No apps installed." in window.log.get("1.0", "end")


def test_apps_tab_shows_installed_app(display, h):
    h.add()
    root = tk.Tk()
    try:
        w = app.App(root)
        assert w.tree.get_children() == ("app",)
    finally:
        root.destroy()


def test_add_form_builds_the_expected_command(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    window.source.set("o/App")
    window.flag["network"].set(True)
    window.editors["dirs"].var.set("~/x:rw")
    window.editors["dirs"].add()
    window._add()
    assert seen == [["add", "o/App", "--dir", "~/x:rw", "--allow", "network"]]


def test_confirm_dialog_answer_and_default(window):
    req = Request("confirm", "Save?", review=("before", "after"))
    window.root.after(200, lambda: next(w for w in window.root.winfo_children() if isinstance(w, tk.Toplevel)).destroy())
    dialogs.answer(window.root, req)
    assert req.wait() is None  # closing the dialog cancels; it never means yes


def test_selection_survives_refresh(display, h):
    h.add()
    root = tk.Tk()
    try:
        w = app.App(root)
        w.tree.selection_set("app")
        w.refresh()
        assert w.tree.selection() == ("app",)
    finally:
        root.destroy()


def test_add_form_greys_out_options_that_do_not_apply(window):
    def state(key):
        return str(window.entries[key].cget("state"))

    assert (state("tag"), state("sha256"), state("max_size")) == ("normal", "disabled", "disabled")
    window.kind.set("url")
    assert (state("tag"), state("sha256"), state("max_size")) == ("disabled", "normal", "normal")
    window.kind.set("file")
    assert (state("tag"), state("sha256"), state("max_size")) == ("disabled", "normal", "disabled")


def test_text_left_in_a_list_entry_counts(window):
    window.editors["dirs"].var.set("~/x")
    assert window.editors["dirs"].values() == ("~/x",)


def test_busy_click_is_reported(window):
    window.busy = True
    window.run(["list"])
    assert "busy" in window.status.get()


def test_the_gui_never_answers_for_the_user():
    import pathlib

    import appjail.gui
    for path in pathlib.Path(appjail.gui.__file__).parent.glob("*.py"):
        assert "--yes" not in path.read_text(encoding="utf-8"), path.name


def test_table_columns_fit_long_real_world_cells(display, h):
    h.add(extra=["--name", "a-rather-long-application-name"])
    root = tk.Tk()
    try:
        w = app.App(root)
        w.tree.set("a-rather-long-application-name", "version", "3.5.3@2026-10-02_1790947336")
        w._fit_columns()
        from tkinter import font as tkfont
        font = tkfont.nametofont("TkDefaultFont")
        for column in ("name", "version", "source", "permissions"):
            cell = w.tree.set("a-rather-long-application-name", column)
            assert int(w.tree.column(column, "width")) >= font.measure(cell), column
        assert str(w.tree.column("note", "stretch")) in ("1", "True")
    finally:
        root.destroy()


def test_list_editors_scroll_long_and_many_entries(window):
    editor = window.editors["dirs"]
    for i in range(8):
        editor.var.set(f"~/Documents/a-very-long-directory-name-number-{i}-for-scrolling")
        editor.add()
    window.root.update()
    assert len(editor.values()) == 8
    assert editor.box.yview()[1] < 1.0  # more entries than rows: the vertical scrollbar has something to scroll
    assert editor.box.xview()[1] < 1.0  # an entry wider than the box: so does the horizontal one


def test_detail_line_shows_the_whole_list_entry(display, h):
    h.add(extra=["--allow", "network"])
    root = tk.Tk()
    try:
        w = app.App(root)
        w.tree.selection_set("app")
        root.update()
        assert "network" in w.detail.get("1.0", "end") and "github:o/App" in w.detail.get("1.0", "end")
    finally:
        root.destroy()


def test_table_rows_are_tall_enough_for_the_font(display, h):
    """ttk keeps a fixed row height; on a larger font (HiDPI) the rows would overlap and cut the text."""
    h.add()
    root = tk.Tk()
    scaling = root.tk.call("tk", "scaling")
    try:
        root.tk.call("tk", "scaling", 3.0)
        from tkinter import font as tkfont
        from tkinter import ttk
        tkfont.nametofont("TkDefaultFont").configure(size=18)
        app.App(root)
        rowheight = int(ttk.Style().lookup("Treeview", "rowheight"))
        assert rowheight >= tkfont.nametofont("TkDefaultFont").metrics("linespace")
    finally:
        root.tk.call("tk", "scaling", scaling)  # the setting belongs to the display and would leak into later tests
        root.destroy()


def test_every_button_is_visible_at_the_starting_size(window):
    """The window starts at the size its layout asks for: nothing needs enlarging to be reached."""
    root = window.root
    root.update()
    for index in range(window.notebook.index("end")):
        window.notebook.select(index)
        root.update()
        tab = window.notebook.nametowidget(window.notebook.select())
        stack = [tab]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if widget.winfo_class() in ("TButton", "TCheckbutton", "TEntry", "TCombobox"):
                assert widget.winfo_ismapped(), (index, widget)
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height(), (index, widget)
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width(), (index, widget)
    # it starts at the requested size, or at what the screen allows
    assert root.winfo_width() >= min(root.winfo_reqwidth(), root.winfo_screenwidth() - 40)
    assert root.winfo_height() >= min(root.winfo_reqheight(), root.winfo_screenheight() - 80)


def test_choice_list_returns_the_selected_types_and_keeps_the_form_open_on_a_problem(window, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs.messagebox, "showerror", lambda *a, **k: shown.append(a[1]))
    calls = []

    def fake_wait(top, focus=None):
        box = next(w for w in _walk(top) if isinstance(w, dialogs.ChoiceList))
        assert box.values() == ("image/png",)  # the registered ones start selected
        box.box.selection_clear(0, "end")
        ok = next(w for w in _walk(top) if isinstance(w, dialogs.ttk.Button) and w.cget("text") == "Go")
        ok.invoke()  # nothing selected: refused, the form stays
        calls.append(top.winfo_exists())
        box.box.selection_set(1)
        ok.invoke()

    def _walk(w):
        yield w
        for c in w.winfo_children():
            yield from _walk(c)

    monkeypatch.setattr(dialogs, "_wait", fake_wait)
    got = dialogs.options_dialog(
        window.root, "t", (("choice", "mime", "Types", {"items": ["image/png", "text/plain"], "selected": ["image/png"]}),),
        ok="Go", validate=lambda v: None if v["mime"] else "select one")
    assert shown == ["select one"] and calls == [1] and got == {"mime": ("text/plain",)}
