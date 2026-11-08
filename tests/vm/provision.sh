#!/bin/sh
# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# Bring a running guest to the state tests expect (idempotent; needs the guest up).
# Installs tests/vm/packages.txt, the pinned ruff (install-ruff.sh), switches from the cloud kernel (no DRM) to the regular one
# (linux-image-amd64 on Debian, linux-image-virtual on Ubuntu; guest.sh) and gives the test user the video and render groups
# (access to /dev/dri). Reboots the guest when the kernel changed. GUEST=debian|ubuntu|debian-pulse (which also makes PulseAudio the
# host's sound server, with a sine source as the microphone).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
. "$here/guest.sh"
pk="$("$here/packages.sh" | grep -v '^linux-image' | tr '\n' ' ') $kernel_pkg"
ssh_() { "$here/ssh.sh" "$@"; }

case $GUEST in *-compositors)  # the GNOME stack recommends plymouth, whose initramfs hook fails in a VM and leaves the kernel unconfigured
	ssh_ 'sudo mkdir -p /etc/initramfs-tools/hooks && printf "#!/bin/sh\n[ \"\$1\" = prereqs ] && echo\nexit 0\n" | sudo tee /etc/initramfs-tools/hooks/plymouth >/dev/null && sudo chmod +x /etc/initramfs-tools/hooks/plymouth' ;;
esac
ssh_ "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pk"
if [ "$GUEST" = debian-compositors ]; then  # Hyprland is only in backports, whose dependencies apt takes only on request; best effort
	ssh_ 'sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -t trixie-backports hyprland' || echo "hyprland: not installed (backports)"
fi
ssh_ 'sh -s' < "$here/install-ruff.sh"
if [ "${GUEST%%-*}" = ubuntu ]; then  # as the CI action does: Ubuntu restricts unprivileged user namespaces through AppArmor
	ssh_ 'sudo sysctl -qw kernel.apparmor_restrict_unprivileged_userns=0 && echo kernel.apparmor_restrict_unprivileged_userns=0 | sudo tee /etc/sysctl.d/99-appjail.conf >/dev/null'
fi
if [ "$GUEST" = debian-pulse ]; then  # PulseAudio proper is the host's sound server; a sine source stands in for a microphone
	ssh_ 'sudo systemctl --global mask pipewire.socket pipewire.service pipewire-pulse.socket pipewire-pulse.service wireplumber.service >/dev/null 2>&1
		rm -f ~/.config/systemd/user/pipewire*.s* ~/.config/systemd/user/wireplumber.service
		sudo mkdir -p /etc/pulse/default.pa.d
		printf "load-module module-sine-source source_name=host-mic frequency=440 rate=48000\nset-default-source host-mic\n" | sudo tee /etc/pulse/default.pa.d/appjail-test.pa >/dev/null
		systemctl --user daemon-reload
		systemctl --user stop pipewire.socket pipewire-pulse.socket pipewire.service pipewire-pulse.service wireplumber.service pulseaudio.service 2>/dev/null
		systemctl --user restart pulseaudio.socket'
fi
ssh_ 'sudo usermod -aG video,render tester'
if ssh_ 'dpkg -l | grep -q "^ii  linux-image-.*'$cloud_kernel'"'; then
	ssh_ 'sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq $(dpkg -l | awk "/^ii  linux-image-.*'$cloud_kernel'/{print \$2}") && sudo update-grub'
fi
reboot_guest() {
	echo "$1: rebooting the guest"
	ssh_ 'sudo reboot' || true
	sleep 15
	for _ in $(seq 1 60); do ssh_ true 2>/dev/null && break; sleep 5; done
}
if ssh_ "uname -r | grep -q $cloud_kernel"; then
	reboot_guest "kernel changed"
elif ! ssh_ 'id -Gn | grep -qw render'; then  # the running sessions do not have the groups yet (seen on Ubuntu)
	reboot_guest "group membership not active"
fi
ssh_ 'uname -r; ls /dev/dri 2>&1 | tr "\n" " "; echo'
