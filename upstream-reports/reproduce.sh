#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Reproduce the evidence of the upstream reports, in the *-compositors guests (never on the host).
#   upstream-reports/reproduce.sh [-g debian|ubuntu|fedora] [ID ...]
# ID is a report number (01 to 12); without IDs, every report. Without -g, every guest a report lists in its repro script.
# Each repro script (upstream-reports/repro/ID.sh) runs in the guest, starts the compositor it needs with fresh processes, and
# prints REPRODUCED or NOT REPRODUCED with the versions it measured. The exit status is 1 when anything was not reproduced.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$here/..
only=
ids=
while [ $# -gt 0 ]; do
	case $1 in
	-g) only=$2; shift 2 ;;
	*) ids="$ids $1"; shift ;;
	esac
done
[ -n "$ids" ] || ids=$(cd "$here/repro" && ls *.sh | sed 's/\.sh$//')
fail=0
synced=
for id in $ids; do
	script=$here/repro/$id.sh
	[ -f "$script" ] || { echo "no repro script for $id" >&2; exit 2; }
	guests=$(sed -n 's/^# guests: //p' "$script")
	title=$(sed -n '5p' "$script" | sed 's/^# //')
	for g in $guests; do
		[ -z "$only" ] || [ "$only" = "$g" ] || continue
		export GUEST=$g-compositors
		case " $synced " in *" $g "*) ;; *) "$root/tests/vm/sync.sh" </dev/null; synced="$synced $g" ;; esac
		echo "== $title [$g]"
		"$root/tests/vm/ssh.sh" 'cat > /tmp/repro.sh && sh /tmp/repro.sh </dev/null' <"$script" || fail=1
	done
done
exit $fail
