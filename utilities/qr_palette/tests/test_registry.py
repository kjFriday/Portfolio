# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_registry.py
# About: Tests for the registry: schema, opening rules, saving, votes and finding.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for the registry: schema, opening rules, saving, votes and finding.

registry.py keeps QR Palette's SQLite database: colors, links, QR codes, votes, short links, their
history and schedules, and scan counts. Every test here works on a fresh palette.db in its own
temporary folder, opened through registry.connect() just as the program opens it: read-write for the
window's work, read-only (the "read rail") for ECP, MCP and print sheets.

What the classes pin:
  1. OpeningTests: a new file gets the schema, the 216 cube colors and the header marks
     (application_id "QRPA", user_version); other files and other versions are refused; read-only
     never creates or writes.
  2. ReadRailTests: the read-only connection may read only the allow-listed columns, is hardened,
     stops a long query and refuses a damaged file.
  3. ShortLinkTests: short links are saved, reused, retargeted and read; older registries (versions 1
     and 2) are read as they are and moved up only after a copy is kept.
  4. HistoryTests, ScanTests, MaskedTests, BackupTests: version 3's history, schedules, scan counts,
     masked payload hashes and checked backups.
  5. SavingTests, VoteTests, FindTests: saving and forgetting records, votes, and find_rows' filters.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
Start reading at RegistryCase.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import registry
import shortlinks
import swatch


def entry(folder, name, link, color):
    """A valid registry Entry for a PNG at `folder`/`name`: level M, version 3, origin "made".

    The file itself is never written; save_qr only needs an absolute path."""
    return {"link": link, "color": color, "path": os.path.join(folder, name), "format": "png", "ec_level": "M",
            "version": 3, "origin": "made"}


class RegistryCase(unittest.TestCase):
    """A registry at palette.db in a fresh temporary folder, with every connection closed at the end."""

    def setUp(self):
        """Make the folder; the registry file itself is created by the first read-write open."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_registry_")
        self.path = os.path.join(self.folder, "palette.db")
        self.connections = []

    def tearDown(self):
        """Close every connection opened through open() (closing one twice is harmless), then remove the folder."""
        for connection in self.connections:
            registry.close(connection)
        shutil.rmtree(self.folder, ignore_errors=True)

    def open(self, read_only):
        """Open the registry, failing the test with registry's own error when it cannot -> the connection."""
        opened = registry.connect(self.path, read_only)
        self.assertTrue(opened["ok"], opened["error"])
        self.connections.append(opened["value"])
        return opened["value"]


