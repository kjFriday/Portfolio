# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_payloads.py
# About: Tests for the code kinds and the local key: escaping, what each payload looks like...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the code kinds and the local key: escaping, what each payload looks like, reading each back from
a real code, masking a Wi-Fi password however it arrives, and that the key stays out of the registry."""

import os
import shutil
import sqlite3
import tempfile
import unittest

import localkey
import payloads
import qr_codec
import qr_palette
import registry
import sheets


def built(kind, **fields):
    made = payloads.build(kind, fields)
    if not made["ok"]:
        raise AssertionError(made["error"])
    return made["value"]


class EscapingTests(unittest.TestCase):
    def test_wifi_escapes_its_five_characters(self):
        self.assertEqual(payloads.wifi_escape('a\\b;c,d:e"f'), 'a\\\\b\\;c\\,d\\:e\\"f')
        made = built("wifi", ssid='Café; "main"', password="p:a,s;s\\")
        self.assertEqual(made["text"], 'WIFI:T:WPA;S:Café\\; \\"main\\";P:p\\:a\\,s\\;s\\\\;;')

    def test_vcard_and_icalendar_text(self):
        self.assertEqual(payloads.text_escape("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")
        made = built("contact", first="Ana", last="Silva, Jr", org="Shop; Co")
        self.assertIn("N:Silva\\, Jr;Ana;;;\r\n", made["text"])
        self.assertIn("ORG:Shop\\; Co\r\n", made["text"])

    def test_long_lines_fold_inside_characters_never(self):
        line = "SUMMARY:" + "é" * 80
        folded = payloads.fold(line)
        parts = folded.split("\r\n")
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part.encode("utf-8")), payloads.FOLD_AT)
        for part in parts[1:]:
            self.assertTrue(part.startswith(" "))
        self.assertEqual(parts[0] + "".join(part[1:] for part in parts[1:]), line)
        self.assertEqual(payloads.fold("short"), "short")


class KindTests(unittest.TestCase):
    def test_wifi(self):
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
        self.assertEqual(built("place", latitude="52.37", longitude="-4,89")["text"], "geo:52.37,-4.89")
        self.assertFalse(payloads.build("place", {"latitude": "91", "longitude": "0"})["ok"])
        self.assertFalse(payloads.build("place", {"latitude": "north", "longitude": "0"})["ok"])
        self.assertEqual(built("email", to="shop@example.com", subject="Hello there", body="Line one\nA&B")["text"],
                         "mailto:shop@example.com?subject=Hello%20there&body=Line%20one%0D%0AA%26B")
        self.assertEqual(built("email", to="shop@example.com")["text"], "mailto:shop@example.com")
        self.assertFalse(payloads.build("email", {"to": "not an address"})["ok"])
        self.assertEqual(built("phone", number="+1 555-0100")["text"], "tel:+15550100")
        self.assertFalse(payloads.build("phone", {"number": "12"})["ok"])
        self.assertEqual(built("text", number="555 0100", message="Table: 4")["text"], "SMSTO:5550100:Table: 4")

    def test_hidden_characters_are_cleaned_from_fields(self):
        made = built("contact", first="An" + chr(0x202E) + "a" + chr(7))
        self.assertIn("FN:Ana\r\n", made["text"])

    def test_every_kind_reads_back_from_a_real_code(self):
        samples = {"wifi": {"ssid": "Café; main", "password": "p:a,s;s\\w\"rd"},
                   "contact": {"first": "Ana", "last": "Silva", "org": "Shop, Co", "email": "ana@example.com"},
                   "event": {"title": "Summer market", "start": "2026-12-01 18:30", "place": "Town square"},
                   "place": {"latitude": "52.37", "longitude": "4.89"},
                   "email": {"to": "shop@example.com", "subject": "Hello there"},
                   "phone": {"number": "+1 555 0100"},
                   "text": {"number": "5550100", "message": "Table for two"}}
        for kind in payloads.BUILDERS:
            made = built(kind, **samples[kind])
            matrix = qr_codec.encode_text(made["text"], "M", 1, -1)["value"]
            reading = qr_codec.decode_image(qr_codec.picture_image(matrix, 4, "#3366cc"))
            self.assertTrue(reading["ok"], kind + ": " + reading["error"])
            self.assertEqual(reading["value"]["text"], made["text"], kind)
            self.assertEqual(payloads.kind_of(made["text"]), kind)

    def test_every_kind_has_a_title_and_a_form(self):
        self.assertEqual(payloads.KINDS[0], "link")
        for kind in payloads.KINDS:
            self.assertIn(kind, payloads.TITLES)
            self.assertIn(kind, payloads.FIELDS)
        self.assertFalse(payloads.build("link", {})["ok"])


class MaskingTests(unittest.TestCase):
    def test_the_password_is_replaced_whatever_it_holds(self):
        self.assertEqual(payloads.stored_form("WIFI:T:WPA;S:Cafe;P:secret;;"), ("WIFI:T:WPA;S:Cafe;P:********;;", True))
        self.assertEqual(payloads.stored_form('WIFI:S:Cafe;P:a\\;b\\\\;T:WPA;;'), ("WIFI:S:Cafe;P:********;T:WPA;;", True))
        self.assertEqual(payloads.stored_form("wifi:P:x;S:Cafe;;")[1], True)
        self.assertEqual(payloads.stored_form("https://example.com/P:x;"), ("https://example.com/P:x;", False))
        self.assertEqual(payloads.stored_form("WIFI:T:nopass;S:Cafe;;"), ("WIFI:T:nopass;S:Cafe;;", False))

    def test_the_mask_says_nothing_about_the_password(self):
        short = built("wifi", ssid="Cafe", password="a")
        long = built("wifi", ssid="Cafe", password="a" * 40)
        self.assertEqual(short["stored"], long["stored"])
        self.assertTrue(short["masked"])
        self.assertNotIn("a;", short["stored"].split("P:")[1])
        self.assertTrue(payloads.is_masked(short["stored"]))
        self.assertFalse(payloads.is_masked(short["text"]))
        self.assertFalse(payloads.is_masked("https://example.com/"))

    def test_a_file_name_never_holds_the_password(self):
        made = built("wifi", ssid="Cafe", password="hunter2")
        self.assertEqual(made["name"], "wifi-Cafe")
        self.assertNotIn("hunter2", qr_palette.suggested_name(made["text"], "#3366cc", "png"))


class StoringTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_payloads_")
        self.db = os.path.join(self.folder, "palette.db")
        self.wifi = built("wifi", ssid="Cafe", password="hunter2")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def make(self, name="wifi.png", text=None, built_text=True):
        made = qr_palette.make_qr(self.db, text or self.wifi["text"], "#3366cc", "M", os.path.join(self.folder, name), 4,
                                  None, None, built_text)
        self.assertTrue(made["ok"], made["error"])
        return made["value"]

    def registry_bytes(self):
        handle = open(self.db, "rb")
        data = handle.read()
        handle.close()
        return data

    def test_the_password_is_not_in_the_registry(self):
        made = self.make()
        self.assertEqual(made["link"], self.wifi["stored"])
        self.assertNotIn(b"hunter2", self.registry_bytes())
        self.assertEqual(qr_codec.read_qr_file(made["path"])["value"]["reading"]["text"], self.wifi["text"])
        rows = qr_palette.search(self.db, "qr_code", "Cafe", False, 20)["value"]
        self.assertEqual(rows[0]["link"], self.wifi["stored"])

    def test_typed_listed_and_registered_passwords_are_masked_too(self):
        self.make("typed.png", self.wifi["text"], False)
        path = os.path.join(self.folder, "elsewhere.png")
        matrix = qr_codec.encode_text(self.wifi["text"], "M", 1, -1)["value"]
        self.assertTrue(qr_codec.save_matrix(matrix, path, 4, "#000000")["ok"])
        self.assertTrue(qr_palette.register_picture(self.db, path, "#000000")["ok"])
        run = qr_palette.make_batch(self.db, [{"row": 2, "link": self.wifi["text"], "color": "#006633", "label": "",
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
        made = self.make()
        found = qr_palette.matches_for_text(self.db, self.wifi["text"], "")["value"]
        self.assertEqual([row["id"] for row in found], [made["id"]])
        other = built("wifi", ssid="Cafe", password="another")
        self.assertEqual(qr_palette.matches_for_text(self.db, other["text"], "")["value"], [])
        self.assertEqual(qr_palette.matches_for_text(self.db, self.wifi["stored"], "")["value"][0]["id"], made["id"])

    def test_two_passwords_for_one_network_stay_two_codes(self):
        self.make("one.png")
        second = built("wifi", ssid="Cafe", password="another")
        self.make("two.png", second["text"])
        self.assertEqual(len(qr_palette.matches_for_text(self.db, self.wifi["text"], "")["value"]), 1)
        self.assertEqual(len(qr_palette.matches_for_text(self.db, second["text"], "")["value"]), 1)

    def test_without_the_key_a_masked_code_is_not_found_and_nothing_breaks(self):
        self.make()
        os.remove(localkey.key_path(self.db))
        self.assertEqual(qr_palette.matches_for_text(self.db, self.wifi["text"], "")["value"], [])
        self.assertEqual(len(qr_palette.search(self.db, "qr_code", "Cafe", False, 20)["value"]), 1)

    def test_exports_and_backups_never_hold_the_password(self):
        self.make()
        for name in ("all.csv", "all.json"):
            path = os.path.join(self.folder, name)
            self.assertTrue(qr_palette.export_registry(self.db, path)["ok"])
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
        made = self.make()
        refused = qr_palette.redraw_record(self.db, made["id"], "#006633", 4)
        self.assertFalse(refused["ok"])
        self.assertIn("does not keep", refused["error"])
        self.assertEqual(qr_codec.read_qr_file(made["path"])["value"]["color"], "#3366cc")

    def test_a_sheet_reads_the_real_text_from_the_picture(self):
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
        contact = built("contact", first="Ana")
        made = self.make("ana.png", contact["text"])
        reading = qr_codec.read_qr_file(made["path"])["value"]["reading"]
        self.assertEqual(reading["text"], contact["text"])
        self.assertIn("\r\n", reading["text"])
        self.assertEqual(made["link"], contact["text"])
        self.assertEqual(len(qr_palette.matches_for_text(self.db, contact["text"], "")["value"]), 1)


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_key_")
        self.db = os.path.join(self.folder, "palette.db")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_key_is_made_once_beside_the_registry(self):
        self.assertIsNone(localkey.read_key(localkey.key_path(self.db)))
        first = localkey.key_for(self.db)
        self.assertTrue(first["ok"], first["error"])
        self.assertEqual(len(first["value"]), localkey.KEY_BYTES)
        self.assertEqual(os.path.dirname(localkey.key_path(self.db)), self.folder)
        self.assertEqual(localkey.key_for(self.db)["value"], first["value"])

    def test_a_file_that_is_not_a_key_is_never_overwritten(self):
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
        key = b"k" * 32
        tag = localkey.tag(key, "payload", "text")
        self.assertEqual(len(tag), 64)
        self.assertEqual(localkey.tag(key, "payload", "text"), tag)
        self.assertNotEqual(localkey.tag(key, "id", "text"), tag)
        self.assertNotEqual(localkey.tag(b"j" * 32, "payload", "text"), tag)
        self.assertNotEqual(localkey.tag(key, "payload", "other"), tag)

    def test_the_key_is_not_in_the_registry(self):
        made = qr_palette.make_qr(self.db, "WIFI:T:WPA;S:Cafe;P:hunter2;;", "#3366cc", "M",
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=ac59424ddf38f7190f1683829c278631cd7536840511244f89b407dac42486fd ====
