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
    monkeypatch.setattr(app.files, "choose_file", lambda *a, **kw: "/data/-notes.txt")
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
    monkeypatch.setattr(app.dialogs, "ask_text", lambda *a, **kw: "https://x.example/c.json")
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


def test_the_list_fits_a_long_name_and_the_detail_pane_shows_the_rest(display, h):
    h.add(extra=["--name", "a-rather-long-application-name"])
    root = tk.Tk()
    try:
        w = app.App(root)
        from tkinter import font as tkfont
        font = tkfont.nametofont("TkDefaultFont")
        assert int(w.tree.column("#0", "width")) >= font.measure("a-rather-long-application-name") + w.px(app.LIST_ICON)
        w.tree.selection_set("a-rather-long-application-name")
        root.update()
        assert w.card_title.cget("text") == "a-rather-long-application-name"
        assert "github:o/App" in w.card_subtitle.cget("text")  # the version and the source, whole, wrapping when long
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
        assert "network" in w.detail.get("1.0", "end") and "display: wayland" in w.detail.get("1.0", "end")
        chips = [c.cget("text") for c in w.detail.winfo_children() if c.winfo_class() == "TLabel"]
        assert chips == ["network"]
        assert all(str(b.cget("state")) == "normal" for b in w.app_buttons)
        w.tree.selection_set(())
        root.update()
        assert all(str(b.cget("state")) == "disabled" for b in w.app_buttons)  # nothing selected: nothing to act on
    finally:
        root.destroy()


def test_an_empty_list_offers_the_ways_to_add_an_app(window):
    assert window.card_title.cget("text") == "No apps yet"
    buttons = {b.cget("text"): b for b in window.card_body.winfo_children()[0].winfo_children()}
    buttons["Search the catalogs"].invoke()
    assert window.page.get() == "search"
    buttons["Add an app"].invoke()
    assert window.page.get() == "add"


def test_an_installed_icon_replaces_the_stand_in(display, h, monkeypatch, tmp_path):
    from appjail.gui import icons
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    h.add()
    root = tk.Tk()
    try:
        w = app.App(root)
        stand_in = w.icon("app", app.LIST_ICON)
        target = tmp_path / "share/icons/hicolor/48x48/apps/appjail-app.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(icons.Canvas(48, 48).paint(icons.circle(24, 24, 20), "#ff0000").png())
        w.refresh()
        pump(w, lambda: w.images.get(f"app:app:{app.LIST_ICON}") is not None)
        assert str(w.tree.item("app", "image")[0]) == str(w.images[f"app:app:{app.LIST_ICON}"]) != str(stand_in)
        target.write_bytes(b"not a png")  # changed and unusable: back to the stand-in, never Tk decoding the file
        w.refresh()
        assert w.images.get(f"app:app:{app.LIST_ICON}") is None
        assert str(w.tree.item("app", "image")[0]) == str(stand_in)
    finally:
        root.destroy()


def test_the_dark_switch_recolours_the_window(window):
    light = window.log.cget("background")
    window.dark.set(True)
    window.toggle_dark()
    assert window.theme.dark and window.log.cget("background") != light
    assert window.log.cget("background") == app.theme.DARK["log"]
    window.dark.set(False)
    window.toggle_dark()
    assert window.log.cget("background") == light


def test_output_is_coloured_by_kind_and_the_pane_opens_for_a_command(window, monkeypatch):
    monkeypatch.setattr(app.worker, "run_command", lambda *a: None)
    assert not window.log_shown
    window.run(["version"])
    assert window.log_shown and window.output_button.cget("text") == "Hide output"
    for line in ("error: bad", "! warning: careful", "note: fyi", "-- exit status 0 --", "plain"):
        window.say(line)
    tags = {window.log.get(f"{i}.0", f"{i}.end"): window.log.tag_names(f"{i}.0") for i in range(1, 7)}
    assert tags["$ appjail version"] == ("cmd",) and tags["error: bad"] == ("err",) and tags["! warning: careful"] == ("warn",)
    assert tags["note: fyi"] == ("note",) and tags["-- exit status 0 --"] == ("ok",) and tags["plain"] == ()
    window.toggle_log()
    assert not window.log_shown