class OpeningTests(RegistryCase):
    """What connect() creates, accepts and refuses."""

    def test_a_new_registry_has_the_cube_and_its_marks(self):
        """A new registry holds its header marks, all 216 cube colors with names, and the rollback journal.

        #006666 stands for every cube color: its name, family and cube index come from swatch."""
        connection = self.open(False)
        self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], registry.APPLICATION_ID)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], registry.SCHEMA_VERSION)
        self.assertEqual(connection.execute("SELECT count(*) FROM colors").fetchone()[0], 216)
        row = connection.execute("SELECT name, family, cube_index FROM colors WHERE hex = '#006666'").fetchone()
        self.assertEqual((row[0], row[1], row[2]), ("Muted teal", "teal", swatch.cube_index("#006666")))
        # "delete" is SQLite's default rollback journal: WAL would make a read-only reader write a -shm file
        self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_an_older_wal_registry_is_switched_back(self):
        """A registry left in WAL mode (as before 0.1.0) is switched back to the rollback journal on a writable open."""
        connection = self.open(False)
        connection.execute("PRAGMA journal_mode=WAL")
        registry.close(connection)
        again = self.open(False)
        self.assertEqual(again.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_reopening_keeps_what_was_saved(self):
        """A saved record is still there after the connection is closed and the file opened again."""
        connection = self.open(False)
        self.assertTrue(registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))["ok"])
        registry.close(connection)
        again = self.open(False)
        self.assertEqual(registry.counts(again)["records"], 1)

    def test_other_databases_are_refused(self):
        """Another SQLite database (no "QRPA" application_id) is refused both ways, and a text file is refused too.

        The SQLite file is refused by registry's own header check; the text file never gets that far,
        because SQLite itself finds no database header in it."""
        other = sqlite3.connect(self.path)
        other.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
        other.commit()
        other.close()
        self.assertIn("not a QR Palette registry", registry.connect(self.path, False)["error"])
        self.assertIn("not a QR Palette registry", registry.connect(self.path, True)["error"])
        os.remove(self.path)
        handle = open(self.path, "w", encoding="utf-8")
        handle.write("this is a text file, not a database\n" * 40)
        handle.close()
        self.assertFalse(registry.connect(self.path, False)["ok"])

    def test_another_schema_version_is_refused(self):
        """A registry whose user_version is not one this program reads (7 here) is refused."""
        connection = self.open(False)
        connection.execute("PRAGMA user_version=7")
        registry.close(connection)
        self.assertIn("another version", registry.connect(self.path, False)["error"])

    def test_read_only_never_creates(self):
        """A read-only open of a missing file fails with "no registry yet" and leaves no file behind."""
        result = registry.connect(self.path, True)
        self.assertFalse(result["ok"])
        self.assertIn("no registry yet", result["error"])
        self.assertFalse(os.path.exists(self.path))

    def test_read_only_refuses_writes(self):
        """A read-only connection refuses writes: save_qr fails, and a raw INSERT raises sqlite3.Error."""
        registry.close(self.open(False))
        reader = self.open(True)
        result = registry.save_qr(reader, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        self.assertFalse(result["ok"])
        with self.assertRaises(sqlite3.Error):
            reader.execute("INSERT INTO links (url) VALUES ('https://example.com/x')")

    def test_read_only_opens_after_every_writer_closed(self):
        """Once the writer has closed, a read-only open sees what it saved."""
        writer = self.open(False)
        registry.save_qr(writer, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        registry.close(writer)
        reader = self.open(True)
        self.assertEqual(len(registry.all_rows(reader)), 1)

    def test_a_reader_works_while_a_write_is_open(self):
        """A reader is not blocked by a writer's open transaction, and sees its rows only after COMMIT.

        BEGIN IMMEDIATE takes SQLite's RESERVED lock, which still lets readers in; the reader sees
        the last committed state (one link) until the writer commits the second."""
        writer = self.open(False)
        registry.save_qr(writer, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        reader = self.open(True)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO links (url) VALUES ('https://example.com/pending')")
        self.assertEqual(len(registry.all_rows(reader)), 1)
        self.assertEqual(registry.counts(reader)["links"], 1)
        writer.execute("COMMIT")
        self.assertEqual(registry.counts(reader)["links"], 2)

    def test_the_registry_holds_data_only(self):
        """The registry's tables are exactly the data tables of schema version 3 (settings live in settings.json)."""
        connection = self.open(False)
        tables = []
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
            tables.append(row[0])
        self.assertEqual(tables, ["colors", "links", "qr_codes", "scans", "scheduled_changes", "short_link_changes",
                                  "short_links", "votes"])


class ReadRailTests(RegistryCase):
    """The read-only connection ("read rail") that ECP and MCP use: allow-list, hardening and time limit."""

    def setUp(self):
        """A registry with one record and one vote, written and closed before any test opens it read-only.

        STATEMENT_SECONDS is a module global one test shortens, so it is kept and put back."""
        RegistryCase.setUp(self)
        self.saved = registry.STATEMENT_SECONDS
        writer = self.open(False)
        registry.save_qr(writer, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        registry.vote(writer, "#3366cc", 1)
        registry.close(writer)

    def tearDown(self):
        """Put STATEMENT_SECONDS back, then clean up as RegistryCase does."""
        registry.STATEMENT_SECONDS = self.saved
        RegistryCase.tearDown(self)

    def test_everything_an_answer_needs_can_be_read(self):
        """Every reader an ECP answer uses passes the read rail's authorizer."""
        reader = self.open(True)
        self.assertEqual(len(registry.all_rows(reader)), 1)
        self.assertEqual(registry.counts(reader)["records"], 1)
        self.assertEqual(registry.vote_log(reader), [{"color": "#3366cc", "voat": 1}])
        self.assertEqual(registry.vote_map(reader), {"#3366cc": 1})
        self.assertEqual(registry.colors_in_use(reader)[0]["hex"], "#3366cc")

    def test_everything_else_is_denied(self):
        """Each statement outside the allow-list fails with a database error.

        In order: a column not allowed (r), a function not allowed (lower), the schema table, any
        PRAGMA, a write, ATTACH, a temporary table, and loading an extension."""
        reader = self.open(True)
        for statement in ("SELECT r FROM colors", "SELECT lower(hex) FROM colors", "SELECT name FROM sqlite_master",
                          "PRAGMA journal_mode", "PRAGMA writable_schema=ON",
                          "INSERT INTO links (url) VALUES ('https://example.com/x')",
                          "ATTACH DATABASE ':memory:' AS other", "CREATE TEMP TABLE scratch (x)",
                          "SELECT load_extension('anything')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=statement):
                reader.execute(statement).fetchall()

    def test_the_connection_is_hardened(self):
        """Where this Python can read them back, DEFENSIVE is on, trusted schema and triggers are off, and the limits hold.

        getconfig arrives in Python 3.12 and getlimit in 3.11, so an older Python checks less. 10000
        is READ_LIMITS' longest SQL statement, in bytes."""
        reader = self.open(True)
        if hasattr(reader, "getconfig") and hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
            self.assertTrue(reader.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE))
            self.assertFalse(reader.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA))
            self.assertFalse(reader.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER))
        if hasattr(reader, "getlimit"):
            self.assertEqual(reader.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED), 0)
            self.assertEqual(reader.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH), 10000)

    def test_a_long_read_is_stopped(self):
        """A query running past STATEMENT_SECONDS is stopped by the progress handler with "interrupted".

        The deadline is cut to 0.05 seconds, and a three-way cross join of the 216 colors (about ten
        million rows) takes far longer than that to count."""
        registry.STATEMENT_SECONDS = 0.05
        reader = self.open(True)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            reader.execute("SELECT count(*) FROM colors a, colors b, colors c").fetchone()
        self.assertIn("interrupted", str(caught.exception))

    def test_a_damaged_registry_is_not_served(self):
        """A registry with a page overwritten by 0xff bytes fails quick_check, so the read rail refuses it.

        SQLite's default page is 4096 bytes, so this is the third page (bytes 8192 to 12287). Page 1,
        with the header marks, is untouched, so the file still looks like a registry until it is checked."""
        handle = open(self.path, "r+b")
        handle.seek(2 * 4096)
        handle.write(b"\xff" * 4096)
        handle.close()
        self.assertFalse(registry.connect(self.path, True)["ok"])


# the destination most short-link tests send their short link to
TARGET = "https://shop.example.com/hours"


def code_of(body):
    """A valid short-link ID: `body` with its Damm check digit added."""
    return body + shortlinks.check_digit(body)


def short_entry(folder, name, code, color, target):
    """An Entry for a code that prints HTTPS://GO.EXAMPLE.COM/`code` and records it as a short link to `target`."""
    made = entry(folder, name, "HTTPS://GO.EXAMPLE.COM/" + code, color)
    made["short"] = {"code": code, "target": target}
    return made


