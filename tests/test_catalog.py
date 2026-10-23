# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import json

import pytest

from appjail import catalog
from appjail.catalog import App, Catalog, IndexProblem


def doc(**kw):
    base = {"format": "appjail-catalog", "version": 1, "apps": [{"name": "gh", "description": "GitHub CLI", "source": "github:cli/cli"}]}
    base.update(kw)
    return json.dumps(base)


def test_a_minimal_catalog_parses():
    cat = catalog.parse(doc(origin="https://example.org", revision="r1"))
    assert cat == Catalog((App("gh", "GitHub CLI", "github:cli/cli", ""),), "https://example.org", "r1")


def test_optional_fields_default_to_empty():
    cat = catalog.parse(doc(apps=[{"name": "x"}]))
    assert cat.apps == (App("x", "", "", ""),) and cat.origin == cat.revision == ""


def test_dumps_is_deterministic_sorted_and_round_trips():
    cat = Catalog((App("b", "second", "github:o/b"), App("a", "first", "", "resolve manually: https://x.org")), "org", "rev")
    text = catalog.dumps(cat)
    assert [a["name"] for a in json.loads(text)["apps"]] == ["a", "b"]
    assert catalog.parse(text) == Catalog(tuple(sorted(cat.apps, key=lambda a: a.name)), "org", "rev")
    assert catalog.dumps(catalog.parse(text)) == text
    assert '"source"' not in json.dumps(json.loads(text)["apps"][0])  # empty fields are left out


def test_texts_are_stripped_of_terminal_escapes_and_cut():
    cat = catalog.parse(doc(apps=[{"name": "x", "description": "a\x1b[31mred\x1b[0m\nline " + "z" * 500, "note": "\x07bell"}]))
    app = cat.apps[0]
    assert "\x1b" not in app.description and "\n" not in app.description and len(app.description) <= catalog.DESCRIPTION_MAX
    assert app.note == "bell"


@pytest.mark.parametrize("text,message", [
    ("not json", "not valid JSON"),
    ("[]", "must be a JSON object"),
    (doc(format="other"), "format"),
    (doc(version=2), "unsupported catalog version"),
    (doc(version=True), "unsupported catalog version"),
    (doc(extra=1), "unknown top-level"),
    (doc(apps={}), "must be a list"),
    (doc(apps=["x"]), "must be an object"),
    (doc(apps=[{"name": "x", "bogus": 1}]), "unknown key"),
    (doc(apps=[{"name": "../evil"}]), "name must match"),
    (doc(apps=[{"name": "-dash"}]), "name must match"),
    (doc(apps=[{}]), "name must match"),
    (doc(apps=[{"name": "x", "source": "a/b"}]), "must start with one of"),
    (doc(apps=[{"name": "x", "source": "https://github.com/a/b"}]), "must start with one of"),
    (doc(apps=[{"name": "x", "source": "file:x.AppImage"}]), "must start with one of"),
    (doc(apps=[{"name": "x", "source": "github:a/.."}]), "expected github:owner/repo"),
    (doc(apps=[{"name": "x", "source": "gitlab:gitlab.com/solo"}]), "path segment"),
    (doc(apps=[{"name": "x", "source": "gitlab:gitlab.com/a/../b"}]), "path segment"),
    (doc(apps=[{"name": "x", "source": "gitlab:user@gitlab.com/a/b"}]), "DNS host"),
    (doc(apps=[{"name": "x", "source": "gitlab:gitlab.com:8443/a/b"}]), "DNS host"),
    (doc(apps=[{"name": "x", "source": "gitlab:localhost/a/b"}]), "DNS host"),
    (doc(apps=[{"name": "x", "source": "gitlab:10.0.0.1/a/b"}]), "DNS host"),
    (doc(apps=[{"name": "x", "source": "forgejo:git.example.net/a/b/c"}]), "path segment"),
    (doc(apps=[{"name": "x", "source": "forgejo:git.example.net"}]), "DNS host"),
    (doc(apps=[{"name": "x", "source": "codeberg:solo"}]), "path segment"),
    (doc(apps=[{"name": "x", "source": "url:http://example.org/a.AppImage"}]), "https"),
    (doc(apps=[{"name": "x", "source": "url:https://u:p@example.org/a"}]), "credentials"),
    (doc(apps=[{"name": "x", "description": 5}]), "must be a string"),
    (doc(apps=[{"name": "x"}, {"name": "x"}]), "duplicate app name"),
    (doc(origin=3), "must be a string"),
])
def test_bad_catalogs_are_refused(text, message):
    with pytest.raises(IndexProblem, match=message):
        catalog.parse(text)


def test_size_and_count_limits(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_APPS", 2)
    with pytest.raises(IndexProblem, match="too many apps"):
        catalog.parse(doc(apps=[{"name": "a"}, {"name": "b"}, {"name": "c"}]))
    monkeypatch.setattr(catalog, "MAX_BYTES", 10)
    with pytest.raises(IndexProblem, match="too large"):
        catalog.parse(doc())


def test_deeply_nested_json_is_a_clean_error():
    with pytest.raises(IndexProblem):
        catalog.parse("[" * 100000)


@pytest.mark.parametrize("given,normalized", [
    ("github:cli/cli", "github:cli/cli"),
    ("codeberg:user/tool", "forgejo:codeberg.org/user/tool"),
    ("forgejo:Git.Example.NET/user/tool", "forgejo:git.example.net/user/tool"),
    ("gitlab:gitlab.example.org/group/sub/tool-b", "gitlab:gitlab.example.org/group/sub/tool-b"),
    ("gitlab:gitlab.com/group/proj", "gitlab:gitlab.com/group/proj"),
    ("url:https://example.com/dl/tool-d.AppImage", "url:https://example.com/dl/tool-d.AppImage"),
])
def test_every_kind_of_source_parses_and_is_normalized(given, normalized):
    cat = catalog.parse(doc(apps=[{"name": "x", "source": given}]))
    assert cat.apps[0].source == normalized
    assert catalog.parse(catalog.dumps(cat)) == cat


@pytest.mark.parametrize("source,who", [
    ("github:Cli/cli", "github:cli"),
    ("forgejo:codeberg.org/User/tool", "forgejo:codeberg.org/user"),
    ("gitlab:gitlab.example.org/Group/sub/tool", "gitlab:gitlab.example.org/group"),
    ("url:https://Example.COM/dl/a.AppImage", "url:example.com"),
])
def test_identity_names_kind_host_and_owner(source, who):
    assert catalog.identity(source) == who
