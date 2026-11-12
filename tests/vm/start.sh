#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Boot an appjail test guest (GUEST=debian, ubuntu, debian-pulse, debian-compositors or ubuntu-compositors, see guest.sh; KVM,
# user-mode networking, ssh on 127.0.0.1 at the port guest.sh gives).
# Images live in ../../vm; nothing here touches the host outside this directory.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
. "$here/guest.sh"
exec qemu-system-x86_64 \
	-enable-kvm -cpu host -smp 4 -m 4096 \
	-drive file="$run/disk.qcow2",if=virtio \
	-drive file="$run/seed.iso",if=virtio,format=raw,readonly=on \
	-nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$port-:22 \
	-device virtio-gpu-pci \
	-display none -serial file:"$run/console.log" \
	-pidfile "$run/qemu.pid" -daemonize
