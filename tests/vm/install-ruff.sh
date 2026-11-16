#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Debian 13 and Ubuntu 26.04 ship no ruff package (Fedora does, but not the pinned release): install the pinned release from PyPI into
# /usr/local (needs sudo and python3-pip; dev-only, tests/test_lint.py skips without it).
# Used by provision.sh (guest) and by the CI workflow.
set -eu
# The version is the one in .github/requirements-ruff.txt, which Dependabot keeps current. provision.sh runs this script over
# ssh and passes the requirement as the argument; CI runs it from the checkout and it reads the file.
spec=${1:-$(grep '^ruff==' "$(dirname "$0")/../../.github/requirements-ruff.txt")}
sudo env PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install -q --no-input "$spec"
ruff --version
