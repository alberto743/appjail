# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""AppImage file checks."""

ELF_MAGIC = b"\x7fELF"


class NotAnAppImage(Exception):
    pass


def appimage_type(path):
    """Return 2 for a type-2 AppImage; raise NotAnAppImage otherwise (type 1 is unsupported)."""
    with open(path, "rb") as f:
        head = f.read(11)
    if len(head) < 11 or head[:4] != ELF_MAGIC:
        raise NotAnAppImage("not an ELF executable")
    if head[8:10] != b"AI":
        raise NotAnAppImage("no AppImage marker (not an AppImage)")
    if head[10] == 2:
        return 2
    raise NotAnAppImage(f"AppImage type {head[10]} is not supported (only type 2)")
