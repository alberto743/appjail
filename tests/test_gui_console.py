# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import queue
import threading

import pytest

from appjail.console import Abort
from appjail.gui import apps, worker
from appjail.gui.console import GuiConsole


def answer_with(events, *values):
    """Play the Tk thread: answer each ("ask", request) with the next value."""
    seen = []

    def loop():
        for v in values:
            kind, req = events.get(timeout=5)
            assert kind == "ask"
            seen.append(req)
            req.reply(v)
    t = threading.Thread(target=loop)
    t.start()
    return t, seen


def test_out_is_cleaned_and_queued():
    events = queue.Queue()
    c = GuiConsole(events)
    c.out("hi \x1b[31mred\x1b[0m")
    c.warn("careful")
    assert [events.get_nowait() for _ in range(2)] == [("out", "hi red"), ("out", "WARNING: careful")]


def test_confirm_default_no_and_review():
    events = queue.Queue()
    c = GuiConsole(events)
    c.out("before: a")
    events.get_nowait()
    t, seen = answer_with(events, False)
    assert c.confirm("Save?") is False
    t.join()
    assert seen[0].default is False and seen[0].review == ("before: a",)


def test_every_prompt_carries_the_review():
    events = queue.Queue()
    c = GuiConsole(events)
    c.out("1. text/plain")
    events.get_nowait()
    t, seen = answer_with(events, "text/plain", 0)
    c.ask("Types?")
    c.choose("pick", ["a"])
    t.join()
    assert all(r.review == ("1. text/plain",) for r in seen)


def test_cancelled_dialog_aborts():
    events = queue.Queue()
    c = GuiConsole(events)
    t, _ = answer_with(events, None)
    with pytest.raises(Abort):
        c.confirm("Save?")
    t.join()


def test_choose_and_ask():
    events = queue.Queue()
    c = GuiConsole(events)
    t, seen = answer_with(events, 1, "  text ")
    assert c.choose("pick", ["a", "b\x1b[0m"]) == 1
    assert c.ask("name?") == "text"
    t.join()
    assert seen[0].options == ("a", "b")


def test_run_command_streams_output_and_done(h):
    events = queue.Queue()
    worker.run_command(["list"], events).join(timeout=10)
    items = []
    while not events.empty():
        items.append(events.get_nowait())
    assert items[0] == ("out", "No apps installed.")
    assert items[-1] == ("done", 0)


def test_run_command_invalid_arguments_do_not_kill_the_thread(h, capsys):
    events = queue.Queue()
    worker.run_command(["no-such-command"], events).join(timeout=10)
    items = [events.get_nowait() for _ in range(events.qsize())]
    assert items[-1] == ("done", 2)


def test_prompting_command_through_the_bridge(h):
    h.add()
    events = queue.Queue()
    t = worker.run_command(["remove", "app"], events)
    kind, req = events.get(timeout=10)  # the first "out" lines come first
    while kind == "out":
        kind, req = events.get(timeout=10)
    assert kind == "ask" and req.kind == "confirm" and req.default is False
    req.reply(False)
    t.join(timeout=10)
    assert events.get(timeout=5)[0] == "out"  # "cancelled"
    assert apps.rows()[0][0] == "app"


def test_rows_lists_installed_apps(h):
    h.add()
    (row,) = apps.rows()
    assert row[0] == "app" and "display=wayland" in row[4] and row[5] == ""
    assert apps.load_permissions("app")["display"] == "wayland"


def test_rows_marks_unreadable_manifest(h):
    from appjail import store
    p = store.manifest_path("bad")
    p.parent.mkdir(parents=True)
    p.write_text("not toml [")
    assert "unreadable" in apps.rows()[0][5]

