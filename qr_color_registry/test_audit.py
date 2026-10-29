# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_audit.py
# About: Tests for the audit log: the hash chain, what it shows and what it cannot, the lock, and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the audit log: the hash chain, what it shows and what it cannot, the lock, and the line format."""

import hashlib
import json
import os
import shutil
import tempfile
import time
import unittest

import audit


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_audit_")
        self.path = os.path.join(self.folder, "logs", "audit.jsonl")
        self.saved = audit.LOCK_SECONDS

    def tearDown(self):
        audit.LOCK_SECONDS = self.saved
        shutil.rmtree(self.folder, ignore_errors=True)

    def lines(self):
        handle = open(self.path, "r", encoding="ascii")
        text = handle.read()
        handle.close()
        return text.splitlines()

    def write_lines(self, lines):
        handle = open(self.path, "w", encoding="ascii", newline="\n")
        handle.write("\n".join(lines) + "\n")
        handle.close()

    def append_three(self):
        for number in (1, 2, 3):
            self.assertEqual(audit.append(self.path, {"tool": "ecp_query", "n": number})["value"], number)

    def test_lines_chain_from_the_genesis(self):
        self.append_three()
        lines = self.lines()
        self.assertEqual(json.loads(lines[0])["prev_sha256"], audit.GENESIS)
        self.assertEqual(json.loads(lines[1])["prev_sha256"], hashlib.sha256(lines[0].encode("ascii")).hexdigest())
        self.assertEqual(json.loads(lines[2])["audit_id"], 3)
        self.assertEqual(audit.verify(self.path)["value"], 3)
        self.assertEqual(audit.verify(os.path.join(self.folder, "none.jsonl"))["value"], 0)
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_edits_and_deletions_show(self):
        self.append_three()
        lines = self.lines()
        self.write_lines([lines[0], lines[1].replace('"n":2', '"n":5'), lines[2]])
        self.assertIn("line 3", audit.verify(self.path)["error"])
        self.write_lines([lines[0], lines[2]])
        self.assertIn("line 2", audit.verify(self.path)["error"])
        self.write_lines([lines[1], lines[2]])
        self.assertIn("line 1", audit.verify(self.path)["error"])

    def test_cutting_off_the_end_is_not_visible(self):
        self.append_three()
        lines = self.lines()
        self.write_lines(lines[:2])
        self.assertEqual(audit.verify(self.path)["value"], 2)  # the chain has no anchor outside the file

    def test_a_damaged_last_line_stops_appending(self):
        self.append_three()
        handle = open(self.path, "a", encoding="ascii")
        handle.write("not json\n")
        handle.close()
        self.assertIn("damaged", audit.append(self.path, {"tool": "x"})["error"])
        self.assertEqual(len(self.lines()), 4)

    def test_a_held_lock_waits_and_a_stale_lock_is_cleared(self):
        audit.append(self.path, {"tool": "x"})
        audit.LOCK_SECONDS = 0.2
        handle = open(self.path + ".lock", "w")
        handle.close()
        self.assertIn("busy", audit.append(self.path, {"tool": "x"})["error"])
        old = time.time() - 60
        os.utime(self.path + ".lock", (old, old))
        self.assertEqual(audit.append(self.path, {"tool": "x"})["value"], 2)
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_any_text_stays_one_ascii_line(self):
        audit.append(self.path, {"client_info": {"name": "caf\u00e9\u2028\n"}})
        lines = self.lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["client_info"]["name"], "caf\u00e9\u2028\n")
        self.assertTrue(lines[0].isascii())


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=4377120322c4facd5ca2acd7e4a794a47e49003cfc2395c2408b2bf8bb89d2a2 ====
