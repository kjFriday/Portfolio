# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_textsafe.py
# About: Tests for textsafe.clean.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for textsafe.clean."""

import unittest

from textsafe import LIMIT, clean

ESC = "\x1b"
CSI = "\x9b"  # the single-character form of ESC [


class CleanTest(unittest.TestCase):
    def test_both_spellings_of_csi_are_removed(self):
        self.assertEqual(clean(ESC + "[2Jinvoice"), "[2Jinvoice")
        self.assertEqual(clean(CSI + "2Jinvoice"), "2Jinvoice")

    def test_del_and_whole_c1_block_are_removed(self):
        for c in range(0x7F, 0xA0):
            self.assertEqual(clean("a" + chr(c) + "b"), "ab", hex(c))

    def test_c0_controls_are_removed_except_tab_and_newline(self):
        for c in range(0x20):
            want = "a" + chr(c) + "b" if chr(c) in "\t\n" else "ab"
            self.assertEqual(clean("a" + chr(c) + "b"), want, hex(c))

    def test_separators_and_bidi_controls_are_removed(self):
        for c in [0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)]:
            self.assertEqual(clean("order" + chr(c) + "42"), "order42", hex(c))

    def test_ordinary_text_is_untouched(self):
        plain = "Order 1042 for Zoë Müller: 3 × Widget, 東京 office \U0001F4E6\tnote\nline two"
        self.assertEqual(clean(plain), plain)

    def test_length_is_capped_after_removal(self):
        self.assertEqual(len(clean("x" * 500)), LIMIT)
        self.assertEqual(clean("abcdef", limit=3), "abc")
        self.assertEqual(clean(ESC * 300 + "ok"), "ok")
        self.assertEqual(len(clean("y" * 500, limit=None)), 500)

    def test_zero_or_negative_limit_gives_empty(self):
        self.assertEqual(clean("hello", limit=0), "")
        self.assertEqual(clean("hello", limit=-1), "")
        self.assertEqual(clean("hello", limit=-2), "")

    def test_none_becomes_empty(self):
        self.assertEqual(clean(None), "")


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=d221be95410f0939e4d8b817f293330be788f4b4cae25151d22c4505c8ea9e98 ====
