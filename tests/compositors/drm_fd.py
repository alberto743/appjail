# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Does binding `wp_drm_lease_device_v1` hand a client an open DRM file descriptor?

    python3 tests/compositors/drm_fd.py --out /tmp/drm-fd.json [--only mutter,sway]

For each compositor that lists the global, on its own socket and on the restricted one: a stdlib client binds it and
reports the descriptors that arrive with the events, and what they are (`/proc/self/fd` link, device numbers). The protocol
says the descriptor is non-master: it is the node `gpu` binds into a jail, handed to a client with nothing but a window.
Guests only.
"""

import argparse
import array
import json
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe

from appjail import wayland

INTERFACE = "wp_drm_lease_device_v1"
DISPLAY, REGISTRY, CALLBACK_1, DEVICE, CALLBACK_2 = 1, 2, 3, 4, 5


def message(obj, opcode, payload=b""):
    return struct.pack("II", obj, ((8 + len(payload)) << 16) | opcode) + payload


def attempt(path):
    sock = socket.socket(socket.AF_UNIX)
    sock.connect(str(path))
    sock.settimeout(5)
    sock.sendall(message(DISPLAY, 1, struct.pack("I", REGISTRY)) + message(DISPLAY, 0, struct.pack("I", CALLBACK_1)))
    buf, offered = b"", {}
    while CALLBACK_1 not in {o for o, _ in offered.get("_seen", [])}:
        buf += sock.recv(65536)
        while len(buf) >= 8:
            obj, word = struct.unpack("II", buf[:8])
            size = word >> 16
            if len(buf) < size:
                break
            body, buf = buf[8:size], buf[size:]
            offered.setdefault("_seen", []).append((obj, word & 0xFFFF))
            if obj == REGISTRY and word & 0xFFFF == 0:
                name, n = struct.unpack_from("II", body)
                iface = body[8:8 + n - 1].decode()
                offered[iface] = (name, struct.unpack_from("I", body, 8 + n + (-n % 4))[0])
    if INTERFACE not in offered:
        return {"listed": False}
    name, _version = offered[INTERFACE]
    raw = INTERFACE.encode() + b"\0"
    sock.sendall(message(REGISTRY, 0, struct.pack("I", name) + struct.pack("I", len(raw)) + raw + b"\0" * (-len(raw) % 4)
                         + struct.pack("II", 1, DEVICE)) + message(DISPLAY, 0, struct.pack("I", CALLBACK_2)))
    fds, done, buf = [], False, b""
    while not done:
        data, ancillary, _flags, _address = sock.recvmsg(65536, socket.CMSG_LEN(16 * 4))
        for level, kind, raw_fds in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                received = array.array("i")
                received.frombytes(raw_fds[:len(raw_fds) - len(raw_fds) % 4])
                fds += list(received)
        buf += data
        while len(buf) >= 8:
            obj, word = struct.unpack("II", buf[:8])
            size = word >> 16
            if len(buf) < size:
                break
            buf = buf[size:]
            done = done or obj == CALLBACK_2
    found = []
    for fd in fds:
        st = os.fstat(fd)
        found.append({"node": os.readlink(f"/proc/self/fd/{fd}"), "device": [os.major(st.st_rdev), os.minor(st.st_rdev)]})
        os.close(fd)
    return {"listed": True, "descriptors": found}


def evaluate(key):
    packages, argv_for, extra = probe.COMPOSITORS[key]
    result = {"version": probe.package_version(*packages)}
    if not probe.installed(argv_for(None)):
        result["status"] = "not installed"
        return result
    with probe.Session() as session, open(session.rt / "compositor.log", "w") as logfile:
        proc = subprocess.Popen(argv_for(session), env=session.env(extra), stdout=logfile, stderr=logfile, start_new_session=True)
        try:
            before = probe.sockets(session.rt)
            display = probe.wait_for_display(proc, session.rt, before)
            if display is None:
                result["status"] = "did not start"
                return result
            result["status"] = "ok"
            result["full"] = attempt(session.rt / display)
            env = {"XDG_RUNTIME_DIR": str(session.rt), "WAYLAND_DISPLAY": display}
            if probe.SECURITY_CONTEXT in probe.registry(session.rt, display):
                with wayland.RestrictedSocket(env, app_id="drm-fd") as path:
                    result["restricted"] = attempt(path) if path else "none"
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {type(e).__name__}: {e}"
        finally:
            probe.stop(proc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    keys = [k for k in probe.COMPOSITORS if not args.only or k in args.only.split(",")]
    data = {"distro": probe.distro(), "compositors": {}}
    for key in keys:
        print(f"== {key}", flush=True)
        data["compositors"][key] = evaluate(key)
    print(json.dumps(data, indent=1))
    Path(args.out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
