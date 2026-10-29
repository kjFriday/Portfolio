# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_registry.py
# About: Tests for the registry: schema, opening rules, saving, votes and finding.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the registry: schema, opening rules, saving, votes and finding."""

import os
import shutil
import sqlite3
import tempfile
import unittest

import registry
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
        self.assertEqual(tables, ["colors", "links", "qr_codes", "votes"])


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

# ==== stamp v1 | author=kjFriday | hmac-sha256=4911ae3a3fa3eb60dfb96ef3289b0260f833b6ced36cf1c368527f8a0cbe26e4 ====
