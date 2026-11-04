# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_scans.py
# About: Tests for scan counts: analytics CSVs with the utm_content tag, server access logs in...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for scan counts: analytics CSVs, access logs, imports twice, and only counts kept.

The CSVs carry the utm_content tag the redirect pages add; the logs come in both common formats
(Common and Combined Log Format), plain or gzipped.

scans.py reads a file into counts per (short-link ID, day); short_link_ops.import_scan_file hands them
to registry.import_scans; finding.search, votes.board and ecp show or rank with them.

What the classes pin:
  1. TagTests: the small parsers (an ID in a utm_content tag or a request path, a day, a count).
  2. ReadingTests: whole files: an analytics export, a plain CSV, a server log, a gzipped log.
  3. ImportTests: a real registry with one short link: importing twice, logs that grew or were
     rotated, that no address or user agent reaches the database, and the scans ranking switch.
  4. EcpTests: ECP's recommendations count scans only when the switch is on.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import gzip
import os
import shutil
import sqlite3
import tempfile
import unittest

import app_settings
import ecp
import finding
import making
import scans
import short_link_ops
import shortlinks
import votes

# Two valid short-link IDs (seven digits and their Damm check digit), and the visitor details a log
# line carries, which must never reach the registry. 203.0.113.0/24 is RFC 5737's documentation range.
FIRST = "1234567" + shortlinks.check_digit("1234567")
SECOND = "7654321" + shortlinks.check_digit("7654321")
ADDRESS = "203.0.113.9"
AGENT = "Mozilla/5.0 (Example Phone)"


def log_line(code_path, day="28/Oct/2026", clock="06:25:03", method="GET", status=200):
    """One Combined Log Format line: a request for `code_path` with a referrer and AGENT, ending in a newline.

    Combined is Common Log Format (host, identity, user, [time], "request", status, size) plus the
    referrer and the user agent."""
    return (ADDRESS + ' - - [' + day + ':' + clock + ' +0000] "' + method + " " + code_path + ' HTTP/1.1" ' + str(status) +
            ' 512 "https://example.com/" "' + AGENT + '"\n')


class TagTests(unittest.TestCase):
    """The parsers scans.py builds its readers from."""

    def test_the_tag_holds_the_id(self):
        """The ID is the part of a tag before its first "-"; text without a valid ID gives "".

        12345678 fails its check digit, so it is no ID even though it looks like one."""
        self.assertEqual(scans.code_in_tag(FIRST + "-3366cc"), FIRST)
        self.assertEqual(scans.code_in_tag(FIRST), FIRST)
        for text in ("", "summer-sale", "12345678-3366cc", "abc"):
            self.assertEqual(scans.code_in_tag(text), "", text)

    def test_days_and_counts(self):
        """Days come as YYYY-MM-DD or YYYYMMDD and must be real; counts may hold thousands commas and spaces.

        A count that is negative, a fraction, a word or empty gives -1."""
        self.assertEqual(scans.day_of("2026-10-28"), "2026-10-28")
        self.assertEqual(scans.day_of("20261028"), "2026-10-28")
        for text in ("2026-13-01", "28/10/2026", "soon", ""):
            self.assertEqual(scans.day_of(text), "", text)
        self.assertEqual(scans.count_of("1,234"), 1234)
        self.assertEqual(scans.count_of(" 7 "), 7)
        for text in ("-1", "1.5", "many", ""):
            self.assertEqual(scans.count_of(text), -1, text)

    def test_ids_in_paths(self):
        """The ID is the last path part, with or without a trailing slash, index.html or a query; other paths give ""."""
        for path in ("/" + FIRST + "/", "/" + FIRST, "/" + FIRST + "/index.html", "/go/" + FIRST + "/?utm_source=qr"):
            self.assertEqual(scans.code_in_path(path), FIRST, path)
        for path in ("/", "/robots.txt", "/12345678/", "/index.html"):
            self.assertEqual(scans.code_in_path(path), "", path)