class ShortLinkTests(RegistryCase):
    """Short links in the registry, and registries left by older versions of the program."""

    def setUp(self):
        """A registry folder and one valid ID, 1234567 with its check digit."""
        RegistryCase.setUp(self)
        self.code = code_of("1234567")

    def test_short_links_are_saved_reused_and_found_by_destination(self):
        """Two pictures of one short link share one row; it is found by destination, color and base, and by every filter.

        The last loop finds both pictures by a word of the destination, the exact destination, the
        exact printed address and the ID alone."""
        connection = self.open(False)
        self.assertTrue(registry.save_qr(connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))["ok"])
        self.assertTrue(registry.save_qr(connection, short_entry(self.folder, "a.svg", self.code, "#3366cc", TARGET))["ok"])
        found = registry.short_links(connection)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["code"], found[0]["target"], found[0]["hex"], found[0]["pictures"]),
                         (self.code, TARGET, "#3366cc", 2))
        self.assertEqual(registry.short_link_for(connection, TARGET, "#3366cc", "HTTPS://GO.EXAMPLE.COM/")["code"],
                         self.code)
        self.assertIsNone(registry.short_link_for(connection, TARGET, "#006633", "HTTPS://GO.EXAMPLE.COM/"))
        self.assertIsNone(registry.short_link_for(connection, TARGET, "#3366cc", "HTTP://LOCALHOST:8000/"))
        row = registry.all_rows(connection)[0]
        self.assertEqual((row["short_code"], row["target"]), (self.code, TARGET))
        rows = registry.all_rows(connection)
        for changes in ({"link": "hours"}, {"link_exact": TARGET}, {"link_exact": "HTTPS://GO.EXAMPLE.COM/" + self.code},
                        {"link": self.code}):
            filters = registry.empty_filters()
            for key in changes:
                filters[key] = changes[key]
            self.assertEqual(len(registry.find_rows(rows, filters, 20)), 2, changes)

    def test_an_id_cannot_move_to_another_address(self):
        """An ID already used for one printed address is refused for another, and an ID with letters is refused.

        Nothing is saved for the refused entry: the record count stays 1."""
        connection = self.open(False)
        registry.save_qr(connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        moved = entry(self.folder, "b.png", "HTTPS://OTHER.EXAMPLE.COM/" + self.code, "#3366cc")
        moved["short"] = {"code": self.code, "target": TARGET}
        self.assertIn("already used", registry.save_qr(connection, moved)["error"])
        self.assertEqual(registry.counts(connection)["records"], 1)
        bad = short_entry(self.folder, "c.png", "12AB", "#3366cc", TARGET)
        self.assertFalse(registry.save_qr(connection, bad)["ok"])

    def test_forgetting_the_pictures_keeps_the_printed_link_and_it_can_be_retargeted(self):
        """Forgetting a short link's last picture keeps the short link and its link, which can still be retargeted.

        Printed codes still use the address, so the link must outlive its pictures; retargeting an
        unknown ID answers False."""
        connection = self.open(False)
        number = registry.save_qr(connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))["value"]
        registry.forget_qr(connection, number)
        found = registry.short_links(connection)
        self.assertEqual((len(found), found[0]["pictures"]), (1, 0))
        self.assertEqual(registry.counts(connection)["links"], 1)
        self.assertTrue(registry.retarget(connection, self.code, "https://shop.example.com/holidays")["value"])
        self.assertEqual(registry.short_links(connection)[0]["target"], "https://shop.example.com/holidays")
        self.assertFalse(registry.retarget(connection, code_of("7654321"), TARGET)["value"])
        self.assertTrue(registry.code_taken(connection, self.code))

    def test_the_read_rail_reads_short_links(self):
        """The read-only connection may read short links and their destinations."""
        writer = self.open(False)
        registry.save_qr(writer, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        registry.close(writer)
        reader = self.open(True)
        self.assertEqual(registry.short_links(reader)[0]["target"], TARGET)
        self.assertEqual(registry.all_rows(reader)[0]["target"], TARGET)

    def older_registry(self, version):
        """A registry as an older program left it, built from that version's own statements.

        Version 1 gets one color, one link and one code. Version 2 adds the short-link tables and a
        second code that prints self.code as a short link to TARGET. The header marks are set last,
        as create_schema sets them."""
        plain = sqlite3.connect(self.path)
        for statement in registry.SCHEMA:
            plain.execute(statement)
        plain.execute("INSERT INTO colors (id, hex, r, g, b, name, family) VALUES (1, '#3366cc', 51, 102, 204, 'Blue', 'blue')")
        plain.execute("INSERT INTO links (id, url) VALUES (1, 'https://example.com/a')")
        plain.execute("INSERT INTO qr_codes (link_id, color_id, path, path_key, format, ec_level, version, origin, created) "
                      "VALUES (1, 1, 'C:\\a.png', 'c:\\a.png', 'png', 'M', 3, 'made', '2026-10-29T10:00:00Z')")
        if version >= 2:
            for statement in registry.TO_VERSION_2:
                plain.execute(statement)
            plain.execute("INSERT INTO links (id, url) VALUES (2, 'HTTPS://GO.EXAMPLE.COM/" + self.code + "')")
            plain.execute("INSERT INTO qr_codes (link_id, color_id, path, path_key, format, ec_level, version, origin, "
                          "created) VALUES (2, 1, 'C:\\b.png', 'c:\\b.png', 'png', 'M', 2, 'made', '2026-10-29T10:00:00Z')")
            plain.execute("INSERT INTO short_links (code, link_id, color_id, target, created, updated) "
                          "VALUES (?, 2, 1, ?, '2026-10-29T10:00:00Z', '2026-10-29T10:00:00Z')", (self.code, TARGET))
        plain.execute("PRAGMA application_id=" + str(registry.APPLICATION_ID))
        plain.execute("PRAGMA user_version=" + str(version))
        plain.commit()
        plain.close()

    def header_version(self):
        """The registry file's user_version, read with plain sqlite3 so nothing is moved up."""
        plain = sqlite3.connect(self.path)
        version = plain.execute("PRAGMA user_version").fetchone()[0]
        plain.close()
        return version

    def test_a_version_1_registry_is_read_as_it_is_and_moved_up_when_written(self):
        """A version 1 registry reads read-only with empty short-link answers, and a writable open moves it to the current version.

        The qr_lookup view counted at the end is created by the upgrade's version 2 statements."""
        self.older_registry(1)
        reader = self.open(True)
        self.assertEqual(registry.all_rows(reader)[0]["short_code"], "")
        self.assertIsNone(registry.all_rows(reader)[0]["payload_hash"])
        self.assertEqual(registry.short_links(reader), [])
        self.assertEqual(registry.short_links_on(reader, "2026-10-29"), [])
        self.assertEqual(registry.scan_totals(reader, "2026-10-29"), {})
        registry.close(reader)
        self.assertEqual(self.header_version(), 1)  # reading changed nothing
        writer = self.open(False)
        self.assertEqual(writer.execute("PRAGMA user_version").fetchone()[0], registry.SCHEMA_VERSION)
        self.assertEqual(writer.execute("PRAGMA application_id").fetchone()[0], registry.APPLICATION_ID)
        self.assertEqual(registry.short_links(writer), [])
        self.assertEqual(len(registry.all_rows(writer)), 1)
        self.assertEqual(writer.execute("SELECT count(*) FROM qr_lookup").fetchone()[0], 1)

    def test_a_version_2_registry_keeps_a_copy_and_everything_it_held(self):
        """A version 2 registry reads as it is; a writable open first keeps palette-v2.db, then moves it to version 3.

        The kept copy is still version 2 with both codes and no scans table."""
        self.older_registry(2)
        reader = self.open(True)
        rows = registry.all_rows(reader)
        self.assertEqual(rows[0]["target"], TARGET)
        self.assertIsNone(rows[0]["payload_hash"])
        self.assertEqual(registry.link_changes(reader, self.code), [])
        self.assertEqual(registry.scheduled(reader, ""), [])
        self.assertEqual(registry.color_scans(reader), {})
        registry.close(reader)
        self.assertFalse(os.path.exists(self.older_copy(2)))  # reading keeps no copy
        writer = self.open(False)
        self.assertEqual(writer.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(registry.short_links(writer)[0]["target"], TARGET)
        self.assertEqual(len(registry.all_rows(writer)), 2)
        registry.close(writer)
        copy = sqlite3.connect(self.older_copy(2))
        self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(copy.execute("SELECT count(*) FROM qr_codes").fetchone()[0], 2)
        self.assertEqual(copy.execute("SELECT count(*) FROM sqlite_master WHERE name = 'scans'").fetchone()[0], 0)
        copy.close()

    def older_copy(self, version):
        """Where registry.keep_older_copy puts the copy of a version `version` registry: palette-vN.db."""
        stem, extension = os.path.splitext(self.path)
        return stem + "-v" + str(version) + extension

    def test_a_registry_is_not_moved_up_without_its_copy(self):
        """When the copy cannot be kept, the writable open fails and the registry stays at version 2.

        registry.backup is swapped for a stand-in that fails as a full disk would; keep_older_copy
        looks it up in the module at call time, so the stand-in is what it calls."""
        self.older_registry(2)
        before = shutil.copyfile(self.path, self.path + ".before")
        saved = registry.backup
        registry.backup = lambda path, target: registry.fail("the disk is full")
        try:
            refused = registry.connect(self.path, False)
        finally:
            registry.backup = saved
        self.assertFalse(refused["ok"])
        self.assertIn("could not be kept", refused["error"])
        self.assertEqual(self.header_version(), 2)
        self.assertTrue(os.path.isfile(before))

    def test_what_other_programs_read_is_unchanged(self):
        """Data Bridge reads these from version 2 on, with its own allow-list: they stay.

        The query is the one such a program runs; 0x51525041 is "QRPA" written out, so a change to
        APPLICATION_ID fails here too."""
        writer = self.open(False)
        registry.save_qr(writer, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        row = writer.execute("SELECT q.id, l.url, c.hex, q.path, q.format, q.ec_level, q.version, q.origin, q.created, "
                             "s.target FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id "
                             "LEFT JOIN short_links s ON s.link_id = l.id ORDER BY q.id").fetchone()
        self.assertEqual((row[2], row[9]), ("#3366cc", TARGET))
        self.assertEqual(writer.execute("PRAGMA application_id").fetchone()[0], 0x51525041)
        for version in registry.READABLE_VERSIONS:
            self.assertIn(version, (1, 2, 3))

    def test_other_versions_are_refused(self):
        """A newer version (4) is refused by both kinds of open."""
        writer = self.open(False)
        writer.execute("PRAGMA user_version=4")
        registry.close(writer)
        self.assertIn("another version", registry.connect(self.path, True)["error"])
        self.assertIn("another version", registry.connect(self.path, False)["error"])


class HistoryTests(RegistryCase):
    """A short link's history (short_link_changes) and its scheduled changes."""

    def setUp(self):
        """One short link to TARGET, on a connection kept open for the test."""
        RegistryCase.setUp(self)
        self.code = code_of("1234567")
        self.connection = self.open(False)
        registry.save_qr(self.connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))

    def target(self):
        """Where the short link sends people now, as the registry holds it."""
        return registry.short_links(self.connection)[0]["target"]

    def test_a_change_keeps_where_it_used_to_go(self):
        """Each retarget is written in the history, newest first, with a UTC time ending in "Z"."""
        self.assertEqual(registry.link_changes(self.connection, self.code), [])
        self.assertTrue(registry.retarget(self.connection, self.code, "https://example.com/b")["value"])
        self.assertTrue(registry.retarget(self.connection, self.code, "https://example.com/c")["value"])
        changes = registry.link_changes(self.connection, self.code)
        self.assertEqual([(change["old_target"], change["new_target"]) for change in changes],
                         [("https://example.com/b", "https://example.com/c"), (TARGET, "https://example.com/b")])
        self.assertTrue(changes[0]["changed"].endswith("Z"))

    def test_going_where_it_already_goes_is_no_change(self):
        """Retargeting to the current destination succeeds but writes no history."""
        self.assertTrue(registry.retarget(self.connection, self.code, TARGET)["value"])
        self.assertEqual(registry.link_changes(self.connection, self.code), [])

    def test_undo_goes_back_and_is_written_too(self):
        """Undo refuses with no history, then goes back one change and writes the undo as a change of its own."""
        self.assertIn("not been changed", registry.undo_last_change(self.connection, self.code)["error"])
        registry.retarget(self.connection, self.code, "https://example.com/b")
        undone = registry.undo_last_change(self.connection, self.code)
        self.assertEqual(undone["value"], TARGET)
        self.assertEqual(self.target(), TARGET)
        changes = registry.link_changes(self.connection, self.code)
        self.assertEqual(len(changes), 2)
        self.assertEqual((changes[0]["old_target"], changes[0]["new_target"]), ("https://example.com/b", TARGET))

    def test_a_schedule_is_applied_by_its_day(self):
        """A scheduled change waits for its day, is applied once, and leaves the later one waiting.

        Month 13 and "soon" are not days; an unknown ID is refused. Applying on 2026-11-30 does
        nothing, on 2026-12-01 applies the winter change, and on 2026-12-02 finds nothing new."""
        self.assertFalse(registry.schedule_change(self.connection, self.code, "https://example.com/b", "2026-13-01")["ok"])
        self.assertFalse(registry.schedule_change(self.connection, self.code, "https://example.com/b", "soon")["ok"])
        self.assertIn("no short link", registry.schedule_change(self.connection, code_of("7654321"),
                                                                "https://example.com/b", "2026-12-01")["error"])
        registry.schedule_change(self.connection, self.code, "https://example.com/winter", "2026-12-01")
        registry.schedule_change(self.connection, self.code, "https://example.com/spring", "2027-03-01")
        self.assertEqual(len(registry.scheduled(self.connection, self.code)), 2)
        self.assertEqual(registry.due_changes(self.connection, "2026-11-30"), [])
        self.assertEqual(registry.apply_due(self.connection, "2026-11-30")["value"], 0)
        self.assertEqual(self.target(), TARGET)
        self.assertEqual(len(registry.due_changes(self.connection, "2026-12-01")), 1)
        self.assertEqual(registry.apply_due(self.connection, "2026-12-01")["value"], 1)
        self.assertEqual(self.target(), "https://example.com/winter")
        self.assertEqual(registry.link_changes(self.connection, self.code)[0]["new_target"], "https://example.com/winter")
        self.assertEqual(registry.apply_due(self.connection, "2026-12-02")["value"], 0)  # never twice
        self.assertEqual([change["target"] for change in registry.scheduled(self.connection, self.code)],
                         ["https://example.com/spring"])

    def test_due_changes_are_applied_in_order(self):
        """Two due changes are applied soonest day first, whatever order they were scheduled in, so the later one stands."""
        registry.schedule_change(self.connection, self.code, "https://example.com/later", "2026-12-05")
        registry.schedule_change(self.connection, self.code, "https://example.com/sooner", "2026-12-01")
        self.assertEqual(registry.apply_due(self.connection, "2026-12-31")["value"], 2)
        self.assertEqual(self.target(), "https://example.com/later")

    def test_a_schedule_can_be_taken_back(self):
        """A scheduled change can be cancelled once; a second cancel finds nothing."""
        number = registry.schedule_change(self.connection, self.code, "https://example.com/b", "2026-12-01")["value"]
        self.assertTrue(registry.cancel_scheduled(self.connection, number)["value"])
        self.assertFalse(registry.cancel_scheduled(self.connection, number)["value"])
        self.assertEqual(registry.scheduled(self.connection, ""), [])

    def test_the_destination_in_force_on_a_day(self):
        """short_links_on gives each day's destination from the schedules, read on the read rail, without applying them.

        The writer is closed first and opened again at the end, so tearDown has a connection to close."""
        registry.schedule_change(self.connection, self.code, "https://example.com/winter", "2026-12-01")
        registry.schedule_change(self.connection, self.code, "https://example.com/spring", "2027-03-01")
        registry.close(self.connection)
        reader = self.open(True)  # the read rail may read them
        self.assertEqual(registry.short_links_on(reader, "2026-11-30")[0]["target"], TARGET)
        self.assertEqual(registry.short_links_on(reader, "2026-12-01")[0]["target"], "https://example.com/winter")
        self.assertEqual(registry.short_links_on(reader, "2027-06-01")[0]["target"], "https://example.com/spring")
        self.assertEqual(registry.short_links(reader)[0]["target"], TARGET)  # only an applied change is in the registry
        registry.close(reader)
        self.connection = self.open(False)


class ScanTests(RegistryCase):
    """Scan counts per short link and day: importing, totals, recent days, and per color."""

    def setUp(self):
        """Two short links in the same color: self.code to TARGET and self.other to another page."""
        RegistryCase.setUp(self)
        self.code = code_of("1234567")
        self.other = code_of("7654321")
        self.connection = self.open(False)
        registry.save_qr(self.connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        registry.save_qr(self.connection, short_entry(self.folder, "b.png", self.other, "#3366cc", "https://example.com/b"))

    def test_importing_twice_changes_nothing(self):
        """The same counts from the same source, imported twice, are counted once: one row per ID, day and source."""
        counts = {(self.code, "2026-10-01"): 5, (self.code, "2026-10-02"): 7, (self.other, "2026-10-02"): 1}
        first = registry.import_scans(self.connection, counts, "analytics")
        self.assertEqual(first["value"], {"days": 3, "unknown": []})
        registry.import_scans(self.connection, counts, "analytics")
        totals = registry.scan_totals(self.connection, "2026-10-03")
        self.assertEqual(totals[self.code], {"total": 12, "recent": 12})
        self.assertEqual(totals[self.other], {"total": 1, "recent": 1})

    def test_a_newer_report_corrects_its_days_and_sources_add_up(self):
        """A newer count from the same source replaces the old one (8, not 13); another source adds to it (10)."""
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 5}, "analytics")
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 8}, "analytics")
        self.assertEqual(registry.scan_totals(self.connection, "2026-10-01")[self.code]["total"], 8)
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 2}, "server log from 2026-10-01T06:25:03")
        self.assertEqual(registry.scan_totals(self.connection, "2026-10-01")[self.code]["total"], 10)

    def test_unknown_ids_are_named_and_left_out(self):
        """An ID that is not a short link here is named in "unknown" and not saved; the known one is."""
        unknown = code_of("1111111")
        saved = registry.import_scans(self.connection, {(unknown, "2026-10-01"): 5, (self.code, "2026-10-01"): 1}, "x")
        self.assertEqual(saved["value"], {"days": 1, "unknown": [unknown]})
        self.assertNotIn(unknown, registry.scan_totals(self.connection, "2026-10-01"))

    def test_recent_means_the_last_thirty_days(self):
        """"recent" is the 30 days ending today, today included; the total counts every day, future ones too.

        On 2026-10-31 the window is 2026-10-02 to 2026-10-31, so 10-01 (30 days back) and 11-01
        (tomorrow) count only in the total."""
        registry.import_scans(self.connection, {(self.code, "2026-10-31"): 1, (self.code, "2026-10-02"): 2,
                                                (self.code, "2026-10-01"): 4, (self.code, "2026-11-01"): 8}, "x")
        totals = registry.scan_totals(self.connection, "2026-10-31")[self.code]
        self.assertEqual(totals, {"total": 15, "recent": 3})  # 1 and 2: not 30 days back, not tomorrow

    def test_scans_per_color_on_the_read_rail(self):
        """color_scans adds up the scans of every short link in a color and counts the links, on the read rail.

        The writer is closed first and opened again at the end, so tearDown has a connection to close."""
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 5, (self.other, "2026-10-01"): 2}, "x")
        registry.close(self.connection)
        reader = self.open(True)
        self.assertEqual(registry.color_scans(reader), {"#3366cc": {"scans": 7, "links": 2}})
        self.assertEqual(registry.scan_totals(reader, "2026-10-01")[self.other]["total"], 2)
        registry.close(reader)
        self.connection = self.open(False)

    def test_a_count_cannot_be_negative(self):
        """A negative count breaks the scans table's CHECK (count >= 0), so the import fails as a whole."""
        saved = registry.import_scans(self.connection, {(self.code, "2026-10-01"): -1}, "x")
        self.assertFalse(saved["ok"])


