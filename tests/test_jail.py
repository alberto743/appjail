# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from bjail import fetcher, jail


class ArgsTests(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, self.stage)
        self.args = jail.download_args(self.stage, ["/usr/bin/python3", "-I", "/fetcher.py", "u", "o", "1"])

    def pairs(self, flag):
        a = self.args
        return [tuple(a[i + 1:i + 3]) for i, x in enumerate(a) if x == flag]

    def test_isolation_flags(self):
        for flag in ("--unshare-all", "--share-net", "--die-with-parent", "--new-session", "--clearenv"):
            self.assertIn(flag, self.args)
        self.assertEqual(self.args[self.args.index("--cap-drop") + 1], "ALL")
        self.assertLess(self.args.index("--unshare-all"), self.args.index("--share-net"))

    def test_root_is_remounted_read_only_after_all_mounts(self):
        i = self.args.index("--remount-ro")
        self.assertEqual(self.args[i + 1], "/")
        self.assertEqual([x for x in self.args[i + 2:] if x.startswith("--")][:2], ["--chdir", "--"])

    def test_only_stage_is_writable(self):
        self.assertEqual(self.pairs("--bind"), [(self.stage, "/stage")])
        self.assertEqual(self.pairs("--dev-bind"), [])

    def test_no_home_or_runtime_dir_exposed(self):
        home = str(Path.home())
        runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user")
        for a in self.args:
            self.assertFalse(a.startswith(home) and a not in (self.stage, str(jail.FETCHER)), a)
            self.assertFalse(a.startswith(runtime), a)

    def test_command_after_separator(self):
        i = self.args.index("--")
        self.assertEqual(self.args[i + 1], "/usr/bin/python3")
        self.assertIn(("/fetcher.py",), [(x,) for x in self.args])

    def test_env_whitelist(self):
        sets = {self.args[i + 1]: self.args[i + 2] for i, x in enumerate(self.args) if x == "--setenv"}
        self.assertEqual(set(sets), set(jail.SAFE_ENV))


class FetcherPolicyTests(unittest.TestCase):
    def test_allowed(self):
        for url in ("https://github.com/o/r/releases/download/v1/a.AppImage",
                    "https://objects.githubusercontent.com/x", "https://release-assets.githubusercontent.com/y"):
            self.assertTrue(fetcher.allowed(url), url)

    def test_refused(self):
        for url in ("http://github.com/o/r", "https://evil.example/", "https://github.com.evil.example/",
                    "https://notgithub.com/", "https://user@github.com/", "https://github.com:8443/",
                    "https://evilgithubusercontent.com/", "file:///etc/passwd", "ftp://github.com/x"):
            self.assertFalse(fetcher.allowed(url), url)

    def test_main_refuses_bad_url_without_network(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetcher.main(["f", "http://github.com/x", "/nonexistent/out", "1"]), 2)
            self.assertEqual(fetcher.main(["f"]), 2)


@unittest.skipUnless(os.environ.get("BJAIL_INTEGRATION") == "1", "run in the test guest with BJAIL_INTEGRATION=1")
class JailIntegrationTests(unittest.TestCase):
    """Real bwrap. Run inside the qemu guest: tests/vm/ssh.sh 'cd ~/bjail && BJAIL_INTEGRATION=1 python3 -m unittest'."""

    CODE = r'''
import json, os, urllib.request
def can_write(p):
    try:
        open(p, "w").close(); os.unlink(p); return True
    except OSError:
        return False
caps = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1]
try:
    status = urllib.request.urlopen("https://api.github.com/rate_limit", timeout=20).status
except Exception as e:
    status = repr(e)
print(json.dumps({
    "env": sorted(os.environ), "pid": os.getpid(), "caps": caps, "net": status,
    "home_exists": os.path.exists("/home"), "host_marker": os.path.exists("/tmp/host-marker"),
    "write_stage": can_write("/stage/x"), "write_root": can_write("/x"), "write_usr": can_write("/usr/x"),
    "write_tmp": can_write("/tmp/x"), "run_user": os.path.exists("/run/user"),
}))
'''

    def test_jail_properties(self):
        marker = Path("/tmp/host-marker")
        marker.write_text("x")
        self.addCleanup(marker.unlink)
        with tempfile.TemporaryDirectory() as stage:
            proc = jail.run(jail.download_args(stage, ["/usr/bin/python3", "-I", "-c", self.CODE]), timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            r = json.loads(proc.stdout)
        self.assertEqual(r["net"], 200)
        self.assertEqual(r["caps"], "0000000000000000")
        self.assertLess(r["pid"], 10)
        self.assertEqual(set(r["env"]) - {"PWD"}, set(jail.SAFE_ENV))
        self.assertFalse(r["home_exists"] or r["host_marker"] or r["run_user"])
        self.assertTrue(r["write_stage"] and r["write_tmp"])
        self.assertFalse(r["write_root"] or r["write_usr"])


if __name__ == "__main__":
    unittest.main()
