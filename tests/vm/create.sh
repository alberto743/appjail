#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Create the bjail test guest from scratch (works on any machine with qemu, KVM,
# cloud-localds and curl). Safe to re-run: existing files are kept unless --force.
#
# Host packages (Debian 13): qemu-system-x86 qemu-utils cloud-image-utils
# Downloads one binary (the Debian cloud image, ~340 MB); the SHA512 is verified
# against Debian's SHA512SUMS before use. Run it only when you agree to that download.
#
# Env: VM_DIR (default <project>/vm), PACKAGES (guest packages, default tests/vm/packages.txt).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
vm=${VM_DIR:-$here/../../vm}
packages=${PACKAGES:-$(sed 's/#.*//' "$here/packages.txt" | tr -s ' \n' ' ' | sed 's/^ *//; s/ *$//')}
base_url=https://cloud.debian.org/images/cloud/trixie/latest
img=debian-13-genericcloud-amd64.qcow2
force=0; [ "${1:-}" = --force ] && force=1

mkdir -p "$vm/dl" "$vm/run"

if [ ! -f "$vm/dl/$img" ]; then
	curl -fSL -o "$vm/dl/SHA512SUMS" "$base_url/SHA512SUMS"
	curl -fSL -o "$vm/dl/$img" "$base_url/$img"
	(cd "$vm/dl" && grep " $img\$" SHA512SUMS | sha512sum -c -)
fi

if [ "$force" = 1 ] || [ ! -f "$vm/run/disk.qcow2" ]; then
	rm -f "$vm/run/disk.qcow2" "$vm/run/seed.iso" "$vm/run/known_hosts" "$vm/run/console.log"
	qemu-img create -q -f qcow2 -F qcow2 -b "../dl/$img" "$vm/run/disk.qcow2" 20G
	[ -f "$vm/run/id_bjail" ] || ssh-keygen -q -t ed25519 -N '' -C bjail-vm -f "$vm/run/id_bjail"
	sed -e "s|@SSH_PUBKEY@|$(cat "$vm/run/id_bjail.pub")|" -e "s|@PACKAGES@|$(echo "$packages" | sed 's/ /, /g')|" \
		"$here/user-data.tmpl" > "$vm/run/user-data"
	printf 'instance-id: bjail-vm-%s\nlocal-hostname: bjail-vm\n' "$(date +%s)" > "$vm/run/meta-data"
	cloud-localds "$vm/run/seed.iso" "$vm/run/user-data" "$vm/run/meta-data"
fi
echo "guest ready: run tests/vm/start.sh, wait for cloud-init (tests/vm/ssh.sh 'cloud-init status --wait'), then tests/vm/provision.sh"
