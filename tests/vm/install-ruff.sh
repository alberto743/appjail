#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Debian 13 and Ubuntu 26.04 ship no ruff package: install the pinned release from PyPI into
# /usr/local (needs sudo and python3-pip; dev-only, tests/test_lint.py skips without it).
# Used by provision.sh (guest) and by the CI workflow.
set -eu
sudo env PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install -q --no-input ruff==0.17.1
ruff --version
