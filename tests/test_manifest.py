# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0


import pytest

from appjail import grants, manifest
from appjail.manifest import Manifest, ManifestError, Permissions

SHA = "a" * 64

GOOD = f"""
schema = 1
name = "gh"
source = "github:cli/cli"
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
dirs = ["~/Downloads:rw", "/mnt/data"]
"""


def make(**kw):
    base = {"name": "gh", "source": "github:cli/cli", "asset_pattern": "*.AppImage", "version": "v1",
                "sha256": SHA, "evidence_tier": 4, "published_at": "2026-09-30T02:40:02Z"}
    base.update(kw)
    return Manifest(**base)


# -- parsing -------------------------------------------------------------------------


def test_good_manifest():
    m = manifest.loads(GOOD)
    assert m.source == "github:cli/cli"
    assert m.evidence_tier == 3
    assert m.owner_id == 59704711
    assert m.permissions.network is True
    assert m.permissions.dirs == ("~/Downloads:rw", "/mnt/data")


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
    *[("source", v) for v in ["cli", "cli/cli", "github:a/b/c", "github:a b/c", "github:../x", "github:a/..",
                              "github:a/.", "github:.a/b", "github:-a/b", "https://github.com/a/b",
                              "gitlab:a/b", "github:", "url:http://example.org/a.AppImage",
                              "url:https://user:pw@example.org/a", "url:https://example.org/a#frag",
                              "url:https://example.org/a b", "url:https:///a", "url:ftp://example.org/a"]],
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


@pytest.mark.parametrize("src", ["github:cli/cli", "github:ivan-hc/AM", "github:a/b.c_d-e", "github:a/.github"])
def test_valid_sources(src):
    manifest.validate(make(source=src))


FP = manifest.Fingerprint(size=1234, chunks="c" * 64, etag='"abc"', last_modified="Tue, 20 Oct 2026 08:00:00 GMT")


def make_url(**kw):
    base = {"source": "url:https://example.org/dl/App-x86_64.AppImage", "asset_pattern": None, "evidence_tier": 5,
            "fingerprint": FP}
    base.update(kw)
    return make(**base)


def make_file(**kw):
    base = {"source": "file:My App.AppImage", "asset_pattern": None, "evidence_tier": 5}
    base.update(kw)
    return make(**base)


@pytest.mark.parametrize("m", [make_url(), make_url(evidence_tier=4), make_file(), make_file(evidence_tier=4),
                               make_url(fingerprint=manifest.Fingerprint(size=1, chunks="a" * 64))])
def test_url_and_file_sources_round_trip(m):
    assert manifest.loads(manifest.dumps(m)) == m
    assert (m.kind, m.target) == tuple(m.source.split(":", 1))


def test_url_manifest_text():
    text = manifest.dumps(make_url())
    assert 'source = "url:https://example.org/dl/App-x86_64.AppImage"' in text
    assert "asset_pattern" not in text and "owner_id" not in text
    assert 'fingerprint = { size = 1234, chunks = "' + "c" * 64 + '", etag = "\\"abc\\"", last_modified = ' in text


@pytest.mark.parametrize("bad", [
    make_url(evidence_tier=3), make_file(evidence_tier=1), make_file(evidence_tier=3),
    make_url(asset_pattern="*"), make_file(asset_pattern="*"), make_url(owner_id=5), make_file(owner_id=5),
    make_file(fingerprint=FP), make(fingerprint=FP),
    make_file(source="file:a/b"), make_file(source="file:.."), make_file(source="file:"),
    make_url(fingerprint=manifest.Fingerprint(size=0, chunks="c" * 64)),
    make_url(fingerprint=manifest.Fingerprint(size=5, chunks="zz")),
    make(asset_pattern=None),
])
def test_kind_rules(bad):
    with pytest.raises(ManifestError):
        manifest.validate(bad)


def test_github_needs_an_asset_pattern_in_the_file():
    text = manifest.dumps(make()).replace('asset_pattern = "*.AppImage"\n', "")
    with pytest.raises(ManifestError, match="asset_pattern"):
        manifest.loads(text)


def test_fingerprint_table_is_strict():
    text = manifest.dumps(make_url())
    with pytest.raises(ManifestError):
        manifest.loads(text.replace("size = 1234, ", "size = 1234, extra = 1, "))
    with pytest.raises(ManifestError):
        manifest.loads(text.replace("size = 1234, ", ""))


@pytest.mark.parametrize("perms", [
    Permissions(network="yes"),
    Permissions(network_host=True),
    Permissions(display="x11"),
    Permissions(dbus_filter=("notaname",)),
    Permissions(dirs=("relative/path",)),
    Permissions(dirs=("/",)),
    Permissions(dirs=("~/",)),
    Permissions(dirs=("~/a/../../etc",)),
    Permissions(dirs=("~/a:wx",)),
    Permissions(dirs=("~/a\nb",)),
    Permissions(dirs=("/etc",)),
    Permissions(dirs=("/run/user/1000",)),
    Permissions(dirs=("/usr/share/fonts",)),
    Permissions(dirs=("/tmp",)),
    Permissions(dirs=("/tmp:rw",)),
    Permissions(dirs=("/tmp/.X11-unix",)),
    Permissions(dirs=("/tmp/tmux-1000",)),
    Permissions(dirs=("/var/tmp/work:rw",)),
    Permissions(dirs=("~/.ssh",)),
    Permissions(dirs=("~/.gnupg/private-keys-v1.d",)),
    Permissions(dirs=("~/.config",)),
    Permissions(dirs=("~/.local/bin:rw",)),
    Permissions(dirs=("~/.config/autostart:rw",)),
    Permissions(dirs=("~/.local/share/applications:rw",)),
])
def test_bad_permissions_rejected(perms):
    with pytest.raises(ManifestError):
        manifest.validate(make(permissions=perms))


