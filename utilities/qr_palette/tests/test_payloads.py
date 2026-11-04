# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_payloads.py
# About: Tests for the code kinds and the local key: payload text, Wi-Fi masking, the key file.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for the code kinds and the local key: payload text, Wi-Fi masking, the key file.

These pin escaping, what each payload looks like, reading each back from a real code, masking a Wi-Fi
password however it arrives, and that the key stays out of the registry.

payloads.py builds the text a code holds for each kind (a WIFI: join, a vCard 3.0, an iCalendar
VEVENT, geo:, mailto:, tel: and SMSTO:). A Wi-Fi password must never be stored: the registry keeps the
text with the password replaced by "********" (payloads.stored_form) and an HMAC-SHA-256 tag of the
real text under a key file beside the registry (localkey.py), so a scanned code still finds its record.

Classes:
  EscapingTests  the WIFI: escapes, vCard/iCalendar text escapes and line folding
  KindTests      the exact text of each kind, its refusals, and a round trip through a real QR code
  MaskingTests   stored_form and is_masked on their own
  StoringTests   that no password reaches the registry, a report, an export or a backup
  KeyTests       the key file and the tags made with it

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import batches
import finding
import localkey
import making
import payloads
import qr_codec
import registry
import registry_export
import sheets


def built(kind, **fields):
    """The Payload payloads.build makes for `kind` from the keyword fields; a refusal fails the test."""
    made = payloads.build(kind, fields)
    if not made["ok"]:
        raise AssertionError(made["error"])
    return made["value"]


class EscapingTests(unittest.TestCase):
    """How special characters and long lines are written inside each format."""

    def test_wifi_escapes_its_five_characters(self):
        """Backslash, semicolon, comma, colon and double quote each get a backslash; other text, "é" too,
        is kept as it is."""
        self.assertEqual(payloads.wifi_escape('a\\b;c,d:e"f'), 'a\\\\b\\;c\\,d\\:e\\"f')
        made = built("wifi", ssid='Café; "main"', password="p:a,s;s\\")
        self.assertEqual(made["text"], 'WIFI:T:WPA;S:Café\\; \\"main\\";P:p\\:a\\,s\\;s\\\\;;')

    def test_vcard_and_icalendar_text(self):
        """vCard and iCalendar text escapes comma, semicolon and backslash, and writes a newline as \\n."""
        self.assertEqual(payloads.text_escape("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")
        made = built("contact", first="Ana", last="Silva, Jr", org="Shop; Co")
        self.assertIn("N:Silva\\, Jr;Ana;;;\r\n", made["text"])
        self.assertIn("ORG:Shop\\; Co\r\n", made["text"])

    def test_long_lines_fold_inside_characters_never(self):
        """A long line folds into pieces of at most FOLD_AT (75) bytes, never inside a UTF-8 character.

        Folding (RFC 5545 3.1) breaks a line with CRLF and starts each next piece with a space, which a
        reader drops when it joins them. "é" is two bytes in UTF-8, so 80 of them force breaks that
        would split a character if the fold counted characters or cut at a fixed byte."""
        line = "SUMMARY:" + "é" * 80
        folded = payloads.fold(line)
        parts = folded.split("\r\n")
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part.encode("utf-8")), payloads.FOLD_AT)
        for part in parts[1:]:
            self.assertTrue(part.startswith(" "))
        # unfolding (drop each leading space and join) gives the line back
        self.assertEqual(parts[0] + "".join(part[1:] for part in parts[1:]), line)
        self.assertEqual(payloads.fold("short"), "short")


