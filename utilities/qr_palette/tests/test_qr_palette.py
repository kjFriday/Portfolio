# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_qr_palette.py
# About: Tests for QR Palette's core and its command line: making, registering, finding, votes...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for QR Palette's core and its command line: making, finding, votes, settings, MCP.

These cover making, registering, finding, votes, settings, and the MCP server (--mcp, --ecp) run as a
real process.

The core is the modules qr_palette.py starts: app_settings.py, making.py, short_link_ops.py, batches.py,
registry_export.py, votes.py, finding.py and print_advice.py. Run from the program folder:
python -m unittest discover -s tests -p test_qr_palette.py

Each test works in its own temporary folder with a fresh registry (palette.db). The command-line tests
start qr_palette.py as a child process with LOCALAPPDATA pointed at that folder, so its data folder,
audit log and settings never touch the real ones, and with FakeOllama (test_local_inference) standing
in for the local model server.

Classes:
  CoreCase            the shared temporary folder and a make() helper
  MakeTests           making codes: files, records, refusals, logos, names
  BatchTests          lists of codes from CSV files: reading, running, naming, skipping, stopping
  TamperTests         tagged short-link IDs and what the Read tab says about a scanned link
  ScheduleTests       destination changes scheduled for a day
  RegisterTests       pictures made elsewhere, and forgetting a record
  VoteTests           color votes and the board, and importing Color Voats votes
  ShortLinkTests      local and nonlocal short links, retargeting, exporting redirect pages
  QuickWinTests       CSV and JSON export, print advice, redrawing
  ApplySettingsTests  settings.json reaching every module
  CommandLineTests    --version, bad options, the MCP server over stdio, --selftest
Start reading at CoreCase.
"""

# Known limitation: csv is imported twice; the second import does nothing.
import csv
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import app_settings
import audit
import batches
import ecp
import finding
import local_inference
import localkey
import making
import mcp_server
import print_advice
import qr_codec
import qr_palette
import registry
import registry_export
import settings
import short_link_ops
import shortlinks
import swatch
import votes
from test_local_inference import QWEN_DIGEST, FakeOllama
from test_qr_codec import sample_logo

# the _meta of a modern (2026-07-28) MCP request, without client info
MODERN = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
          "io.modelcontextprotocol/clientCapabilities": {}}

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/
PROGRAM = os.path.join(HERE, "qr_palette.py")


def child_environment(folder):
    """The environment for a child qr_palette.py: this one, minus settings that change Python's text
    handling or run a startup script, with LOCALAPPDATA set to `folder`.

    LOCALAPPDATA decides the program's data folder (qr_palette.data_folder), so the child's audit log
    and default files land in the test's folder."""
    environment = dict(os.environ)
    for key in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONSTARTUP"):
        environment.pop(key, None)
    environment["LOCALAPPDATA"] = folder
    return environment


def file_hash(path):
    """SHA-256 hex digest of a file's bytes, to show a file was not changed."""
    handle = open(path, "rb")
    data = handle.read()
    handle.close()
    return hashlib.sha256(data).hexdigest()


class CoreCase(unittest.TestCase):
    """A temporary folder with a registry path (palette.db, made on first use) for each test."""

    def setUp(self):
        """Make the folder; self.db is the registry path inside it."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_core_")
        self.db = os.path.join(self.folder, "palette.db")

    def tearDown(self):
        """Remove the folder and everything in it."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def path(self, name):
        """A path for `name` in the test's folder."""
        return os.path.join(self.folder, name)

    def make(self, name, link, color):
        """Make and register a level-M code of `link` in `color` at 4 pixels per module -> Made."""
        made = making.make_qr(self.db, link, color, "M", self.path(name), 4)
        self.assertTrue(made["ok"], made["error"])
        return made["value"]


class MakeTests(CoreCase):
    """making.make_qr: the picture, its registry record, refusals, logos and file names."""

    def test_made_codes_are_files_and_records(self):
        """A made PNG reads back with its link and color; an SVG is found by its link with color, path and
        an existing file."""
        made = self.make("shop.png", "https://shop.example.com/", "#3366cc")
        self.assertTrue(os.path.isfile(made["path"]))
        picture = qr_codec.read_qr_file(made["path"])
        self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["color"]),
                         ("https://shop.example.com/", "#3366cc"))
        svg = self.make("menu.svg", "https://example.com/menu", "#006633")
        self.assertTrue(svg["path"].endswith("menu.svg"))
        found = finding.search(self.db, "qr_code", "https://example.com/menu", False, 20)["value"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["hex"], found[0]["path"], found[0]["exists"]), ("#006633", svg["path"], True))

    def test_what_cannot_be_made(self):
        """No link, no color, a color too light to scan (yellow) and a link too long for any version are
        refused, and no file is left behind."""
        for link, color, problem in (("", "#3366cc", "type a link"), ("x", "", "pick a color"),
                                     ("x", "#ffff00", "too light"), ("x" * 4000, "#3366cc", "too long")):
            made = making.make_qr(self.db, link, color, "M", self.path("bad.png"), 4)
            self.assertFalse(made["ok"])
            self.assertIn(problem, made["error"])
        self.assertFalse(os.path.exists(self.path("bad.png")))

    def test_saving_over_a_code_replaces_its_record(self):
        """Saving a new code over the same file replaces that file's record rather than adding a second."""
        self.make("same.png", "https://example.com/a", "#3366cc")
        self.make("same.png", "https://example.com/b", "#cc0000")
        rows = finding.search(self.db, "color", "red", False, 20)["value"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(finding.search(self.db, "qr_code", "example.com", False, 20)["value"][0]["link"],
                         "https://example.com/b")

    def test_control_characters_are_cleaned_before_encoding(self):
        """A right-to-left override (U+202E) and a bell character are dropped from a typed link."""
        made = self.make("clean.png", "https://example.com/\u202eabc\x07", "#3366cc")
        self.assertEqual(made["link"], "https://example.com/abc")

    def test_a_logo_code_is_level_h_and_reads_back(self):
        """With a logo the level is raised to H whatever was asked; PNG and SVG both read back, and a logo
        picture 2000 pixels wide is refused as too big with no file written."""
        for name in ("logo.png", "logo.svg"):
            made = making.make_qr(self.db, "https://shop.example.com/p/blue-mug", "#663399", "L", self.path(name), 4,
                                  None, sample_logo(40))
            self.assertTrue(made["ok"], made["error"])
            self.assertEqual(made["value"]["level"], "H")
            picture = qr_codec.read_qr_file(made["value"]["path"])
            self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["reading"]["level"]),
                             ("https://shop.example.com/p/blue-mug", "H"))
        found = finding.search(self.db, "qr_code", "blue-mug", False, 20)["value"]
        self.assertEqual(len(found), 2)
        refused = making.make_qr(self.db, "https://shop.example.com/", "#663399", "M", self.path("big.png"), 4,
                                 None, qr_codec.make_image(2000, 20, 0))
        self.assertIn("too big", refused["error"])
        self.assertFalse(os.path.exists(self.path("big.png")))

    def test_a_logo_is_never_lost_by_redrawing(self):
        """The registry does not keep logos, so a logo code is marked has_logo and redrawing it is refused,
        leaving its file byte for byte; a plain code redraws, and saving over the logo code without a logo
        keeps its record id and clears has_logo."""
        made = making.make_qr(self.db, "https://shop.example.com/p/blue-mug", "#663399", "M", self.path("logo.png"), 4,
                              None, sample_logo(40))["value"]
        handle = open(made["path"], "rb")
        before = handle.read()
        handle.close()
        found = finding.search(self.db, "qr_code", "blue-mug", False, 20)["value"]
        self.assertTrue(found[0]["has_logo"])
        refused = making.redraw_record(self.db, made["id"], "#006633", 4)
        self.assertIn("has a logo", refused["error"])
        handle = open(made["path"], "rb")
        self.assertEqual(handle.read(), before)
        handle.close()
        plain = self.make("plain.png", "https://shop.example.com/p/green-mug", "#663399")
        self.assertFalse(finding.search(self.db, "qr_code", "green-mug", False, 20)["value"][0]["has_logo"])
        self.assertTrue(making.redraw_record(self.db, plain["id"], "#006633", 4)["ok"])
        made_again = making.make_qr(self.db, "https://shop.example.com/p/blue-mug", "#663399", "M",
                                    self.path("logo.png"), 4)["value"]  # saved over, without a logo
        self.assertEqual(made_again["id"], made["id"])
        self.assertFalse(finding.search(self.db, "qr_code", "blue-mug", False, 20)["value"][0]["has_logo"])

    def test_print_advice_for_a_logo_is_level_h_at_its_version(self):
        """Without a logo, advice covers all four levels; given the version place_logo chose, only H at that
        version, and a version one higher is kept as given. 3 cm wide, read from 0.3 m."""
        text = "https://shop.example.com/p/blue-mug"
        everything = print_advice.print_advice(text, 3, 0.3, "")["value"]
        self.assertEqual([row["level"] for row in everything["levels"]], ["L", "M", "Q", "H"])
        placed = qr_codec.place_logo(text, sample_logo(40))["value"]
        version = placed["matrix"]["version"]
        with_logo = print_advice.print_advice(text, 3, 0.3, "", version)["value"]
        self.assertEqual([(row["level"], row["version"]) for row in with_logo["levels"]], [("H", version)])
        one_up = print_advice.print_advice(text, 3, 0.3, "", version + 1)["value"]
        self.assertEqual(one_up["levels"][0]["version"], version + 1)

    def test_names(self):
        """slug drops the scheme and "www.", lower-cases and joins words with "-", with "qr-code" when
        nothing is left; suggested_name adds the color without "#" and the extension."""
        self.assertEqual(making.slug("https://www.Shop.example.com/sale?id=4"), "shop-example-com-sale-id-4")
        self.assertEqual(making.slug("::"), "qr-code")
        self.assertEqual(making.suggested_name("https://example.com/a", "#3366cc", "svg"), "example-com-a-3366cc.svg")


