# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import pytest

from appjail import cli, portal, store
from appjail.cli import Abort
from .helpers import Script, installed

APP = "app.appjail.app"


class FakeStore:
    """Answers like `dbus-send --print-reply` for the PermissionStore's documents table."""

    def __init__(self, docs):
        self.docs, self.calls = {d: dict(a) for d, a in docs.items()}, []

    def __call__(self, host_env, dest, path, member, *args, timeout=10.0):
        method = member.rsplit(".", 1)[1]
        self.calls.append((method, *args))
        if method == "List":
            ids = "".join(f'      string "{d}"\n' for d in self.docs)
            return f"method return time=1 sender=:1.1 -> destination=:1.2 serial=3 reply_serial=2\n   array [\n{ids}   ]\n"
        if method == "Lookup":
            doc = args[1].removeprefix("string:")
            entries = "".join(f'      dict entry(\n         string "{a}"\n         array [\n'
                              + "".join(f'            string "{p}"\n' for p in perms) + "         ]\n      )\n"
                              for a, perms in self.docs.get(doc, {}).items())
            return f"method return\n   array [\n{entries}   ]\n   variant       byte 0\n"
        if method == "RevokePermissions":
            assert args[2] == "array:string:read,write,grant-permissions,delete"
            self.docs[args[0].removeprefix("string:")].pop(args[1].removeprefix("string:"))
            return "method return\n"
        raise AssertionError(method)


@pytest.fixture
def docs(monkeypatch):
    fake = FakeStore({"aaa": {APP: ["read"], "app.appjail.other": ["read"]},
                      "bbb": {APP: ["read", "write"]}, "ccc": {"app.appjail.other": ["read"]}})
    monkeypatch.setattr(portal, "bus_call", fake)
    return fake


def run(*argv, answers=()):
    c = Script(answers)
    cli.cmd_portals(cli.build_parser().parse_args(["portals", "app", *argv]), c, host_env={})
    return c


def test_lists_only_this_apps_grants(h, docs):
    installed(h)
    text = run().text
    assert "2 document grant(s)" in text and "aaa  [read]" in text and "bbb  [read, write]" in text
    assert "ccc" not in text


def test_revoke_one_leaves_other_apps_and_documents(h, docs):
    installed(h)
    run("--revoke", "aaa", answers=["y"])
    assert docs.docs["aaa"] == {"app.appjail.other": ["read"]} and docs.docs["bbb"] == {APP: ["read", "write"]}


def test_revoke_all_and_cancel(h, docs):
    installed(h)
    with pytest.raises(Abort):
        run("--revoke-all", answers=["n"])
    assert APP in docs.docs["aaa"]
    run("--revoke-all", "--yes")
    assert all(APP not in apps for apps in docs.docs.values()) and "ccc" in docs.docs


def test_revoking_a_document_without_a_grant_is_refused(h, docs):
    installed(h)
    with pytest.raises(Abort, match="no grant on document 'ccc'"):
        run("--revoke", "ccc", "--yes")


def test_unknown_app_and_unreachable_store(h):
    with pytest.raises(Abort, match="unknown app"):
        run()
    installed(h)
    with pytest.raises(Abort, match="no permission store"):
        run()


def test_remove_revokes_the_grants(h, docs):
    installed(h)
    cli.cmd_remove(cli.build_parser().parse_args(["remove", "app", "--yes"]), Script())
    assert all(APP not in apps for apps in docs.docs.values()) and not store.manifest_path("app").exists()
