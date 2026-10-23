# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Where appjail keeps its files. Nothing is written outside these two trees."""

import os
import secrets
from pathlib import Path


def _dir(env, fallback):
    base = os.environ.get(env)
    return Path(base) if base else Path.home() / fallback


def data_dir():
    return _dir("APPJAIL_DATA_DIR", ".local/share/appjail")


def config_dir():
    return _dir("APPJAIL_CONFIG_DIR", ".config/appjail")


def app_dir(name):
    return data_dir() / "apps" / name


def tools_dir():
    """Pinned helper binaries (see appjail.tools)."""
    return data_dir() / "tools"


def appimage_path(name):
    return app_dir(name) / "app.AppImage"


def manifest_path(name):
    return config_dir() / "apps" / f"{name}.toml"


def staging_root():
    return data_dir() / "staging"


def atomic_write(path, data, mode=0o666):
    """Replace `path` with `data` (str or bytes) through a temp file in the same directory.
    The file is created with `mode` (before the umask), so it is never readable wider than asked."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def new_staging_dir(prefix=""):
    """A new private directory under the staging root (the caller removes it)."""
    stage = staging_root() / (prefix + secrets.token_hex(8))
    stage.mkdir(parents=True, mode=0o700)
    return stage


def root_path(name):
    """Extracted AppImage tree (contains AppRun)."""
    return app_dir(name) / "root"


def root_marker(name):
    """Holds the sha256 of the AppImage the tree was extracted from."""
    return app_dir(name) / "root.sha256"


def tree_marker(name):
    """Holds the digest of the extracted tree itself, taken right after extraction."""
    return app_dir(name) / "root.tree.sha256"


def home_path(name):
    """The app's private home (persistent, bound at /home/app)."""
    return app_dir(name) / "home"


def etc_path(name):
    """Generated /etc/passwd and /etc/group for the app."""
    return app_dir(name) / "etc"
