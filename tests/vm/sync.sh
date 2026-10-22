#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Copy the project (without vm/ and caches) into ~/appjail in the guest. No host mounts.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root="$here/../.."
tar -C "$root" --exclude=./vm --exclude=__pycache__ --exclude=.ruff_cache --exclude=.git -cf - . |
	"$here/ssh.sh" 'rm -rf ~/appjail && mkdir ~/appjail && tar -C ~/appjail -xf -'
