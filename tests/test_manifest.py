# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest

from bjail import manifest
from bjail.manifest import Manifest, ManifestError, Permissions

SHA = "a" * 64

GOOD = f"""
schema = 1
name = "gh"
source = "cli/cli"
asset_pattern = "*linux_amd64.tar.gz"
version = "v2.102.0"
sha256 = "{SHA}"
evidence_tier = 3
published_at = "2026-09-30T02:40:02Z"
owner_id = 59704711

[permissions]
network = true
audio = false
gpu = true
display = "wayland"
dbus_filter = ["org.freedesktop.Notifications"]
portals = false
dirs = ["~/Downloads:rw", "/usr/share/fonts"]
"""


def make(**kw):
    base = dict(name="gh", source="cli/cli", asset_pattern="*.AppImage", version="v1",
                sha256=SHA, evidence_tier=4, published_at="2026-09-30T02:40:02Z")
    base.update(kw)
    return Manifest(**base)


# -- parsing -------------------------------------------------------------------------


def test_good_manifest():
    m = manifest.loads(GOOD)
    assert m.source == "cli/cli"
    assert m.evidence_tier == 3
    assert m.owner_id == 59704711
    assert m.permissions.network is True
    assert m.permissions.dirs == ("~/Downloads:rw", "/usr/share/fonts")


def test_permissions_default_to_deny():
    p = manifest.loads(GOOD.split("[permissions]")[0]).permissions
    assert p == Permissions()
    assert not (p.network or p.audio or p.gpu or p.portals)


def test_unknown_top_key():
    with pytest.raises(ManifestError, match="unknown key"):
        manifest.loads(GOOD.replace('name = "gh"', 'name = "gh"\nurl = "http://x"'))


def test_unknown_permission_key():
    with pytest.raises(ManifestError, match="unknown key"):
        manifest.loads(GOOD + "shell = true\n")


def test_missing_key():
    with pytest.raises(ManifestError, match="missing"):
        manifest.loads(GOOD.replace(f'sha256 = "{SHA}"\n', ""))


def test_wrong_schema():
    with pytest.raises(ManifestError, match="schema"):
        manifest.loads(GOOD.replace("schema = 1", "schema = 2"))


def test_bad_toml():
    with pytest.raises(ManifestError, match="invalid TOML"):
        manifest.loads("schema = [")


@pytest.mark.parametrize("field,value", [
    *[("name", v) for v in ["", "Upper", "-x", "a/b", "a" * 65, "x\ny"]],
    *[("source", v) for v in ["cli", "a/b/c", "a b/c", "../x", "a/..", "a/.", ".a/b", "-a/b",
                              "https://github.com/a/b"]],
    *[("sha256", v) for v in ["A" * 64, "a" * 63, "g" * 64, "sha256:" + "a" * 64]],
    *[("evidence_tier", v) for v in [0, 6, True, "3", 3.0]],
    *[("published_at", v) for v in ["2026-09-30", "2026-13-30T02:40:02Z", "2026-09-30T02:40:02+00:00"]],
    *[("asset_pattern", v) for v in ["", "a/b", "a\x00b"]],
    *[("version", v) for v in ["", "v" * 129, "v\n1"]],
    *[("owner_id", v) for v in [0, -1, True, "5", 1.5]],
])
def test_bad_values_rejected(field, value):
    with pytest.raises(ManifestError):
        manifest.validate(make(**{field: value}))


@pytest.mark.parametrize("src", ["cli/cli", "ivan-hc/AM", "a/b.c_d-e", "a/.github"])
def test_valid_sources(src):
    manifest.validate(make(source=src))


@pytest.mark.parametrize("perms", [
    Permissions(network="yes"),
    Permissions(display="x11"),
    Permissions(dbus_filter=("notaname",)),
    Permissions(dirs=("relative/path",)),
    Permissions(dirs=("/",)),
    Permissions(dirs=("~/",)),
    Permissions(dirs=("~/a/../../etc",)),
    Permissions(dirs=("~/a:wx",)),
    Permissions(dirs=("~/a\nb",)),
])
def test_bad_permissions_rejected(perms):
    with pytest.raises(ManifestError):
        manifest.validate(make(permissions=perms))


def test_permission_types_from_toml():
    with pytest.raises(ManifestError):
        manifest.loads(GOOD.replace("network = true", 'network = "true"'))
    with pytest.raises(ManifestError):
        manifest.loads(GOOD.replace('dirs = ["~/Downloads:rw", "/usr/share/fonts"]', "dirs = 5"))


# -- writing -------------------------------------------------------------------------


def test_round_trip():
    m = manifest.loads(GOOD)
    assert manifest.loads(manifest.dumps(m)) == m


def test_dumps_is_deterministic():
    m = make(permissions=Permissions(audio=True, dirs=("~/x:rw",)))
    assert manifest.dumps(m) == manifest.dumps(manifest.loads(manifest.dumps(m)))


def test_owner_id_optional_and_round_trips():
    assert manifest.loads(GOOD.replace("owner_id = 59704711\n", "")).owner_id is None
    assert manifest.loads(manifest.dumps(make(owner_id=7))).owner_id == 7
    assert "owner_id" not in manifest.dumps(make())


def test_quoting():
    m = make(asset_pattern='a"b\\c*.AppImage', version="v1 ü")
    assert manifest.loads(manifest.dumps(m)) == m


def test_dumps_refuses_invalid():
    with pytest.raises(ManifestError):
        manifest.dumps(make(sha256="zz"))


def test_dump_and_load_are_atomic(tmp_path):
    path = tmp_path / "sub" / "gh.toml"
    m = make()
    manifest.dump(path, m)
    assert manifest.load(path) == m
    assert [p.name for p in path.parent.iterdir()] == ["gh.toml"]


# -- --dir helpers -----------------------------------------------------------------------


@pytest.mark.parametrize("spec,expected", [
    ("/home/u/Docs", "~/Docs"),
    ("/home/u/Docs:rw", "~/Docs:rw"),
    ("/home/u/Docs:ro", "~/Docs"),
    ("~/Docs", "~/Docs"),
    ("Docs", "~/work/Docs"),
    ("../x/", "~/x"),
    ("/mnt/data:rw", "/mnt/data:rw"),
    ("/home/u/Docs/../Music", "~/Music"),
])
def test_normalize_dir(spec, expected):
    assert manifest.normalize_dir(spec, "/home/u", "/home/u/work") == expected


@pytest.mark.parametrize("spec", ["/", "~/", "/home/u", "..", "~/..", "", ":rw", "/a\nb", "/home"])
def test_normalize_dir_rejects_broad_or_odd_paths(spec):
    with pytest.raises(ManifestError):
        manifest.normalize_dir(spec, "/home/u", "/home/u/work")


def test_merge_dirs_read_write_wins_and_order_is_kept():
    assert manifest.merge_dirs(("~/A", "~/B:rw"), ("~/A:rw", "~/B", "~/C")) == ("~/A:rw", "~/B:rw", "~/C")
    assert manifest.merge_dirs((), ()) == ()
