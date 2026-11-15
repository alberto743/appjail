#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0
# guests: fedora
# 06: the definition of xapp_shell_v1 in Muffin 6.8 says the icon may be an absolute path the shell uses (source only)
set -u
D=$(mktemp -d) && cd "$D" &&
dnf download --source --enablerepo=fedora-source,updates-source muffin >/dev/null 2>&1 &&
mkdir x && cd x && rpm2cpio ../muffin-*.src.rpm | cpio -idm >/dev/null 2>&1 &&
tar -xf muffin-*.tar.gz --wildcards '*/src/wayland/protocol/xapp-shell.xml' &&
echo "  $(ls ../muffin-*.src.rpm | xargs -n1 basename)" &&
grep -h -A4 'name="set_icon_name"' muffin-*/src/wayland/protocol/xapp-shell.xml | sed 's/^ */    /' &&
grep -q 'absolute path to an icon file' muffin-*/src/wayland/protocol/xapp-shell.xml && echo "  REPRODUCED" || { echo "  NOT REPRODUCED"; exit 1; }
