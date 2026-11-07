#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Create the appjail test guest from scratch (works on any machine with qemu, KVM,
# cloud-localds and curl). Safe to re-run: existing files are kept unless --force.
#
# Host packages (Debian 13): qemu-system-x86 qemu-utils cloud-image-utils
# Downloads one binary per guest: GUEST=debian (default) the Debian 13 cloud image (~340 MB), GUEST=ubuntu the Ubuntu 26.04
# cloud image (~860 MB). The checksum is verified against the distribution's own SHA512SUMS / SHA256SUMS (fetched over TLS) before
# use. Run it only when you agree to that download.
#
# Env: GUEST, VM_DIR (default <project>/vm), PACKAGES (guest packages, default tests/vm/packages.txt without the kernel line;
# provision.sh installs the kernel).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
. "$here/guest.sh"
packages=${PACKAGES:-$("$here/packages.sh" | grep -v '^linux-image' | tr '\n' ' ' | sed 's/ $//')}
force=0; [ "${1:-}" = --force ] && force=1

mkdir -p "$vm/dl" "$vm/run"

if [ ! -f "$vm/dl/$img" ]; then
	curl -fsSL -o "$vm/dl/$sums" "$base_url/$sums"
	curl -fsSL -o "$vm/dl/$img" "$base_url/$img"
	(cd "$vm/dl" && grep "[ *]$img\$" "$sums" | "$sumtool" -c -)
fi

if [ "$force" = 1 ] || [ ! -f "$vm/run/disk.qcow2" ]; then
	rm -f "$vm/run/disk.qcow2" "$vm/run/seed.iso" "$vm/run/known_hosts" "$vm/run/console.log"
	qemu-img create -q -f qcow2 -F qcow2 -b "../dl/$img" "$vm/run/disk.qcow2" 20G
	[ -f "$vm/run/id_appjail" ] || ssh-keygen -q -t ed25519 -N '' -C "appjail-$GUEST" -f "$vm/run/id_appjail"
	sed -e "s|@SSH_PUBKEY@|$(cat "$vm/run/id_appjail.pub")|" -e "s|@PACKAGES@|$(echo "$packages" | sed 's/ /, /g')|" \
		-e "s|@HOSTNAME@|appjail-$GUEST|" "$here/user-data.tmpl" > "$vm/run/user-data"
	printf 'instance-id: appjail-%s-%s\nlocal-hostname: appjail-%s\n' "$GUEST" "$(date +%s)" "$GUEST" > "$vm/run/meta-data"
	cloud-localds "$vm/run/seed.iso" "$vm/run/user-data" "$vm/run/meta-data"
fi
echo "guest $GUEST ready: run tests/vm/start.sh, wait for cloud-init (tests/vm/ssh.sh 'cloud-init status --wait'), then tests/vm/provision.sh"