def test_permission_types_from_toml():
    with pytest.raises(ManifestError):
        manifest.loads(GOOD.replace("network = true", 'network = "true"'))
    with pytest.raises(ManifestError):
        manifest.loads(GOOD.replace('dirs = ["~/Downloads:rw", "/mnt/data"]', "dirs = 5"))


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
    assert grants.normalize_dir(spec, "/home/u", "/home/u/work") == expected


@pytest.mark.parametrize("spec", ["/", "~/", "/home/u", "..", "~/..", "", ":rw", "/a\nb", "/home"])
def test_normalize_dir_rejects_broad_or_odd_paths(spec):
    with pytest.raises(ManifestError):
        grants.normalize_dir(spec, "/home/u", "/home/u/work")


def test_merge_dirs_read_write_wins_and_order_is_kept():
    assert grants.merge_dirs(("~/A", "~/B:rw"), ("~/A:rw", "~/B", "~/C")) == ("~/A:rw", "~/B:rw", "~/C")
    assert grants.merge_dirs((), ()) == ()


@pytest.mark.parametrize("path,mode,refused", [
    ("~/.local/bin", "", False),  # reading binaries is not an escape
    ("~/.local/bin", "rw", True),
    ("~/.config/myapp", "rw", False),
    ("~/.config/autostart/x", "rw", True),
    ("~/.ssh", "", True),
    ("~/Documents", "rw", False),
    ("/mnt/data", "rw", False),
    ("/dev/dri", "", True),
    ("~/.bash_history", "", True),
    ("~/.git-credentials", "", True),
    ("~/.pki/nssdb", "", True),
    ("~/.mozilla/firefox", "", True),
    ("~/.config/google-chrome/Default", "", True),
    ("~/.thunderbird", "", True),
    ("~/.var/app/org.x.App", "", True),
    ("~/Vault/pass.KDBX", "", True),
    ("~/.configuration", "", False),  # prefix of a rule is not the rule
    ("~/.varnish", "", False),
])
def test_sensitive_reason(path, mode, refused):
    assert bool(grants.sensitive_reason(path, mode)) is refused


@pytest.mark.parametrize("path,refused", [("/tmp", True), ("/tmp/x/y", True), ("/var/tmp", True), ("/tmpfiles", False),
                                          ("/var/tmpl", False), ("/mnt/tmp", False), ("~/tmp", False)])
def test_directory_reason_refuses_the_shared_temp_dirs(path, refused):
    assert bool(grants.directory_reason(path, "")) is refused
    assert grants.sensitive_reason(path, "") is None  # single files there are fine


@pytest.mark.parametrize("spec", ["~/.ssh", "~/.config", "~/.local/bin:rw", "/etc/ssl", "/proc", "/tmp", "/var/tmp/x"])
def test_normalize_dir_refuses_sensitive(spec):
    with pytest.raises(manifest.ManifestError, match="refused"):
        grants.normalize_dir(spec, "/home/u", "/home/u/work")


def test_userns_defaults_to_denied_and_round_trips():
    assert Permissions().userns is False
    m = make(permissions=Permissions(userns=True))
    assert manifest.loads(manifest.dumps(m)).permissions.userns is True
    assert "userns = false" in manifest.dumps(make())


def test_linger_defaults_to_off_is_written_only_when_on_and_round_trips():
    assert Permissions().linger is False
    assert "linger" not in manifest.dumps(make())
    m = make(permissions=Permissions(linger=True))
    assert "linger = true" in manifest.dumps(m)
    assert manifest.loads(manifest.dumps(m)).permissions.linger is True


def test_linger_must_be_a_boolean():
    text = manifest.dumps(make(permissions=Permissions(linger=True))).replace("linger = true", 'linger = "yes"')
    with pytest.raises(manifest.ManifestError, match="linger"):
        manifest.loads(text)


def test_channel_defaults_to_stable_and_round_trips():
    assert make().channel == "stable" and "channel" not in manifest.dumps(make())
    m = make(channel="pinned")
    assert manifest.loads(manifest.dumps(m)).channel == "pinned"
    with pytest.raises(ManifestError):
        manifest.validate(make(channel="nightly"))


def test_url_source_needs_a_fingerprint():
    with pytest.raises(ManifestError, match="needs a fingerprint"):
        manifest.validate(make_url(fingerprint=None))
    text = manifest.dumps(make_url()).replace(manifest._fingerprint_line(FP) + "\n", "")
    with pytest.raises(ManifestError, match="needs a fingerprint"):
        manifest.loads(text)