class BatchTests(CoreCase):
    """batches: reading a list of codes from a CSV file and making them all in one run."""

    def write(self, text, name="list.csv", encoding="utf-8"):
        """Write `text` to `name` in `encoding` exactly as given (newline="" keeps its line ends) -> path."""
        handle = open(self.path(name), "w", encoding=encoding, newline="")
        handle.write(text)
        handle.close()
        return self.path(name)

    def rows(self, text):
        """The BatchRows read from a CSV file holding `text`; a refusal fails the test."""
        read = batches.read_batch_csv(self.write(text))
        self.assertTrue(read["ok"], read["error"])
        return read["value"]

    def batch(self, rows, section="", snap=False, watch=None, kind="png"):
        """Run make_batch into the folder "run" at level M, 4 pixels per module, report named "T" ->
        BatchReport; a failed run fails the test."""
        made = batches.make_batch(self.db, rows, self.path("run"), kind, "M", 4, section, snap, watch, "T")
        self.assertTrue(made["ok"], made["error"])
        return made["value"]

    def test_a_list_with_a_byte_order_mark_quotes_and_bad_rows(self):
        """A UTF-8 list with a byte-order mark, headers in any case and order, an extra column, quoted
        commas and doubled quotes reads as written; rows without a color or link, or with a color that is
        not #rrggbb, carry their problem; a wholly empty row is dropped. Row numbers count the header as 1."""
        path = self.write('Color,LINK,label,file,extra\r\n'
                          '#3366CC,"https://shop.example.com/a,b",Blue mug,,x\r\n'
                          '006633,https://example.com/menu,"Lunch, ""new""",menu.svg,\r\n'
                          ',https://example.com/no-color,,,\r\n'
                          'blue,https://example.com/bad-color,,,\r\n'
                          '#cc0000,,no link,,\r\n'
                          ',,,,\r\n', encoding="utf-8-sig")
        read = batches.read_batch_csv(path)
        self.assertTrue(read["ok"], read["error"])
        rows = read["value"]
        self.assertEqual(len(rows), 5)  # the empty row is not a row
        self.assertEqual((rows[0]["link"], rows[0]["color"], rows[0]["label"], rows[0]["problem"], rows[0]["row"]),
                         ("https://shop.example.com/a,b", "#3366cc", "Blue mug", "", 2))
        self.assertEqual((rows[1]["color"], rows[1]["label"], rows[1]["file"]), ("#006633", 'Lunch, "new"', "menu.svg"))
        self.assertEqual(rows[2]["problem"], "no color")
        self.assertIn("not a #rrggbb color", rows[3]["problem"])
        self.assertEqual(rows[4]["problem"], "no link")

    def test_lists_from_spreadsheets(self):
        """Semicolon- and tab-separated lists (as spreadsheets in some locales save them) and a cp1252 file
        read correctly; unknown headers, a header with no rows, an empty file and a missing file are refused."""
        rows = self.rows("link;color;label\nhttps://example.com/a;#3366cc;Caf\u00e9\n")
        self.assertEqual((rows[0]["link"], rows[0]["label"]), ("https://example.com/a", "Caf\u00e9"))
        path = self.write("link\tcolor\tlabel\r\nhttps://example.com/b\t#3366cc\tCaf\u00e9\r\n", encoding="cp1252")
        self.assertEqual(batches.read_batch_csv(path)["value"][0]["label"], "Caf\u00e9")
        for text, problem in (("url,colour\nhttps://example.com,#000000\n", "first row"), ("link,color\n", "no rows"),
                              ("", "no rows")):
            refused = batches.read_batch_csv(self.write(text))
            self.assertFalse(refused["ok"], text)
            self.assertIn(problem, refused["error"])
        self.assertFalse(batches.read_batch_csv(self.path("missing.csv"))["ok"])

    def test_a_run_makes_pictures_and_a_report(self):
        """Three codes are made and one row skipped; file names come from the label and link, a name given
        without an extension gets the run's kind, and a .svg name makes an SVG. Each picture reads back,
        each is registered, and the report (made-T.csv) lists every row with its status and reason."""
        rows = self.rows("link,color,label,file\n"
                         "https://example.com/a,#3366cc,Blue mug,\n"
                         "https://example.com/b,#006633,,own-name\n"
                         "https://example.com/c,#663399,,c.svg\n"
                         ",#663399,,\n")
        made = self.batch(rows)
        self.assertEqual((made["made"], made["skipped"], made["stopped"]), (3, 1, False))
        names = sorted(os.listdir(self.path("run")))
        self.assertEqual(names, ["blue-mug-example-com-a-3366cc.png", "c.svg", "made-T.csv", "own-name.png"])
        for line in made["rows"][:3]:
            self.assertEqual(line["status"], "made")
            picture = qr_codec.read_qr_file(line["path"])
            self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["color"]),
                             (line["link"], line["color"]))
        self.assertEqual(len(finding.search(self.db, "qr_code", "example.com", False, 20)["value"]), 3)
        handle = open(made["report"], encoding="utf-8-sig", newline="")
        report = list(csv.DictReader(handle))
        handle.close()
        self.assertEqual(report[3]["status"], "skipped")
        self.assertEqual(report[3]["reason"], "no link")
        self.assertEqual(report[0]["path"], made["rows"][0]["path"])

    def test_a_run_never_overwrites(self):
        """An existing same.png is left alone, and three rows asking for "same" (in any case, since Windows
        file names ignore case) become same-2, same-3 and same-4. A second run makes three more and writes
        a new report beside the first."""
        rows = self.rows("link,color,file\nhttps://example.com/a,#3366cc,same\nhttps://example.com/b,#3366cc,same\n"
                         "https://example.com/c,#3366cc,SAME.png\n")
        os.makedirs(self.path("run"))
        keep = os.path.join(self.path("run"), "same.png")
        handle = open(keep, "wb")
        handle.write(b"keep me")
        handle.close()
        made = self.batch(rows)
        self.assertEqual(made["made"], 3)
        self.assertEqual(sorted(os.path.basename(line["path"]).lower() for line in made["rows"]),
                         ["same-2.png", "same-3.png", "same-4.png"])
        handle = open(keep, "rb")
        self.assertEqual(handle.read(), b"keep me")
        handle.close()
        second = self.batch(rows)
        self.assertEqual(second["made"], 3)
        self.assertNotEqual(second["report"], made["report"])  # the earlier report stays too

    def test_duplicates_and_paths_are_skipped(self):
        """A row the same as an earlier one (color case aside) is skipped; file names that climb out, are
        absolute or hold a folder are "not a path"; CON (a reserved device name) and a name with ":" cannot
        be used on Windows. Nothing is written outside the run folder."""
        rows = self.rows("link,color,label,file\n"
                         "https://example.com/a,#3366cc,x,\n"
                         "https://example.com/a,#3366CC,x,\n"
                         "https://example.com/a,#3366cc,y,\n"
                         "https://example.com/b,#3366cc,,../outside.png\n"
                         "https://example.com/c,#3366cc,,C:\\Temp\\outside.png\n"
                         "https://example.com/d,#3366cc,,sub\\inside.png\n"
                         "https://example.com/e,#3366cc,,CON\n"
                         "https://example.com/f,#3366cc,,bad:name.png\n")
        made = self.batch(rows)
        self.assertEqual(made["made"], 2)
        self.assertEqual(made["rows"][1]["reason"], "the same as row 2")
        self.assertEqual(made["rows"][2]["status"], "made")  # the same code under another label is another picture
        for line in made["rows"][3:6]:
            self.assertIn("not a path", line["reason"])
        for line in made["rows"][6:]:
            self.assertIn("cannot be used on Windows", line["reason"])
        self.assertFalse(os.path.exists(self.path("outside.png")))

    def test_colors_too_light_are_skipped_or_snapped(self):
        """Yellow is too light to scan: skipped by default, or with snap replaced by the nearest usable
        color, which the note names and the picture is drawn in."""
        rows = self.rows("link,color\nhttps://example.com/a,#ffff00\nhttps://example.com/b,#3366cc\n")
        made = self.batch(rows)
        self.assertEqual((made["made"], made["rows"][0]["status"]), (1, "skipped"))
        self.assertIn("too light", made["rows"][0]["reason"])
        made = self.batch(rows, snap=True)
        self.assertEqual(made["made"], 2)
        near = swatch.nearest_usable("#ffff00")
        self.assertEqual(made["rows"][0]["color"], near)
        self.assertIn("#ffff00", made["rows"][0]["note"])
        self.assertEqual(qr_codec.read_qr_file(made["rows"][0]["path"])["value"]["color"], near)

    def test_short_links_are_reused_by_destination_and_color(self):
        """With a section, the same destination in the same color shares one short ID, another color gets
        its own, text that is not a web link is skipped, and the picture holds base + ID."""
        rows = self.rows("link,color,label\n"
                         "https://example.com/menu,#3366cc,first\n"
                         "https://example.com/menu,#3366cc,second\n"
                         "https://example.com/menu,#006633,green\n"
                         "not a web link,#006633,odd\n")
        made = self.batch(rows, section="nonlocal")
        self.assertEqual(made["made"], 3)
        ids = [line["short_id"] for line in made["rows"]]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])
        self.assertTrue(shortlinks.is_valid_code(ids[0]))
        self.assertIn("http", made["rows"][3]["reason"])
        picture = qr_codec.read_qr_file(made["rows"][0]["path"])
        self.assertEqual(picture["value"]["reading"]["text"], app_settings.LINKS["nonlocal"]["base"] + ids[0])

    def test_a_run_can_be_stopped(self):
        """watch is called before each row with (done, total); returning True after the first row stops the
        run, the rest are reported as not made, and the report is still written."""
        rows = self.rows("link,color\nhttps://example.com/a,#3366cc\nhttps://example.com/b,#3366cc\n"
                         "https://example.com/c,#3366cc\n")
        seen = []

        # record each call, and ask to stop once one row is done
        def watch(done, total):
            seen.append((done, total))
            return done == 1

        made = self.batch(rows, watch=watch)
        self.assertEqual((made["made"], made["stopped"]), (1, True))
        self.assertEqual(seen, [(0, 3), (1, 3)])
        self.assertEqual(made["rows"][2]["reason"], "stopped before this row")
        self.assertTrue(os.path.isfile(made["report"]))


