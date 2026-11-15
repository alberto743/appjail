#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# The package names of packages.txt, one per line, without comments. GUEST=debian-pulse also gets PulseAudio proper, which
# provision.sh makes the host's sound server (PipeWire's units masked); pipewire-pulse stays installed there for the private
# graph. The *-compositors guests also get packages-compositors.txt, without hyprland on Debian (it is in backports:
# provision.sh). The fedora guests get the Fedora names of packages-fedora.map instead of the Debian ones.
here=$(dirname "$0")
{
	cat "$here/packages.txt"
	case "${GUEST:-}" in *-compositors) cat "$here/packages-compositors.txt" ;; esac
} | sed 's/#.*//' | tr -s ' \t' '\n\n' | grep -v '^$' \
	| if [ "${GUEST:-}" = debian-pulse ]; then sed 's/^pipewire-pulse$/pipewire-pulse\npulseaudio/'; else cat; fi \
	| if [ "${GUEST:-}" = debian-compositors ]; then grep -v '^hyprland$'; else cat; fi \
	| case "${GUEST:-}" in fedora*) awk -v map="$here/packages-fedora.map" '
		BEGIN { while ((getline l < map) > 0) { sub(/#.*/, "", l); n = split(l, f, " "); if (n) { m[f[1]] = 1; v = ""; for (i = 2; i <= n; i++) v = v " " f[i]; r[f[1]] = v } } }
		{ if ($0 in m) { n = split(r[$0], f, " "); for (i = 1; i <= n; i++) print f[i] } else print }' ;; *) cat ;; esac
