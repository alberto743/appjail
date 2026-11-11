# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""A canonical copy of an untrusted PNG, made without decoding a pixel.

An app's icon is written where the desktop's own image loaders read it (the shell, the file manager, the launcher), so a
crafted file is a way into those programs. This module reads the PNG as data only: it checks every chunk and its CRC,
inflates the image data with a hard size limit, checks that it is exactly what the header promises (every row has a legal
filter byte), and writes a new file that has only the critical chunks and the transparency chunk, with the data deflated
again. The loaders then see a well-formed minimal file instead of whatever the app shipped (text chunks, embedded profiles,
trailing bytes, split or oversized chunks, stray data). Pixel values are not interpreted, so a loader bug triggered by the
pixels themselves is not removed; an unusual file is refused rather than repaired.
"""

import struct
import zlib

MAGIC = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
TRNS_LENGTH = {0: 2, 2: 6}  # for the other colour types a tRNS holds at most one byte per palette entry


def _chunks(data):
    """[(type, body)] of a PNG whose structure is complete and whose CRCs are right, else None."""
    pos, out = 8, []
    while pos + 12 <= len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        end = pos + 8 + length
        if length > len(data) or end + 4 > len(data) or struct.unpack_from(">I", data, end)[0] != zlib.crc32(kind + body):
            return None
        out.append((kind, body))
        pos = end + 4
        if kind == b"IEND":
            return out if pos == len(data) and not body else None
    return None


def _rows(width, height, interlace, bits):
    """[(row count, row length in bytes)] of each pass of the image."""
    if not interlace:
        return [(height, (width * bits + 7) // 8)]
    passes = []
    for x0, y0, dx, dy in ADAM7:
        w, h = (width - x0 + dx - 1) // dx, (height - y0 + dy - 1) // dy
        if w > 0 and h > 0:
            passes.append((h, (w * bits + 7) // 8))
    return passes


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def sanitize(data, lo=16, hi=1024):
    """(png bytes, size) for a square PNG whose side is in lo..hi and whose data is exactly what its header describes,
    else None."""
    if data[:8] != MAGIC:
        return None
    chunks = _chunks(data)
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        return None
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if (width != height or not lo <= width <= hi or colour not in DEPTHS or depth not in DEPTHS[colour]
            or compression or filtering or interlace not in (0, 1)):
        return None
    palette = trns = None
    idat, closed = [], False  # the image data is one run of IDAT chunks
    for kind, body in chunks[1:-1]:
        if kind == b"IDAT":
            if closed:
                return None
            idat.append(body)
            continue
        closed = closed or bool(idat)
        if kind in (b"PLTE", b"tRNS"):
            if idat or (kind == b"PLTE" and palette is not None) or (kind == b"tRNS" and trns is not None):
                return None
            if kind == b"PLTE":
                palette = body
            else:
                trns = body
        elif kind[0] & 0x20 == 0:  # an unknown critical chunk, or IHDR/IEND where they cannot be
            return None
    if not idat:
        return None
    if colour == 3:
        if not palette or len(palette) % 3 or len(palette) // 3 > 1 << depth:
            return None
        if trns is not None and len(trns) > len(palette) // 3:
            return None
    elif colour in (0, 2):
        if trns is not None and len(trns) != TRNS_LENGTH[colour]:
            return None
    else:
        trns = None
    if colour != 3:
        if palette is not None and (len(palette) % 3 or len(palette) > 768 or colour in (0, 4)):
            return None
        palette = None
    passes = _rows(width, height, interlace, CHANNELS[colour] * depth)
    expected = sum(rows * (1 + length) for rows, length in passes)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(b"".join(idat), expected + 1)
    except zlib.error:
        return None
    if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        return None
    pos = 0
    for rows, length in passes:
        for _ in range(rows):
            if raw[pos] > 4:
                return None
            pos += 1 + length
    out = [MAGIC, _chunk(b"IHDR", chunks[0][1])]
    if palette is not None:
        out.append(_chunk(b"PLTE", palette))
    if trns is not None:
        out.append(_chunk(b"tRNS", trns))
    out += [_chunk(b"IDAT", zlib.compress(raw, 9)), _chunk(b"IEND", b"")]
    return b"".join(out), (width, height)
