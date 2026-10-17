# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import tempfile
import unittest
from pathlib import Path

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


class ParseTests(unittest.TestCase):
    def test_good(self):
        m = manifest.loads(GOOD)
        self.assertEqual(m.source, "cli/cli")
        self.assertEqual(m.evidence_tier, 3)
        self.assertEqual(m.owner_id, 59704711)
        self.assertTrue(m.permissions.network)
        self.assertEqual(m.permissions.dirs, ("~/Downloads:rw", "/usr/share/fonts"))

    def test_permissions_default_to_deny(self):
        text = GOOD.split("[permissions]")[0]
        p = manifest.loads(text).permissions
        self.assertEqual(p, Permissions())
        self.assertFalse(p.network or p.audio or p.gpu or p.portals)

    def test_unknown_top_key(self):
        with self.assertRaisesRegex(ManifestError, "unknown key"):
            manifest.loads(GOOD.replace('name = "gh"', 'name = "gh"\nurl = "http://x"'))

    def test_unknown_permission_key(self):
        with self.assertRaisesRegex(ManifestError, "unknown key"):
            manifest.loads(GOOD + "shell = true\n")

    def test_missing_key(self):
        with self.assertRaisesRegex(ManifestError, "missing"):
            manifest.loads(GOOD.replace(f'sha256 = "{SHA}"\n', ""))

    def test_wrong_schema(self):
        with self.assertRaisesRegex(ManifestError, "schema"):
            manifest.loads(GOOD.replace("schema = 1", "schema = 2"))

    def test_bad_toml(self):
        with self.assertRaisesRegex(ManifestError, "invalid TOML"):
            manifest.loads("schema = [")

    def test_bad_values(self):
        cases = {
            "name": ["", "Upper", "-x", "a/b", "a" * 65, "x\ny"],
            "source": ["cli", "a/b/c", "a b/c", "../x", "a/..", "a/.", ".a/b", "-a/b", "https://github.com/a/b"],
            "sha256": ["A" * 64, "a" * 63, "g" * 64, "sha256:" + "a" * 64],
            "evidence_tier": [0, 6, True, "3", 3.0],
            "published_at": ["2026-09-30", "2026-13-30T02:40:02Z", "2026-09-30T02:40:02+00:00"],
            "asset_pattern": ["", "a/b", "a\x00b"],
            "version": ["", "v" * 129, "v\n1"],
            "owner_id": [0, -1, True, "5", 1.5],
        }
        for field_, values in cases.items():
            for v in values:
                with self.subTest(field=field_, value=v):
                    with self.assertRaises(ManifestError):
                        manifest.validate(make(**{field_: v}))

    def test_valid_sources(self):
        for src in ("cli/cli", "ivan-hc/AM", "a/b.c_d-e", "a/.github"):
            with self.subTest(src=src):
                manifest.validate(make(source=src))

    def test_bad_permissions(self):
        cases = [
            Permissions(network="yes"),
            Permissions(display="x11"),
            Permissions(dbus_filter=("notaname",)),
            Permissions(dirs=("relative/path",)),
            Permissions(dirs=("/",)),
            Permissions(dirs=("~/",)),
            Permissions(dirs=("~/a/../../etc",)),
            Permissions(dirs=("~/a:wx",)),
            Permissions(dirs=("~/a\nb",)),
        ]
        for p in cases:
            with self.subTest(p=p):
                with self.assertRaises(ManifestError):
                    manifest.validate(make(permissions=p))

    def test_permission_types_from_toml(self):
        with self.assertRaises(ManifestError):
            manifest.loads(GOOD.replace("network = true", 'network = "true"'))
        with self.assertRaises(ManifestError):
            manifest.loads(GOOD.replace('dirs = ["~/Downloads:rw", "/usr/share/fonts"]', "dirs = 5"))


class WriteTests(unittest.TestCase):
    def test_round_trip(self):
        m = manifest.loads(GOOD)
        self.assertEqual(manifest.loads(manifest.dumps(m)), m)

    def test_dumps_deterministic(self):
        m = make(permissions=Permissions(audio=True, dirs=("~/x:rw",)))
        self.assertEqual(manifest.dumps(m), manifest.dumps(manifest.loads(manifest.dumps(m))))

    def test_owner_id_optional_and_round_trips(self):
        self.assertIsNone(manifest.loads(GOOD.replace("owner_id = 59704711\n", "")).owner_id)
        m = make(owner_id=7)
        self.assertEqual(manifest.loads(manifest.dumps(m)).owner_id, 7)
        self.assertNotIn("owner_id", manifest.dumps(make()))

    def test_quoting(self):
        m = make(asset_pattern='a"b\\c*.AppImage', version="v1 ü")
        self.assertEqual(manifest.loads(manifest.dumps(m)), m)

    def test_dumps_refuses_invalid(self):
        with self.assertRaises(ManifestError):
            manifest.dumps(make(sha256="zz"))

    def test_dump_load_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "gh.toml"
            m = make()
            manifest.dump(path, m)
            self.assertEqual(manifest.load(path), m)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["gh.toml"])


if __name__ == "__main__":
    unittest.main()
