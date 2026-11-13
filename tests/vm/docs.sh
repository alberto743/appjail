#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Build the documentation site in the guest (GUEST=debian|ubuntu) with the pinned tooling of
# .github/requirements-docs.txt, in strict mode, and copy the result to vm/<guest>/site for viewing on the host
# (open vm/<guest>/site/index.html). The venv lives in the guest's ~/docs-venv, outside the synced tree, and is
# rebuilt when the requirements change.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
. "$here/guest.sh"
"$here/sync.sh"
"$here/ssh.sh" 'set -eu
req=~/appjail/.github/requirements-docs.txt
if ! cmp -s "$req" ~/docs-venv/requirements.txt 2>/dev/null; then
	rm -rf ~/docs-venv
	python3 -m venv ~/docs-venv
	~/docs-venv/bin/pip install -q --no-input --require-hashes --only-binary=:all: -r "$req"
	cp "$req" ~/docs-venv/requirements.txt
fi
cd ~/appjail && ~/docs-venv/bin/zensical build --strict --clean'
rm -rf "$run/../site"
"$here/ssh.sh" 'tar -C ~/appjail/site -cf - .' | { mkdir -p "$run/../site" && tar -C "$run/../site" -xf -; }
echo "site: vm/$GUEST/site/index.html"
