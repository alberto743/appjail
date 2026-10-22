#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Bring a running guest to the state tests expect (idempotent; needs the guest up).
# Installs tests/vm/packages.txt, the pinned ruff (install-ruff.sh), switches from the cloud kernel (no DRM) to the regular one,
# and gives the test user the video and render groups (access to /dev/dri). Reboots the guest when the kernel changed.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
pk=$(sed 's/#.*//' "$here/packages.txt" | tr -s ' \n' ' ')
ssh_() { "$here/ssh.sh" "$@"; }

ssh_ "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pk"
ssh_ 'sh -s' < "$here/install-ruff.sh"
ssh_ 'sudo rm -f /etc/udev/rules.d/70-bjail-dri.rules; sudo usermod -aG video,render tester'
if ssh_ 'dpkg -l | grep -q "^ii  linux-image-.*cloud"'; then
	ssh_ 'sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq $(dpkg -l | awk "/^ii  linux-image-.*cloud/{print \$2}") && sudo update-grub'
fi
if ssh_ 'uname -r | grep -q cloud'; then
	echo "kernel changed: rebooting the guest"
	ssh_ 'sudo reboot' || true
	sleep 15
	for _ in $(seq 1 60); do ssh_ true 2>/dev/null && break; sleep 5; done
fi
ssh_ 'uname -r; ls /dev/dri 2>&1 | tr "\n" " "; echo'
