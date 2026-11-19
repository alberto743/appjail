# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

"""Neutralise untrusted text (network, catalogs) before it reaches a terminal."""

import re

# OSC (ESC ] ... BEL | ESC \), DCS/SOS/PM/APC strings, CSI (ESC [ params final),
# then any remaining two-byte ESC sequence.
_ESC = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[PX^_][^\x1b]*(?:\x1b\\)?"
    r"|\x1b\[[0-?]*[ -/]*[@-~]?"
    r"|\x1b[ -~]?"
    r"|\x9b[0-?]*[ -/]*[@-~]?"
    r"|[\x90\x98\x9d-\x9f][^\x07\x9c\x1b]*(?:\x07|\x9c|\x1b\\)?"
)
# C0/C1 controls and DEL, plus characters that are invisible or spoof text: zero-width and bidirectional controls,
# soft hyphen, fillers (braille blank, hangul), interlinear annotation, Unicode tag characters and the variation
# selectors other than the emoji presentation selector U+FE0F (which is kept so emoji still render).
_CTRL = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f"
    "\u2028-\u202e\u2060-\u2069\u2800\u3164\ufe00-\ufe0e\ufeff\uffa0\ufff9-\ufffb"
    "\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)
_SPACE = re.compile(r"[\t\n\r]+")


def clean(text, max_len=2000):
    """Return text with escape sequences and control characters removed.

    Tabs and newlines become single spaces; the result is cut to max_len (None: never cut).
    """
    text = _ESC.sub("", str(text))
    text = _SPACE.sub(" ", text)
    text = _CTRL.sub("", text)
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def has_escape(text):
    """Whether the text holds an escape sequence (what clean_output would remove)."""
    return _ESC.search(str(text)) is not None


def clean_output(text):
    """One line of an app's output without escape sequences and control characters; tabs and spaces are kept.

    For text that is shown as it was written (an app's output), unlike clean, which turns the line into one short
    sentence: it does not collapse white space and does not cut the line.
    """
    return _CTRL.sub("", _ESC.sub("", str(text)))
