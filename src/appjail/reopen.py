# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The granted paths opened again inside pasta's namespace, refused unless they are still the files that were checked.

The launcher opens and checks each grant and binds the descriptor (runtimejail.Grants), but pasta closes every inherited
descriptor. So this exec wrapper runs between pasta and bwrap, as `python3 -I reopen.py COUNT (FD DEV INO PATH)... COMMAND...`:
it opens each path, compares the device and inode with what the launcher recorded, gives the descriptor the number FD
that bwrap's arguments name, and execs COMMAND. The comparison follows the open, so nothing can change in between; the
launcher keeps its own descriptors open meanwhile, so the inode numbers cannot be reused.
Standalone: stdlib only, no appjail imports.
"""

import os
import sys

FIELDS = 4
REFUSED, EXEC_FAILED = 126, 127


def wrap(items, argv):
    """argv preceded by the wrapper; items: (descriptor number for bwrap, device, inode, path)."""
    return [sys.executable, "-I", os.path.abspath(__file__), str(len(items)), *(str(f) for item in items for f in item), *argv]


def main(argv):
    count = int(argv[1])
    command = argv[2 + count * FIELDS:]
    for i in range(count):
        number, dev, ino, path = argv[2 + i * FIELDS:2 + (i + 1) * FIELDS]
        try:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            st = os.fstat(fd)
        except OSError as e:
            print(f"appjail: granted path {path!r} changed before the jail started: {e.strerror}", file=sys.stderr)
            return REFUSED
        if (st.st_dev, st.st_ino) != (int(dev), int(ino)):
            print(f"appjail: granted path {path!r} changed before the jail started; refused", file=sys.stderr)
            return REFUSED
        os.dup2(fd, int(number))
        os.set_inheritable(int(number), True)
    try:
        os.execvp(command[0], command)
    except OSError as e:
        print(f"appjail: cannot run {command[0]}: {e}", file=sys.stderr)
        return EXEC_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
