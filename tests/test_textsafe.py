# SPDX-FileCopyrightText: 2026 Alberto P
# SPDX-License-Identifier: MPL-2.0

import unittest

from bjail import textsafe


class CleanTests(unittest.TestCase):
    def test_plain_text_untouched(self):
        self.assertEqual(textsafe.clean("Drum machine — C11 audio engine"), "Drum machine — C11 audio engine")

    def test_csi_and_osc_removed(self):
        self.assertEqual(textsafe.clean("a\x1b[31mred\x1b[0m b"), "ared b")
        self.assertEqual(textsafe.clean("x\x1b]0;evil title\x07y"), "xy")
        self.assertEqual(textsafe.clean("x\x1b]8;;http://e\x1b\\link\x1b]8;;\x1b\\"), "xlink")
        self.assertEqual(textsafe.clean("x\x9b2Jy"), "xy")

    def test_other_escapes_and_controls(self):
        self.assertEqual(textsafe.clean("a\x1bcb\x00c\x07d\x7fe\x85f"), "abcdef")

    def test_unterminated_sequences_do_not_leak(self):
        for s in ("a\x1b[", "a\x1b]0;title", "a\x1bP1;2", "a\x1b"):
            self.assertEqual(textsafe.clean(s), "a", s)

    def test_whitespace_collapsed(self):
        self.assertEqual(textsafe.clean("a\nb\t\tc\r\nd"), "a b c d")

    def test_bidi_overrides_removed(self):
        self.assertEqual(textsafe.clean("evil‮txt.exe⁦"), "eviltxt.exe")

    def test_truncation(self):
        out = textsafe.clean("x" * 50, max_len=10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))

    def test_non_string(self):
        self.assertEqual(textsafe.clean(None), "None")


if __name__ == "__main__":
    unittest.main()
