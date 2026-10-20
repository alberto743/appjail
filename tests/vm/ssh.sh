#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Run a command (or open a shell) in the appjail test guest.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
run="$here/../../vm/run"
exec ssh -i "$run/id_appjail" -p 2222 \
	-o UserKnownHostsFile="$run/known_hosts" -o StrictHostKeyChecking=accept-new \
	-o BatchMode=yes -o ConnectTimeout=20 tester@127.0.0.1 "$@"
