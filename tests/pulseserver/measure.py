# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Whether appjail can tell which program serves the host's Pulse socket, and how long it takes (guest only; not run by
pytest). The results are on docs/decisions/desktop/pulseaudio.md.

Usage, in a guest after tests/vm/sync.sh: tests/vm/ssh.sh 'python3 -I - UNIT' < tests/pulseserver/measure.py, where UNIT
is pipewire-pulse (debian, ubuntu, fedora) or pulseaudio (debian-pulse). It stops and starts that user unit: the server
running, three cold starts (socket activation), six cold starts under load (eight busy processes per CPU and a disk
writer), a socket file left with no server, and the socket started again. The start counter is reset and cold starts are
11 s apart: systemd allows five starts in 10 s, and hitting that limit would measure the limit, not the server.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.expanduser("~/appjail/src"))
from appjail import audiomode

env = dict(os.environ)
sock = audiomode.host_pulse(env)
unit = sys.argv[1] if len(sys.argv) > 1 else "pipewire-pulse"


def sh(cmd):
    subprocess.run(cmd, shell=True, capture_output=True)


def measure(label):
    t = time.monotonic()
    server = audiomode.host_server(sock)
    took = time.monotonic() - t
    st = subprocess.run(f"systemctl --user is-active {unit}.socket {unit}.service | tr '\\n' ' '; "
                        f"systemctl --user show -p Result --value {unit}.socket", shell=True, capture_output=True,
                        text=True).stdout.strip().replace("\n", " ")
    print(f"{label:28} server={server!s:16} {took:5.2f}s  [{st}]", flush=True)
    return server, took


def cold(label, n):
    out = []
    for i in range(n):
        sh(f"systemctl --user stop {unit}.service; systemctl --user reset-failed {unit}.socket {unit}.service")
        time.sleep(11)  # systemd's start limit is 5 starts in 10 s
        out.append(measure(f"{label} #{i + 1}"))
    return out


print("socket", sock, "unit", unit, "cpus", os.cpu_count())
measure("running")
cold("cold start", 3)

hogs = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(os.cpu_count() * 8)]
io = subprocess.Popen(["sh", "-c", "while :; do dd if=/dev/zero of=/tmp/io.bin bs=1M count=256 conv=fsync 2>/dev/null; done"])
try:
    time.sleep(2)
    cold("cold start, loaded", 6)
finally:
    for p in [*hogs, io]:
        p.kill()
    sh("rm -f /tmp/io.bin")

sh(f"systemctl --user stop {unit}.socket {unit}.service")
time.sleep(1)
print("socket file left:", os.path.exists(sock), "is_socket:", audiomode.host_pulse(env) is not None)
measure("no server (stale file)")
sh(f"systemctl --user start {unit}.socket")
time.sleep(1)
measure("socket back, cold")
