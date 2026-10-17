# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Where bjail keeps its files. Nothing is written outside these two trees."""

import os
from pathlib import Path


def _dir(env, fallback):
    base = os.environ.get(env)
    return Path(base) if base else Path.home() / fallback


def data_dir():
    return _dir("BJAIL_DATA_DIR", ".local/share/bjail")


def config_dir():
    return _dir("BJAIL_CONFIG_DIR", ".config/bjail")


def app_dir(name):
    return data_dir() / "apps" / name


def appimage_path(name):
    return app_dir(name) / "app.AppImage"


def manifest_path(name):
    return config_dir() / "apps" / f"{name}.toml"


def staging_root():
    return data_dir() / "staging"
