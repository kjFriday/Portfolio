# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_registry.py
# About: Tests for the registry: schema, opening rules, saving, votes and finding.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for the registry: schema, opening rules, saving, votes and finding."""

import os
import shutil
import sqlite3
import tempfile
import unittest

import registry
import shortlinks
import swatch


def entry(folder, name, link, color):
    return {"link": link, "color": color, "path": os.path.join(folder, name), "format": "png", "ec_level": "M",
            "version": 3, "origin": "made"}


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_registry_")
        self.path = os.path.join(self.folder, "palette.db")
        self.connections = []

    def tearDown(self):
        for connection in self.connections:
            registry.close(connection)
        shutil.rmtree(self.folder, ignore_errors=True)

    def open(self, read_only):
        opened = registry.connect(self.path, read_only)
        self.assertTrue(opened["ok"], opened["error"])
        self.connections.append(opened["value"])
        return opened["value"]


class OpeningTests(RegistryCase):
    def test_a_new_registry_has_the_cube_and_its_marks(self):
        connection = self.open(False)
        self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], registry.APPLICATION_ID)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], registry.SCHEMA_VERSION)
        self.assertEqual(connection.execute("SELECT count(*) FROM colors").fetchone()[0], 216)
        row = connection.execute("SELECT name, family, cube_index FROM colors WHERE hex = '#006666'").fetchone()
        self.assertEqual((row[0], row[1], row[2]), ("Muted teal", "teal", swatch.cube_index("#006666")))
        self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_an_older_wal_registry_is_switched_back(self):
        connection = self.open(False)
        connection.execute("PRAGMA journal_mode=WAL")
        registry.close(connection)
        again = self.open(False)
        self.assertEqual(again.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_reopening_keeps_what_was_saved(self):
        connection = self.open(False)
        self.assertTrue(registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))["ok"])
        registry.close(connection)
        again = self.open(False)
        self.assertEqual(registry.counts(again)["records"], 1)

    def test_other_databases_are_refused(self):
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
        connection = self.open(False)
        connection.execute("PRAGMA user_version=7")
        registry.close(connection)
        self.assertIn("another version", registry.connect(self.path, False)["error"])

    def test_read_only_never_creates(self):
        result = registry.connect(self.path, True)
        self.assertFalse(result["ok"])
        self.assertIn("no registry yet", result["error"])
        self.assertFalse(os.path.exists(self.path))

    def test_read_only_refuses_writes(self):
        registry.close(self.open(False))
        reader = self.open(True)
        result = registry.save_qr(reader, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        self.assertFalse(result["ok"])
        with self.assertRaises(sqlite3.Error):
            reader.execute("INSERT INTO links (url) VALUES ('https://example.com/x')")

    def test_read_only_opens_after_every_writer_closed(self):
        writer = self.open(False)
        registry.save_qr(writer, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        registry.close(writer)
        reader = self.open(True)
        self.assertEqual(len(registry.all_rows(reader)), 1)

    def test_a_reader_works_while_a_write_is_open(self):
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
        connection = self.open(False)
        tables = []
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
            tables.append(row[0])
        self.assertEqual(tables, ["colors", "links", "qr_codes", "scans", "scheduled_changes", "short_link_changes",
                                  "short_links", "votes"])


class ReadRailTests(RegistryCase):
    def setUp(self):
        RegistryCase.setUp(self)
        self.saved = registry.STATEMENT_SECONDS
        writer = self.open(False)
        registry.save_qr(writer, entry(self.folder, "a.png", "https://example.com/a", "#3366cc"))
        registry.vote(writer, "#3366cc", 1)
        registry.close(writer)

    def tearDown(self):
        registry.STATEMENT_SECONDS = self.saved
        RegistryCase.tearDown(self)

    def test_everything_an_answer_needs_can_be_read(self):
        reader = self.open(True)
        self.assertEqual(len(registry.all_rows(reader)), 1)
        self.assertEqual(registry.counts(reader)["records"], 1)
        self.assertEqual(registry.vote_log(reader), [{"color": "#3366cc", "voat": 1}])
        self.assertEqual(registry.vote_map(reader), {"#3366cc": 1})
        self.assertEqual(registry.colors_in_use(reader)[0]["hex"], "#3366cc")

    def test_everything_else_is_denied(self):
        reader = self.open(True)
        for statement in ("SELECT r FROM colors", "SELECT lower(hex) FROM colors", "SELECT name FROM sqlite_master",
                          "PRAGMA journal_mode", "PRAGMA writable_schema=ON",
                          "INSERT INTO links (url) VALUES ('https://example.com/x')",
                          "ATTACH DATABASE ':memory:' AS other", "CREATE TEMP TABLE scratch (x)",
                          "SELECT load_extension('anything')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=statement):
                reader.execute(statement).fetchall()

    def test_the_connection_is_hardened(self):
        reader = self.open(True)
        if hasattr(reader, "getconfig") and hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
            self.assertTrue(reader.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE))
            self.assertFalse(reader.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA))
            self.assertFalse(reader.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER))
        if hasattr(reader, "getlimit"):
            self.assertEqual(reader.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED), 0)
            self.assertEqual(reader.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH), 10000)

    def test_a_long_read_is_stopped(self):
        registry.STATEMENT_SECONDS = 0.05
        reader = self.open(True)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            reader.execute("SELECT count(*) FROM colors a, colors b, colors c").fetchone()
        self.assertIn("interrupted", str(caught.exception))

    def test_a_damaged_registry_is_not_served(self):
        handle = open(self.path, "r+b")
        handle.seek(2 * 4096)
        handle.write(b"\xff" * 4096)
        handle.close()
        self.assertFalse(registry.connect(self.path, True)["ok"])