class MaskedTests(RegistryCase):
    """Codes whose stored text is masked (a Wi-Fi password) keep the hash of their real payload."""

    def test_a_masked_code_keeps_its_hash(self):
        """payload_hash is kept for the masked code, None for a plain one, and readable on the read rail.

        "ab" * 32 stands in for a SHA-256 in hex (64 characters); rows come newest first, so the
        masked code saved first is rows[1]."""
        connection = self.open(False)
        saved = entry(self.folder, "a.png", "WIFI:T:WPA;S:Cafe;P:********;;", "#3366cc")
        saved["payload_hash"] = "ab" * 32
        registry.save_qr(connection, saved)
        registry.save_qr(connection, entry(self.folder, "b.png", "https://example.com/b", "#3366cc"))
        rows = registry.all_rows(connection)
        self.assertEqual(rows[1]["payload_hash"], "ab" * 32)
        self.assertIsNone(rows[0]["payload_hash"])
        registry.close(connection)
        reader = self.open(True)
        self.assertEqual(registry.all_rows(reader)[1]["payload_hash"], "ab" * 32)
        registry.close(reader)


class BackupTests(RegistryCase):
    """registry.backup: a checked copy made through SQLite's online backup API."""

    def test_a_backup_is_a_checked_copy(self):
        """The copy holds the same records and votes, leaves no .part file, and is never written over an existing file.

        A backup of a missing registry fails with "no registry"; the backups/ folder is made on the way."""
        connection = self.open(False)
        registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        registry.vote(connection, "#3366cc", 1)
        target = os.path.join(self.folder, "backups", "copy.db")
        made = registry.backup(self.path, target)
        self.assertTrue(made["ok"], made["error"])
        copy = self.open_path(target)
        self.assertEqual(registry.counts(copy), registry.counts(connection))
        self.assertEqual(registry.vote_entries(copy)[0]["color"], "#3366cc")
        self.assertFalse(os.path.exists(target + ".part"))
        self.assertIn("already exists", registry.backup(self.path, target)["error"])
        self.assertIn("no registry", registry.backup(os.path.join(self.folder, "none.db"), target + "2")["error"])

    def open_path(self, path):
        """Open another registry file read-only, closed again in tearDown -> the connection."""
        opened = registry.connect(path, True)
        self.assertTrue(opened["ok"], opened["error"])
        self.connections.append(opened["value"])
        return opened["value"]


