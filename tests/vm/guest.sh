#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Sourced by the other scripts: which guest they work on and where its files are. GUEST=debian (default), ubuntu or
# debian-pulse; they can run side by side (own overlay, key, ssh port, console log under vm/<guest>/).
#   debian: Debian 13, the reference guest, ssh on 127.0.0.1:2222
#   ubuntu: Ubuntu 26.04 (resolute), the runner's operating system, ssh on 127.0.0.1:2223
#   debian-pulse: Debian 13 with PulseAudio proper instead of pipewire-pulse (packages.sh), for tests/test_pulseaudio.py; it
#     uses the image downloaded for debian, ssh on 127.0.0.1:2224
here=$(cd "$(dirname "$0")" && pwd)
GUEST=${GUEST:-debian}
vm_root=${VM_DIR:-$here/../../vm}
case $GUEST in
debian|debian-pulse)
	base_url=https://cloud.debian.org/images/cloud/trixie/latest
	img=debian-13-genericcloud-amd64.qcow2
	sums=SHA512SUMS sumtool=sha512sum
	port=2222 cloud_kernel=cloud kernel_pkg=linux-image-amd64
	[ "$GUEST" = debian-pulse ] && port=2224 ;;
ubuntu)
	base_url=https://cloud-images.ubuntu.com/resolute/current
	img=resolute-server-cloudimg-amd64.img
	sums=SHA256SUMS sumtool=sha256sum
	port=2223 cloud_kernel=kvm kernel_pkg=linux-image-virtual ;;
*) echo "GUEST must be debian, ubuntu or debian-pulse" >&2; exit 2 ;;
esac
vm=$vm_root/$GUEST
run=$vm/run
dl=$vm/dl
[ "$GUEST" = debian-pulse ] && dl=$vm_root/debian/dl  # the same image: no second download