def test_the_access_segments_count_their_entries(window):
    window.editors["dirs"].var.set("~/x")
    window.editors["dirs"].add()
    assert window.segments["dirs"].cget("text") == "Directories  1"
    window.access.set("portals")
    window._show_access()
    window.root.update()
    assert window.editors["portals"].winfo_ismapped() and not window.editors["dirs"].winfo_ismapped()
    window.editors["dirs"].box.selection_set(0)
    window.editors["dirs"].remove()
    assert window.segments["dirs"].cget("text") == "Directories"


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


def _controls(widget):
    """The buttons, boxes and fields under `widget`, with each portal list as one (its rows scroll inside it)."""
    stack = [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, dialogs.PortalChecks):
            yield w
            continue
        stack.extend(w.winfo_children())
        if w.winfo_class() in ("TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox"):
            yield w


def _assert_inside(widget, box, where):
    assert widget.winfo_ismapped(), (where, widget)
    assert widget.winfo_rooty() >= box.winfo_rooty(), (where, widget)
    assert widget.winfo_rooty() + widget.winfo_height() <= box.winfo_rooty() + box.winfo_height(), (where, widget)
    assert widget.winfo_rootx() + widget.winfo_width() <= box.winfo_rootx() + box.winfo_width(), (where, widget)


@pytest.fixture(scope="module")
def servers():
    """X servers by screen size, kept until the module ends: Tk keeps its connection to a display after its window is
    destroyed, and a server stopped under it ends the whole process."""
    if not shutil.which("Xvfb"):
        pytest.skip("Xvfb is not installed")
    running = {}

    def start(size):
        if size not in running:
            num = f":{600 + os.getpid() % 300 + len(running) * 300}"
            running[size] = (num, subprocess.Popen(["Xvfb", num, "-screen", "0", f"{size}x24"], stdout=subprocess.DEVNULL,
                                                   stderr=subprocess.DEVNULL))
            time.sleep(1)
        return running[size][0]
    yield start
    for _num, proc in running.values():
        proc.terminate()
        proc.wait()


@pytest.fixture(params=["1024x768", "800x600"])
def screen(request, servers, monkeypatch):
    """A display at each supported smallest size (800x600 is the smallest the window is laid out for)."""
    monkeypatch.setenv("DISPLAY", servers(request.param))
    return request.param


@pytest.mark.parametrize("dark", [False, True])
def test_every_control_is_reachable_at_the_starting_size(screen, h, dark):
    """The window starts at the size its layout asks for, or what the screen allows: every control is in view, except
    in the Add form and the app's detail pane, which scroll when the screen is too small and bring each control into
    view. Nothing is past the right edge: rows of buttons wrap."""
    h.add()
    root = tk.Tk()
    try:
        window = app.App(root, dark=dark)
        root.update()
        for key in window.pages:
            window.show(key)
            window.catalogs.open()  # the Catalogs card opens on request: check what it holds
            root.update()
            root.update()
            scrolls = {"add": [window.add_scroll], "apps": [window.card_scroll]}.get(key, [])
            segments = list(window.segments) if key == "add" else [None]
            for segment in segments:  # the Access card shows one list at a time
                if segment:
                    window.access.set(segment)
                    window._show_access()
                    root.update()
                hidden = [str(e) for k, e in getattr(window, "editors", {}).items() if key == "add" and k != segment]
                for widget in _controls(window.pages[key]):
                    if any(str(widget).startswith(h) for h in hidden):
                        continue  # another segment's list: checked when its segment is shown
                    for scroll in scrolls:
                        if str(widget).startswith(str(scroll.body)):
                            scroll.see(widget)
                            root.update()
                            _assert_inside(widget, scroll.canvas, (screen, key, segment))
                    _assert_inside(widget, root, (screen, key, segment))
        assert root.winfo_width() >= min(root.winfo_reqwidth(), root.winfo_screenwidth() - 40)
        assert root.winfo_height() >= min(root.winfo_reqheight(), root.winfo_screenheight() - 80)
    finally:
        root.destroy()


