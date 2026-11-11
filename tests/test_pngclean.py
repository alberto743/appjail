# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The canonical copy of an app's PNG icon: what it keeps, and the files it refuses."""

import struct
import zlib

import pytest

from appjail import pngclean

from .helpers import make_png


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def chunks_of(data):
    pos, out = 8, []
    while pos < len(data):
        (n,) = struct.unpack_from(">I", data, pos)
        out.append((data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]))
        pos += 12 + n
    return out


def kinds(data):
    return [kind for kind, _ in chunks_of(data)]


def split_idat(png):
    """The same PNG with its image data in two IDAT chunks."""
    parts = chunks_of(png)
    idat = next(body for kind, body in parts if kind == b"IDAT")
    middle = len(idat) // 2
    rebuilt = [(k, b) for k, b in parts if k != b"IDAT" and k != b"IEND"]
    return png[:8] + b"".join(chunk(k, b) for k, b in rebuilt) + chunk(b"IDAT", idat[:middle]) + chunk(b"IDAT", idat[middle:]) + chunk(b"IEND", b"")


@pytest.mark.parametrize(("colour", "depth"), [(0, 8), (0, 1), (0, 16), (2, 8), (2, 16), (3, 8), (3, 4), (3, 1), (4, 8), (6, 8), (6, 16)])
@pytest.mark.parametrize("interlace", [False, True])
def test_every_colour_type_and_depth_comes_out_as_a_valid_png_of_the_same_size(colour, depth, interlace):
    out = pngclean.sanitize(make_png(32, colour, depth, interlace))
    assert out is not None
    data, size = out
    assert size == (32, 32) and kinds(data)[0] == b"IHDR" and kinds(data)[-1] == b"IEND"
    assert pngclean.sanitize(data) is not None  # and what it writes it also accepts


def test_only_the_chunks_the_image_needs_survive():
    noisy = make_png(64, extra=[(b"tEXt", b"Comment\0hello"), (b"iCCP", b"x\0\0" + b"\1" * 40), (b"gAMA", b"\0\0\xb1\x8f"),
                                (b"eXIf", b"MM\0*"), (b"zzZz", b"private")])
    data, _ = pngclean.sanitize(noisy)
    assert kinds(data) == [b"IHDR", b"IDAT", b"IEND"]


def test_transparency_and_the_palette_are_kept_where_they_mean_something():
    indexed, _ = pngclean.sanitize(make_png(32, 3, 8, extra=[(b"tRNS", b"\0\x80")]))
    assert kinds(indexed) == [b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"]
    grey, _ = pngclean.sanitize(make_png(32, 0, 8, extra=[(b"tRNS", b"\0\x10")]))
    assert b"tRNS" in kinds(grey)
    rgba, _ = pngclean.sanitize(make_png(32, 6, 8, extra=[(b"tRNS", b"\0\x10")]))  # meaningless with an alpha channel
    assert b"tRNS" not in kinds(rgba)


def test_image_data_split_in_several_chunks_is_joined():
    data, _ = pngclean.sanitize(split_idat(make_png(48)))
    assert kinds(data).count(b"IDAT") == 1


def test_trailing_bytes_after_iend_are_refused_not_copied():
    assert pngclean.sanitize(make_png(32) + b"payload") is None


def test_a_bad_crc_is_refused():
    png = bytearray(make_png(32))
    png[20] ^= 1  # inside IHDR
    assert pngclean.sanitize(bytes(png)) is None


@pytest.mark.parametrize("size", [8, 2000])
def test_sizes_outside_the_icon_range_are_refused(size):
    assert pngclean.sanitize(make_png(size)) is None


def test_a_non_square_image_is_refused():
    assert pngclean.sanitize(make_png(32, width=64)) is None


def test_image_data_that_is_not_what_the_header_promises_is_refused():
    png = make_png(32)
    short = png[:8] + b"".join(chunk(k, struct.pack(">IIBBBBB", 32, 33, 8, 6, 0, 0, 0) if k == b"IHDR" else b) for k, b in chunks_of(png))
    assert pngclean.sanitize(short) is None  # the header claims one more row than the data holds


def test_an_inflate_bomb_is_stopped_at_the_expected_size():
    body = zlib.compress(b"\0" * (200 * 1024 * 1024), 9)  # a few hundred KB that expand to 200 MB
    header = struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0)
    bomb = pngclean.MAGIC + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")
    assert pngclean.sanitize(bomb) is None


def test_an_illegal_filter_byte_is_refused():
    header = struct.pack(">IIBBBBB", 16, 16, 8, 0, 0, 0, 0)
    rows = (b"\x07" + b"\0" * 16) * 16
    png = pngclean.MAGIC + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    assert pngclean.sanitize(png) is None


@pytest.mark.parametrize("bad", [b"", b"\x89PNG\r\n\x1a\n", b"GIF89a" + b"\0" * 40, make_png(32)[:-5]])
def test_garbage_and_truncated_files_are_refused(bad):
    assert pngclean.sanitize(bad) is None


def test_an_unknown_critical_chunk_is_refused():
    assert pngclean.sanitize(make_png(32, extra=[(b"ZZZZ", b"x")])) is None


def test_the_palette_must_fit_the_depth():
    header = struct.pack(">IIBBBBB", 16, 16, 1, 3, 0, 0, 0)
    rows = (b"\0" + b"\0\0") * 16
    png = (pngclean.MAGIC + chunk(b"IHDR", header) + chunk(b"PLTE", b"\0" * 9) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    assert pngclean.sanitize(png) is None  # 3 entries do not fit 1 bit
