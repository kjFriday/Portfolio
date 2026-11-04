# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_textsafe.py
# About: Tests for textsafe.clean.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for textsafe.clean.

textsafe.clean guards text that arrives from outside (typed links and questions, text read from files or sent by clients): it drops
invisible control characters that could rewrite a terminal or reorder what a person sees, and caps the
length. These tests walk every refused range code point by code point and check that ordinary text,
non-ASCII included, passes unchanged.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import unittest

from textsafe import LIMIT, clean

ESC = "\x1b"  # the escape character that starts terminal control sequences
CSI = "\x9b"  # the single-character form of ESC [


class CleanTest(unittest.TestCase):
    """What clean() removes, keeps and cuts."""

    def test_both_spellings_of_csi_are_removed(self):
        """ESC [ and its one-character form U+009B both lose their control character; the rest stays as plain text.

        "[2J" is the ANSI "clear screen" sequence: without its ESC it is only text."""
        self.assertEqual(clean(ESC + "[2Jinvoice"), "[2Jinvoice")
        self.assertEqual(clean(CSI + "2Jinvoice"), "2Jinvoice")

    def test_del_and_whole_c1_block_are_removed(self):
        """DEL (0x7F) and every C1 control (0x80 to 0x9F) are removed."""
        for c in range(0x7F, 0xA0):
            self.assertEqual(clean("a" + chr(c) + "b"), "ab", hex(c))

    def test_c0_controls_are_removed_except_tab_and_newline(self):
        """Every C0 control (below 0x20) is removed except tab and newline, which text may need."""
        for c in range(0x20):
            want = "a" + chr(c) + "b" if chr(c) in "\t\n" else "ab"
            self.assertEqual(clean("a" + chr(c) + "b"), want, hex(c))

    def test_separators_and_bidi_controls_are_removed(self):
        """The line and paragraph separators and the bidirectional embeddings, overrides and isolates are removed.

        U+202A to U+202E and U+2066 to U+2069 can make text display in another order than it is
        stored, which hides what a link or name really says."""
        for c in [0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)]:
            self.assertEqual(clean("order" + chr(c) + "42"), "order42", hex(c))

    def test_ordinary_text_is_untouched(self):
        """Accented Latin, a multiplication sign, Japanese, an emoji (U+1F4E6), tab and newline all pass unchanged."""
        plain = "Order 1042 for Zoë Müller: 3 × Widget, 東京 office \U0001F4E6\tnote\nline two"
        self.assertEqual(clean(plain), plain)

    def test_length_is_capped_after_removal(self):
        """The cap (LIMIT by default) counts characters left after removal; limit=None means no cap.

        300 ESCs before "ok" are removed first, so "ok" survives a 240-character cap."""
        self.assertEqual(len(clean("x" * 500)), LIMIT)
        self.assertEqual(clean("abcdef", limit=3), "abc")
        self.assertEqual(clean(ESC * 300 + "ok"), "ok")
        self.assertEqual(len(clean("y" * 500, limit=None)), 500)

    def test_zero_or_negative_limit_gives_empty(self):
        """A limit of 0 or below gives "" (a negative slice would otherwise count from the end)."""
        self.assertEqual(clean("hello", limit=0), "")
        self.assertEqual(clean("hello", limit=-1), "")
        self.assertEqual(clean("hello", limit=-2), "")

    def test_none_becomes_empty(self):
        """None is treated as no text and gives ""."""
        self.assertEqual(clean(None), "")


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a38ac02ffb830e13ffed1097e58713ef66d4480a5114282cf045f21b8a0de5eb ====
