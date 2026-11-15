# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A bare Wayland window that logs its keyboard focus and can send a few gtk_shell1 requests (tests/compositors/focus_steal.py).

    python3 focus_client.py OUTFILE

Stdlib only; it speaks the wire protocol itself. OUTFILE gets a line per event (`mapped`, `gtk_shell1:<version>` or
`no-gtk_shell1`, `keyboard-enter`, `keyboard-leave`). Lines on stdin are commands: `present TIME` (gtk_surface1.present),
`notify ID` (gtk_shell1.notify_launch), `request_focus ID` (gtk_surface1.request_focus), `quit`; several, separated by `;`.
"""

import array
import os
import select
import socket
import struct
import sys
import time
from pathlib import Path

WIDTH, HEIGHT = 300, 200


def string(text):
    raw = text.encode() + b"\0"
    return struct.pack("I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def read_string(payload, pos):
    (n,) = struct.unpack_from("I", payload, pos)
    return payload[pos + 4:pos + 4 + max(n - 1, 0)].decode("utf-8", "replace"), pos + 4 + n + (-n % 4)


class Client:
    def __init__(self, out):
        self.out, self.next, self.buf, self.handlers, self.globals = out, 2, b"", {}, {}
        rt, wl = os.environ["XDG_RUNTIME_DIR"], os.environ["WAYLAND_DISPLAY"]
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(str(Path(rt) / wl))

    def log(self, line):
        with open(self.out, "a") as f:
            f.write(line + "\n")

    def new(self, handler=None):
        obj, self.next = self.next, self.next + 1
        self.handlers[obj] = handler
        return obj

    def send(self, obj, opcode, payload=b"", fds=()):
        anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
        self.sock.sendmsg([struct.pack("II", obj, ((8 + len(payload)) << 16) | opcode) + payload], anc)

    def pump(self, timeout=0.5, extra=()):
        ready = select.select([self.sock, *extra], [], [], timeout)[0]
        if self.sock in ready:
            data, anc, _flags, _addr = self.sock.recvmsg(65536, socket.CMSG_LEN(16 * 4))
            if not data:
                raise SystemExit(0)
            for level, kind, raw in anc:  # the keymap of the keyboard arrives as a descriptor: not needed
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    received = array.array("i")
                    received.frombytes(raw[:len(raw) - len(raw) % 4])
                    for fd in received:
                        os.close(fd)
            self.buf += data
            while len(self.buf) >= 8:
                obj, word = struct.unpack("II", self.buf[:8])
                size = word >> 16
                if len(self.buf) < size:
                    break
                payload, self.buf = self.buf[8:size], self.buf[size:]
                handler = self.handlers.get(obj)
                if handler:
                    handler(word & 0xFFFF, payload)
        return ready

    def roundtrip(self):
        done = []
        callback = self.new(lambda opcode, payload: done.append(1))
        self.send(1, 0, struct.pack("I", callback))
        while not done:
            self.pump(2.0)

    def bind(self, interface, version):
        name, offered = self.globals[interface]
        obj = self.new()
        self.send(self.registry, 0, struct.pack("I", name) + string(interface) + struct.pack("II", min(version, offered), obj))
        return obj


def main(out):
    c = Client(out)

    def on_global(opcode, payload):
        if opcode == 0:
            (name,) = struct.unpack_from("I", payload)
            interface, pos = read_string(payload, 4)
            c.globals[interface] = (name, struct.unpack_from("I", payload, pos)[0])

    c.registry = c.new(on_global)
    c.send(1, 1, struct.pack("I", c.registry))
    c.roundtrip()
    compositor, shm, base, seat = c.bind("wl_compositor", 4), c.bind("wl_shm", 1), c.bind("xdg_wm_base", 1), c.bind("wl_seat", 5)
    c.handlers[base] = lambda opcode, payload: c.send(base, 3, payload) if opcode == 0 else None  # ping -> pong

    def on_keyboard(opcode, payload):
        if opcode in (1, 2):
            c.log("keyboard-enter" if opcode == 1 else "keyboard-leave")

    def on_seat(opcode, payload):
        if opcode == 0 and struct.unpack_from("I", payload)[0] & 2 and not c.keyboard:
            c.keyboard = c.new(on_keyboard)
            c.send(seat, 1, struct.pack("I", c.keyboard))

    c.keyboard = None
    c.handlers[seat] = on_seat
    surface = c.new()
    c.send(compositor, 0, struct.pack("I", surface))
    xdg_surface = c.new()
    c.send(base, 2, struct.pack("II", xdg_surface, surface))
    toplevel = c.new()
    c.send(xdg_surface, 1, struct.pack("I", toplevel))
    c.send(toplevel, 2, string("focus-test"))
    configured = []

    def on_configure(opcode, payload):
        if opcode == 0:
            c.send(xdg_surface, 4, payload[:4])  # ack_configure
            configured.append(1)

    c.handlers[xdg_surface] = on_configure
    c.send(surface, 6)  # commit without a buffer: the compositor answers with a configure
    while not configured:
        c.pump(2.0)
    fd = os.memfd_create("focus-client")
    size = WIDTH * HEIGHT * 4
    os.ftruncate(fd, size)
    os.write(fd, b"\x40\x80\xc0\xff" * (WIDTH * HEIGHT))
    pool = c.new()
    c.send(shm, 0, struct.pack("II", pool, size), fds=(fd,))
    buffer = c.new()
    c.send(pool, 0, struct.pack("IiiiII", buffer, 0, WIDTH, HEIGHT, WIDTH * 4, 0))  # argb8888
    c.send(surface, 1, struct.pack("Iii", buffer, 0, 0))
    c.send(surface, 2, struct.pack("iiii", 0, 0, WIDTH, HEIGHT))
    c.send(surface, 6)
    gtk_shell = gtk_surface = None
    if "gtk_shell1" in c.globals:
        gtk_shell = c.bind("gtk_shell1", 3)
        gtk_surface = c.new()
        c.send(gtk_shell, 0, struct.pack("II", gtk_surface, surface))
        c.log(f"gtk_shell1:{min(3, c.globals['gtk_shell1'][1])}")
    else:
        c.log("no-gtk_shell1")
    c.log("mapped")

    def handle(word):
        if not word:
            return
        if gtk_surface is None:
            c.log("error:no gtk_shell1")
        elif word[0] == "present":
            c.send(gtk_surface, 3, struct.pack("I", int(word[1])))
        elif word[0] == "notify":
            c.send(gtk_shell, 3, string(word[1]))
        elif word[0] == "request_focus":
            c.send(gtk_surface, 4, string(word[1]))
        c.log("sent:" + " ".join(word))
        time.sleep(0.05)

    while True:
        if c.pump(0.3, extra=(sys.stdin,)) and sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if not line:
                return
            for part in line.split(";"):
                if part.split() == ["quit"]:
                    return
                handle(part.split())


if __name__ == "__main__":
    main(sys.argv[1])