class TamperTests(CoreCase):
    """Tagged short-link IDs and the Read tab's verdict on a scanned link.

    An ID is random digits, then (with the registry's key) two tag digits, an HMAC of the random digits,
    then a Damm check digit. Only the key's holder can make a valid tag, so an ID on your address with a
    wrong tag was not made by you. An untagged ID passes the tag check by chance 1 time in 100."""

    BASE = "HTTPS://GO.EXAMPLE.COM/"

    def made(self, code="", link="https://example.com/menu"):
        """Make a code whose nonlocal short link has ID `code` ("" for a fresh one) -> Made."""
        made = making.make_qr(self.db, link, "#3366cc", "M", self.path("a" + code + ".png"), 4,
                              short_link_ops.short_request(code, "nonlocal"))
        self.assertTrue(made["ok"], made["error"])
        return made["value"]

    def test_new_short_links_are_tagged_when_links_json_says_so(self):
        """A fresh ID is 10 digits (7 random, 2 tag, 1 check) with a valid tag; with tag_ids off it is 8."""
        code = self.made()["short_code"]
        self.assertEqual(len(code), 10)
        key = localkey.read_key(localkey.key_path(self.db))
        self.assertTrue(shortlinks.has_valid_tag(code, key))
        saved = app_settings.LINKS["tag_ids"]
        app_settings.LINKS["tag_ids"] = False
        try:
            self.assertEqual(len(short_link_ops.fresh_code(self.db, 7)), 8)
        finally:
            app_settings.LINKS["tag_ids"] = saved

    def test_a_key_that_cannot_be_made_never_stops_a_code(self):
        """With a non-key file where the key belongs, the code is still made with an untagged 8-digit ID,
        and its verdict is no warning."""
        handle = open(localkey.key_path(self.db), "w", encoding="utf-8")
        handle.write("my own notes")
        handle.close()
        code = self.made()["short_code"]
        self.assertEqual(len(code), 8)
        self.assertEqual(short_link_ops.tamper_verdict(self.db, self.BASE + code)["warning"], False)

    def test_what_the_read_tab_says(self):
        """Each verdict: your tagged ID (in any case), your older untagged ID, a stranger's ID on your
        address, a wrong check digit, a lookalike host, and links with nothing to do with your address.

        The untagged and stranger IDs are found by counting up from 1234567, skipping any body whose ID
        happens to carry a valid tag."""
        tagged = self.made()
        self.assertIn("Made with your key", short_link_ops.tamper_verdict(self.db, tagged["link"])["line"])
        self.assertIn("Made with your key", short_link_ops.tamper_verdict(self.db, tagged["link"].lower())["line"])
        key = localkey.read_key(localkey.key_path(self.db))
        body = "1234567"
        while shortlinks.has_valid_tag(body + shortlinks.check_digit(body), key):
            body = str(int(body) + 1)  # the 1 in 100
        old = self.made(body + shortlinks.check_digit(body), "https://example.com/old-menu")
        said = short_link_ops.tamper_verdict(self.db, old["link"])
        self.assertIn("without a tag", said["line"])
        self.assertFalse(said["warning"])
        body = str(int(body) + 1)
        while shortlinks.has_valid_tag(body + shortlinks.check_digit(body), key):
            body = str(int(body) + 1)
        stranger = short_link_ops.tamper_verdict(self.db, self.BASE + body + shortlinks.check_digit(body))
        self.assertIn("Not yours", stranger["line"])
        self.assertTrue(stranger["warning"])
        # change the check digit (position 9 of 10), so the ID no longer passes the Damm check
        wrong_digit = tagged["short_code"][:9] + str((int(tagged["short_code"][9]) + 1) % 10)
        self.assertTrue(short_link_ops.tamper_verdict(self.db, self.BASE + wrong_digit)["warning"])
        # "exampie" for "example": a host made to look like yours
        imitation = short_link_ops.tamper_verdict(self.db, "https://go.exampie.com/" + tagged["short_code"])
        self.assertIn("only looks like your GO.EXAMPLE.COM", imitation["line"])
        self.assertTrue(imitation["warning"])
        for text in ("https://shop.example.net/1", "WIFI:T:WPA;S:Cafe;P:x;;", self.BASE, "plain words"):
            self.assertEqual(short_link_ops.tamper_verdict(self.db, text), {"line": "", "warning": False}, text)

    def test_losing_the_key_makes_tags_unverifiable_never_invalid(self):
        """Without the key file no tag can be checked: the verdict says so without a warning, and the ID's
        check digit still makes it valid."""
        tagged = self.made()
        os.remove(localkey.key_path(self.db))
        said = short_link_ops.tamper_verdict(self.db, tagged["link"])
        self.assertIn("cannot be checked", said["line"])
        self.assertFalse(said["warning"])
        elsewhere = shortlinks.new_code(7, b"k" * 32)
        said = short_link_ops.tamper_verdict(self.db, self.BASE + elsewhere)
        self.assertIn("cannot be checked", said["line"])
        self.assertFalse(said["warning"])
        self.assertTrue(shortlinks.is_valid_code(tagged["short_code"]))


