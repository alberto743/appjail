#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Sync the project into the guest and run the full test suite there (never on the host).
# Extra arguments are passed to unittest, e.g. tests/vm/test.sh -v tests.test_appimage
set -eu
here=$(cd "$(dirname "$0")" && pwd)
"$here/sync.sh"
"$here/ssh.sh" "cd ~/bjail && BJAIL_INTEGRATION=1 python3 -m unittest $*"
