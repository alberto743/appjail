# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import pytest

from appjail import cli
from appjail.gui import argv

STATE = {"network": False, "network_host": False, "audio": True, "gpu": True, "portals": False, "userns": False,
         "display": "wayland", "dirs": ("~/a", "~/b:rw"), "dbus_filter": (), "dbus_own": (), "portal_interfaces": ()}


def parses(command):
    return cli.build_parser().parse_args(command)


def test_add_github_defaults():
    command = argv.add_argv({"kind": "github", "source": " o/App ", "allow": ["audio", "gpu"]})
    assert command == ["add", "o/App"]
    parses(command)


def test_add_all_options_parse():
    form = {"kind": "github", "source": "o/App", "tag": "v1", "prerelease": True, "name": "app", "allow": ["audio", "network"],
            "display": "xwayland", "dirs": ["~/x:rw"], "dbus": ["org.a.B"], "desktop": True, "mime_all": True}
    command = argv.add_argv(form)
    assert "--no-gpu" in command and "--no-audio" not in command
    assert command[command.index("--allow") + 1] == "network"
    args = parses(command)
    assert (args.tag, args.display, args.dir, args.desktop, args.mime_all) == ("v1", "xwayland", ["~/x:rw"], True, True)


@pytest.mark.parametrize("kind,flag", [("url", "--url"), ("file", "--file")])
def test_add_image_sources(kind, flag):
    command = argv.add_argv({"kind": kind, "source": "X", "sha256": "ab", "max_size": "5", "tag": "ignored", "allow": ["audio", "gpu"]})
    assert command[:3] == ["add", flag, "X"]
    assert "--tag" not in command and ("--max-size" in command) == (kind == "url")
    parses(command)


def test_perms_no_change_is_bare():
    assert argv.perms_argv("app", STATE, dict(STATE)) == ["perms", "app"]


def test_perms_changes_parse_and_never_say_yes():
    new = dict(STATE, network=True, audio=False, display="xwayland", dirs=("~/b:rw", "~/c"), dbus_filter=("org.a.B",))
    command = argv.perms_argv("app", STATE, new)
    assert "--yes" not in command
    args = parses(command)
    assert (args.allow, args.deny, args.display) == (["network"], ["audio"], "xwayland")
    assert (args.rm_dir, args.add_dir, args.add_dbus) == (["~/a"], ["~/c"], ["org.a.B"])


def test_perms_dir_mode_change_removes_then_adds():
    args = parses(argv.perms_argv("app", STATE, dict(STATE, dirs=("~/a:rw", "~/b:rw"))))
    assert (args.rm_dir, args.add_dir) == (["~/a"], ["~/a:rw"])


def test_search_and_update():
    assert argv.search_argv("video  player", 5) == ["search", "video", "player", "--limit", "5"]
    assert argv.search_argv("x", 5, True) == ["search", "x", "--all"]
    assert argv.update_argv("app", True, "pinned") == ["update", "app", "--prerelease", "--channel", "pinned"]


def test_update_options_parse():
    command = argv.update_argv("app", True, "pinned", " 3 ", "/x/y.AppImage", " ab ", True)
    args = parses(command)
    assert (args.quarantine, args.file, args.sha256, args.verify, args.channel) == (3, "/x/y.AppImage", "ab", True, "pinned")
    assert argv.update_argv("app", quarantine="") == ["update", "app"]


def test_run_desktop_portals_history_parse():
    assert parses(argv.run_argv("app", ["~/d:rw"], ["/f:rw"])).dir == ["~/d:rw"]
    assert parses(argv.run_argv("app")).file == []
    args = parses(argv.desktop_argv("app", ["text/plain"], False, True))
    assert (args.mime, args.rw, args.remove) == (["text/plain"], True, False)
    assert parses(argv.desktop_argv(prune=True)).prune
    assert parses(argv.desktop_argv("app", remove=True)).remove
    assert parses(argv.portals_argv("app", ["1", "2"])).revoke == ["1", "2"]
    assert parses(argv.portals_argv("app", (), True)).revoke_all
    assert argv.history_argv() == ["history"]
    assert parses(argv.history_argv("app", 5)).limit == 5


def test_add_followup_offers_the_declared_types():
    assert argv.defers_menu_entry({"desktop": True, "mime": []})
    assert not argv.defers_menu_entry({"desktop": True, "mime": ["text/plain"]})
    assert not argv.defers_menu_entry({"desktop": True, "mime_all": True})
    assert not argv.defers_menu_entry({"desktop": False})
    assert argv.add_followup(["a"], ["a", "b"]) == ["desktop", "b"]
    assert argv.add_followup(["a"], ["a"]) is None
    assert argv.add_followup([], ["a", "b"]) is None
    assert argv.add_followup(["a"], ["a", "b"], rw=True) == ["desktop", "b", "--rw"]
    args = parses(argv.add_argv({"source": "o/App", "desktop": True, "mime": ["text/plain"], "rw": True}))
    assert args.rw and args.mime == ["text/plain"]