class ReadingTests(unittest.TestCase):
    """scans.read_file on whole files written into a temporary folder."""

    def setUp(self):
        """Make the temporary folder."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_scans_")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, name, text, encoding="utf-8"):
        """Write `text` as it is (newline="" keeps its own line ends) -> the file's path."""
        path = os.path.join(self.folder, name)
        handle = open(path, "w", encoding=encoding, newline="")
        handle.write(text)
        handle.close()
        return path

    def test_an_analytics_export(self):
        """An analytics export with a BOM, comment lines, CRLF and extra columns is read; rows of one ID and day add up.

        The two Delft and Leiden rows make 7; "1,204" is quoted because of its comma. Five rows are
        read and two ignored: summer-sale holds no ID and the last row has no tag."""
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
        """A CSV separated by ";" (as spreadsheets write where the comma is the decimal mark) is read too."""
        read = scans.read_file(self.write("a.csv", "day;utm_content;count\n2026-10-28;" + FIRST + "-3366cc;3\n"))
        self.assertEqual(read["value"]["counts"], {(FIRST, "2026-10-28"): 3})

    def test_a_csv_without_the_columns_is_refused(self):
        """A CSV without a date, tag and count column is refused by name; an empty file and a missing one fail too."""
        refused = scans.read_file(self.write("a.csv", "name,value\nx,1\n"))
        self.assertFalse(refused["ok"])
        self.assertIn("date column", refused["error"])
        self.assertFalse(scans.read_file(self.write("b.csv", ""))["ok"])
        self.assertFalse(scans.read_file(os.path.join(self.folder, "missing.csv"))["ok"])

    def test_a_server_log(self):
        """A log counts successful GETs of /ID/ or /ID per day, and its source is named after its first request's time.

        Counted: FIRST twice on the 28th (with and without the slash), once on the 29th (with a
        query), SECOND on the 28th once with 304 (a 3xx still served the page) and once in Common
        Log Format (no referrer or agent). Ignored (4): the HEAD, the 404, robots.txt and the line
        that is not a log line."""
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
        """A rotated, gzipped log (.gz) is read through gzip like a plain one."""
        path = os.path.join(self.folder, "access.log.1.gz")
        handle = gzip.open(path, "wb")
        handle.write(log_line("/" + FIRST + "/").encode("ascii"))
        handle.close()
        self.assertEqual(scans.read_file(path)["value"]["counts"], {(FIRST, "2026-10-28"): 1})

    def test_a_log_with_odd_bytes_is_read(self):
        """A line of bytes that are not UTF-8 (0xff 0xfe) does not stop the log: it is read as Latin-1 and ignored."""
        path = os.path.join(self.folder, "access.log")
        handle = open(path, "wb")
        handle.write(log_line("/" + FIRST + "/").encode("ascii") + b'\xff\xfe odd "\n')
        handle.close()
        self.assertEqual(scans.read_file(path)["value"]["counts"], {(FIRST, "2026-10-28"): 1})


