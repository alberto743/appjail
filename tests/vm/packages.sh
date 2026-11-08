#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# The package names of packages.txt, one per line, without comments. GUEST=debian-pulse has PulseAudio proper where the
# others have pipewire-pulse (the two conflict).
sed 's/#.*//' "$(dirname "$0")/packages.txt" | tr -s ' \t' '\n\n' | grep -v '^$' \
	| if [ "${GUEST:-}" = debian-pulse ]; then sed 's/^pipewire-pulse$/pulseaudio/'; else cat; fi
