#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Sourced by the other scripts: which guest they work on and where its files are. GUEST=debian (default), ubuntu,
# debian-pulse, debian-compositors, ubuntu-compositors, fedora or fedora-compositors; they can run side by side (own overlay, key, ssh port, console log
# under vm/<guest>/).
#   debian: Debian 13, the reference guest, ssh on 127.0.0.1:2222
#   ubuntu: Ubuntu 26.04 (resolute), the runner's operating system, ssh on 127.0.0.1:2223
#   debian-pulse: Debian 13 with PulseAudio proper instead of pipewire-pulse (packages.sh), for tests/test_pulseaudio.py; it
#     uses the image downloaded for debian, ssh on 127.0.0.1:2224
#   fedora: Fedora 45, the third supported system, ssh on 127.0.0.1:2227; SELinux stays enforcing
#   debian-compositors, ubuntu-compositors, fedora-compositors: the base guest plus the Wayland compositors the distribution
#     packages (packages-compositors.txt), for tests/compositors/; same image as the base, ssh on 127.0.0.1:2225, :2226 and :2228
here=$(cd "$(dirname "$0")" && pwd)
GUEST=${GUEST:-debian}
vm_root=${VM_DIR:-$here/../../vm}
case $GUEST in
debian|debian-pulse|debian-compositors)
	base_url=https://cloud.debian.org/images/cloud/trixie/latest
	img=debian-13-genericcloud-amd64.qcow2
	sums=SHA512SUMS sumtool=sha512sum
	port=2222 cloud_kernel=cloud kernel_pkg=linux-image-amd64
	if [ "$GUEST" = debian-pulse ]; then port=2224; fi
	if [ "$GUEST" = debian-compositors ]; then port=2225; fi ;;
ubuntu|ubuntu-compositors)
	base_url=https://cloud-images.ubuntu.com/resolute/current
	img=resolute-server-cloudimg-amd64.img
	sums=SHA256SUMS sumtool=sha256sum
	port=2223 cloud_kernel=kvm kernel_pkg=linux-image-virtual
	if [ "$GUEST" = ubuntu-compositors ]; then port=2226; fi ;;
fedora|fedora-compositors)  # the images are numbered by build, so the release is pinned here with its CHECKSUM file
	base_url=https://download.fedoraproject.org/pub/fedora/linux/releases/45/Cloud/x86_64/images
	img=Fedora-Cloud-Base-Generic-45-1.4.x86_64.qcow2
	sums=Fedora-Cloud-45-1.4-x86_64-CHECKSUM sumtool=sha256sum
	port=2227 cloud_kernel=none kernel_pkg=
	if [ "$GUEST" = fedora-compositors ]; then port=2228; fi ;;
*) echo "GUEST must be debian, ubuntu, fedora, debian-pulse, debian-compositors, ubuntu-compositors or fedora-compositors" >&2; exit 2 ;;
esac
vm=$vm_root/$GUEST
run=$vm/run
dl=$vm/dl
case $GUEST in  # a variant uses the image of its base: no second download
debian-pulse|debian-compositors) dl=$vm_root/debian/dl ;;
ubuntu-compositors) dl=$vm_root/ubuntu/dl ;;
fedora-compositors) dl=$vm_root/fedora/dl ;;
esac