class SavingTests(RegistryCase):
    """save_qr's checks and its one-record-per-file rule, colors outside the cube, and forgetting."""

    def test_saving_the_same_file_again_replaces_its_record(self):
        """A file saved again keeps its record id and takes the new link and color; the old link, now unused, goes."""
        connection = self.open(False)
        first = registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/a", "#3366cc"))
        second = registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/b", "#006633"))
        self.assertEqual(first["value"], second["value"])
        rows = registry.all_rows(connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["link"], rows[0]["hex"]), ("https://example.com/b", "#006633"))
        self.assertEqual(registry.counts(connection)["links"], 1)  # the old link went with it

    def test_paths_differing_only_in_case_are_one_file_on_windows(self):
        """On Windows, Code.PNG and code.png are one file, so they are one record (path_key is case-folded there)."""
        if os.name != "nt":
            self.skipTest("case-insensitive paths are a Windows rule")
        connection = self.open(False)
        registry.save_qr(connection, entry(self.folder, "Code.PNG", "https://example.com/a", "#3366cc"))
        registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/a", "#3366cc"))
        self.assertEqual(registry.counts(connection)["records"], 1)

    def test_bad_entries_are_refused(self):
        """Each bad field alone is refused: a color name, GIF, level Z, version 41, an unknown origin, a relative path."""
        connection = self.open(False)
        good = entry(self.folder, "a.png", "https://example.com/a", "#3366cc")
        changes = (("color", "blue"), ("format", "gif"), ("ec_level", "Z"), ("version", 41), ("origin", "found"),
                   ("path", "relative.png"))
        for change in changes:
            bad = dict(good)
            bad[change[0]] = change[1]
            self.assertFalse(registry.save_qr(connection, bad)["ok"], change)
        self.assertEqual(registry.counts(connection)["records"], 0)

    def test_off_cube_colors_are_added_with_their_names(self):
        """A color outside the 216 is added to colors with no cube index but with its family (#3467cb is blue)."""
        connection = self.open(False)
        registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3467cb"))
        row = registry.all_rows(connection)[0]
        self.assertEqual((row["hex"], row["cube_index"], row["family"]), ("#3467cb", None, "blue"))

    def test_forgetting_keeps_the_file(self):
        """forget_qr removes the record once (a second time answers False) and its unused link, but never the picture."""
        connection = self.open(False)
        path = os.path.join(self.folder, "a.png")
        handle = open(path, "wb")
        handle.write(b"picture")
        handle.close()
        number = registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))["value"]
        self.assertTrue(registry.forget_qr(connection, number)["value"])
        self.assertFalse(registry.forget_qr(connection, number)["value"])
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(registry.counts(connection), {"records": 0, "links": 0, "colors_used": 0})

    def test_file_state(self):
        """file_state is True or False for local files, and None for network and device paths when local_only.

        None keeps a query from making this computer reach out to a share. The UNC and \\\\.\\pipe
        cases are Windows paths, so they are checked on Windows only."""
        here = os.path.join(self.folder, "here.png")
        handle = open(here, "wb")
        handle.close()
        self.assertTrue(registry.file_state(here, True))
        self.assertFalse(registry.file_state(os.path.join(self.folder, "gone.png"), True))
        if os.name == "nt":
            self.assertIsNone(registry.file_state("\\\\server\\share\\code.png", True))
            self.assertIsNone(registry.file_state("\\\\.\\pipe\\name", True))
            self.assertFalse(registry.is_local_drive_path("relative\\code.png"))