class KindTests(unittest.TestCase):
    """The exact text each kind builds, what it refuses, and that a real code carries it intact."""

    def test_wifi(self):
        """WPA by default; WEP and hidden networks as asked; an open network uses T:nopass and masks nothing.

        Refused: no network name, WPA without a password, a password on an open network, and an
        unknown security type."""
        self.assertEqual(built("wifi", ssid="Cafe", password="secret")["text"], "WIFI:T:WPA;S:Cafe;P:secret;;")
        self.assertEqual(built("wifi", ssid="Cafe", password="secret", security="WEP", hidden="yes")["text"],
                         "WIFI:T:WEP;S:Cafe;P:secret;H:true;;")
        open_network = built("wifi", ssid="Cafe")
        self.assertEqual((open_network["text"], open_network["masked"]), ("WIFI:T:nopass;S:Cafe;;", False))
        for fields, problem in (({"password": "x"}, "network name"), ({"ssid": "Cafe", "security": "WPA"}, "password"),
                                ({"ssid": "Cafe", "security": "none", "password": "x"}, "open network"),
                                ({"ssid": "Cafe", "security": "ROT13", "password": "x"}, "security")):
            refused = payloads.build("wifi", fields)
            self.assertFalse(refused["ok"], fields)
            self.assertIn(problem, refused["error"])

    def test_contact(self):
        """A vCard 3.0 with CRLF line ends; the phone loses its separators, a URL keeps its comma.

        An organization alone becomes the FN (formatted name). Refused: no name at all, a phone with
        letters, and an email without "@"."""
        made = built("contact", first="Ana", last="Silva", phone="+1 (555) 010-0", email="ana@example.com",
                     url="https://example.com/a,b")
        self.assertEqual(made["text"].split("\r\n"),
                         ["BEGIN:VCARD", "VERSION:3.0", "N:Silva;Ana;;;", "FN:Ana Silva", "TEL:+15550100",
                          "EMAIL:ana@example.com", "URL:https://example.com/a,b", "END:VCARD", ""])
        self.assertIn("FN:Shop Co\r\n", built("contact", org="Shop Co")["text"])
        for fields, problem in (({}, "name"), ({"first": "A", "phone": "call me"}, "phone"),
                                ({"first": "A", "email": "nobody"}, "email")):
            self.assertIn(problem, payloads.build("contact", fields)["error"])

    def test_event(self):
        """A VEVENT with local date-times (no time zone), escaped place and description; whole days use
        VALUE=DATE.

        Refused: no title, a start that is not a date or not a real day (month 13), a date mixed with a
        date-time, and an end before the start."""
        made = built("event", title="Summer market", start="2026-12-01 18:30", end="2026-12-01 21:00",
                     place="Town square, north", about="Stalls\nand music")
        self.assertEqual(made["text"].split("\r\n"),
                         ["BEGIN:VEVENT", "SUMMARY:Summer market", "DTSTART:20261201T183000", "DTEND:20261201T210000",
                          "LOCATION:Town square\\, north", "DESCRIPTION:Stalls\\nand music", "END:VEVENT", ""])
        whole = built("event", title="Fair", start="2026-12-01", end="2026-12-02")
        self.assertIn("DTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261202\r\n", whole["text"])
        for fields, problem in (({"start": "2026-12-01"}, "title"), ({"title": "x", "start": "soon"}, "start"),
                                ({"title": "x", "start": "2026-13-01"}, "start"),
                                ({"title": "x", "start": "2026-12-01", "end": "2026-12-01 10:00"}, "both"),
                                ({"title": "x", "start": "2026-12-02", "end": "2026-12-01"}, "before")):
            self.assertIn(problem, payloads.build("event", fields)["error"])

    def test_place_email_phone_text(self):
        """The URI kinds: geo: (a decimal comma is read as a point; latitude past 90 or words refused),
        mailto: (subject and body percent-encoded, body breaks as CRLF), tel: and SMSTO:."""
        self.assertEqual(built("place", latitude="52.37", longitude="-4,89")["text"], "geo:52.37,-4.89")
        self.assertFalse(payloads.build("place", {"latitude": "91", "longitude": "0"})["ok"])
        self.assertFalse(payloads.build("place", {"latitude": "north", "longitude": "0"})["ok"])
        self.assertEqual(built("email", to="shop@example.com", subject="Hello there", body="Line one\nA&B")["text"],
                         "mailto:shop@example.com?subject=Hello%20there&body=Line%20one%0D%0AA%26B")
        self.assertEqual(built("email", to="shop@example.com")["text"], "mailto:shop@example.com")
        self.assertFalse(payloads.build("email", {"to": "not an address"})["ok"])
        self.assertEqual(built("phone", number="+1 555-0100")["text"], "tel:+15550100")
        self.assertFalse(payloads.build("phone", {"number": "12"})["ok"])  # a number needs 3 to 20 digits
        self.assertEqual(built("text", number="555 0100", message="Table: 4")["text"], "SMSTO:5550100:Table: 4")

    def test_hidden_characters_are_cleaned_from_fields(self):
        """A right-to-left override (U+202E) and a bell (7) typed into a field are dropped before building."""
        made = built("contact", first="An" + chr(0x202E) + "a" + chr(7))
        self.assertIn("FN:Ana\r\n", made["text"])

    def test_every_kind_reads_back_from_a_real_code(self):
        """Each kind, with awkward characters where it allows them, survives encode, draw and decode exactly,
        and kind_of names it again from the text."""
        samples = {"wifi": {"ssid": "Café; main", "password": "p:a,s;s\\w\"rd"},
                   "contact": {"first": "Ana", "last": "Silva", "org": "Shop, Co", "email": "ana@example.com"},
                   "event": {"title": "Summer market", "start": "2026-12-01 18:30", "place": "Town square"},
                   "place": {"latitude": "52.37", "longitude": "4.89"},
                   "email": {"to": "shop@example.com", "subject": "Hello there"},
                   "phone": {"number": "+1 555 0100"},
                   "text": {"number": "5550100", "message": "Table for two"}}
        for kind in payloads.BUILDERS:
            # level M, the smallest version that fits, the best of the eight masks (-1)
            made = built(kind, **samples[kind])
            matrix = qr_codec.encode_text(made["text"], "M", 1, -1)["value"]
            reading = qr_codec.decode_image(qr_codec.picture_image(matrix, 4, "#3366cc"))
            self.assertTrue(reading["ok"], kind + ": " + reading["error"])
            self.assertEqual(reading["value"]["text"], made["text"], kind)
            self.assertEqual(payloads.kind_of(made["text"]), kind)

    def test_every_kind_has_a_title_and_a_form(self):
        """The form offers "link" first, every kind has a title and fields, and "link" has no builder."""
        self.assertEqual(payloads.KINDS[0], "link")
        for kind in payloads.KINDS:
            self.assertIn(kind, payloads.TITLES)
            self.assertIn(kind, payloads.FIELDS)
        self.assertFalse(payloads.build("link", {})["ok"])