TARGET = "https://shop.example.com/hours"


def code_of(body):
    return body + shortlinks.check_digit(body)


def short_entry(folder, name, code, color, target):
    made = entry(folder, name, "HTTPS://GO.EXAMPLE.COM/" + code, color)
    made["short"] = {"code": code, "target": target}
    return made


class ShortLinkTests(RegistryCase):
    def setUp(self):
        RegistryCase.setUp(self)
        self.code = code_of("1234567")

    def test_short_links_are_saved_reused_and_found_by_destination(self):
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
        connection = self.open(False)
        registry.save_qr(connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        moved = entry(self.folder, "b.png", "HTTPS://OTHER.EXAMPLE.COM/" + self.code, "#3366cc")
        moved["short"] = {"code": self.code, "target": TARGET}
        self.assertIn("already used", registry.save_qr(connection, moved)["error"])
        self.assertEqual(registry.counts(connection)["records"], 1)
        bad = short_entry(self.folder, "c.png", "12AB", "#3366cc", TARGET)
        self.assertFalse(registry.save_qr(connection, bad)["ok"])

    def test_forgetting_the_pictures_keeps_the_printed_link_and_it_can_be_retargeted(self):
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
        writer = self.open(False)
        registry.save_qr(writer, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        registry.close(writer)
        reader = self.open(True)
        self.assertEqual(registry.short_links(reader)[0]["target"], TARGET)
        self.assertEqual(registry.all_rows(reader)[0]["target"], TARGET)

    def older_registry(self, version):
        """A registry as an older program left it, built from that version's own statements."""
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
        plain = sqlite3.connect(self.path)
        version = plain.execute("PRAGMA user_version").fetchone()[0]
        plain.close()
        return version

    def test_a_version_1_registry_is_read_as_it_is_and_moved_up_when_written(self):
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
        stem, extension = os.path.splitext(self.path)
        return stem + "-v" + str(version) + extension

    def test_a_registry_is_not_moved_up_without_its_copy(self):
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
        """Data Bridge reads these from version 2 on, with its own allow-list: they stay."""
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
        writer = self.open(False)
        writer.execute("PRAGMA user_version=4")
        registry.close(writer)
        self.assertIn("another version", registry.connect(self.path, True)["error"])
        self.assertIn("another version", registry.connect(self.path, False)["error"])


class HistoryTests(RegistryCase):
    def setUp(self):
        RegistryCase.setUp(self)
        self.code = code_of("1234567")
        self.connection = self.open(False)
        registry.save_qr(self.connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))

    def target(self):
        return registry.short_links(self.connection)[0]["target"]

    def test_a_change_keeps_where_it_used_to_go(self):
        self.assertEqual(registry.link_changes(self.connection, self.code), [])
        self.assertTrue(registry.retarget(self.connection, self.code, "https://example.com/b")["value"])
        self.assertTrue(registry.retarget(self.connection, self.code, "https://example.com/c")["value"])
        changes = registry.link_changes(self.connection, self.code)
        self.assertEqual([(change["old_target"], change["new_target"]) for change in changes],
                         [("https://example.com/b", "https://example.com/c"), (TARGET, "https://example.com/b")])
        self.assertTrue(changes[0]["changed"].endswith("Z"))

    def test_going_where_it_already_goes_is_no_change(self):
        self.assertTrue(registry.retarget(self.connection, self.code, TARGET)["value"])
        self.assertEqual(registry.link_changes(self.connection, self.code), [])

    def test_undo_goes_back_and_is_written_too(self):
        self.assertIn("not been changed", registry.undo_last_change(self.connection, self.code)["error"])
        registry.retarget(self.connection, self.code, "https://example.com/b")
        undone = registry.undo_last_change(self.connection, self.code)
        self.assertEqual(undone["value"], TARGET)
        self.assertEqual(self.target(), TARGET)
        changes = registry.link_changes(self.connection, self.code)
        self.assertEqual(len(changes), 2)
        self.assertEqual((changes[0]["old_target"], changes[0]["new_target"]), ("https://example.com/b", TARGET))

    def test_a_schedule_is_applied_by_its_day(self):
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
        registry.schedule_change(self.connection, self.code, "https://example.com/later", "2026-12-05")
        registry.schedule_change(self.connection, self.code, "https://example.com/sooner", "2026-12-01")
        self.assertEqual(registry.apply_due(self.connection, "2026-12-31")["value"], 2)
        self.assertEqual(self.target(), "https://example.com/later")

    def test_a_schedule_can_be_taken_back(self):
        number = registry.schedule_change(self.connection, self.code, "https://example.com/b", "2026-12-01")["value"]
        self.assertTrue(registry.cancel_scheduled(self.connection, number)["value"])
        self.assertFalse(registry.cancel_scheduled(self.connection, number)["value"])
        self.assertEqual(registry.scheduled(self.connection, ""), [])

    def test_the_destination_in_force_on_a_day(self):
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
    def setUp(self):
        RegistryCase.setUp(self)
        self.code = code_of("1234567")
        self.other = code_of("7654321")
        self.connection = self.open(False)
        registry.save_qr(self.connection, short_entry(self.folder, "a.png", self.code, "#3366cc", TARGET))
        registry.save_qr(self.connection, short_entry(self.folder, "b.png", self.other, "#3366cc", "https://example.com/b"))

    def test_importing_twice_changes_nothing(self):
        counts = {(self.code, "2026-10-01"): 5, (self.code, "2026-10-02"): 7, (self.other, "2026-10-02"): 1}
        first = registry.import_scans(self.connection, counts, "analytics")
        self.assertEqual(first["value"], {"days": 3, "unknown": []})
        registry.import_scans(self.connection, counts, "analytics")
        totals = registry.scan_totals(self.connection, "2026-10-03")
        self.assertEqual(totals[self.code], {"total": 12, "recent": 12})
        self.assertEqual(totals[self.other], {"total": 1, "recent": 1})

    def test_a_newer_report_corrects_its_days_and_sources_add_up(self):
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 5}, "analytics")
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 8}, "analytics")
        self.assertEqual(registry.scan_totals(self.connection, "2026-10-01")[self.code]["total"], 8)
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 2}, "server log from 2026-10-01T06:25:03")
        self.assertEqual(registry.scan_totals(self.connection, "2026-10-01")[self.code]["total"], 10)

    def test_unknown_ids_are_named_and_left_out(self):
        unknown = code_of("1111111")
        saved = registry.import_scans(self.connection, {(unknown, "2026-10-01"): 5, (self.code, "2026-10-01"): 1}, "x")
        self.assertEqual(saved["value"], {"days": 1, "unknown": [unknown]})
        self.assertNotIn(unknown, registry.scan_totals(self.connection, "2026-10-01"))

    def test_recent_means_the_last_thirty_days(self):
        registry.import_scans(self.connection, {(self.code, "2026-10-31"): 1, (self.code, "2026-10-02"): 2,
                                                (self.code, "2026-10-01"): 4, (self.code, "2026-11-01"): 8}, "x")
        totals = registry.scan_totals(self.connection, "2026-10-31")[self.code]
        self.assertEqual(totals, {"total": 15, "recent": 3})  # 1 and 2: not 30 days back, not tomorrow

    def test_scans_per_color_on_the_read_rail(self):
        registry.import_scans(self.connection, {(self.code, "2026-10-01"): 5, (self.other, "2026-10-01"): 2}, "x")
        registry.close(self.connection)
        reader = self.open(True)
        self.assertEqual(registry.color_scans(reader), {"#3366cc": {"scans": 7, "links": 2}})
        self.assertEqual(registry.scan_totals(reader, "2026-10-01")[self.other]["total"], 2)
        registry.close(reader)
        self.connection = self.open(False)

    def test_a_count_cannot_be_negative(self):
        saved = registry.import_scans(self.connection, {(self.code, "2026-10-01"): -1}, "x")
        self.assertFalse(saved["ok"])