class ScheduleTests(CoreCase):
    """Short-link destination changes scheduled for a day."""

    def page_target(self, folder, code):
        """The text of the redirect page for ID `code` in an export folder."""
        handle = open(os.path.join(folder, code, "index.html"), encoding="utf-8")
        page = handle.read()
        handle.close()
        return page

    def test_exports_use_the_destination_in_force_on_their_day(self):
        """A change due 2026-12-01 is not in an export for the day before but is in one for that day; it is
        due only from that day, applying it counts one, and the history shows it with nothing still coming."""
        made = making.make_qr(self.db, "https://example.com/menu", "#3366cc", "M", self.path("a.png"), 4,
                              short_link_ops.short_request(shortlinks.new_code(7), "local"))
        self.assertTrue(made["ok"], made["error"])
        code = made["value"]["short_code"]
        self.assertTrue(short_link_ops.schedule_link_change(self.db, code, "https://example.com/winter",
                                                            "2026-12-01")["ok"])
        before = self.path("before")
        after = self.path("after")
        self.assertTrue(short_link_ops.export_redirects(self.db, before, "local", "2026-11-30")["ok"])
        self.assertTrue(short_link_ops.export_redirects(self.db, after, "local", "2026-12-01")["ok"])
        self.assertIn("https://example.com/menu", self.page_target(before, code))
        self.assertIn("https://example.com/winter", self.page_target(after, code))
        self.assertEqual(short_link_ops.due_link_changes(self.db, "2026-11-30")["value"], [])
        self.assertEqual(len(short_link_ops.due_link_changes(self.db, "2026-12-01")["value"]), 1)
        self.assertEqual(short_link_ops.apply_due_changes(self.db, "2026-12-01")["value"], 1)
        known = short_link_ops.link_history(self.db, code)["value"]
        self.assertEqual((known["changes"][0]["new_target"], known["coming"]), ("https://example.com/winter", []))

    def test_a_change_must_be_a_web_link_on_a_real_day(self):
        """A destination that is not a web link, or a day that is not YYYY-MM-DD, is refused; a scheduled
        change can be cancelled, and with no change applied there is nothing to undo."""
        made = making.make_qr(self.db, "https://example.com/menu", "#3366cc", "M", self.path("a.png"), 4,
                              short_link_ops.short_request(shortlinks.new_code(7), "local"))
        code = made["value"]["short_code"]
        self.assertFalse(short_link_ops.schedule_link_change(self.db, code, "not a link", "2026-12-01")["ok"])
        self.assertFalse(short_link_ops.schedule_link_change(self.db, code, "https://example.com/a", "tomorrow")["ok"])
        number = short_link_ops.schedule_link_change(self.db, code, "https://example.com/a", "2026-12-01")["value"]
        self.assertTrue(short_link_ops.cancel_link_change(self.db, number)["value"])
        self.assertFalse(short_link_ops.undo_link_change(self.db, code)["ok"])


