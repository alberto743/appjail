# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Manifest history: every change appjail makes to ~/.config/appjail is committed to a local git repository.

The manifests hold the pins (hash, tier, owner, permissions) and sit in a directory any process of
the user can write, so the history is the tamper evidence: `run` warns when a manifest differs from
the last commit, and `appjail history` shows who changed what and when.

git runs inside a jail with no network and only the config directory visible, with the user's and
the system's git configuration ignored, so a hostile `.git/config` (filters, fsmonitor, hooks)
cannot execute anything outside it. Everything here is best effort: no git, no jail, or a repository
that belongs to the user's own dotfiles never stops a command.
"""

from pathlib import Path

from . import jail, store
from .jail import JailError

enabled = True
GIT = "/usr/bin/git"
AUTHOR = ("appjail", "appjail@localhost")
SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false",
        "-c", "core.pager=cat", "-c", "protocol.allow=never", "-c", "safe.directory=*"]


def _git(args, workdir):
    argv = [jail.find_bwrap(), *jail.local_git_args(workdir, [GIT, *SAFE, *args])]
    return jail.supervise(argv, timeout=30)


def _inside_another_repo(base):
    return any((p / ".git").exists() for p in Path(base).resolve().parents)


def _ready(create):
    base = store.config_dir()
    if not enabled or not Path(GIT).exists() or not base.is_dir():
        return False
    if (base / ".git").is_dir():
        return True
    if not create or _inside_another_repo(base):
        return False
    return _git(["init", "-q", "-b", "main"], base).returncode == 0


def record(message):
    """Commit the current state of the config directory. Returns True if a commit was made."""
    try:
        if not _ready(create=True):
            return False
        base = store.config_dir()
        (base / ".gitignore").write_text("*.tmp\n.*.tmp\n")
        _git(["add", "-A"], base)
        if _git(["diff", "--cached", "--quiet"], base).returncode == 0:
            return False
        return _git(["-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "commit", "-q", "-m", message],
                    base).returncode == 0
    except (JailError, OSError):
        return False


def modified(name):
    """True if the app's manifest differs from the last commit; None when there is no history to compare."""
    try:
        if not _ready(create=False):
            return None
        base = store.config_dir()
        if _git(["rev-parse", "-q", "--verify", "HEAD"], base).returncode != 0:
            return None
        rel = f"apps/{name}.toml"
        out = _git(["status", "--porcelain", "--", rel], base)
        return out.returncode == 0 and bool(out.stdout.strip())
    except (JailError, OSError):
        return None


def log(name=None, limit=20):
    """Lines of `date  message` for the whole config directory or one manifest; empty without history."""
    try:
        if not _ready(create=False):
            return []
        args = ["log", f"-{int(limit)}", "--format=%ad  %s", "--date=iso-strict"]
        if name:
            args += ["--", f"apps/{name}.toml"]
        out = _git(args, store.config_dir())
        return out.stdout.splitlines() if out.returncode == 0 else []
    except (JailError, OSError):
        return []
