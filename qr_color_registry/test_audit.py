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

    def test_cutting_off_the_end_shows_through_the_anchor_and_a_kept_fingerprint(self):
        self.append_three()
        kept = audit.fingerprint(self.path)["value"]
        self.assertEqual(kept["audit_id"], 3)
        self.write_lines(self.lines()[:2])
        self.assertIn("cut off", audit.verify(self.path)["error"])
        os.remove(self.path + ".anchor")
        self.assertEqual(audit.verify(self.path)["value"], 2)  # without its anchor, the chain alone looks whole
        self.assertIn("cut off", audit.check_fingerprint(self.path, audit.fingerprint_text(kept))["error"])

    def test_fingerprints(self):
        self.append_three()
        text = audit.fingerprint_text(audit.fingerprint(self.path)["value"])
        self.assertEqual(audit.check_fingerprint(self.path, text)["value"], 3)
        audit.append(self.path, {"tool": "x"})
        self.assertEqual(audit.check_fingerprint(self.path, text)["value"], 4)  # lines after it are fine
        changed = text[:-1] + ("1" if text[-1] == "0" else "0")
        self.assertIn("not the line", audit.check_fingerprint(self.path, changed)["error"])
        self.assertFalse(audit.check_fingerprint(self.path, "nonsense")["ok"])
        self.assertFalse(audit.fingerprint(os.path.join(self.folder, "none.jsonl"))["ok"])

    def test_the_anchor_follows_the_last_line(self):
        self.append_three()
        anchor = audit.read_anchor(self.path)
        self.assertEqual(anchor["audit_id"], 3)
        self.assertEqual(anchor["line_sha256"], hashlib.sha256(self.lines()[2].encode("ascii")).hexdigest())
        self.assertFalse(os.path.exists(self.path + ".anchor.part"))

    def test_records_for_reading(self):
        self.append_three()
        handle = open(self.path, "a", encoding="ascii")
        handle.write("not json\n")
        handle.close()
        records = audit.read_records(self.path, 2)
        self.assertEqual((records[0]["n"], records[1]["audit_id"]), (3, "?"))
        self.assertEqual(audit.read_records(os.path.join(self.folder, "none.jsonl"), 5), [])

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

# ==== stamp v1 | author=kjFriday | hmac-sha256=f02c4d3e9330cc9b3a76c0042fe95aa4221ee4d410ffbf52cae2c013c713a59e ====
