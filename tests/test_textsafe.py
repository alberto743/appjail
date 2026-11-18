# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import pytest

from appjail import textsafe


def test_plain_text_untouched():
    assert textsafe.clean("Drum machine — C11 audio engine") == "Drum machine — C11 audio engine"


@pytest.mark.parametrize("raw,expected", [
    ("a\x1b[31mred\x1b[0m b", "ared b"),
    ("x\x1b]0;evil title\x07y", "xy"),
    ("x\x1b]8;;http://e\x1b\\link\x1b]8;;\x1b\\", "xlink"),
    ("x\x9b2Jy", "xy"),
    ("a\x1bcb\x00c\x07d\x7fe\x85f", "abcdef"),
])
def test_escapes_and_controls_removed(raw, expected):
    assert textsafe.clean(raw) == expected


@pytest.mark.parametrize("raw", ["a\x1b[", "a\x1b]0;title", "a\x1bP1;2", "a\x1b"])
def test_unterminated_sequences_do_not_leak(raw):
    assert textsafe.clean(raw) == "a"


def test_whitespace_collapsed():
    assert textsafe.clean("a\nb\t\tc\r\nd") == "a b c d"


def test_bidi_overrides_removed():
    assert textsafe.clean("evil‮txt.exe⁦") == "eviltxt.exe"


def test_truncation():
    out = textsafe.clean("x" * 50, max_len=10)
    assert len(out) == 10 and out.endswith("…")


def test_non_string():
    assert textsafe.clean(None) == "None"


def test_clean_drops_zero_width_and_bidi_characters():
    assert textsafe.clean("a\u200bb\u202ec\u2066d\ufeffe\u061cf") == "abcdef"


@pytest.mark.parametrize("raw,expected", [
    ("x\x9d0;evil title\x07y", "xy"),            # C1 OSC introducer: the payload goes with it
    ("x\x9d0;evil\x9cy", "xy"),                  # terminated by C1 ST
    ("x\x90q1;2\x9cy", "xy"),                    # C1 DCS
    ("a\U000e0041\U000e0042b", "ab"),            # Unicode tag characters hide text
    ("a­b⠀cㅤd", "abcd"),          # soft hyphen, braille blank, hangul filler
    ("a￹b￻c", "abc"),                  # interlinear annotation
    ("a︀b\U000e0100c", "abc"),              # variation selectors that spoof
    ("❤️", "❤️"),            # emoji presentation selector is kept
    ("Ünïcödé 日本語 العربية", "Ünïcödé 日本語 العربية"),
])
def test_hidden_and_spoofing_characters(raw, expected):
    assert textsafe.clean(raw) == expected
