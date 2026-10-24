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
)
# C0/C1 controls and DEL, plus bidirectional overrides and isolates (spoofing).
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")
_SPACE = re.compile(r"[\t\n\r]+")


def clean(text, max_len=2000):
    """Return text with escape sequences and control characters removed.

    Tabs and newlines become single spaces; the result is cut to max_len.
    """
    text = _ESC.sub("", str(text))
    text = _SPACE.sub(" ", text)
    text = _CTRL.sub("", text)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text