class MaskedTests(RegistryCase):
    def test_a_masked_code_keeps_its_hash(self):
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
    def test_a_backup_is_a_checked_copy(self):
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
        opened = registry.connect(path, True)
        self.assertTrue(opened["ok"], opened["error"])
        self.connections.append(opened["value"])
        return opened["value"]


class SavingTests(RegistryCase):
    def test_saving_the_same_file_again_replaces_its_record(self):
        connection = self.open(False)
        first = registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/a", "#3366cc"))
        second = registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/b", "#006633"))
        self.assertEqual(first["value"], second["value"])
        rows = registry.all_rows(connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["link"], rows[0]["hex"]), ("https://example.com/b", "#006633"))
        self.assertEqual(registry.counts(connection)["links"], 1)  # the old link went with it

    def test_paths_differing_only_in_case_are_one_file_on_windows(self):
        if os.name != "nt":
            self.skipTest("case-insensitive paths are a Windows rule")
        connection = self.open(False)
        registry.save_qr(connection, entry(self.folder, "Code.PNG", "https://example.com/a", "#3366cc"))
        registry.save_qr(connection, entry(self.folder, "code.png", "https://example.com/a", "#3366cc"))
        self.assertEqual(registry.counts(connection)["records"], 1)

    def test_bad_entries_are_refused(self):
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
        connection = self.open(False)
        registry.save_qr(connection, entry(self.folder, "a.png", "https://example.com/a", "#3467cb"))
        row = registry.all_rows(connection)[0]
        self.assertEqual((row["hex"], row["cube_index"], row["family"]), ("#3467cb", None, "blue"))

    def test_forgetting_keeps_the_file(self):
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
    def test_one_vote_per_color_taken_back_by_pressing_again(self):
        connection = self.open(False)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 1)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 0)
        self.assertEqual(registry.vote(connection, "#3366cc", -1)["value"], -1)
        self.assertEqual(registry.vote(connection, "#3366cc", 1)["value"], 1)
        self.assertEqual(registry.vote_map(connection), {"#3366cc": 1})
        self.assertFalse(registry.vote(connection, "#3366cc", 2)["ok"])
        self.assertFalse(registry.vote(connection, "blue", 1)["ok"])

    def test_the_log_is_oldest_first(self):
        connection = self.open(False)
        connection.execute("BEGIN")
        for color, voat, voted in (("#000033", 1, "2026-10-29T10:00:00Z"), ("#cc0000", -1, "2026-10-29T09:00:00Z")):
            number = registry.color_id(connection, color)
            connection.execute("INSERT INTO votes (color_id, voat, voted) VALUES (?, ?, ?)", (number, voat, voted))
        connection.execute("COMMIT")
        self.assertEqual(registry.vote_log(connection), [{"color": "#cc0000", "voat": -1}, {"color": "#000033", "voat": 1}])

    def test_importing_twice_changes_nothing_and_newer_wins(self):
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
    def setUp(self):
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
        filters = registry.empty_filters()
        for key in changes:
            filters[key] = changes[key]
        found = registry.find_rows(self.rows, filters, limit)
        names = []
        for row in found:
            names.append(os.path.basename(row["path"]))
        return names

    def test_no_filter_is_newest_first(self):
        self.assertEqual(self.find({}), ["shop-red.png", "école.png", "menu-green.png", "shop-blue.png"])
        self.assertEqual(self.find({}, 2), ["shop-red.png", "école.png"])

    def test_by_color(self):
        self.assertEqual(self.find({"color": "#3366cc"}), ["shop-blue.png"])
        self.assertEqual(self.find({"color": "#3366cc", "near": True}), ["école.png", "shop-blue.png"])
        self.assertEqual(self.find({"family": "blue"}), ["école.png", "shop-blue.png"])
        self.assertEqual(self.find({"family": "pink"}), [])

    def test_by_link(self):
        self.assertEqual(self.find({"link": "SHOP"}), ["shop-red.png", "shop-blue.png"])
        self.assertEqual(self.find({"link": "école"}), ["école.png"])
        self.assertEqual(self.find({"link_exact": "https://example.com/menu"}), ["menu-green.png"])
        self.assertEqual(self.find({"link_exact": "https://example.com/MENU"}), [])
        self.assertEqual(self.find({"link": "%"}), [])

    def test_by_path_and_together(self):
        self.assertEqual(self.find({"path": "marketing"}), ["école.png"])
        self.assertEqual(self.find({"path": os.path.join(self.folder, "menu-green.png")}), ["menu-green.png"])
        self.assertEqual(self.find({"link": "shop", "family": "blue"}), ["shop-blue.png"])
        self.assertEqual(self.find({"link": "shop", "family": "green"}), [])

    def test_words_match_without_punctuation(self):
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
        self.assertEqual(registry.clamp_limit(0), 1)
        self.assertEqual(registry.clamp_limit(999), registry.MAX_LIMIT)
        self.assertEqual(registry.clamp_limit("5"), registry.DEFAULT_LIMIT)
        self.assertEqual(registry.clamp_limit(True), registry.DEFAULT_LIMIT)

    def test_colors_in_use(self):
        used = registry.colors_in_use(self.connection)
        self.assertEqual(len(used), 4)
        self.assertEqual(used[0]["uses"], 1)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a705b62c31a7bffe6d55fd10c226e97fde590b2b88a5dfb9de4a610f795057d2 ====