class ImportTests(unittest.TestCase):
    """Importing scan files into a real registry with one short link, and what then reads them."""

    def setUp(self):
        """Make a code for example.com/menu with a nonlocal short link (ID FIRST, if free) and keep its ID.

        make_qr draws, saves and registers the picture at 4 pixels per module."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_scan_import_")
        self.db = os.path.join(self.folder, "palette.db")
        made = making.make_qr(self.db, "https://example.com/menu", "#3366cc", "M", os.path.join(self.folder, "a.png"),
                              4, short_link_ops.short_request(FIRST, "nonlocal"))
        self.assertTrue(made["ok"], made["error"])
        self.code = made["value"]["short_code"]

    def tearDown(self):
        """Remove the folder and the registry in it."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, name, text):
        """Write `text` as it is into the folder (replacing any file of that name) -> the file's path."""
        path = os.path.join(self.folder, name)
        handle = open(path, "w", encoding="utf-8", newline="")
        handle.write(text)
        handle.close()
        return path

    def total(self, today="2026-10-31"):
        """The menu code's ScanCount as the Find tab shows it, with "recent" counted back from `today`."""
        found = finding.search(self.db, "qr_code", "example.com/menu", False, 20, today)["value"]
        return found[0]["scans"]

    def test_importing_the_same_file_twice_changes_nothing(self):
        """A report imported twice still counts 7: the second import replaces its own rows."""
        path = self.write("r.csv", "date,utm_content,count\n2026-10-28," + self.code + "-3366cc,5\n"
                                   "2026-10-29," + self.code + "-3366cc,2\n")
        first = short_link_ops.import_scan_file(self.db, path)
        self.assertTrue(first["ok"], first["error"])
        self.assertEqual((first["value"]["days"], first["value"]["scans"], first["value"]["unknown"]), (2, 7, []))
        self.assertEqual(self.total(), {"total": 7, "recent": 7})
        short_link_ops.import_scan_file(self.db, path)
        self.assertEqual(self.total(), {"total": 7, "recent": 7})

    def test_a_log_that_grew_or_was_rotated_imports_over_itself(self):
        """A log is known by its first request's time, so the same lines never count twice, whatever the file is called.

        The grown log and its rotated copy share their first line, so each replaces the other's count;
        the new log starts later, so it is a new source and adds to the day."""
        first = log_line("/" + self.code + "/")
        path = self.write("access.log", first)
        short_link_ops.import_scan_file(self.db, path)
        self.assertEqual(self.total()["total"], 1)
        path = self.write("access.log", first + log_line("/" + self.code + "/", clock="09:00:00"))
        short_link_ops.import_scan_file(self.db, path)
        self.assertEqual(self.total()["total"], 2)  # the same file, grown
        rotated = self.write("access.log.1", first + log_line("/" + self.code + "/", clock="09:00:00"))
        short_link_ops.import_scan_file(self.db, rotated)
        self.assertEqual(self.total()["total"], 2)  # the same lines under the rotated name
        newer = self.write("access.log", log_line("/" + self.code + "/", clock="10:00:00"))
        short_link_ops.import_scan_file(self.db, newer)
        self.assertEqual(self.total()["total"], 3)  # a new file for the same day adds to it

    def test_only_counts_are_kept(self):
        """Only an ID, a day, a source and a count are written: the visitor's address and user agent appear nowhere in the file.

        SECOND is no short link in this registry, so it is reported as unknown and not counted. The
        whole database file is searched as bytes, so no table or free page holds them either."""
        path = self.write("access.log", log_line("/" + self.code + "/") + log_line("/" + SECOND + "/"))
        read = short_link_ops.import_scan_file(self.db, path)
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
        """A code without a short link shows None for scans (not zero); the short link with no imports shows zeros."""
        making.make_qr(self.db, "https://example.com/plain", "#3366cc", "M", os.path.join(self.folder, "b.png"), 4)
        found = finding.search(self.db, "qr_code", "example.com/plain", False, 20)["value"]
        self.assertIsNone(found[0]["scans"])
        self.assertEqual(self.total(), {"total": 0, "recent": 0})

    def test_scans_feed_the_ranking_only_when_turned_on(self):
        """With 50 scans imported, #3366cc tops the scans preset only while SCANS_VOTE is on; the mixer preset never changes.

        SCANS_VOTE is a module global (settings.json's colors.scans_vote), set here and put back."""
        self.write("r.csv", "date,utm_content,count\n2026-10-28," + self.code + "-3366cc,50\n")
        short_link_ops.import_scan_file(self.db, os.path.join(self.folder, "r.csv"))
        before = votes.board(self.db, "scans")["value"]["order"]
        saved = app_settings.SCANS_VOTE
        app_settings.SCANS_VOTE = True
        try:
            after = votes.board(self.db, "scans")["value"]["order"]
            mixer = votes.board(self.db, "mixer")["value"]["order"]
        finally:
            app_settings.SCANS_VOTE = saved
        self.assertNotEqual(before[0], "#3366cc")
        self.assertEqual(after[0], "#3366cc")
        self.assertEqual(mixer, votes.board(self.db, "mixer")["value"]["order"])


class EcpTests(unittest.TestCase):
    """ECP's recommend intent with and without scans counting."""

    def setUp(self):
        """A registry with one #3366cc short link (ID FIRST) and 50 scans imported for it."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_scan_ecp_")
        self.db = os.path.join(self.folder, "palette.db")
        made = making.make_qr(self.db, "https://example.com/menu", "#3366cc", "M", os.path.join(self.folder, "a.png"),
                              4, short_link_ops.short_request(FIRST, "nonlocal"))
        self.assertTrue(made["ok"], made["error"])
        path = os.path.join(self.folder, "r.csv")
        handle = open(path, "w", encoding="utf-8")
        handle.write("date,utm_content,count\n2026-10-28," + FIRST + "-3366cc,50\n")
        handle.close()
        self.assertTrue(short_link_ops.import_scan_file(self.db, path)["ok"])

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def first_color(self, scans_vote):
        """The first color ECP recommends with the scans preset -> "#rrggbb".

        The engine's model address (127.0.0.1 port 1) is never called: a recommend plan built here
        runs without a model. "0.1.0" is only the version an MCP client would be told."""
        engine = ecp.new_engine(self.db, "http://127.0.0.1:1", 1.0, "0.1.0")
        engine["scans_vote"] = scans_vote
        snapshot = ecp.read_environment(engine)
        self.assertTrue(snapshot["ok"], snapshot["detail"])
        plan = ecp.empty_plan()
        plan["intent"] = "recommend"
        return ecp.run_plan(snapshot["value"], plan, "scans", engine["links"])["colors"][0]["hex"]

    def test_recommendations_count_scans_only_when_turned_on(self):
        """#3366cc comes first only when the engine's scans_vote is on."""
        self.assertNotEqual(self.first_color(False), "#3366cc")
        self.assertEqual(self.first_color(True), "#3366cc")


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=07ee7b01961bb6df33e87a06507555fc6f3be2eee3c249f2b9e4844e450ad5e0 ====
