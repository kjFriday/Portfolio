# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_audit.py
# About: Tests for the audit log: the hash chain, what it shows and what it cannot, the lock, and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for the audit log: hash chain, anchor, fingerprints, lock and line format.

audit.py writes one JSON line per ECP tool call, each holding the SHA-256 of the line before it (the
first one holds GENESIS, 64 zeros), plus an anchor file beside the log naming the last line. These tests
write small logs in a temporary folder, damage them by hand (edit, delete, cut off the end) and check
that verify() and check_fingerprint() name the damage. Run them with the rest of the suite:
python -m unittest discover -s tests, in the program folder.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
import unittest

import audit


class AuditLogTests(unittest.TestCase):
    """The audit log in one temporary folder per test, at logs/audit.jsonl (a folder audit.append makes)."""

    def setUp(self):
        """Make the temporary folder and remember audit.LOCK_SECONDS, which one test shortens."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_audit_")
        self.path = os.path.join(self.folder, "logs", "audit.jsonl")
        self.saved = audit.LOCK_SECONDS

    def tearDown(self):
        """Put LOCK_SECONDS back and remove the folder."""
        audit.LOCK_SECONDS = self.saved
        shutil.rmtree(self.folder, ignore_errors=True)

    def lines(self):
        """The log's lines as written, without their newlines."""
        handle = open(self.path, "r", encoding="ascii")
        text = handle.read()
        handle.close()
        return text.splitlines()

    def write_lines(self, lines):
        """Rewrite the log with `lines` (the anchor is left as it was, as a tamperer might)."""
        handle = open(self.path, "w", encoding="ascii", newline="\n")
        handle.write("\n".join(lines) + "\n")
        handle.close()

    def append_three(self):
        """Append three records and check they get audit_ids 1, 2 and 3."""
        for number in (1, 2, 3):
            self.assertEqual(audit.append(self.path, {"tool": "ecp_query", "n": number})["value"], number)

    def test_lines_chain_from_the_genesis(self):
        """Line 1 links to GENESIS, line 2 to line 1's hash; verify counts 3, a missing log 0, and no lock stays."""
        self.append_three()
        lines = self.lines()
        self.assertEqual(json.loads(lines[0])["prev_sha256"], audit.GENESIS)
        self.assertEqual(json.loads(lines[1])["prev_sha256"], hashlib.sha256(lines[0].encode("ascii")).hexdigest())
        self.assertEqual(json.loads(lines[2])["audit_id"], 3)
        self.assertEqual(audit.verify(self.path)["value"], 3)
        self.assertEqual(audit.verify(os.path.join(self.folder, "none.jsonl"))["value"], 0)
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_edits_and_deletions_show(self):
        """An edited line breaks the next line's link, and a deleted line breaks the one after it.

        Editing line 2 shows at line 3 (its prev_sha256 no longer matches); dropping line 2 shows at
        the new line 2; dropping line 1 shows at line 1, which no longer holds GENESIS."""
        self.append_three()
        lines = self.lines()
        self.write_lines([lines[0], lines[1].replace('"n":2', '"n":5'), lines[2]])
        self.assertIn("line 3", audit.verify(self.path)["error"])
        self.write_lines([lines[0], lines[2]])
        self.assertIn("line 2", audit.verify(self.path)["error"])
        self.write_lines([lines[1], lines[2]])
        self.assertIn("line 1", audit.verify(self.path)["error"])

    def test_cutting_off_the_end_shows_through_the_anchor_and_a_kept_fingerprint(self):
        """Lines cut off the end pass the chain alone, so the anchor catches it, and a kept fingerprint
        still does once the anchor is deleted too."""
        self.append_three()
        kept = audit.fingerprint(self.path)["value"]
        self.assertEqual(kept["audit_id"], 3)
        self.write_lines(self.lines()[:2])
        self.assertIn("cut off", audit.verify(self.path)["error"])
        os.remove(self.path + ".anchor")
        self.assertEqual(audit.verify(self.path)["value"], 2)  # without its anchor, the chain alone looks whole
        self.assertIn("cut off", audit.check_fingerprint(self.path, audit.fingerprint_text(kept))["error"])

    def test_fingerprints(self):
        """A fingerprint "N:sha" checks the log up to line N, allows later lines, and refuses a changed
        hash, nonsense text and a missing log."""
        self.append_three()
        text = audit.fingerprint_text(audit.fingerprint(self.path)["value"])
        self.assertEqual(audit.check_fingerprint(self.path, text)["value"], 3)
        audit.append(self.path, {"tool": "x"})
        self.assertEqual(audit.check_fingerprint(self.path, text)["value"], 4)  # lines after it are fine
        # flip the last hex digit of the kept hash, so it names a line that was never written
        changed = text[:-1] + ("1" if text[-1] == "0" else "0")
        self.assertIn("not the line", audit.check_fingerprint(self.path, changed)["error"])
        self.assertFalse(audit.check_fingerprint(self.path, "nonsense")["ok"])
        self.assertFalse(audit.fingerprint(os.path.join(self.folder, "none.jsonl"))["ok"])

    def test_the_anchor_follows_the_last_line(self):
        """The anchor holds the last line's audit_id and SHA-256, and its .part file is moved into place."""
        self.append_three()
        anchor = audit.read_anchor(self.path)
        self.assertEqual(anchor["audit_id"], 3)
        self.assertEqual(anchor["line_sha256"], hashlib.sha256(self.lines()[2].encode("ascii")).hexdigest())
        self.assertFalse(os.path.exists(self.path + ".anchor.part"))

    def test_records_for_reading(self):
        """read_records gives the last N records oldest first, a damaged line as audit_id "?", and [] for no log."""
        self.append_three()
        handle = open(self.path, "a", encoding="ascii")
        handle.write("not json\n")
        handle.close()
        records = audit.read_records(self.path, 2)
        self.assertEqual((records[0]["n"], records[1]["audit_id"]), (3, "?"))
        self.assertEqual(audit.read_records(os.path.join(self.folder, "none.jsonl"), 5), [])

    def test_a_damaged_last_line_stops_appending(self):
        """A last line that is not JSON leaves no audit_id to continue from, so append refuses and adds nothing."""
        self.append_three()
        handle = open(self.path, "a", encoding="ascii")
        handle.write("not json\n")
        handle.close()
        self.assertIn("damaged", audit.append(self.path, {"tool": "x"})["error"])
        self.assertEqual(len(self.lines()), 4)

    def test_a_held_lock_waits_and_a_stale_lock_is_cleared(self):
        """A fresh lock file makes append give up as busy after LOCK_SECONDS; one over 30 seconds old is
        taken as left by a dead writer, removed, and the append goes through.

        LOCK_SECONDS is cut to 0.2 so the busy case is quick; the lock's time is set 60 seconds back
        to pass audit.py's 30-second staleness limit."""
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
        """Non-ASCII text, U+2028 and a newline in a field are escaped, so a record stays one ASCII line.

        U+2028 (line separator) is included because some line readers split on it."""
        audit.append(self.path, {"client_info": {"name": "caf\u00e9\u2028\n"}})
        lines = self.lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["client_info"]["name"], "caf\u00e9\u2028\n")
        self.assertTrue(lines[0].isascii())


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=99b45a1963f7af5548715945323ebac9900a0a609b8856708a05f74ad5421527 ====
