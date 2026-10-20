# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Snappy block decompressor (raw format, no framing), bounded by an output limit.

GitHub stores attestation bundles Snappy-compressed. The input is untrusted: every length and
offset is checked and the output never exceeds `max_out`.
"""


class SnappyError(ValueError):
    pass


def decompress(data, max_out=4 * 1024 * 1024):
    pos, shift, length = 0, 0, 0
    while True:
        if pos >= len(data) or shift > 28:
            raise SnappyError("bad length header")
        b = data[pos]
        pos += 1
        length |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    if length > max_out:
        raise SnappyError("decompressed size exceeds the limit")
    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:  # literal
            n = tag >> 2
            if n >= 60:
                extra = n - 59
                if pos + extra > len(data):
                    raise SnappyError("truncated literal length")
                n = int.from_bytes(data[pos:pos + extra], "little")
                pos += extra
            n += 1
            if pos + n > len(data) or len(out) + n > length:
                raise SnappyError("literal out of bounds")
            out += data[pos:pos + n]
            pos += n
            continue
        if kind == 1:
            if pos >= len(data):
                raise SnappyError("truncated copy")
            n = ((tag >> 2) & 7) + 4
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        else:
            size = 2 if kind == 2 else 4
            if pos + size > len(data):
                raise SnappyError("truncated copy")
            n = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + size], "little")
            pos += size
        if offset == 0 or offset > len(out) or len(out) + n > length:
            raise SnappyError("copy out of bounds")
        for _ in range(n):  # may overlap its own output
            out.append(out[-offset])
    if len(out) != length:
        raise SnappyError("size mismatch")
    return bytes(out)