class RegisterTests(CoreCase):
    """Registering pictures made elsewhere, and forgetting a record."""

    def test_pictures_made_elsewhere_are_registered_in_the_color_given(self):
        """A level-Q PNG in #3467cb (not a palette color) registers in the color given, found by a near-color
        search for #3366cc and by its text, with its level read from the picture."""
        matrix = qr_codec.encode_text("https://example.com/elsewhere", "Q", 1, -1)["value"]
        qr_codec.save_matrix(matrix, self.path("elsewhere.png"), 4, "#3467cb")
        picture = qr_codec.read_qr_file(self.path("elsewhere.png"))
        self.assertEqual(picture["value"]["color"], "#3467cb")
        registered = making.register_picture(self.db, self.path("elsewhere.png"), "#3467CB")
        self.assertTrue(registered["ok"], registered["error"])
        found = finding.search(self.db, "color", "#3366cc", True, 20)["value"]
        self.assertEqual(found[0]["link"], "https://example.com/elsewhere")
        self.assertEqual(found[0]["ec_level"], "Q")
        matches = finding.matches_for_text(self.db, "https://example.com/elsewhere", "")["value"]
        self.assertEqual(len(matches), 1)

    def test_other_formats_and_bad_files_are_refused(self):
        """A readable PGM (P5) is refused (only PNG and SVG are registered), as are a missing file and a
        color that is not #rrggbb."""
        matrix = qr_codec.encode_text("x", "M", 1, -1)["value"]
        image = qr_codec.matrix_to_image(matrix, 3, 4)
        ppm = b"P5 " + str(image["width"]).encode() + b" " + str(image["height"]).encode() + b" 255\n" + bytes(image["gray"])
        handle = open(self.path("code.ppm"), "wb")
        handle.write(ppm)
        handle.close()
        refused = making.register_picture(self.db, self.path("code.ppm"), "#000000")
        self.assertIn("only PNG and SVG", refused["error"])
        self.assertFalse(making.register_picture(self.db, self.path("missing.png"), "#000000")["ok"])
        self.assertFalse(making.register_picture(self.db, self.path("code.ppm"), "black")["ok"])

    def test_forgetting_leaves_the_file(self):
        """forget_record removes the record but never the picture file."""
        made = self.make("keep.png", "https://example.com/keep", "#3366cc")
        self.assertTrue(making.forget_record(self.db, made["id"])["value"])
        self.assertTrue(os.path.isfile(made["path"]))
        self.assertEqual(finding.search(self.db, "qr_code", "keep", False, 20)["value"], [])


class VoteTests(CoreCase):
    """Color votes and the board they order."""

    def test_votes_reorder_the_board(self):
        """The mixer board orders 118 colors; a Good vote puts #009966 first, and the same vote again takes
        it back (vote_color returns the new vote, 0) and restores the order."""
        first = votes.board(self.db, "mixer")["value"]
        self.assertEqual(len(first["order"]), 118)
        self.assertEqual(votes.vote_color(self.db, "#009966", 1)["value"], 1)
        self.assertEqual(votes.board(self.db, "mixer")["value"]["order"][0], "#009966")
        self.assertEqual(votes.vote_color(self.db, "#009966", 1)["value"], 0)
        self.assertEqual(votes.board(self.db, "mixer")["value"]["order"], first["order"])

    def test_color_voats_votes_are_imported_once(self):
        """Votes from a Color Voats social.json are imported once (2, then 0 on the second import) and show
        on the board; a file that is not an object is refused. The "when" values are Unix times in 2026."""
        social = {"posts": [], "votes": {"#3366cc": {"voat": 1, "when": 1793188800.0},
                                         "#cc0000": {"voat": -1, "when": 1793188900.0}},
                  "comments": {}, "saved": {}}
        handle = open(self.path("social.json"), "w", encoding="utf-8")
        json.dump(social, handle)
        handle.close()
        self.assertEqual(votes.import_color_voats(self.db, self.path("social.json"))["value"], 2)
        self.assertEqual(votes.import_color_voats(self.db, self.path("social.json"))["value"], 0)
        self.assertEqual(votes.board(self.db, "popular")["value"]["votes"], {"#3366cc": 1, "#cc0000": -1})
        handle = open(self.path("bad.json"), "w", encoding="utf-8")
        handle.write("[]")
        handle.close()
        self.assertFalse(votes.import_color_voats(self.db, self.path("bad.json"))["ok"])