class VoteTests(RegistryCase):
    """Votes: one per color, imported from Color Voats, and the log rankers read."""

    def test_one_vote_per_color_taken_back_by_pressing_again(self):
        """The same vote again takes it back (0); the other vote replaces it; only 1 and -1 on a #rrggbb color are allowed."""
        connection = self.open(False)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 1)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 0)
        self.assertEqual(registry.vote(connection, "#3366cc", -1)["value"], -1)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 1)
        self.assertEqual(registry.vote_map(connection), {"#3366cc": 1})
        self.assertFalse(registry.vote(connection, "#3366cc", 2)["ok"])
        self.assertFalse(registry.vote(connection, "blue", 1)["ok"])

    def test_the_log_is_oldest_first(self):
        """vote_log orders by the time voted, not by insertion: the 09:00 vote written second comes first.

        The rows are inserted by hand to set their times."""
        connection = self.open(False)
        connection.execute("BEGIN")
        for color, voat, voted in (("#000033", 1, "2026-10-29T10:00:00Z"), ("#cc0000", -1, "2026-10-29T09:00:00Z")):
            number = registry.color_id(connection, color)
            connection.execute("INSERT INTO votes (color_id, voat, voted) VALUES (?, ?, ?)", (number, voat, voted))
        connection.execute("COMMIT")
        self.assertEqual(registry.vote_log(connection), [{"color": "#cc0000", "voat": -1}, {"color": "#000033", "voat": 1}])

    def test_importing_twice_changes_nothing_and_newer_wins(self):
        """Color Voats' votes import once; an older vote is ignored and a newer one replaces.

        Of the five entries only two are usable: "nonsense" is no color, 5 is no vote, and True is no
        time (a bool is refused although Python counts it as a number). #3366CC is read as #3366cc.
        1793188800 is late 2026 and 1893456000 is 2030-01-01, so the last import is the newest."""
        connection = self.open(False)
        votes = {"#3366CC": {"voat": 1, "when": 1793188800.0}, "#cc0000": {"voat": -1, "when": 1793188900.0},
                 "nonsense": {"voat": 1, "when": 1.0}, "#00ff00": {"voat": 5, "when": 1.0},
                 "#0000ff": {"voat": 1, "when": True}}
        self.assertEqual(registry.import_votes(connection, votes)["value"], 2)
        self.assertEqual(registry.import_votes(connection, votes)["value"], 0)
        self.assertEqual(registry.import_votes(connection, {"#3366cc": {"voat": -1, "when": 1.0}})["value"], 0)
        self.assertEqual(registry.import_votes(connection, {"#3366cc": {"voat": -1, "when": 1893456000.0}})["value"], 1)
        self.assertEqual(registry.vote_map(connection), {"#3366cc": -1, "#cc0000": -1})


