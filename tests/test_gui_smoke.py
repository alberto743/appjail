# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Builds the real window under a virtual X server (Xvfb); skipped where tkinter or Xvfb is missing."""

import os
import shutil
import subprocess
import time

import pytest

tk = pytest.importorskip("tkinter")

from appjail import grants
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


def test_add_form_passes_the_limits(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    window.source.set("o/App")
    window.limits["memory_max"].set("2G")
    window.limits["cpu_quota"].set(" 200% ")
    window._add()
    assert seen == [["add", "o/App", "--memory-max", "2G", "--cpu-quota", "200%"]]


def test_the_private_redirect_choice_is_for_urls_only_and_a_search_hit_never_carries_it(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    window.kind.set("url")
    window.source.set("https://x.example/a.AppImage")
    window.private_redirects.set(True)
    assert str(window.private_check.cget("state")) == "normal"
    window._add()
    assert seen[-1] == ["add", "--url", "https://x.example/a.AppImage", "--allow-private-redirects"]
    window.kind.set("github")
    assert str(window.private_check.cget("state")) == "disabled"
    window.source.set("o/App")
    window._add()
    assert "--allow-private-redirects" not in seen[-1]
    window.kind.set("url")
    window.hits = [type("Hit", (), {"source": "github:o/r", "name": "r", "description": "", "note": "", "catalog": "c"})()]
    window.hit_tree.insert("", "end", iid="0", values=("r", "", "github:o/r", "c"))
    window.hit_tree.selection_set("0")
    window._use_hit()
    assert window.private_redirects.get() is False


def test_open_file_asks_whether_the_app_may_change_it(window, monkeypatch):
    launched = []
    monkeypatch.setattr(window, "launch", launched.append)
    monkeypatch.setattr(app.filedialog, "askopenfilename", lambda **kw: "/data/-notes.txt")
    for rw in (False, True):
        monkeypatch.setattr(app.dialogs, "options_dialog", lambda *a, _rw=rw, **kw: {"rw": _rw})
        window._open_file("app")
    assert launched == [["open", "app", "--", "/data/-notes.txt"], ["open", "app", "--rw", "--", "/data/-notes.txt"]]
    monkeypatch.setattr(app.dialogs, "options_dialog", lambda *a, **kw: None)  # cancelled: nothing starts
    window._open_file("app")
    assert len(launched) == 2


def test_the_update_dialog_and_the_catalog_buttons_send_the_new_options(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    monkeypatch.setattr(app.dialogs, "options_dialog", lambda *a, **kw: {
        "prerelease": False, "channel": app.KEEP, "quarantine": "", "file": "", "sha256": "", "verify": False,
        "pattern": "*.AppImage", "private": True})
    window._update_options("app")
    assert seen[-1] == ["update", "app", "--pattern", "*.AppImage", "--allow-private-redirects"]
    window.source_name.set("db")
    window.index_commit.set("b" * 40)
    window.index_private.set(True)
    window._index("update")
    assert seen[-1] == ["index", "update", "db", "--commit", "b" * 40, "--allow-private-redirects"]
    monkeypatch.setattr(app.simpledialog, "askstring", lambda *a, **kw: "https://x.example/c.json")
    window._index_add("--url")
    assert seen[-1] == ["index", "add", "db", "--url", "https://x.example/c.json", "--allow-private-redirects"]


def test_add_form_offers_a_check_box_for_each_opt_in_portal(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    checks = window.editors["portals"].checks
    assert list(checks) == list(grants.PORTAL_OPT_IN) and not any(v.get() for v in checks.values())
    window.source.set("o/App")
    window.flag["portals"].set(True)
    checks["OpenURI"].set(True)
    checks["Camera"].set(True)
    window._add()
    assert seen == [["add", "o/App", "--portal", "OpenURI", "--portal", "Camera", "--allow", "portals"]]
    assert "--yes" not in seen[0]


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


def _ancestors(widget):
    while widget is not None:
        widget = getattr(widget, "master", None)
        if widget is not None:
            yield widget


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
            scrolled = isinstance(widget, dialogs.PortalChecks)  # its list scrolls: the box must fit, not every row in it
            if widget.winfo_class() in ("TButton", "TCheckbutton", "TEntry", "TCombobox") or scrolled:
                if widget.winfo_class() == "TCheckbutton" and any(isinstance(a, dialogs.PortalChecks) for a in _ancestors(widget)):
                    continue
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


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


PERMS_STATE = {"network": True, "audio_mode": "pipewire", "display": "wayland", "display_size": "1280x800", "dirs": ("~/a",),
               "dbus_filter": ("org.a.B",), "dbus_own": (), "portal_interfaces": (), "env": ("A=1", "B=x=y")}


def _open_permissions(window, monkeypatch, act):
    """Run permissions_editor with `act(top, editors, buttons)` standing in for the person at the dialog."""
    def fake_wait(top, focus=None):
        top.update()
        editors = {w.cget("text"): w for w in _walk(top) if isinstance(w, (dialogs.ListEditor, dialogs.PortalChecks))}
        buttons = {w.cget("text"): w for w in _walk(top) if isinstance(w, dialogs.ttk.Button)}
        act(top, editors, buttons)

    monkeypatch.setattr(dialogs, "_wait", fake_wait)
    return dialogs.permissions_editor(window.root, "app", PERMS_STATE)


def test_permissions_editor_returns_the_state_it_was_given_when_nothing_changes(window, monkeypatch):
    got = _open_permissions(window, monkeypatch, lambda top, ed, bt: bt["Review changes…"].invoke())
    assert got["env"] == ("A=1", "B=x=y") and got["dirs"] == ("~/a",) and got["network"] is True
    assert not app.argv.perms_argv("app", PERMS_STATE, got)[2:]


def test_permissions_editor_shows_and_changes_the_limits(window, monkeypatch):
    state = dict(PERMS_STATE, memory_max="2G", cpu_quota="", tasks_max="")

    def act(top, ed, bt):
        box = next(w for w in _walk(top) if isinstance(w, dialogs.ttk.LabelFrame) and w.cget("text") == "Permissions")
        _size, memory, cpu, tasks = [w for w in box.winfo_children() if type(w) is dialogs.ttk.Entry]
        assert (memory.get(), cpu.get(), tasks.get()) == ("2G", "", "")
        memory.delete(0, "end")  # emptied: the limit goes
        cpu.insert(0, "150%")
        bt["Review changes…"].invoke()

    monkeypatch.setattr(dialogs, "_wait", lambda top, focus=None: (top.update(), act(top, {}, {w.cget("text"): w for w in _walk(top) if isinstance(w, dialogs.ttk.Button)})))
    got = dialogs.permissions_editor(window.root, "app", state)
    assert (got["memory_max"], got["cpu_quota"], got["tasks_max"]) == ("", "150%", "")
    assert app.argv.perms_argv("app", state, got) == ["perms", "app", "--memory-max", "infinity", "--cpu-quota", "150%"]


def test_permissions_editor_edits_the_environment_and_the_other_lists(window, monkeypatch):
    def act(top, ed, bt):
        env = ed["Environment"]
        assert env.values(flush=False) == ("A=1", "B=x=y")
        env.box.selection_set(0)
        env.remove()  # A=1 goes
        env.var.set("MYAPP_USE_WAYLAND=1")  # text left in the entry counts
        ed["D-Bus names (talk)"].var.set("org.c.D")
        bt["Review changes…"].invoke()

    got = _open_permissions(window, monkeypatch, act)
    assert got["env"] == ("B=x=y", "MYAPP_USE_WAYLAND=1") and got["dbus_filter"] == ("org.a.B", "org.c.D")
    command = app.argv.perms_argv("app", PERMS_STATE, got)
    assert command[:2] == ["perms", "app"] and "--yes" not in command
    assert command[command.index("--unset-env") + 1] == "A" and "MYAPP_USE_WAYLAND=1" in command


def test_permissions_editor_shows_the_granted_portals_and_builds_the_changes(window, monkeypatch):
    state = dict(PERMS_STATE, portals=True, portal_interfaces=("Camera", "Usb"))

    def act(top, ed, bt):
        checks = ed["Privileged portals"].checks
        assert {n for n, v in checks.items() if v.get()} == {"Camera", "Usb"}
        checks["Camera"].set(False)
        checks["OpenURI"].set(True)
        bt["Review changes…"].invoke()

    monkeypatch.setattr(dialogs, "_wait", lambda top, focus=None: act(top, {w.cget("text"): w for w in _walk(top) if isinstance(
        w, dialogs.PortalChecks)}, {w.cget("text"): w for w in _walk(top) if isinstance(w, dialogs.ttk.Button)}))
    got = dialogs.permissions_editor(window.root, "app", state)
    assert got["portal_interfaces"] == ("OpenURI", "Usb")
    command = app.argv.perms_argv("app", state, got)
    assert command == ["perms", "app", "--rm-portal", "Camera", "--add-portal", "OpenURI"]


def test_permissions_editor_cancel_returns_none_and_every_editor_fits_the_screen(window, monkeypatch):
    seen = {}

    def act(top, ed, bt):
        seen["titles"] = sorted(ed)
        for widget in ed.values():
            assert widget.winfo_ismapped()
            assert widget.winfo_rooty() + widget.winfo_height() <= top.winfo_screenheight()
            assert widget.winfo_rootx() + widget.winfo_width() <= top.winfo_screenwidth()
        for name in ("Review changes…", "Cancel"):
            assert bt[name].winfo_ismapped() and bt[name].winfo_rooty() + bt[name].winfo_height() <= top.winfo_screenheight()
        bt["Cancel"].invoke()

    assert _open_permissions(window, monkeypatch, act) is None
    assert seen["titles"] == ["D-Bus names (own)", "D-Bus names (talk)", "Directories", "Environment", "Privileged portals", "URL schemes"]


def test_search_hit_goes_to_the_add_tab(window, monkeypatch):
    hits = [app.apps.index.Hit("good", "an app", "github:o/good", "", "db"),
            app.apps.index.Hit("other", "elsewhere", "gitlab:gitlab.com/g/p", "", "db")]
    monkeypatch.setattr(app.apps, "search_hits", lambda *_a: (hits, 2, ["db"]))
    window.keywords.set("app")
    window._search()
    assert len(window.hit_tree.get_children()) == 2
    window.hit_tree.selection_set("1")
    window.root.update()
    assert str(window.use_hit["state"]) == "disabled"
    window.hit_tree.selection_set("0")
    window.root.update()
    assert str(window.use_hit["state"]) == "normal"
    window._use_hit()
    assert (window.kind.get(), window.source.get()) == ("github", "o/good")
    assert window.notebook.select() == str(window.add_tab)
