# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

# The measurements of docs/develop/a11y-evidence.md, in the Debian guest (needs tests/vm/packages.txt: weston, gir1.2-gtk-3.0,
# gir1.2-atspi-2.0, python3-pyqt6, python3-dbus). Copy this directory to ~/a11y in the guest first; it needs ~/appjail
# (tests/vm/sync.sh). Prints what each scenario saw; read it next to the evidence page.
set -u
cd ~/a11y
H="python3 harness.py"
export WAYLAND_DISPLAY=wl-a11y
pgrep -x weston >/dev/null || { setsid weston --backend=headless --socket=$WAYLAND_DISPLAY >weston.log 2>&1 </dev/null & sleep 3; }
status() { gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus --method org.freedesktop.DBus.Properties.Set \
	org.a11y.Status IsEnabled "<$1>" >/dev/null; }
status true

echo "== 1. a GTK 3 and a Qt 6 app behind the proxy are seen by a screen reader (tree) and send it events"
for tk in gtk qt; do
	python3 at.py events 8 &
	events=$!
	sleep 1
	$H proxy python3 /a11y/apps.py $tk 9 >/dev/null 2>&1 &
	sleep 3; python3 at.py tree apps 2>&1 | grep -v dbind; wait $events
done

echo "== 2. a hostile client behind the proxy, with a neighbour app running"
$H proxy python3 /a11y/apps.py gtk 14 >/dev/null 2>&1 &
sleep 3
python3 at.py keys 9 &
keys=$!
sleep 2
$H proxy python3 /a11y/probe.py
wait $keys

echo "== 3. the same client on the raw bus"
$H raw python3 /a11y/probe.py

echo "== 4. which of Flatpak's rules a toolkit needs (tree nodes seen with one rule removed)"
for tk in gtk qt; do
	for drop in "" --sloppy-names GetRegisteredEvents GetKeystrokeListeners NotifyListeners Socket.Unembed \
		EventListenerRegistered GetDeviceEventListeners Socket.Embed; do
		EXP_DROP=$drop $H proxy python3 /a11y/apps.py $tk 6 >/dev/null 2>&1 &
		app=$!
		sleep 3
		echo "$tk drop=[$drop] nodes: $(python3 at.py tree apps 2>&1 | grep -c -E 'button|frame')"
		wait $app
	done
done

echo "== 5. no screen reader (IsEnabled false): does the app still use the bus?"
status false
timeout 10 dbus-monitor --address unix:path=/run/user/1000/at-spi/bus >mon.log 2>&1 &
sleep 1
$H proxy python3 /a11y/apps.py gtk 4 >/dev/null 2>&1
sleep 1; echo "Socket.Embed calls with IsEnabled=false: $(grep -c 'member=Embed' mon.log)"
status true
