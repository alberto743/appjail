# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The manifest's [env] table: schema, policy, the jail's environment and `perms --set-env`."""

from dataclasses import replace

import pytest

from appjail import cli, grants, manifest, runtimejail, store
from appjail.errors import RunError
from appjail.manifest import Manifest, ManifestError

from .helpers import Script, build


def sample(**kw):
    return Manifest("app", "github:o/a", "v1", "a" * 64, 3, "2026-01-01T00:00:00Z", asset_pattern="*.AppImage", **kw)


def perms(h, *argv, answers=("y",)):
    c = Script(answers)
    cli.cmd_perms(cli.build_parser().parse_args(["perms", "app", *argv]), c)
    return c


def setenv(args):
    return {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}


# -- manifest ----------------------------------------------------------------------------


def test_no_env_is_not_written_and_round_trips():
    assert "[env]" not in manifest.dumps(sample())
    assert manifest.loads(manifest.dumps(sample())).env == ()


def test_env_round_trips_sorted():
    m = sample(env=(("B_VAR", 'a "quoted" \\ value'), ("A_VAR", "1"), ("EMPTY", "")))
    text = manifest.dumps(m)
    assert text.index("A_VAR") < text.index("B_VAR")
    assert dict(manifest.loads(text).env) == dict(m.env)


@pytest.mark.parametrize("key", ["lower", "1X", "A-B", "", "A" * 65, "PATH", "HOME", "DISPLAY", "WAYLAND_DISPLAY", "GDK_BACKEND",
                                 "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV", "PYTHONPATH", "PERL5LIB", "NODE_OPTIONS",
                                 "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER"])
def test_refused_names(key):
    with pytest.raises(ManifestError):
        manifest.validate(sample(env=((key, "x"),)))


@pytest.mark.parametrize("value", ["x" * 1025, "a\nb", "a\x00b", "\x1b[31m", 5])
def test_refused_values(value):
    with pytest.raises(ManifestError):
        manifest.validate(sample(env=(("OK", value),)))


def test_too_many_entries_and_duplicates():
    many = tuple((f"V{i}", "1") for i in range(grants.ENV_MAX_ENTRIES + 1))
    with pytest.raises(ManifestError, match="more than"):
        manifest.validate(sample(env=many))
    with pytest.raises(ManifestError, match="unique"):
        manifest.validate(sample(env=(("A", "1"), ("A", "2"))))


def test_hand_edited_manifest_is_checked_and_env_must_be_a_table():
    good = manifest.dumps(sample(env=(("A", "1"),)))
    with pytest.raises(ManifestError, match="refused"):
        manifest.loads(good.replace('A = "1"', 'LD_PRELOAD = "/x"'))
    with pytest.raises(ManifestError, match="env"):
        manifest.loads(manifest.dumps(sample()) + 'env = "x"\n')
    with pytest.raises(ManifestError, match="string"):
        manifest.loads(good.replace('A = "1"', "A = 1"))


# -- the jail ----------------------------------------------------------------------------


def test_user_env_reaches_the_jail(sandbox, runtime):
    kw = build(sandbox, runtime)
    env = setenv(runtimejail.runtime_args(**kw, user_env=(("CLAUDE_USE_WAYLAND", "1"),)))
    assert env["CLAUDE_USE_WAYLAND"] == "1" and env["HOME"] == runtimejail.APP_HOME
    assert "CLAUDE_USE_WAYLAND" not in setenv(runtimejail.runtime_args(**kw))


@pytest.mark.parametrize("key", ["HOME", "LD_PRELOAD", "GDK_BACKEND", "TZ"])
def test_the_jail_refuses_names_appjail_sets(sandbox, runtime, key):
    with pytest.raises((RunError, ManifestError)):
        runtimejail.runtime_args(**build(sandbox, runtime), user_env=((key, "x"),))


# -- perms -------------------------------------------------------------------------------


def saved():
    return manifest.load(store.manifest_path("app"))


def test_perms_set_and_unset_env(h):
    h.add()
    c = perms(h, "--set-env", "CLAUDE_USE_WAYLAND=1", "--set-env", "B=2")
    assert saved().env == (("B", "2"), ("CLAUDE_USE_WAYLAND", "1"))
    assert "plain text" in c.text and "+ B=2" in c.text
    c = perms(h, "--unset-env", "B")
    assert saved().env == (("CLAUDE_USE_WAYLAND", "1"),)
    assert "CLAUDE_USE_WAYLAND=1" in perms(h).text


def test_perms_refuses_bad_env(h):
    h.add()
    for argv in (["--set-env", "NOVALUE"], ["--set-env", "PATH=/x"], ["--unset-env", "NOPE"]):
        with pytest.raises(cli.Abort):
            perms(h, *argv)
    assert saved().env == ()


def test_env_survives_a_permission_change_and_an_update_record(h):
    h.add()
    perms(h, "--set-env", "A=1")
    perms(h, "--allow", "network", answers=("y", "y"))
    assert saved().env == (("A", "1"),)
    assert replace(saved(), version="v2").env == (("A", "1"),)