def test_on_a_tall_screen_the_add_form_does_not_scroll(window):
    """The form asks for its whole height: where the screen has room, nothing hides below the fold."""
    window.show("add")
    window.root.update()
    assert int(window.add_scroll.canvas.cget("height")) == window.add_scroll.body.winfo_reqheight()
    window.root.geometry(f"{window.root.winfo_width()}x{window.root.winfo_height() + 600}")  # a window with room to spare
    window.root.update()
    assert window.add_scroll.canvas.yview() == (0.0, 1.0)


def test_choice_list_returns_the_selected_types_and_keeps_the_form_open_on_a_problem(window, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs, "notice", lambda parent, text, **k: shown.append(text))
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
        editors = {w.title: w for w in _walk(top) if isinstance(w, (dialogs.ListEditor, dialogs.PortalChecks))}
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
        _size, memory, cpu, tasks = [w for w in _walk(box) if type(w) is dialogs.ttk.Entry]
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

    monkeypatch.setattr(dialogs, "_wait", lambda top, focus=None: act(top, {w.title: w for w in _walk(top) if isinstance(
        w, dialogs.PortalChecks)}, {w.cget("text"): w for w in _walk(top) if isinstance(w, dialogs.ttk.Button)}))
    got = dialogs.permissions_editor(window.root, "app", state)
    assert got["portal_interfaces"] == ("OpenURI", "Usb")
    command = app.argv.perms_argv("app", state, got)
    assert command == ["perms", "app", "--rm-portal", "Camera", "--add-portal", "OpenURI"]


def test_permissions_editor_cancel_returns_none_and_every_editor_fits_the_screen(window, monkeypatch):
    seen = {}

    def act(top, ed, bt):
        seen["titles"] = sorted(ed)
        lists = next(w for w in _walk(top) if isinstance(w, dialogs.Segmented))
        for key, widget in lists.editors.items():  # one list at a time, each behind its segment
            lists.current.set(key)
            lists.show()
            top.update()
            assert widget.winfo_ismapped()
            assert widget.winfo_rooty() + widget.winfo_height() <= top.winfo_screenheight()
            assert widget.winfo_rootx() + widget.winfo_width() <= top.winfo_screenwidth()
        # compact enough for a 1024x768 screen with the desktop's panels: well under its height
        assert top.winfo_reqwidth() <= 760 and top.winfo_reqheight() <= 600, (top.winfo_reqwidth(), top.winfo_reqheight())
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
    pump(window, lambda: len(window.hit_tree.get_children()) == 2)
    assert len(window.hit_tree.get_children()) == 2
    window.hit_tree.selection_set("1")
    window.root.update()
    assert str(window.use_hit["state"]) == "disabled"
    window.hit_tree.selection_set("0")
    window.root.update()
    assert str(window.use_hit["state"]) == "normal"
    window._use_hit()
    assert (window.kind.get(), window.source.get()) == ("github", "o/good")
    assert window.page.get() == "add" and window.add_page.winfo_manager() == "grid"


def test_the_filter_narrows_the_list_and_says_when_nothing_matches(display, h):
    h.add(extra=["--name", "lagrange"], source="skyjake/lagrange")
    h.add(extra=["--name", "htop"], source="pkgforge-dev/htop-AppImage")
    root = tk.Tk()
    try:
        w = app.App(root)
        assert w.tree.get_children() == ("htop", "lagrange")
        w.filter.set("LAG")
        assert w.tree.get_children() == ("lagrange",) and w.tree.selection() == ("lagrange",)
        w.filter.set("GITHUB:O/")  # the source counts too (the test harness installs both from o/App)
        assert w.tree.get_children() == ("htop", "lagrange")
        w.filter.set("nothing-like-this")
        root.update()
        assert w.tree.get_children() == () and w.no_match.winfo_ismapped()
        assert w.card_title.cget("text") == "Select an app"  # apps exist: not the empty state
        w.filter.set("")
        root.update()
        assert len(w.tree.get_children()) == 2 and not w.no_match.winfo_ismapped()
        assert w.filter_entry.hint.winfo_ismapped()
    finally:
        root.destroy()