class ShortLinkTests(CoreCase):
    """Short links: the code holds base + ID, and the registry holds the destination it sends to."""

    TARGET = "https://shop.example.com/hours"

    def make_short(self, name, color, target=TARGET, section="nonlocal"):
        """Make a code for `target` with a short link in `section`, offering a fresh 7-digit ID -> Result Made.

        When this destination already has an ID in that color, the existing ID is used instead."""
        return making.make_qr(self.db, target, color, "M", self.path(name), 4,
                              short_link_ops.short_request(shortlinks.new_code(7), section))

    def test_local_and_nonlocal_short_links_are_separate(self):
        """One destination gets separate local (HTTP://LOCALHOST:8000/) and nonlocal IDs; a second local
        code reuses the local ID; short_note names each record's section."""
        public = self.make_short("hours.png", "#3366cc")["value"]
        local = self.make_short("hours-local.png", "#3366cc", section="local")["value"]
        self.assertNotEqual(local["short_code"], public["short_code"])
        self.assertEqual(local["link"], "HTTP://LOCALHOST:8000/" + local["short_code"])
        self.assertEqual(local["target"], public["target"])
        self.assertEqual(qr_codec.read_qr_file(local["path"])["value"]["reading"]["text"], local["link"])
        again = self.make_short("hours-local.svg", "#3366cc", section="local")["value"]
        self.assertEqual(again["short_code"], local["short_code"])
        notes = []
        for shown in finding.search(self.db, "qr_code", "hours", False, 20)["value"]:
            notes.append(short_link_ops.short_note(shown))
        self.assertEqual(sorted(notes), [" (local)", " (local)", " (nonlocal)"])

    def test_a_short_link_is_printed_and_its_destination_registered(self):
        """The picture holds the short address (a small version 2 code) and search finds the record by a
        word of the destination, the destination itself, or the ID."""
        made = self.make_short("hours.png", "#3366cc")
        self.assertTrue(made["ok"], made["error"])
        code = made["value"]["short_code"]
        self.assertTrue(shortlinks.is_valid_code(code))
        self.assertEqual(made["value"]["link"], "HTTPS://GO.EXAMPLE.COM/" + code)
        self.assertEqual(made["value"]["target"], self.TARGET)
        self.assertEqual(made["value"]["version"], 2)
        picture = qr_codec.read_qr_file(made["value"]["path"])
        self.assertEqual(picture["value"]["reading"]["text"], made["value"]["link"])
        for value in ("hours", self.TARGET, code):
            found = finding.search(self.db, "qr_code", value, False, 20)["value"]
            self.assertEqual(len(found), 1, value)
            self.assertEqual((found[0]["short_code"], found[0]["target"]), (code, self.TARGET))

    def test_the_same_destination_and_color_reuse_the_id(self):
        """A second picture of the same destination and color shares the ID; another color gets a new one.
        All three are separate records."""
        first = self.make_short("hours.png", "#3366cc")["value"]
        again = self.make_short("hours.svg", "#3366cc")["value"]
        other = self.make_short("hours-green.png", "#006633")["value"]
        self.assertEqual(again["short_code"], first["short_code"])
        self.assertNotEqual(other["short_code"], first["short_code"])
        self.assertEqual(len(finding.search(self.db, "qr_code", "hours", False, 20)["value"]), 3)

    def test_only_web_links_get_short_links(self):
        """Text that is not an http(s) link cannot have a short link, and no picture is left."""
        refused = self.make_short("x.png", "#3366cc", "just some text")
        self.assertFalse(refused["ok"])
        self.assertIn("http", refused["error"])
        self.assertFalse(os.path.exists(self.path("x.png")))

    def test_destinations_change_without_a_new_picture(self):
        """retarget_link changes the destination in the registry while the picture stays byte for byte; a
        destination that is not a link, or an ID never made, is refused."""
        made = self.make_short("hours.png", "#3366cc")["value"]
        before = file_hash(made["path"])
        self.assertTrue(short_link_ops.retarget_link(self.db, made["short_code"],
                                                     "https://shop.example.com/holidays")["ok"])
        found = finding.search(self.db, "qr_code", "holidays", False, 20)["value"]
        self.assertEqual(found[0]["target"], "https://shop.example.com/holidays")
        self.assertEqual(file_hash(made["path"]), before)
        self.assertFalse(short_link_ops.retarget_link(self.db, made["short_code"], "not a link")["ok"])
        self.assertFalse(short_link_ops.retarget_link(self.db, shortlinks.new_code(7), self.TARGET)["ok"])

    def export(self, arguments):
        """Run qr_palette.py --db <registry> with `arguments` as a child process -> CompletedProcess."""
        return subprocess.run([sys.executable, PROGRAM, "--db", self.db] + arguments, capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)

    def test_redirect_pages_are_exported_from_the_command_line_one_section_at_a_time(self):
        """--export-redirects writes one section's pages: the two nonlocal pages (with the scan tag added to
        the destination) and not the local one, then, with no --section, the local page. An unknown section
        exits 2, and a registry that is not there cannot be exported."""
        first = self.make_short("hours.png", "#3366cc")["value"]
        second = self.make_short("menu.png", "#006633", "https://example.com/menu")["value"]
        local = self.make_short("try.png", "#006633", "https://example.com/try", "local")["value"]
        site = self.path("site")
        done = self.export(["--export-redirects", site, "--section", "nonlocal"])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(b"wrote 2 nonlocal redirect page(s)", done.stdout)
        handle = open(os.path.join(site, first["short_code"], "index.html"), encoding="utf-8")
        page = handle.read()
        handle.close()
        self.assertIn("url=https://shop.example.com/hours?utm_source=qr", page)
        self.assertTrue(os.path.isfile(os.path.join(site, second["short_code"], "index.html")))
        self.assertFalse(os.path.exists(os.path.join(site, local["short_code"])))
        lan = self.path("lan")
        done = self.export(["--export-redirects", lan])  # settings.json's links.use: local by default
        self.assertIn(b"wrote 1 local redirect page(s)", done.stdout)
        self.assertTrue(os.path.isfile(os.path.join(lan, local["short_code"], "index.html")))
        self.assertEqual(self.export(["--export-redirects", lan, "--section", "elsewhere"]).returncode, 2)
        self.assertFalse(short_link_ops.export_redirects(self.path("none.db"), site, "local")["ok"])


class QuickWinTests(CoreCase):
    """Exports, print advice and redrawing."""

    def test_csv_export_for_spreadsheets(self):
        """The CSV export counts codes and short links, starts with a UTF-8 byte-order mark, uses
        CSV_COLUMNS in order, writes "=example" as "'=example" so no spreadsheet runs it as a formula, and
        gives a short link's destination, ID and section. Any other extension is refused."""
        self.make("a.png", "https://example.com/a", "#3366cc")
        self.make("b.png", "=example", "#006633")
        short = making.make_qr(self.db, "https://shop.example.com/hours", "#3366cc", "M", self.path("s.png"), 4,
                               short_link_ops.short_request(shortlinks.new_code(7), "nonlocal"))["value"]
        exported = registry_export.export_registry(self.db, self.path("codes.csv"))
        self.assertEqual((exported["value"]["codes"], exported["value"]["short_links"]), (3, 1))
        handle = open(self.path("codes.csv"), "rb")
        raw = handle.read()
        handle.close()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # a byte-order mark, so spreadsheets read it as UTF-8
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        self.assertEqual(list(rows[0].keys()), list(registry_export.CSV_COLUMNS))
        by_id = {}
        for row in rows:
            by_id[int(row["id"])] = row
        self.assertEqual(by_id[2]["link"], "'=example")  # never read as a formula
        self.assertEqual((by_id[short["id"]]["destination"], by_id[short["id"]]["short_id"],
                          by_id[short["id"]]["section"]), (self.TARGET, short["short_code"], "nonlocal"))
        self.assertFalse(registry_export.export_registry(self.db, self.path("codes.txt"))["ok"])

    def test_json_export_holds_everything(self):
        """The JSON export holds codes, short links and votes."""
        self.make("a.png", "https://example.com/a", "#3366cc")
        votes.vote_color(self.db, "#3366cc", 1)
        self.assertTrue(registry_export.export_registry(self.db, self.path("all.json"))["ok"])
        handle = open(self.path("all.json"), encoding="utf-8")
        data = json.load(handle)
        handle.close()
        self.assertEqual((len(data["codes"]), data["short_links"], data["votes"][0]["color"]), (1, [], "#3366cc"))

    def test_print_advice(self):
        """Module size from reading distance (distance / 250, the 10:1 rule for a 25-module code), the
        printed width each level needs, and the caption's letter size.

        At 0.3 m a module needs 1.2 mm; level M is version 2, 25 modules plus an 8-module quiet zone = 33,
        so it needs 33 * 1.2 = 39.6 mm, rounded up to 4.0 cm: a 3 cm print does not fit, a 5 cm one does.
        A very short distance is held at MIN_MODULE_MM. Widths and distances that are zero, text or a bool
        are refused."""
        url = "HTTPS://GO.EXAMPLE.COM/12345674"
        advice = print_advice.print_advice(url, 3.0, 0.3, "GO.EXAMPLE.COM/12345674")["value"]
        self.assertEqual(advice["need_mm"], 1.2)  # 300 mm / 250
        level_m = advice["levels"][1]
        self.assertEqual((level_m["level"], level_m["version"], level_m["modules"]), ("M", 2, 33))
        self.assertFalse(level_m["fits"])
        self.assertEqual(level_m["min_width_cm"], 4.0)
        self.assertGreater(level_m["caption_mm"], 1.0)
        roomy = print_advice.print_advice(url, 5.0, 0.3, "")["value"]
        self.assertTrue(roomy["levels"][1]["fits"])
        self.assertIsNone(roomy["levels"][1]["caption_mm"])
        self.assertEqual(print_advice.print_advice(url, 3.0, 0.05, "")["value"]["need_mm"], print_advice.MIN_MODULE_MM)
        for width, distance in ((0, 0.3), (3, 0), ("3", 0.3), (True, 0.3)):
            self.assertFalse(print_advice.print_advice(url, width, distance, "")["ok"], (width, distance))

    def test_redraw_keeps_the_link_and_the_short_link(self):
        """Redrawing in a new color keeps the text, level Q and the short link's destination; a color too
        light is refused and leaves the picture as it was; an unknown id is refused; no trial file is left
        in the folder."""
        short = making.make_qr(self.db, "https://shop.example.com/hours", "#3366cc", "Q", self.path("s.png"), 4,
                               short_link_ops.short_request(shortlinks.new_code(7), "local"))["value"]
        redrawn = making.redraw_record(self.db, short["id"], "#663399", 6)
        self.assertTrue(redrawn["ok"], redrawn["error"])
        picture = qr_codec.read_qr_file(short["path"])["value"]
        self.assertEqual((picture["reading"]["text"], picture["color"], picture["reading"]["level"]),
                         (short["link"], "#663399", "Q"))
        found = finding.search(self.db, "qr_code", short["short_code"], False, 20)["value"]
        self.assertEqual((len(found), found[0]["hex"], found[0]["target"]), (1, "#663399", self.TARGET))
        self.assertIn("dark enough", making.redraw_record(self.db, short["id"], "#ffff00", 6)["error"])
        self.assertEqual(qr_codec.read_qr_file(short["path"])["value"]["color"], "#663399")  # left as it was
        self.assertFalse(making.redraw_record(self.db, 999, "#663399", 6)["ok"])
        self.assertEqual(sorted(os.listdir(self.folder)), ["palette.db", "s.png"])

    TARGET = "https://shop.example.com/hours"

    def test_local_pages_have_a_home(self):
        """With no export folder in links.json, local pages go to "local pages" in the data folder."""
        self.assertEqual(qr_palette.local_pages_folder(), os.path.join(qr_palette.data_folder(), "local pages"))


