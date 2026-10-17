#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Boot the bjail test guest (KVM, user-mode networking, ssh on 127.0.0.1:2222).
# Images live in ../../vm; nothing here touches the host outside this directory.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
run="$here/../../vm/run"
exec qemu-system-x86_64 \
	-enable-kvm -cpu host -smp 4 -m 4096 \
	-drive file="$run/disk.qcow2",if=virtio \
	-drive file="$run/seed.iso",if=virtio,format=raw,readonly=on \
	-nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:2222-:22 \
	-display none -serial file:"$run/console.log" \
	-pidfile "$run/qemu.pid" -daemonize
