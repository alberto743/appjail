# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""The window's images (gui/icons.py), the dark-mode setting (gui/theme.py) and the detail pane's data (gui/apps.py).
Nothing here needs a display."""

import struct
import zlib

import pytest

from appjail import pngclean
from appjail.errors import RunError
from appjail.gui import apps, icons

# --- a small PNG writer for the tests: every filter type, every colour type, interlaced or not --------------------------


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _filter(kind, line, prev, bpp):
    out = bytearray()
    for i, x in enumerate(line):
        a = line[i - bpp] if i >= bpp else 0
        b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
        out.append((x - (0, a, b, (a + b) // 2, _paeth(a, b, c))[kind]) & 255)
    return bytes([kind]) + bytes(out)


def _rows(samples, width, depth):
    """Pack rows of samples (ints) at `depth` bits."""
    if depth == 8:
        return bytes(samples)
    if depth == 16:
        return b"".join(struct.pack(">H", s) for s in samples)
    out, acc, bits = bytearray(), 0, 0
    for s in samples:
        acc, bits = (acc << depth) | s, bits + depth
        if bits == 8:
            out.append(acc)
            acc, bits = 0, 0
    if bits:
        out.append(acc << (8 - bits))
    return bytes(out)


def make_png(side, colour, depth, pixel, interlace=False, plte=None, trns=None, filters=(0, 1, 2, 3, 4)):
    """pixel(x, y) -> tuple of samples for the colour type."""
    channels = pngclean.CHANNELS[colour]
    bpp = max(channels * depth // 8, 1)
    passes = [(x0, y0, dx, dy) for x0, y0, dx, dy in pngclean.ADAM7] if interlace else [(0, 0, 1, 1)]
    raw, n = bytearray(), 0
    for x0, y0, dx, dy in passes:
        xs, ys = range(x0, side, dx), range(y0, side, dy)
        if not xs or not ys:
            continue
        prev = bytes(len(_rows([0] * len(xs) * channels, len(xs), depth)))
        for y in ys:
            line = _rows([s for x in xs for s in pixel(x, y)], len(xs), depth)
            raw += _filter(filters[n % len(filters)], line, prev, bpp)
            prev, n = line, n + 1
    chunks = [(b"IHDR", struct.pack(">IIBBBBB", side, side, depth, colour, 0, 0, int(interlace)))]
    if plte:
        chunks.append((b"PLTE", plte))
    if trns:
        chunks.append((b"tRNS", trns))
    chunks += [(b"IDAT", zlib.compress(bytes(raw))), (b"IEND", b"")]
    return pngclean.MAGIC + b"".join(pngclean._chunk(k, b) for k, b in chunks)


def rgba_at(decoded, x, y):
    (side, _), rgba = decoded
    o = (y * side + x) * 4
    return tuple(rgba[o:o + 4])


SIDE = 17  # odd: the last byte of a packed row and the smaller interlace passes are partial


def test_rgba_with_every_filter_decodes_exactly():
    def px(x, y):
        return (x * 13 % 256, y * 7 % 256, (x * y) % 256, (x + y) * 5 % 256)
    for interlace in (False, True):
        decoded = icons.decode_png(make_png(SIDE, 6, 8, px, interlace=interlace))
        assert decoded[0] == (SIDE, SIDE)
        assert all(rgba_at(decoded, x, y) == px(x, y) for x in range(SIDE) for y in range(SIDE)), interlace


@pytest.mark.parametrize("depth", [1, 2, 4, 8, 16])
def test_grey_at_every_depth(depth):
    top = (1 << depth) - 1

    def px(x, y):
        return ((x + y) % (top + 1),)
    decoded = icons.decode_png(make_png(SIDE, 0, depth, px))
    for x in range(SIDE):
        v = (x + 3) % (top + 1)
        expected = v >> 8 if depth == 16 else v * (255 // top)
        assert rgba_at(decoded, x, 3) == (expected, expected, expected, 255)


def test_grey_and_rgb_with_a_transparent_colour():
    grey = icons.decode_png(make_png(SIDE, 0, 4, lambda x, y: (x % 16,), trns=struct.pack(">H", 5)))
    assert rgba_at(grey, 5, 0)[3] == 0 and rgba_at(grey, 6, 0)[3] == 255
    rgb = icons.decode_png(make_png(SIDE, 2, 16, lambda x, y: (x * 1000, 7, 9), trns=struct.pack(">HHH", 2000, 7, 9)))
    assert rgba_at(rgb, 2, 4)[3] == 0 and rgba_at(rgb, 3, 4) == ((3000 >> 8), 0, 0, 255)


def test_palette_with_alpha_and_an_index_past_the_palette():
    plte = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255))
    decoded = icons.decode_png(make_png(SIDE, 3, 2, lambda x, y: (x % 4,), plte=plte, trns=bytes((128,))))
    assert rgba_at(decoded, 0, 0) == (255, 0, 0, 128)
    assert rgba_at(decoded, 1, 0) == (0, 255, 0, 255)
    assert rgba_at(decoded, 3, 0) == (0, 0, 0, 255)  # index 3: no palette entry; black, never a read past the end


def test_grey_alpha_sixteen_bit_interlaced():
    decoded = icons.decode_png(make_png(SIDE, 4, 16, lambda x, y: (x * 3000, y * 3000), interlace=True))
    assert rgba_at(decoded, 4, 6) == ((12000 >> 8),) * 3 + ((18000 >> 8),)


def test_what_pngclean_refuses_is_not_decoded():
    good = make_png(SIDE, 6, 8, lambda x, y: (1, 2, 3, 4))
    assert icons.decode_png(b"GIF89a") is None
    assert icons.decode_png(good[:-20]) is None
    assert icons.decode_png(make_png(8, 6, 8, lambda x, y: (1, 2, 3, 4))) is None  # smaller than the icon range


def test_scaling_keeps_a_flat_colour_and_ignores_the_colour_of_transparent_pixels():
    def px(x, y):
        return (200, 100, 50, 255) if x < 32 else (0, 0, 0, 0)
    size, rgba = icons.decode_png(make_png(64, 6, 8, px))
    small = icons.scale(size, rgba, 16)
    assert small[0:4] == bytes((200, 100, 50, 255))
    assert small[7 * 4:8 * 4] == bytes((200, 100, 50, 255))  # beside the transparent half: not darkened by its black
    assert small[8 * 4 + 3] == 0
    big = icons.scale((16, 16), small, 40)  # enlarging a small icon works too
    assert big[0:4] == bytes((200, 100, 50, 255))


def test_app_icon_gives_each_size_with_its_margin_as_a_png_pngclean_accepts():
    data = make_png(48, 2, 8, lambda x, y: (x * 5, y * 5, 0))
    out = icons.app_icon(data, (32, 64), {32: 10})
    assert set(out) == {32, 64}
    assert struct.unpack(">II", out[32][16:24]) == (42, 32)
    assert pngclean.sanitize(out[64]) is not None
    assert icons.app_icon(b"nope", (32,)) is None


def test_drawn_images_are_valid_and_the_stand_in_depends_only_on_the_name():
    for png in (icons.frame(20, 20, 8, "#ffffff", "#000000"), icons.logo(64), icons.check(18, "#ffffff", "#000000", margin=7),
                icons.radio(18, None, "#0369a1", "#ffffff"), icons.switch(20, "#0369a1", "#ffffff", 8)):
        assert png.startswith(pngclean.MAGIC) and zlib.decompress(png[png.index(b"IDAT") + 4:-16])
    assert icons.stand_in("lagrange", 32) == icons.stand_in("lagrange", 32) != icons.stand_in("htop", 32)
    assert icons.decode_png(icons.logo(64)) is not None
    logo = icons.decode_png(icons.logo(64))
    assert rgba_at(logo, 0, 0)[3] < 64 and rgba_at(logo, 32, 32)[3] == 255  # rounded corner, solid middle


# --- dark mode -----------------------------------------------------------------------------------------------------


def test_the_desktop_colour_scheme_reply_is_read():
    from appjail.gui import theme
    assert theme.parse_color_scheme("method return\n   variant       variant          uint32 1\n")
    assert not theme.parse_color_scheme("method return\n   variant       uint32 2\n")
    assert not theme.parse_color_scheme("method return\n   variant       uint32 0\n")
    assert not theme.parse_color_scheme("")


def test_prefers_dark_asks_the_settings_portal_and_falls_back_to_light(monkeypatch):
    from appjail.gui import theme
    seen = []

    def reply(env, dest, path, member, *args, timeout):
        seen.append((dest, member, args, timeout))
        return "variant variant uint32 1"
    monkeypatch.setattr(theme.portal, "bus_call", reply)
    assert theme.prefers_dark({}) is True
    assert seen == [("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Settings.ReadOne",
                     ("string:org.freedesktop.appearance", "string:color-scheme"), 1.0)]

    def unreachable(*a, **k):
        raise RunError("no bus")
    monkeypatch.setattr(theme.portal, "bus_call", unreachable)
    assert theme.prefers_dark({}) is False


def test_both_palettes_have_the_same_keys():
    from appjail.gui import theme
    assert set(theme.LIGHT) == set(theme.DARK)


# --- the detail pane's data ----------------------------------------------------------------------------------------


def test_card_has_the_grants_as_chips_and_the_rest_as_lines(h):
    h.add(extra=["--allow", "network", "--dbus", "org.example.A"])
    card = apps.card("app")
    assert card["name"] == "app" and "github:o/App" in card["subtitle"] and not card["error"]
    assert card["grants"] == ["network"]
    assert ("plain", "no menu entry") in card["badges"]
    assert "dbus: org.example.A" in card["lines"] and not any(line.startswith("grants:") for line in card["lines"])


def test_card_of_an_unreadable_manifest_says_so(h):
    h.add()
    from appjail import store
    store.manifest_path("app").write_text("not = [toml")
    card = apps.card("app")
    assert card["error"].startswith("unreadable manifest") and card["grants"] == []


def test_icon_key_follows_the_installed_icon_and_a_large_file_is_not_read(h, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert apps.icon_key("app") is None
    target = tmp_path / "share/icons/hicolor/48x48/apps/appjail-app.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(make_png(48, 6, 8, lambda x, y: (9, 9, 9, 255)))
    key = apps.icon_key("app")
    assert key[0] == str(target) and apps.icon_pngs(key, (32,))[32].startswith(pngclean.MAGIC)
    monkeypatch.setattr(apps.desktop, "MAX_PNG_BYTES", 10)
    assert apps.icon_pngs(key, (32,)) is None