def test_an_older_search_never_replaces_a_newer_one(window, monkeypatch):
    import threading
    release = threading.Event()
    hit = app.apps.index.Hit

    def slow(words, limit, show_all):
        if words == "first":
            release.wait(5)
        return [hit(words, "", "github:o/" + words, "", "db")], 1, ["db"]
    monkeypatch.setattr(app.apps, "search_hits", slow)
    window.keywords.set("first")
    window._search()
    window.keywords.set("second")
    window._search()
    pump(window, lambda: window.hit_tree.get_children() == ("0",))
    release.set()
    for _ in range(20):
        window.root.update()
        time.sleep(0.02)
    assert [h.name for h in window.hits] == ["second"]


def test_a_search_problem_is_reported_not_raised(window, monkeypatch):
    def missing(*a):
        raise app.IndexProblem("no local index; run `appjail index update` first")
    monkeypatch.setattr(app.apps, "search_hits", missing)
    window.keywords.set("x")
    window._search()
    pump(window, lambda: "no local index" in window.status.get())
    assert "error: no local index" in window.log.get("1.0", "end")


def test_the_portals_dialog_waits_for_the_bus_without_freezing_the_window(window, monkeypatch):
    import threading
    release = threading.Event()
    monkeypatch.setattr(app.apps, "portal_grants", lambda name: (release.wait(5), (["Portal interfaces: none"], []))[1])
    shown, seen = [], []
    monkeypatch.setattr(app.dialogs, "options_dialog", lambda *a, **k: shown.append(a[1]) or {"all": True})
    monkeypatch.setattr(window, "run", lambda command, label=None: seen.append(command))
    window._portals("app")
    window._portals("app")  # a second click while the first waits does nothing
    window.root.update()
    assert window.status.get() == "reading the portal grants…" and shown == []
    release.set()
    pump(window, lambda: shown)
    assert shown == ["Portal grants of app"] and seen == [app.argv.portals_argv("app", [], True)]


def test_a_late_dark_answer_is_followed_once_the_window_is_up(display, h, monkeypatch):
    import threading
    release = threading.Event()
    monkeypatch.setattr(app, "DARK_WAIT", 0.01)
    monkeypatch.setattr(app.theme, "prefers_dark", lambda: release.wait(5))
    root = tk.Tk()
    try:
        w = app.App(root)
        assert not w.theme.dark  # did not wait for the desktop
        release.set()
        pump(w, lambda: w.theme.dark)
        assert w.dark.get()
    finally:
        root.destroy()


def test_the_themed_notice_and_text_prompt(window, monkeypatch):
    def press(name):
        def fake_wait(top, focus=None):
            top.update()
            buttons = {b.cget("text"): b for b in _walk(top) if isinstance(b, dialogs.ttk.Button)}
            entries = [e for e in _walk(top) if isinstance(e, dialogs.ttk.Entry)]
            if entries:
                entries[0].insert(0, "https://x.example/c.json")
            labels = [lab.cget("text") for lab in _walk(top) if isinstance(lab, dialogs.ttk.Label)]
            seen.append(labels)
            buttons[name].invoke()
        return fake_wait
    seen = []
    monkeypatch.setattr(dialogs, "_wait", press("OK"))
    dialogs.notice(window.root, "bad thing", error=True)
    assert seen[-1][:2] == ["Something went wrong", "bad thing"]
    monkeypatch.setattr(dialogs, "_wait", press("Add"))
    assert dialogs.ask_text(window.root, "t", "URL:", ok="Add") == "https://x.example/c.json"
    monkeypatch.setattr(dialogs, "_wait", press("Cancel"))
    assert dialogs.ask_text(window.root, "t", "URL:") is None


