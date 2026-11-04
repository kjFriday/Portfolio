# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: tests/test_qr_studio.py
# About: Tests for QR Studio's own code around the codec: the history and links...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Tests for QR Studio's code around the codec: the history and links in studio_history.py.

They use a throwaway temp folder, never the real history in the user's data folder. The codec's tests are in test_qr_codec.py. Run from the program folder: python -m unittest discover -s tests
"""

import os
import shutil
import tempfile
import unittest

import studio_history as history


class HistoryTests(unittest.TestCase):
    """The history list, its file, and which texts count as links."""

    def test_round_trip_and_dedupe(self):
        """A repeated read moves to the top with its new time; the list survives a save and load.

        The file goes in a "sub" folder that does not exist yet, so save_history must create it; a
        missing file loads as an empty history.
        """
        folder = tempfile.mkdtemp(prefix="qr_studio_test_")
        try:
            path = os.path.join(folder, "sub", "history.json")
            entries = history.add_history([], "read", "one", 1.0)
            entries = history.add_history(entries, "made", "two", 2.0)
            entries = history.add_history(entries, "read", "one", 3.0)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["when"], 3.0)
            self.assertTrue(history.save_history(path, entries)["ok"])
            self.assertEqual(history.load_history(path), entries)
            self.assertEqual(history.load_history(os.path.join(folder, "missing.json")), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_links(self):
        """A web link with a leading space counts; a javascript: address, which could run script, does not."""
        self.assertTrue(history.is_link(" https://example.com"))
        self.assertFalse(history.is_link("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=ada94b1822f02000de81ca20350d415b30d3324a4be539afd84db3b9179d7eea ====