class MaskingTests(unittest.TestCase):
    """stored_form and is_masked: what the registry may keep of a Wi-Fi text."""

    def test_the_password_is_replaced_whatever_it_holds(self):
        """The P: field becomes ******** wherever it sits and whatever escapes it holds; a lowercase "wifi:"
        prefix still counts. A URL that merely contains "P:" and an open network are kept unchanged."""
        self.assertEqual(payloads.stored_form("WIFI:T:WPA;S:Cafe;P:secret;;"), ("WIFI:T:WPA;S:Cafe;P:********;;", True))
        self.assertEqual(payloads.stored_form('WIFI:S:Cafe;P:a\\;b\\\\;T:WPA;;'), ("WIFI:S:Cafe;P:********;T:WPA;;", True))
        self.assertEqual(payloads.stored_form("wifi:P:x;S:Cafe;;")[1], True)
        self.assertEqual(payloads.stored_form("https://example.com/P:x;"), ("https://example.com/P:x;", False))
        self.assertEqual(payloads.stored_form("WIFI:T:nopass;S:Cafe;;"), ("WIFI:T:nopass;S:Cafe;;", False))

    def test_the_mask_says_nothing_about_the_password(self):
        """A 1-character and a 40-character password store the same text, so the mask leaks no length;
        is_masked tells stored text from real text."""
        short = built("wifi", ssid="Cafe", password="a")
        long = built("wifi", ssid="Cafe", password="a" * 40)
        self.assertEqual(short["stored"], long["stored"])
        self.assertTrue(short["masked"])
        self.assertNotIn("a;", short["stored"].split("P:")[1])
        self.assertTrue(payloads.is_masked(short["stored"]))
        self.assertFalse(payloads.is_masked(short["text"]))
        self.assertFalse(payloads.is_masked("https://example.com/"))

    def test_a_file_name_never_holds_the_password(self):
        """The payload's name part and making.suggested_name both leave the password out."""
        made = built("wifi", ssid="Cafe", password="hunter2")
        self.assertEqual(made["name"], "wifi-Cafe")
        self.assertNotIn("hunter2", making.suggested_name(made["text"], "#3366cc", "png"))


