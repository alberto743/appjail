#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# The package names of packages.txt, one per line, without comments. GUEST=debian-pulse has PulseAudio proper where the
# others have pipewire-pulse (the two conflict); the *-compositors guests also get packages-compositors.txt.
here=$(dirname "$0")
{
	cat "$here/packages.txt"
	case "${GUEST:-}" in *-compositors) cat "$here/packages-compositors.txt" ;; esac
} | sed 's/#.*//' | tr -s ' \t' '\n\n' | grep -v '^$' \
	| if [ "${GUEST:-}" = debian-pulse ]; then sed 's/^pipewire-pulse$/pulseaudio/'; else cat; fi \
	| if [ "${GUEST:-}" = debian-compositors ]; then grep -v '^hyprland$'; else cat; fi  # Debian's is in backports: provision.sh