def test_the_chooser_lists_folders_first_filters_and_returns_the_real_path(window, monkeypatch, tmp_path):
    from appjail.gui import files
    (tmp_path / "Sub").mkdir()
    (tmp_path / "b.AppImage").write_bytes(b"x")
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / ".hidden.AppImage").write_bytes(b"x")
    (tmp_path / "evil\x1b[31m.AppImage").write_bytes(b"x")
    names = []

    def act(top, focus=None):
        chooser = next(c for c in _choosers)
        top.update()
        names.append([chooser.tree.item(i, "text") for i in chooser.tree.get_children()])
        chooser.pattern.set("All files")
        chooser.refresh()
        names.append([chooser.tree.item(i, "text") for i in chooser.tree.get_children()])
        assert str(chooser.ok.cget("state")) == "disabled"  # a folder is selected first: nothing to open
        iid = next(i for i, (n, _d) in chooser.names.items() if n.startswith("evil"))
        chooser.tree.selection_set(iid)
        chooser.activate()

    _choosers = []
    real_init = files.Chooser.__init__

    def init(self, *a, **k):
        _choosers.append(self)
        real_init(self, *a, **k)
    monkeypatch.setattr(files.Chooser, "__init__", init)
    monkeypatch.setattr(dialogs, "_wait", act)
    got = files.Chooser(window.root, "Pick", patterns=[("AppImages", "*.appimage")], start=tmp_path).result
    from appjail import textsafe
    assert names[0] == ["Sub", "b.AppImage", textsafe.clean("evil\x1b[31m.AppImage", 200)]
    assert "\x1b" not in "".join(names[0] + names[1]) and "a.txt" in names[1] and ".hidden.AppImage" not in names[1]
    assert got == str(tmp_path / "evil\x1b[31m.AppImage")  # the name shown is cleaned, the path is the real one


def test_a_flow_row_wraps_instead_of_cutting_off(window):
    frame = tk.Toplevel(window.root)
    flow = dialogs.Flow(frame)
    flow.pack(fill="x")
    buttons = [flow.add(dialogs.ttk.Button(flow, text=f"A rather long button {i}")) for i in range(4)]
    frame.geometry("900x200")
    frame.update()
    assert len({b.winfo_y() for b in buttons}) == 1  # room for one row
    frame.geometry("300x200")
    frame.update()
    frame.update()
    assert len({b.winfo_y() for b in buttons}) == 4  # one per row, none past the right edge
    assert all(b.winfo_x() + b.winfo_width() <= flow.winfo_width() for b in buttons)
    assert flow.winfo_height() >= sum(b.winfo_height() for b in buttons)
    frame.destroy()


def test_the_catalogs_card_is_closed_until_opened(window):
    window.show("search")
    window.root.update()
    assert not window.catalogs.body.winfo_ismapped()
    window.catalogs.header.invoke()
    window.root.update()
    assert window.catalogs.body.winfo_ismapped() and window.catalogs.header.cget("text").startswith("▾")


def test_a_failing_step_never_stops_the_window_polling(window):
    def broken(_result, _error):
        raise RuntimeError("a bug in a callback")
    later = []
    window.off_thread(lambda: 1, broken)
    with pytest.raises(RuntimeError):  # Tk reports it; the next round is scheduled all the same
        for _ in range(100):
            window._poll()
            time.sleep(0.01)
    window.off_thread(lambda: 2, lambda result, _error: later.append(result))
    pump(window, lambda: later == [2])


def test_a_bus_failure_is_reported_not_raised(window, monkeypatch):
    def unreachable(name):
        from appjail.errors import RunError
        raise RunError("the session bus did not answer")
    monkeypatch.setattr(app.apps, "portal_grants", unreachable)
    window._portals("app")
    pump(window, lambda: not window.portals_pending)
    assert "error: reading the portal grants: the session bus did not answer" in window.log.get("1.0", "end")
    assert window.status.get() == "reading the portal grants failed"
