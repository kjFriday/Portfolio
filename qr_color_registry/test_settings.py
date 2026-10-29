# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_settings.py
# About: Tests for settings: defaults, checking every value, keeping hand edits, and never...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for settings: defaults, checking every value, keeping hand edits, and never overwriting a broken file."""

import json
import os
import shutil
import tempfile
import unittest

import settings

HERE = os.path.dirname(os.path.abspath(__file__))


def write(path, text):
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()


def read(path):
    handle = open(path, encoding="utf-8")
    text = handle.read()
    handle.close()
    return text


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_settings_")
        self.path = os.path.join(self.folder, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def load_with(self, data):
        write(self.path, json.dumps(data))
        return settings.load(self.path)


class DefaultTests(SettingsCase):
    def test_a_missing_file_means_the_defaults(self):
        state = settings.load(self.path)
        self.assertEqual(state["state"], "missing")
        self.assertEqual(state["values"], settings.DEFAULTS)
        self.assertEqual(state["warnings"], [])
        self.assertFalse(os.path.exists(self.path))

    def test_the_example_file_shows_the_defaults(self):
        self.assertEqual(read(os.path.join(HERE, "settings.example.json")), settings.example_text())
        self.assertEqual(json.loads(settings.example_text()), settings.DEFAULTS)

    def test_every_setting_has_a_rule_and_every_section_says_what_it_is(self):
        named = []
        for entry in settings.SPEC:
            named.append((entry[0], entry[1]))
        for key in settings.DEFAULTS:
            if isinstance(settings.DEFAULTS[key], dict):
                self.assertIn("about", settings.DEFAULTS[key], key)
                for inner in settings.DEFAULTS[key]:
                    if inner != "about":
                        self.assertIn((key, inner), named)
            elif key != "about":
                self.assertIn(("", key), named)


class CheckingTests(SettingsCase):
    def test_good_values_are_used(self):
        os.environ["QR_PALETTE_TEST_FOLDER"] = self.folder
        try:
            state = self.load_with({"pictures": {"folder": "%QR_PALETTE_TEST_FOLDER%\\codes", "pixels_per_module": 12,
                                                 "error_correction": "H"},
                                    "colors": {"preset": "popular", "minimum_contrast": 4.5},
                                    "inference": {"timeout_seconds": 60, "model": "qwen2.5:7b-instruct"},
                                    "registry": "~/palette.db"})
        finally:
            del os.environ["QR_PALETTE_TEST_FOLDER"]
        values = state["values"]
        self.assertEqual(state["warnings"], [])
        self.assertEqual(values["pictures"]["folder"], os.path.normpath(os.path.join(self.folder, "codes")))
        self.assertEqual(values["pictures"]["pixels_per_module"], 12)
        self.assertEqual(values["colors"]["minimum_contrast"], 4.5)
        self.assertEqual(values["colors"]["near_distance"], 0.08)  # left out: its default
        self.assertEqual(values["inference"]["model"], "qwen2.5:7b-instruct")
        self.assertEqual(values["registry"], os.path.normpath(os.path.join(os.path.expanduser("~"), "palette.db")))

    def test_values_that_cannot_be_used_keep_their_defaults(self):
        state = self.load_with({"pictures": {"pixels_per_module": 0, "error_correction": "Z"},
                                "colors": {"minimum_contrast": "high", "near_distance": 2, "preset": "Bad Name"},
                                "inference": {"timeout_seconds": -1, "max_answer_tokens": 3.5, "url": 5},
                                "queries": {"default_limit": True}, "protocol": "big"})
        values = state["values"]
        self.assertEqual(values["pictures"], settings.DEFAULTS["pictures"])
        self.assertEqual(values["colors"], settings.DEFAULTS["colors"])
        self.assertEqual(values["inference"], settings.DEFAULTS["inference"])
        self.assertEqual(values["queries"]["default_limit"], 20)
        self.assertEqual(len(state["warnings"]), 10)
        self.assertIn("pictures.pixels_per_module must be a whole number from 1 to 40; using 8", state["warnings"][0])

    def test_the_default_limit_stays_under_the_most(self):
        state = self.load_with({"queries": {"default_limit": 300, "max_limit": 100}})
        self.assertEqual(state["values"]["queries"]["default_limit"], 100)
        self.assertEqual(len(state["warnings"]), 1)


class SavingTests(SettingsCase):
    def test_a_broken_file_is_never_overwritten(self):
        write(self.path, '{"colors": {"preset": "popular",}')
        state = settings.load(self.path)
        self.assertEqual(state["state"], "broken")
        self.assertEqual(state["values"], settings.DEFAULTS)
        self.assertIn("not valid JSON", state["warnings"][0])
        self.assertFalse(settings.save(state, [("colors", "preset", "mixer")])["ok"])
        self.assertEqual(read(self.path), '{"colors": {"preset": "popular",}')

    def test_saving_keeps_what_was_written_by_hand(self):
        state = self.load_with({"my_note": "keep me", "pictures": {"folder": "D:\\Codes", "extra": 1}})
        self.assertTrue(settings.save(state, [("colors", "preset", "popular")])["ok"])
        text = read(self.path)
        saved = json.loads(text)
        self.assertEqual(saved["my_note"], "keep me")
        self.assertEqual(saved["pictures"], {"folder": "D:\\Codes", "extra": 1})
        self.assertEqual(saved["colors"], {"preset": "popular"})
        self.assertIn('\n  "pictures": {\n    "folder"', text)  # indented, one setting per line
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(state["values"]["colors"]["preset"], "popular")
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_the_first_save_writes_every_setting(self):
        state = settings.load(self.path)
        self.assertTrue(settings.save(state, [("inference", "model", "qwen2.5:7b-instruct")])["ok"])
        saved = json.loads(read(self.path))
        expected = json.loads(settings.example_text())
        expected["inference"]["model"] = "qwen2.5:7b-instruct"
        self.assertEqual(saved, expected)
        self.assertEqual(state["state"], "ok")

    def test_defaults_are_written_once(self):
        state = settings.load(self.path)
        self.assertTrue(settings.write_defaults(state)["ok"])
        write(self.path, '{"colors": {"preset": "discover"}}')
        again = settings.load(self.path)
        self.assertTrue(settings.write_defaults(again)["ok"])
        self.assertEqual(read(self.path), '{"colors": {"preset": "discover"}}')


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=eb03c6d92265c776d59c359124fa4d9f81cb1f0a3f448edf55ca4c665f37d3ad ====