class StoringTests(unittest.TestCase):
    """Wi-Fi codes made, listed and registered in a real registry in a temporary folder.

    "hunter2" is the password; the tests search raw file bytes for it, so it would show in any column
    or index that held it."""

    def setUp(self):
        """A temporary folder, a registry path in it (made on first use) and a built Wi-Fi payload."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_payloads_")
        self.db = os.path.join(self.folder, "palette.db")
        self.wifi = built("wifi", ssid="Cafe", password="hunter2")

    def tearDown(self):
        """Remove the folder, registry and key file with it."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def make(self, name="wifi.png", text=None, built_text=True):
        """Make and register a #3366cc level-M code of `text` (the Wi-Fi payload by default) -> Made.

        built_text False makes it as if the text were typed as a link rather than built by the form;
        the scale is 4 pixels per module, with no short link and no logo."""
        made = making.make_qr(self.db, text or self.wifi["text"], "#3366cc", "M", os.path.join(self.folder, name), 4,
                              None, None, built_text)
        self.assertTrue(made["ok"], made["error"])
        return made["value"]

    def registry_bytes(self):
        """The registry file's raw bytes."""
        handle = open(self.db, "rb")
        data = handle.read()
        handle.close()
        return data

    def test_the_password_is_not_in_the_registry(self):
        """The record keeps the masked text, the picture still holds the real one, and search shows the mask."""
        made = self.make()
        self.assertEqual(made["link"], self.wifi["stored"])
        self.assertNotIn(b"hunter2", self.registry_bytes())
        self.assertEqual(qr_codec.read_qr_file(made["path"])["value"]["reading"]["text"], self.wifi["text"])
        rows = finding.search(self.db, "qr_code", "Cafe", False, 20)["value"]
        self.assertEqual(rows[0]["link"], self.wifi["stored"])

    def test_typed_listed_and_registered_passwords_are_masked_too(self):
        """The password is masked however the text arrives: typed as a link, from a picture made elsewhere,
        or in a batch list, whose report and file names leave it out too."""
        self.make("typed.png", self.wifi["text"], False)
        path = os.path.join(self.folder, "elsewhere.png")
        matrix = qr_codec.encode_text(self.wifi["text"], "M", 1, -1)["value"]
        self.assertTrue(qr_codec.save_matrix(matrix, path, 4, "#000000")["ok"])
        self.assertTrue(making.register_picture(self.db, path, "#000000")["ok"])
        # one BatchRow; png, level M, scale 4, no section, no snapping, no watcher, report named "T"
        run = batches.make_batch(self.db, [{"row": 2, "link": self.wifi["text"], "color": "#006633", "label": "",
                                            "file": "", "problem": ""}], os.path.join(self.folder, "run"), "png", "M",
                                 4, "", False, None, "T")
        self.assertEqual(run["value"]["made"], 1)
        self.assertNotIn(b"hunter2", self.registry_bytes())
        handle = open(run["value"]["report"], "rb")
        report = handle.read()
        handle.close()
        self.assertNotIn(b"hunter2", report)
        self.assertNotIn("hunter2", os.path.basename(run["value"]["rows"][0]["path"]))

    def test_a_scanned_code_finds_its_record(self):
        """A scan of the real text finds the record by its keyed tag; another password finds nothing; the
        masked text itself still matches the stored link."""
        made = self.make()
        found = finding.matches_for_text(self.db, self.wifi["text"], "")["value"]
        self.assertEqual([row["id"] for row in found], [made["id"]])
        other = built("wifi", ssid="Cafe", password="another")
        self.assertEqual(finding.matches_for_text(self.db, other["text"], "")["value"], [])
        self.assertEqual(finding.matches_for_text(self.db, self.wifi["stored"], "")["value"][0]["id"], made["id"])

    def test_two_passwords_for_one_network_stay_two_codes(self):
        """Two passwords mask to the same stored text, yet the tags keep them two records, each found by its own."""
        self.make("one.png")
        second = built("wifi", ssid="Cafe", password="another")
        self.make("two.png", second["text"])
        self.assertEqual(len(finding.matches_for_text(self.db, self.wifi["text"], "")["value"]), 1)
        self.assertEqual(len(finding.matches_for_text(self.db, second["text"], "")["value"]), 1)

    def test_without_the_key_a_masked_code_is_not_found_and_nothing_breaks(self):
        """With the key file gone, a scan cannot match the masked record, but searching by name still works."""
        self.make()
        os.remove(localkey.key_path(self.db))
        self.assertEqual(finding.matches_for_text(self.db, self.wifi["text"], "")["value"], [])
        self.assertEqual(len(finding.search(self.db, "qr_code", "Cafe", False, 20)["value"]), 1)

    def test_exports_and_backups_never_hold_the_password(self):
        """CSV and JSON exports hold the mask, not the password; a backup copy holds no password either."""
        self.make()
        for name in ("all.csv", "all.json"):
            path = os.path.join(self.folder, name)
            self.assertTrue(registry_export.export_registry(self.db, path)["ok"])
            handle = open(path, "rb")
            data = handle.read()
            handle.close()
            self.assertNotIn(b"hunter2", data)
            self.assertIn(b"********", data)
        copy = os.path.join(self.folder, "copy.db")
        self.assertTrue(registry.backup(self.db, copy)["ok"])
        handle = open(copy, "rb")
        self.assertNotIn(b"hunter2", handle.read())
        handle.close()

    def test_redraw_refuses_what_the_registry_cannot_draw(self):
        """Redrawing a masked record in a new color is refused (the registry lacks the password) and the
        picture keeps its old color."""
        made = self.make()
        refused = making.redraw_record(self.db, made["id"], "#006633", 4)
        self.assertFalse(refused["ok"])
        self.assertIn("does not keep", refused["error"])
        self.assertEqual(qr_codec.read_qr_file(made["path"])["value"]["color"], "#3366cc")

    def test_a_sheet_reads_the_real_text_from_the_picture(self):
        """A print sheet takes a masked code's real text from its picture; with the picture gone the code is
        skipped with the reason."""
        made = self.make()
        found = sheets.codes_from_registry(self.db, [made["id"]])
        self.assertEqual(found["value"]["skipped"], [])
        text = qr_codec.decode_matrix(found["value"]["codes"][0]["matrix"]["dark"])["value"]["text"]
        self.assertEqual(text, self.wifi["text"])
        os.remove(made["path"])
        found = sheets.codes_from_registry(self.db, [made["id"]])
        self.assertEqual(found["value"]["codes"], [])
        self.assertIn("does not keep", found["value"]["skipped"][0])

    def test_line_ends_reach_the_code_exactly(self):
        """A built vCard keeps its CRLF line ends through making, reading and the registry, and is found again.

        Text typed by hand is cleaned of CRs, so a built payload must skip that cleaning."""
        contact = built("contact", first="Ana")
        made = self.make("ana.png", contact["text"])
        reading = qr_codec.read_qr_file(made["path"])["value"]["reading"]
        self.assertEqual(reading["text"], contact["text"])
        self.assertIn("\r\n", reading["text"])
        self.assertEqual(made["link"], contact["text"])
        self.assertEqual(len(finding.matches_for_text(self.db, contact["text"], "")["value"]), 1)