class ApplySettingsTests(unittest.TestCase):
    """app_settings.apply_settings: each settings.json value reaches the module that uses it.

    "no-such-settings.json" is a file that does not exist, so settings.load gives the defaults."""

    def tearDown(self):
        """Apply the default settings again, so no test leaks its changes into the next."""
        app_settings.apply_settings(settings.load("no-such-settings.json")["values"])

    def test_settings_reach_every_module(self):
        """Changed values land in swatch, registry, local_inference, ecp and mcp_server; an unknown preset
        falls back to "mixer" with one warning. A minimum contrast of 4.5 leaves 77 usable colors."""
        values = settings.load("no-such-settings.json")["values"]
        values["colors"]["minimum_contrast"] = 4.5
        values["queries"]["max_limit"] = 50
        values["queries"]["statement_seconds"] = 0.5
        values["inference"]["max_answer_tokens"] = 128
        values["inference"]["retry_answer_tokens"] = 300
        values["inference"]["require_cloud_disabled"] = False
        values["protocol"]["max_field_characters"] = 80
        values["protocol"]["rate_burst"] = 9
        values["colors"]["preset"] = "nothing_like_it"
        warnings = app_settings.apply_settings(values)
        self.assertEqual(len(swatch.usable_colors()), 77)
        self.assertEqual(registry.MAX_LIMIT, 50)
        self.assertEqual(registry.STATEMENT_SECONDS, 0.5)
        self.assertEqual(local_inference.PLAN_OPTIONS["num_predict"], 128)
        self.assertEqual(local_inference.RETRY_ANSWER_TOKENS, 300)
        self.assertIs(ecp.REQUIRE_CLOUD_DISABLED, False)
        self.assertEqual(ecp.MAX_FIELD_CHARACTERS, 80)
        self.assertEqual(mcp_server.RATE_BURST, 9)
        self.assertEqual(values["colors"]["preset"], "mixer")
        self.assertEqual(len(warnings), 1)

    def test_the_engine_follows_the_settings(self):
        """make_engine takes the preset, default model and timeout given; the audit file is the data
        folder's audit.jsonl unless settings name another."""
        values = settings.load("no-such-settings.json")["values"]
        values["colors"]["preset"] = "popular"
        engine = qr_palette.make_engine("x.db", "http://127.0.0.1:11434", 9.0, values, "qwen2.5:7b-instruct")
        self.assertEqual((engine["preset"], engine["default_model"], engine["timeout"]),
                         ("popular", "qwen2.5:7b-instruct", 9.0))
        self.assertEqual(engine["audit_file"], qr_palette.default_audit_path())
        values["audit"]["file"] = os.path.abspath("elsewhere.jsonl")
        self.assertEqual(qr_palette.make_engine("x.db", "", 9.0, values, "")["audit_file"],
                         os.path.abspath("elsewhere.jsonl"))

    def test_ecp_records_become_result_rows(self):
        """finding.shown_from_record maps an ECP record to the window's Shown row, with defaults for the
        fields ECP leaves out; a short-link record yields its ID and its destination."""
        record = {"id": 3, "hex": "#3366cc", "color_name": "Blue", "color_family": "blue", "rank": 1,
                  "payload_url": "https://example.com/a", "target_url": "", "file_path": "C:\\Codes\\a.png",
                  "net_votes": 0, "created_at": "2026-10-29T10:00:00Z", "exists": None}
        self.assertEqual(finding.shown_from_record(record),
                         {"id": 3, "link": "https://example.com/a", "hex": "#3366cc", "name": "Blue", "family": "blue",
                          "path": "C:\\Codes\\a.png", "exists": None, "ec_level": "M", "version": 1,
                          "short_code": "", "target": "", "scans": None, "has_logo": False})
        record["payload_url"] = "HTTPS://GO.EXAMPLE.COM/12345674"
        record["target_url"] = "https://example.com/a"
        shown = finding.shown_from_record(record)
        self.assertEqual((shown["short_code"], finding.destination(shown)), ("12345674", "https://example.com/a"))

    def test_links_json_comes_from_the_settings(self):
        """settings' links.file and links.use pick the links.json and section; its base and id_digits reach
        app_settings, and a short request then uses that base. Use is "local" by default."""
        folder = tempfile.mkdtemp(prefix="qr_palette_links_setting_")
        try:
            path = os.path.join(folder, "links.json")
            handle = open(path, "w", encoding="utf-8")
            handle.write(json.dumps({"nonlocal": {"base": "HTTPS://GO.SHOP.TEST/"}, "id_digits": 5}))
            handle.close()
            values = settings.load("no-such-settings.json")["values"]
            self.assertEqual(values["links"]["use"], "local")
            values["links"]["file"] = path
            values["links"]["use"] = "nonlocal"
            self.assertEqual(app_settings.apply_settings(values), [])
            self.assertEqual((app_settings.LINKS["nonlocal"]["base"], app_settings.LINKS["id_digits"]),
                             ("HTTPS://GO.SHOP.TEST/", 5))
            self.assertEqual(app_settings.LINK_SECTION, "nonlocal")
            self.assertEqual(short_link_ops.short_request("1", app_settings.LINK_SECTION)["base"],
                             "HTTPS://GO.SHOP.TEST/")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class CommandLineTests(CoreCase):
    """qr_palette.py run as a child process: options, the MCP server over stdio, and --selftest.

    setUp starts a FakeOllama and registers two codes: shop.png (#3366cc) and menu.png (#006633)."""

    def setUp(self):
        """The CoreCase folder, a FakeOllama, and the two codes."""
        CoreCase.setUp(self)
        self.fake = FakeOllama()
        self.make("shop.png", "https://shop.example.com/", "#3366cc")
        self.make("menu.png", "https://example.com/menu", "#006633")

    def tearDown(self):
        """Stop the fake model server, then remove the folder."""
        self.fake.stop()
        CoreCase.tearDown(self)

    def run_program(self, arguments, lines):
        """Run qr_palette.py with `arguments`, feeding `lines` as JSON lines on stdin -> (CompletedProcess,
        the answers parsed from stdout).

        stdout must hold no carriage return (text mode on Windows would add one) and only ASCII JSON lines."""
        data = b""
        for line in lines:
            data = data + json.dumps(line).encode("utf-8") + b"\n"
        done = subprocess.run([sys.executable, PROGRAM] + arguments, input=data, capture_output=True, timeout=120,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertNotIn(b"\r", done.stdout)
        answers = []
        for line in done.stdout.split(b"\n"):
            if line != b"":
                answers.append(json.loads(line.decode("ascii")))
        return done, answers

    def test_version_and_bad_options(self):
        """--version prints the name and version; --ecp with an inference address that is not on this
        computer exits 2 naming local inference; --db without its value exits 2."""
        done = subprocess.run([sys.executable, PROGRAM, "--version"], capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.stdout.decode("ascii").strip(), "Generic Company QR Palette 0.1.0")
        done = subprocess.run([sys.executable, PROGRAM, "--ecp", "--inference", "http://example.com:11434"],
                              capture_output=True, timeout=60, env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"local inference", done.stdout)
        done = subprocess.run([sys.executable, PROGRAM, "--db"], capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 2)

    def lines_of(self, number, prompt, model_id, meta):
        """A tools/call request for ecp_query with id `number`; model_id and _meta only when given."""
        params = {"name": "ecp_query", "arguments": {"prompt": prompt}}
        if model_id != "":
            params["arguments"]["model_id"] = model_id
        if meta is not None:
            params["_meta"] = meta
        return {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": params}

    def legacy_start(self):
        """The two lines that start a legacy (2025-11-25) MCP session: initialize and notifications/initialized."""
        return [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}]

    def audit_file(self):
        """Where the child's default audit log goes: its data folder under the test's LOCALAPPDATA."""
        return os.path.join(self.folder, "Generic Company Inc", qr_palette.APP_ID, "audit.jsonl")

    def test_mcp_over_stdio_in_both_eras(self):
        """A legacy session (--mcp) and a modern one (--ecp) each answer their requests over stdio, the
        registry file is not changed, and the audit log holds one valid line per tool call (4).

        The legacy run: initialize, tools/list, a query before any model is chosen (args_invalid), select
        the qwen model, then a query pinned to its digest that finds shop.png. The modern run: discover,
        then a query by model name that finds the menu record."""
        before = file_hash(self.db)
        done, answers = self.run_program(["--mcp", "--db", self.db, "--inference", self.fake.url], self.legacy_start() + [
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self.lines_of(3, "#3366cc", "", None),
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "ecp_select_model", "arguments": {"name": "qwen2.5:7b-instruct"}}},
            self.lines_of(5, "#3366cc", "qwen2.5:7b-instruct@" + QWEN_DIGEST, None)])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(answers), 5)
        self.assertEqual(answers[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(len(answers[1]["result"]["tools"]), 3)
        self.assertEqual(answers[2]["result"]["structuredContent"]["kind"], "args_invalid")  # no model chosen yet
        self.assertEqual(answers[3]["result"]["structuredContent"]["model_id"], "qwen2.5:7b-instruct@" + QWEN_DIGEST)
        self.assertFalse(answers[4]["result"]["isError"])
        self.assertEqual(answers[4]["result"]["structuredContent"]["records"][0]["file_path"], self.path("shop.png"))
        done, answers = self.run_program(["--ecp", "--db", self.db, "--inference", self.fake.url], [
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN}},
            self.lines_of(2, "#006633", "qwen2.5:7b-instruct", MODERN)])
        self.assertEqual(answers[0]["result"]["supportedVersions"], ["2026-07-28"])
        self.assertEqual(answers[1]["result"]["resultType"], "complete")
        self.assertEqual(answers[1]["result"]["structuredContent"]["records"][0]["payload_url"],
                         "https://example.com/menu")
        self.assertEqual(file_hash(self.db), before)
        self.assertEqual(audit.verify(self.audit_file())["value"], 4)

    def test_the_default_model(self):
        """With --model, a query that names no model uses that one; the menu link finds the green record."""
        done, answers = self.run_program(["--mcp", "--db", self.db, "--inference", self.fake.url, "--model",
                                          "qwen2.5:7b-instruct"], self.legacy_start() + [
            self.lines_of(2, "https://example.com/menu", "", None)])
        self.assertEqual(answers[1]["result"]["structuredContent"]["records"][0]["hex"], "#006633")

    def test_settings_change_what_the_server_does(self):
        """A --settings file sets the registry, the audit log's place, the inference server and default
        model, and a default limit of 1: a query for the folder's path (both pictures are in it) returns
        one row, and the audit log gets one line."""
        custom = self.path("custom-settings.json")
        audit_path = os.path.join(self.folder, "logs", "ecp-audit.jsonl")
        handle = open(custom, "w", encoding="utf-8")
        handle.write(json.dumps({"queries": {"default_limit": 1}, "registry": self.db, "audit": {"file": audit_path},
                                 "inference": {"url": self.fake.url, "model": "qwen2.5:7b-instruct"}}))
        handle.close()
        done, answers = self.run_program(["--mcp", "--settings", custom], self.legacy_start() + [
            self.lines_of(2, self.folder, "", None)])
        self.assertEqual(done.returncode, 0, done.stderr)
        content = answers[1]["result"]["structuredContent"]
        self.assertEqual((content["row_count"], content["model_id"]), (1, "qwen2.5:7b-instruct@" + QWEN_DIGEST))
        self.assertEqual(audit.verify(audit_path)["value"], 1)

    def test_a_broken_settings_file_is_reported_not_fatal(self):
        """A settings file that is not valid JSON is reported on stderr, the server runs on defaults, and
        the file is left untouched."""
        broken = self.path("broken-settings.json")
        handle = open(broken, "w", encoding="utf-8")
        handle.write('{"colors": ')
        handle.close()
        before = file_hash(broken)
        done, answers = self.run_program(["--mcp", "--settings", broken, "--db", self.db, "--inference", self.fake.url],
                                         self.legacy_start() + [self.lines_of(2, "#3366cc", "qwen2.5:7b-instruct", None)])
        self.assertIn(b"not valid JSON", done.stderr)
        self.assertEqual(answers[1]["result"]["structuredContent"]["row_count"], 1)
        self.assertEqual(file_hash(broken), before)

    def test_selftest(self):
        """qr_palette.py --selftest exits 0."""
        done = subprocess.run([sys.executable, PROGRAM, "--selftest"], capture_output=True, timeout=120,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=94adc3c228c14458cfcbdce9fe75b50c1d0eca4423e9193b1877da58901cf5ff ====
