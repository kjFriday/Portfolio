# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_scans.py
# About: Tests for scan counts: analytics CSVs with the utm_content tag, server access logs in...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for scan counts: analytics CSVs with the utm_content tag, server access logs in both common formats,
importing the same file twice, and that nothing but counts is kept."""

import gzip
import os
import shutil
import sqlite3
import tempfile
import unittest

import qr_palette
import scans
import shortlinks

FIRST = "1234567" + shortlinks.check_digit("1234567")
SECOND = "7654321" + shortlinks.check_digit("7654321")
ADDRESS = "203.0.113.9"
AGENT = "Mozilla/5.0 (Example Phone)"


def log_line(code_path, day="28/Oct/2026", clock="06:25:03", method="GET", status=200):
    return (ADDRESS + ' - - [' + day + ':' + clock + ' +0000] "' + method + " " + code_path + ' HTTP/1.1" ' + str(status) +
            ' 512 "https://example.com/" "' + AGENT + '"\n')


class TagTests(unittest.TestCase):
    def test_the_tag_holds_the_id(self):
        self.assertEqual(scans.code_in_tag(FIRST + "-3366cc"), FIRST)
        self.assertEqual(scans.code_in_tag(FIRST), FIRST)
        for text in ("", "summer-sale", "12345678-3366cc", "abc"):
            self.assertEqual(scans.code_in_tag(text), "", text)

    def test_days_and_counts(self):
        self.assertEqual(scans.day_of("2026-10-28"), "2026-10-28")
        self.assertEqual(scans.day_of("20261028"), "2026-10-28")
        for text in ("2026-13-01", "28/10/2026", "soon", ""):
            self.assertEqual(scans.day_of(text), "", text)
        self.assertEqual(scans.count_of("1,234"), 1234)
        self.assertEqual(scans.count_of(" 7 "), 7)
        for text in ("-1", "1.5", "many", ""):
            self.assertEqual(scans.count_of(text), -1, text)

    def test_ids_in_paths(self):
        for path in ("/" + FIRST + "/", "/" + FIRST, "/" + FIRST + "/index.html", "/go/" + FIRST + "/?utm_source=qr"):
            self.assertEqual(scans.code_in_path(path), FIRST, path)
        for path in ("/", "/robots.txt", "/12345678/", "/index.html"):
            self.assertEqual(scans.code_in_path(path), "", path)


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_scans_")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, name, text, encoding="utf-8"):
        path = os.path.join(self.folder, name)
        handle = open(path, "w", encoding=encoding, newline="")
        handle.write(text)
        handle.close()
        return path

    def test_an_analytics_export(self):
        path = self.write("report.csv",
                          "# Traffic report\r\n# 2026-10-01 to 2026-10-31\r\n\r\n"
                          "Date,Session manual ad content,City,Sessions\r\n"
                          "20261028," + FIRST + "-3366cc,Delft,5\r\n"
                          "20261028," + FIRST + "-3366cc,Leiden,2\r\n"
                          "20261029," + SECOND + "-006633,Delft,\"1,204\"\r\n"
                          "20261029,summer-sale,Delft,9\r\n"
                          "20261029,,Delft,3\r\n", "utf-8-sig")
        read = scans.read_file(path)
        self.assertTrue(read["ok"], read["error"])
        self.assertEqual(read["value"]["counts"], {(FIRST, "2026-10-28"): 7, (SECOND, "2026-10-29"): 1204})
        self.assertEqual((read["value"]["kind"], read["value"]["source"]), ("analytics", "analytics"))
        self.assertEqual((read["value"]["read"], read["value"]["ignored"]), (5, 2))

    def test_a_plain_csv_and_semicolons(self):
        read = scans.read_file(self.write("a.csv", "day;utm_content;count\n2026-10-28;" + FIRST + "-3366cc;3\n"))
        self.assertEqual(read["value"]["counts"], {(FIRST, "2026-10-28"): 3})

    def test_a_csv_without_the_columns_is_refused(self):
        refused = scans.read_file(self.write("a.csv", "name,value\nx,1\n"))
        self.assertFalse(refused["ok"])
        self.assertIn("date column", refused["error"])
        self.assertFalse(scans.read_file(self.write("b.csv", ""))["ok"])
        self.assertFalse(scans.read_file(os.path.join(self.folder, "missing.csv"))["ok"])

    def test_a_server_log(self):
        path = self.write("access.log",
                          log_line("/" + FIRST + "/") + log_line("/" + FIRST, clock="07:00:00") +
                          log_line("/" + FIRST + "/?utm_source=qr", day="29/Oct/2026") +
                          log_line("/" + SECOND + "/", status=304) +
                          log_line("/" + FIRST + "/", method="HEAD") +
                          log_line("/" + FIRST + "/", status=404) +
                          log_line("/robots.txt") + "not a log line\n" +
                          ADDRESS + ' - - [28/Oct/2026:08:00:00 +0000] "GET /' + SECOND + '/ HTTP/1.1" 200 512\n')
        read = scans.read_file(path)
        self.assertTrue(read["ok"], read["error"])
        self.assertEqual(read["value"]["counts"], {(FIRST, "2026-10-28"): 2, (FIRST, "2026-10-29"): 1,
                                                   (SECOND, "2026-10-28"): 2})
        self.assertEqual(read["value"]["source"], "server log from 2026-10-28T06:25:03")
        self.assertEqual(read["value"]["kind"], "log")
        self.assertEqual(read["value"]["ignored"], 4)

    def test_a_gzipped_log(self):
        path = os.path.join(self.folder, "access.log.1.gz")
        handle = gzip.open(path, "wb")
        handle.write(log_line("/" + FIRST + "/").encode("ascii"))
        handle.close()
        self.assertEqual(scans.read_file(path)["value"]["counts"], {(FIRST, "2026-10-28"): 1})

    def test_a_log_with_odd_bytes_is_read(self):
        path = os.path.join(self.folder, "access.log")
        handle = open(path, "wb")
        handle.write(log_line("/" + FIRST + "/").encode("ascii") + b'\xff\xfe odd "\n')
        handle.close()
        self.assertEqual(scans.read_file(path)["value"]["counts"], {(FIRST, "2026-10-28"): 1})


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_scan_import_")
        self.db = os.path.join(self.folder, "palette.db")
        made = qr_palette.make_qr(self.db, "https://example.com/menu", "#3366cc", "M", os.path.join(self.folder, "a.png"),
                                  4, qr_palette.short_request(FIRST, "nonlocal"))
        self.assertTrue(made["ok"], made["error"])
        self.code = made["value"]["short_code"]

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.folder, name)
        handle = open(path, "w", encoding="utf-8", newline="")
        handle.write(text)
        handle.close()
        return path

    def total(self, today="2026-10-31"):
        found = qr_palette.search(self.db, "qr_code", "example.com/menu", False, 20, today)["value"]
        return found[0]["scans"]

    def test_importing_the_same_file_twice_changes_nothing(self):
        path = self.write("r.csv", "date,utm_content,count\n2026-10-28," + self.code + "-3366cc,5\n"
                                   "2026-10-29," + self.code + "-3366cc,2\n")
        first = qr_palette.import_scan_file(self.db, path)
        self.assertTrue(first["ok"], first["error"])
        self.assertEqual((first["value"]["days"], first["value"]["scans"], first["value"]["unknown"]), (2, 7, []))
        self.assertEqual(self.total(), {"total": 7, "recent": 7})
        qr_palette.import_scan_file(self.db, path)
        self.assertEqual(self.total(), {"total": 7, "recent": 7})

    def test_a_log_that_grew_or_was_rotated_imports_over_itself(self):
        first = log_line("/" + self.code + "/")
        path = self.write("access.log", first)
        qr_palette.import_scan_file(self.db, path)
        self.assertEqual(self.total()["total"], 1)
        path = self.write("access.log", first + log_line("/" + self.code + "/", clock="09:00:00"))
        qr_palette.import_scan_file(self.db, path)
        self.assertEqual(self.total()["total"], 2)  # the same file, grown
        rotated = self.write("access.log.1", first + log_line("/" + self.code + "/", clock="09:00:00"))
        qr_palette.import_scan_file(self.db, rotated)
        self.assertEqual(self.total()["total"], 2)  # the same lines under the rotated name
        newer = self.write("access.log", log_line("/" + self.code + "/", clock="10:00:00"))
        qr_palette.import_scan_file(self.db, newer)
        self.assertEqual(self.total()["total"], 3)  # a new file for the same day adds to it

    def test_only_counts_are_kept(self):
        path = self.write("access.log", log_line("/" + self.code + "/") + log_line("/" + SECOND + "/"))
        read = qr_palette.import_scan_file(self.db, path)
        self.assertEqual(read["value"]["unknown"], [SECOND])
        self.assertEqual(read["value"]["scans"], 1)
        handle = open(self.db, "rb")
        data = handle.read()
        handle.close()
        for text in (ADDRESS, AGENT):
            self.assertNotIn(text.encode("ascii"), data)
        connection = sqlite3.connect(self.db)
        row = connection.execute("SELECT code, day, source, count FROM scans").fetchone()
        connection.close()
        self.assertEqual(row, (self.code, "2026-10-28", "server log from 2026-10-28T06:25:03", 1))

    def test_a_code_without_a_short_link_has_no_scans_to_show(self):
        qr_palette.make_qr(self.db, "https://example.com/plain", "#3366cc", "M", os.path.join(self.folder, "b.png"), 4)
        found = qr_palette.search(self.db, "qr_code", "example.com/plain", False, 20)["value"]
        self.assertIsNone(found[0]["scans"])
        self.assertEqual(self.total(), {"total": 0, "recent": 0})

    def test_scans_feed_the_ranking_only_when_turned_on(self):
        self.write("r.csv", "date,utm_content,count\n2026-10-28," + self.code + "-3366cc,50\n")
        qr_palette.import_scan_file(self.db, os.path.join(self.folder, "r.csv"))
        before = qr_palette.board(self.db, "scans")["value"]["order"]
        saved = qr_palette.SCANS_VOTE
        qr_palette.SCANS_VOTE = True
        try:
            after = qr_palette.board(self.db, "scans")["value"]["order"]
            mixer = qr_palette.board(self.db, "mixer")["value"]["order"]
        finally:
            qr_palette.SCANS_VOTE = saved
        self.assertNotEqual(before[0], "#3366cc")
        self.assertEqual(after[0], "#3366cc")
        self.assertEqual(mixer, qr_palette.board(self.db, "mixer")["value"]["order"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=5e64d10fb7a5a22cf6ed34cd48d5953314b3a27f195a646d57ebefe3b9b6b8c2 ====
