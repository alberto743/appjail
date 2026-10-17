#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Shut the guest down cleanly, falling back to killing qemu.
set -u
here=$(cd "$(dirname "$0")" && pwd)
run="$here/../../vm/run"
"$here/ssh.sh" 'sudo poweroff' >/dev/null 2>&1
sleep 5
[ -f "$run/qemu.pid" ] && kill "$(cat "$run/qemu.pid")" 2>/dev/null
rm -f "$run/qemu.pid"