class KeyTests(unittest.TestCase):
    """localkey: the key file beside the registry and the HMAC tags made with it."""

    def setUp(self):
        """A temporary folder with a registry path in it; neither the registry nor the key exist yet."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_key_")
        self.db = os.path.join(self.folder, "palette.db")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_key_is_made_once_beside_the_registry(self):
        """No key at first; key_for makes KEY_BYTES (32) random bytes in the registry's folder and later
        calls return the same key."""
        self.assertIsNone(localkey.read_key(localkey.key_path(self.db)))
        first = localkey.key_for(self.db)
        self.assertTrue(first["ok"], first["error"])
        self.assertEqual(len(first["value"]), localkey.KEY_BYTES)
        self.assertEqual(os.path.dirname(localkey.key_path(self.db)), self.folder)
        self.assertEqual(localkey.key_for(self.db)["value"], first["value"])

    def test_a_file_that_is_not_a_key_is_never_overwritten(self):
        """A file at the key's path that holds no key is refused and left exactly as it was."""
        path = localkey.key_path(self.db)
        handle = open(path, "w", encoding="utf-8")
        handle.write("notes")
        handle.close()
        refused = localkey.key_for(self.db)
        self.assertFalse(refused["ok"])
        self.assertIn("does not hold a key", refused["error"])
        handle = open(path, encoding="utf-8")
        self.assertEqual(handle.read(), "notes")
        handle.close()

    def test_tags_differ_by_purpose_key_and_text(self):
        """A tag is 64 hex digits (SHA-256), the same for the same inputs, and changes with any of purpose,
        key or text, so a tag made for one purpose never matches another."""
        key = b"k" * 32
        tag = localkey.tag(key, "payload", "text")
        self.assertEqual(len(tag), 64)
        self.assertEqual(localkey.tag(key, "payload", "text"), tag)
        self.assertNotEqual(localkey.tag(key, "id", "text"), tag)
        self.assertNotEqual(localkey.tag(b"j" * 32, "payload", "text"), tag)
        self.assertNotEqual(localkey.tag(key, "payload", "other"), tag)

    def test_the_key_is_not_in_the_registry(self):
        """The registry holds the payload tag but never the key itself (searched for in hex, the form the key
        file keeps it in); also checks in
        passing that registry.is_day accepts a real day."""
        made = making.make_qr(self.db, "WIFI:T:WPA;S:Cafe;P:hunter2;;", "#3366cc", "M",
                              os.path.join(self.folder, "a.png"), 4)
        self.assertTrue(made["ok"], made["error"])
        key = localkey.read_key(localkey.key_path(self.db))
        handle = open(self.db, "rb")
        data = handle.read()
        handle.close()
        self.assertNotIn(key.hex().encode("ascii"), data)
        connection = sqlite3.connect(self.db)
        stored = connection.execute("SELECT payload_hash FROM qr_codes").fetchone()[0]
        connection.close()
        self.assertEqual(stored, localkey.tag(key, "payload", "WIFI:T:WPA;S:Cafe;P:hunter2;;"))
        self.assertTrue(registry.is_day("2026-12-01"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=c4e2f67f846ec47eca402273de652987081db5bb2e136134850408ca10fb427b ====