class FindTests(RegistryCase):
    """find_rows' filters over four saved codes, and the helpers behind them."""

    def setUp(self):
        """Save four codes, oldest first; école.png sits in a Marketing subfolder with a non-ASCII link.

        #3467cb is off the cube but near #3366cc and in the blue family, which the color tests use."""
        RegistryCase.setUp(self)
        self.connection = self.open(False)
        codes = (("shop-blue.png", "https://shop.example.com/", "#3366cc"),
                 ("menu-green.png", "https://example.com/menu", "#006633"),
                 (os.path.join("Marketing", "école.png"), "https://example.com/École", "#3467cb"),
                 ("shop-red.png", "https://shop.example.com/sale", "#cc0000"))
        os.makedirs(os.path.join(self.folder, "Marketing"))
        for code in codes:
            registry.save_qr(self.connection, entry(self.folder, code[0], code[1], code[2]))
        self.rows = registry.all_rows(self.connection)

    def find(self, changes, limit=20):
        """find_rows with `changes` set over empty filters -> the file names found, in order."""
        filters = registry.empty_filters()
        for key in changes:
            filters[key] = changes[key]
        found = registry.find_rows(self.rows, filters, limit)
        names = []
        for row in found:
            names.append(os.path.basename(row["path"]))
        return names

    def test_no_filter_is_newest_first(self):
        """With no filter every row comes back newest first, cut to the limit."""
        self.assertEqual(self.find({}), ["shop-red.png", "école.png", "menu-green.png", "shop-blue.png"])
        self.assertEqual(self.find({}, 2), ["shop-red.png", "école.png"])

    def test_by_color(self):
        """A color matches exactly, or with "near" also #3467cb; a family matches by name, an unused one finds nothing."""
        self.assertEqual(self.find({"color": "#3366cc"}), ["shop-blue.png"])
        self.assertEqual(self.find({"color": "#3366cc", "near": True}), ["école.png", "shop-blue.png"])
        self.assertEqual(self.find({"family": "blue"}), ["école.png", "shop-blue.png"])
        self.assertEqual(self.find({"family": "pink"}), [])

    def test_by_link(self):
        """"link" matches any case and non-ASCII letters; "link_exact" matches only as written; "%" is no wildcard.

        Finding runs in Python, not through SQL LIKE, so "%" is a plain character that no link holds."""
        self.assertEqual(self.find({"link": "SHOP"}), ["shop-red.png", "shop-blue.png"])
        self.assertEqual(self.find({"link": "école"}), ["école.png"])
        self.assertEqual(self.find({"link_exact": "https://example.com/menu"}), ["menu-green.png"])
        self.assertEqual(self.find({"link_exact": "https://example.com/MENU"}), [])
        self.assertEqual(self.find({"link": "%"}), [])

    def test_by_path_and_together(self):
        """A path matches by a folder's word or by the whole path, and filters given together must all match."""
        self.assertEqual(self.find({"path": "marketing"}), ["école.png"])
        self.assertEqual(self.find({"path": os.path.join(self.folder, "menu-green.png")}), ["menu-green.png"])
        self.assertEqual(self.find({"link": "shop", "family": "blue"}), ["shop-blue.png"])
        self.assertEqual(self.find({"link": "shop", "family": "green"}), [])

    def test_words_match_without_punctuation(self):
        """text_contains matches each typed word anywhere, ignoring punctuation and case, and reads %-escapes.

        Every word must be there ("shop menu" fails on the sale link); a needle with no words, such
        as "%" or "--", matches only as typed."""
        self.assertTrue(registry.text_contains("https://shop.example.com/store-hours", "store hours"))
        self.assertTrue(registry.text_contains("https://shop.example.com/store-hours", "Store-Hours"))
        self.assertTrue(registry.text_contains("https://example.com/École", "école"))
        self.assertTrue(registry.text_contains("https://shop.example.com/sale", "shop sale"))
        self.assertFalse(registry.text_contains("https://shop.example.com/sale", "shop menu"))
        self.assertFalse(registry.text_contains("https://example.com/careers", "careers page"))
        self.assertFalse(registry.text_contains("https://example.com/careers", "%"))
        self.assertFalse(registry.text_contains("https://example.com/careers", "--"))
        self.assertTrue(registry.text_contains("https://shop.example.com/p/blue%20mug", "blue mug"))
        self.assertTrue(registry.text_contains("https://shop.example.com/p/blue%20mug", "BLUE%20MUG"))
        self.assertFalse(registry.text_contains("https://shop.example.com/p/blue%20mug", "red mug"))

    def test_limits(self):
        """clamp_limit holds a limit to 1..MAX_LIMIT, and anything that is not a whole number (text, a bool) gets the default."""
        self.assertEqual(registry.clamp_limit(0), 1)
        self.assertEqual(registry.clamp_limit(999), registry.MAX_LIMIT)
        self.assertEqual(registry.clamp_limit("5"), registry.DEFAULT_LIMIT)
        self.assertEqual(registry.clamp_limit(True), registry.DEFAULT_LIMIT)

    def test_colors_in_use(self):
        """colors_in_use lists the four colors, each used once."""
        used = registry.colors_in_use(self.connection)
        self.assertEqual(len(used), 4)
        self.assertEqual(used[0]["uses"], 1)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=e37faabf378ce5492b91fa4139de6e546506e93d2b5c9fbf5586f432b285f737 ====
