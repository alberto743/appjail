# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Images for the window, made in Python: the theme's shapes, the logo, a stand-in for an app without an icon, and an
app's own icon decoded, scaled and encoded again. No tkinter and no I/O.

An app's icon is decoded here, in memory-safe Python, after `pngclean.sanitize` has checked its structure; the window
gives Tk only the small PNG this module writes, so Tk's own decoder never reads bytes that came from an app."""

import math
import struct
import zlib

from .. import pngclean

# --- encoding ---------------------------------------------------------------------------------------------------------


def encode_png(width, height, rgba):
    """A PNG (8-bit RGBA, no filter) of `rgba`, width*height*4 bytes."""
    stride = width * 4
    raw = b"".join(b"\0" + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(height))
    return b"".join((pngclean.MAGIC, pngclean._chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
                     pngclean._chunk(b"IDAT", zlib.compress(raw, 6)), pngclean._chunk(b"IEND", b"")))


# --- decoding (input already passed pngclean.sanitize) ----------------------------------------------------------------


def _unfilter(raw, rows, length, bpp, pos):
    """The pass's rows without their filter bytes; returns (rows, new pos)."""
    out, prev = [], bytearray(length)
    for _ in range(rows):
        kind, line = raw[pos], bytearray(raw[pos + 1:pos + 1 + length])
        pos += 1 + length
        if kind == 1:
            for i in range(bpp, length):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif kind == 3:
            for i in range(length):
                line[i] = (line[i] + ((line[i - bpp] if i >= bpp else 0) + prev[i]) // 2) & 255
        elif kind == 4:
            for i in range(length):
                a = line[i - bpp] if i >= bpp else 0
                b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out.append(line)
        prev = line
    return out, pos


def _samples(line, count, depth):
    """`count` samples of `depth` bits from a row, as 0..255 (16-bit samples keep their high byte)."""
    if depth == 8:
        return line[:count]
    if depth == 16:
        return line[0:count * 2:2]
    per, mask, scale = 8 // depth, (1 << depth) - 1, 255 // ((1 << depth) - 1)
    out = bytearray(count)
    for i in range(count):
        out[i] = ((line[i // per] >> (8 - depth * (i % per + 1))) & mask) * scale
    return out


def _indices(line, count, depth):
    if depth == 8:
        return line[:count]
    per, mask = 8 // depth, (1 << depth) - 1
    return [(line[i // per] >> (8 - depth * (i % per + 1))) & mask for i in range(count)]


def decode_png(data):
    """(size, rgba) of a PNG that pngclean.sanitize accepts, else None. Every sample becomes 8-bit RGBA."""
    clean = pngclean.sanitize(data)
    if clean is None:
        return None
    chunks = dict(pngclean._chunks(clean[0])[:-1])
    width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    channels = pngclean.CHANNELS[colour]
    raw = zlib.decompress(chunks[b"IDAT"])
    bpp = max(channels * depth // 8, 1)
    palette, trns = chunks.get(b"PLTE"), chunks.get(b"tRNS")
    rgba = bytearray(width * height * 4)
    if interlace:
        passes = [(x0, y0, dx, dy, (width - x0 + dx - 1) // dx, (height - y0 + dy - 1) // dy) for x0, y0, dx, dy in pngclean.ADAM7]
    else:
        passes = [(0, 0, 1, 1, width, height)]
    key = None
    if trns is not None and colour == 0:
        key = struct.unpack(">H", trns)[0]
    elif trns is not None and colour == 2:
        key = struct.unpack(">HHH", trns)
    pos = 0
    for x0, y0, dx, dy, w, h in passes:
        if w <= 0 or h <= 0:
            continue
        rows, pos = _unfilter(raw, h, (w * channels * depth + 7) // 8, bpp, pos)
        for r, line in enumerate(rows):
            y = y0 + r * dy
            if colour == 3:
                values = _indices(line, w, depth)
            else:
                values = _samples(line, w * channels, depth)
                if key is not None:  # the transparent colour is compared at full depth
                    full = (struct.unpack(f">{w * channels}H", bytes(line[:w * channels * 2])) if depth == 16 else
                            values if depth == 8 else [v * ((1 << depth) - 1) // 255 for v in values])
            for i in range(w):
                o = ((y * width) + x0 + i * dx) * 4
                if colour == 3:
                    k = values[i]
                    rgba[o:o + 3] = palette[k * 3:k * 3 + 3] if k * 3 + 3 <= len(palette) else b"\0\0\0"
                    rgba[o + 3] = trns[k] if trns is not None and k < len(trns) else 255
                elif colour in (0, 4):
                    g = values[i * channels]
                    rgba[o:o + 3] = bytes((g, g, g))
                    rgba[o + 3] = values[i * 2 + 1] if colour == 4 else (0 if key is not None and full[i] == key else 255)
                else:
                    rgba[o:o + 3] = values[i * channels:i * channels + 3]
                    rgba[o + 3] = values[i * 4 + 3] if colour == 6 else (
                        0 if key is not None and tuple(full[i * 3:i * 3 + 3]) == key else 255)
    return (width, height), bytes(rgba)


def scale(size, rgba, target):
    """A square image of side `target`: the source's pixels averaged over each target pixel, weighted by alpha."""
    side = size[0]
    out = bytearray(target * target * 4)
    edges = [round(i * side / target) for i in range(target + 1)]
    for ty in range(target):
        y0 = min(edges[ty], side - 1)
        y1 = max(edges[ty + 1], y0 + 1)
        for tx in range(target):
            x0 = min(edges[tx], side - 1)
            x1 = max(edges[tx + 1], x0 + 1)
            r = g = b = a = 0
            for y in range(y0, y1):
                row = y * side * 4
                for x in range(x0, x1):
                    o = row + x * 4
                    alpha = rgba[o + 3]
                    r += rgba[o] * alpha
                    g += rgba[o + 1] * alpha
                    b += rgba[o + 2] * alpha
                    a += alpha
            o = (ty * target + tx) * 4
            n = (y1 - y0) * (x1 - x0)
            if a:
                out[o:o + 4] = bytes((r // a, g // a, b // a, (a + n // 2) // n))
    return bytes(out)


def with_margin(side, rgba, margin):
    """The square image with `margin` transparent columns added at its right (space before a label's text)."""
    if not margin:
        return side, rgba
    row, blank = side * 4, bytes(margin * 4)
    return side + margin, b"".join(rgba[y * row:(y + 1) * row] + blank for y in range(side))


def app_icon(data, sizes, margins=None):
    """{side: png} of an app's icon for each side (with margins.get(side) transparent columns at its right), or None
    when the file is not a PNG appjail accepts."""
    decoded = decode_png(data)
    if decoded is None:
        return None
    size, rgba = decoded
    largest = max(sizes)
    big = scale(size, rgba, largest) if size[0] != largest else rgba
    out = {}
    for s in sizes:
        width, pixels = with_margin(s, big if s == largest else scale((largest, largest), big, s), (margins or {}).get(s, 0))
        out[s] = encode_png(width, s, pixels)
    return out


# --- drawing ----------------------------------------------------------------------------------------------------------


def hex_rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


class Canvas:
    """A small RGBA image painted with antialiased shapes given as signed distance functions (negative inside)."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.px = [[0.0, 0.0, 0.0, 0.0] for _ in range(width * height)]  # premultiplied

    def paint(self, sdf, colour, opacity=1.0, box=None):
        r, g, b = (c / 255 for c in hex_rgb(colour))
        x0, y0, x1, y1 = box or (0, 0, self.width, self.height)
        for y in range(max(int(y0), 0), min(math.ceil(y1), self.height)):
            for x in range(max(int(x0), 0), min(math.ceil(x1), self.width)):
                cover = min(max(0.5 - sdf(x + 0.5, y + 0.5), 0.0), 1.0) * opacity
                if cover:
                    p = self.px[y * self.width + x]
                    keep = 1 - cover
                    p[0] = r * cover + p[0] * keep
                    p[1] = g * cover + p[1] * keep
                    p[2] = b * cover + p[2] * keep
                    p[3] = cover + p[3] * keep
        return self

    def png(self):
        out = bytearray()
        for r, g, b, a in self.px:
            if a:
                out += bytes((round(r / a * 255), round(g / a * 255), round(b / a * 255), round(a * 255)))
            else:
                out += b"\0\0\0\0"
        return encode_png(self.width, self.height, out)


def rounded_rect(x0, y0, x1, y1, radius):
    cx, cy, hx, hy = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 - radius, (y1 - y0) / 2 - radius

    def sdf(x, y):
        qx, qy = abs(x - cx) - hx, abs(y - cy) - hy
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
    return sdf


def circle(cx, cy, radius):
    return lambda x, y: math.hypot(x - cx, y - cy) - radius


def segment(ax, ay, bx, by, width):
    """A stroke from a to b with round ends."""
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy or 1e-9

    def sdf(x, y):
        t = min(max(((x - ax) * dx + (y - ay) * dy) / length, 0), 1)
        return math.hypot(x - ax - t * dx, y - ay - t * dy) - width / 2
    return sdf


def arc(cx, cy, radius, start, end, width):
    """A stroke along the circle from angle `start` to `end` (degrees, clockwise on screen, 0 = right)."""
    a0, a1 = math.radians(start), math.radians(end)

    def sdf(x, y):
        angle = math.atan2(y - cy, x - cx) % (2 * math.pi)
        lo, hi = a0 % (2 * math.pi), a1 % (2 * math.pi)
        inside = lo <= angle <= hi if lo <= hi else (angle >= lo or angle <= hi)
        if inside:
            return abs(math.hypot(x - cx, y - cy) - radius) - width / 2
        ends = [(cx + radius * math.cos(a), cy + radius * math.sin(a)) for a in (a0, a1)]
        return min(math.hypot(x - ex, y - ey) for ex, ey in ends) - width / 2
    return sdf


def union(*sdfs):
    return lambda x, y: min(f(x, y) for f in sdfs)


def frame(width, height, radius, fill, border=None, line=1.0):
    """A rounded rectangle, filled and optionally outlined: the 9-slice image of a button, a field or a card."""
    c = Canvas(width, height)
    if border:
        c.paint(rounded_rect(0, 0, width, height, radius), border)
        c.paint(rounded_rect(line, line, width - line, height - line, max(radius - line, 0)), fill)
    else:
        c.paint(rounded_rect(0, 0, width, height, radius), fill)
    return c.png()


def check(side, fill, border, mark=None, margin=0):
    """A check box: a rounded square, with a check mark when `mark` is a colour."""
    c = Canvas(side + margin, side)
    s = side / 18
    c.paint(rounded_rect(1 * s, 1 * s, 17 * s, 17 * s, 4 * s), border)
    if not mark:
        c.paint(rounded_rect(2.5 * s, 2.5 * s, 15.5 * s, 15.5 * s, 2.8 * s), fill)
    else:
        c.paint(union(segment(5 * s, 9.5 * s, 7.8 * s, 12.3 * s, 2.2 * s), segment(7.8 * s, 12.3 * s, 13.2 * s, 6.2 * s, 2.2 * s)), mark)
    return c.png()


def radio(side, fill, border, dot=None, margin=0):
    c = Canvas(side + margin, side)
    s = side / 18
    c.paint(circle(9 * s, 9 * s, 8 * s), border)
    if not dot:
        c.paint(circle(9 * s, 9 * s, 6.5 * s), fill)
    else:
        c.paint(circle(9 * s, 9 * s, 3.2 * s), dot)
    return c.png()


def switch(height, track, knob, margin=0):
    """A toggle switch: a pill with the knob at the right end (switch_off has it at the left)."""
    width = round(height * 1.8)
    c = Canvas(width + margin, height)
    c.paint(rounded_rect(0, 0, width, height, height / 2), track)
    c.paint(circle(width - height / 2, height / 2, height / 2 - 2.5 * height / 20), knob)
    return c.png()


def switch_off(height, track, knob, margin=0):
    width = round(height * 1.8)
    c = Canvas(width + margin, height)
    c.paint(rounded_rect(0, 0, width, height, height / 2), track)
    c.paint(circle(height / 2, height / 2, height / 2 - 2.5 * height / 20), knob)
    return c.png()


def logo(side):
    """appjail's logo (gui/appjail.svg), drawn at `side` pixels."""
    s = side / 256
    c = Canvas(side, side)
    c.paint(rounded_rect(0, 0, side, side, 56 * s), "#1f2937")
    w = 14 * s
    brackets = union(
        segment(100 * s, 52 * s, 76 * s, 52 * s, w), arc(76 * s, 76 * s, 24 * s, 180, 270, w), segment(52 * s, 76 * s, 52 * s, 100 * s, w),
        segment(156 * s, 52 * s, 180 * s, 52 * s, w), arc(180 * s, 76 * s, 24 * s, 270, 360, w), segment(204 * s, 76 * s, 204 * s, 100 * s, w),
        segment(52 * s, 156 * s, 52 * s, 180 * s, w), arc(76 * s, 180 * s, 24 * s, 90, 180, w), segment(76 * s, 204 * s, 180 * s, 204 * s, w),
        arc(180 * s, 180 * s, 24 * s, 0, 90, w), segment(204 * s, 180 * s, 204 * s, 156 * s, w))
    c.paint(brackets, "#38bdf8")
    c.paint(rounded_rect(92 * s, 92 * s, 164 * s, 164 * s, 16 * s), "#f9fafb")
    c.paint(circle(128 * s, 128 * s, 10 * s), "#1f2937")
    return c.png()


# soft, distinct hues for apps without an icon; the same name always gets the same one
STAND_IN_HUES = ("#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#6366f1", "#14b8a6")


def stand_in(name, side, margin=0):
    """The icon of an app that has none: a rounded square in a colour chosen by its name, with the logo's inner box."""
    hue = STAND_IN_HUES[zlib.crc32(name.encode()) % len(STAND_IN_HUES)]
    s = side / 32
    c = Canvas(side + margin, side)
    c.paint(rounded_rect(1 * s, 1 * s, 31 * s, 31 * s, 8 * s), hue)
    c.paint(rounded_rect(10 * s, 10 * s, 22 * s, 22 * s, 3.5 * s), "#ffffff", 0.92)
    c.paint(circle(16 * s, 16 * s, 2 * s), hue)
    return c.png()
