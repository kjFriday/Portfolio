# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_settings.py
# About: Tests for settings.json: defaults, value checks, hand edits kept, broken files left alone.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for settings.json: defaults, value checks, hand edits kept, broken files left alone.

settings.py reads settings.json into a record whose "values" always hold every setting: what is left
out takes its default quietly, what is wrong takes its default with a warning. save() writes changed
settings into the file's own data, so keys typed by hand survive, and never overwrites a file that is
not valid JSON. Each test works on settings.json in a fresh temporary folder.

What the classes pin:
  1. DefaultTests: a missing file means the defaults; settings.example.json matches DEFAULTS; SPEC
     has a rule for every setting.
  2. CheckingTests: good values are used and paths expanded; bad ones keep their defaults with one
     warning each.
  3. SavingTests: broken files are kept, hand edits stay, the first save writes every setting.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import json
import os
import shutil
import tempfile
import unittest

import settings

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/


def write(path, text):
    """Write `text` to `path` as UTF-8, replacing the file."""
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()


def read(path):
    """The whole text of a UTF-8 file."""
    handle = open(path, encoding="utf-8")
    text = handle.read()
    handle.close()
    return text


class SettingsCase(unittest.TestCase):
    """A settings.json path in a fresh temporary folder; the file itself does not exist yet."""

    def setUp(self):
        """Make the folder and name the settings file in it."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_settings_")
        self.path = os.path.join(self.folder, "settings.json")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def load_with(self, data):
        """Write `data` as the settings file and load it -> the Settings record."""
        write(self.path, json.dumps(data))
        return settings.load(self.path)


class DefaultTests(SettingsCase):
    """The defaults, the example file and SPEC agree."""

    def test_a_missing_file_means_the_defaults(self):
        """No file: state "missing", the defaults, no warnings, and load() creates nothing."""
        state = settings.load(self.path)
        self.assertEqual(state["state"], "missing")
        self.assertEqual(state["values"], settings.DEFAULTS)
        self.assertEqual(state["warnings"], [])
        self.assertFalse(os.path.exists(self.path))

    def test_the_example_file_shows_the_defaults(self):
        """settings.example.json beside the program is exactly example_text(), and parses back to DEFAULTS."""
        self.assertEqual(read(os.path.join(HERE, "settings.example.json")), settings.example_text())
        self.assertEqual(json.loads(settings.example_text()), settings.DEFAULTS)

    def test_every_setting_has_a_rule_and_every_section_says_what_it_is(self):
        """Every default has a SPEC rule under its (section, key), and every section has an "about" text.

        Top-level settings are named in SPEC with "" as their section; "about" itself is text, not a
        setting."""
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
    """load() takes what is usable and replaces what is not."""

    def test_good_values_are_used(self):
        """Valid values are used as given; %VARIABLE% and ~ in path settings are expanded; settings left out keep their defaults.

        QR_PALETTE_TEST_FOLDER is set for this test alone and removed again, so the expansion has a
        known value."""
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
        """Ten unusable values give ten warnings and leave every default in place.

        One each: a pixel scale of 0, level Z, contrast as text, a near distance above 1, a preset
        name with a space and capitals, a negative timeout, a fraction of tokens, a URL that is a
        number, a bool as a limit (refused although Python counts True as 1), and a whole section
        ("protocol") that is not an object. The first warning is checked word for word."""
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
        """A default_limit above max_limit is held to max_limit, with one warning."""
        state = self.load_with({"queries": {"default_limit": 300, "max_limit": 100}})
        self.assertEqual(state["values"]["queries"]["default_limit"], 100)
        self.assertEqual(len(state["warnings"]), 1)


class SavingTests(SettingsCase):
    """save() and write_defaults()."""

    def test_a_broken_file_is_never_overwritten(self):
        """A file that is not valid JSON (a trailing comma, a missing brace) loads as "broken", and save refuses to touch it."""
        write(self.path, '{"colors": {"preset": "popular",}')
        state = settings.load(self.path)
        self.assertEqual(state["state"], "broken")
        self.assertEqual(state["values"], settings.DEFAULTS)
        self.assertIn("not valid JSON", state["warnings"][0])
        self.assertFalse(settings.save(state, [("colors", "preset", "mixer")])["ok"])
        self.assertEqual(read(self.path), '{"colors": {"preset": "popular",}')

    def test_saving_keeps_what_was_written_by_hand(self):
        """Saving one setting keeps keys typed by hand, writes indented JSON ending in a newline, and leaves no .tmp file.

        Only the changed setting is added to the file: colors holds just "preset", while the loaded
        values hold every setting."""
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
        """With no file yet, a save writes the whole example with the one change, and the state becomes "ok"."""
        state = settings.load(self.path)
        self.assertTrue(settings.save(state, [("inference", "model", "qwen2.5:7b-instruct")])["ok"])
        saved = json.loads(read(self.path))
        expected = json.loads(settings.example_text())
        expected["inference"]["model"] = "qwen2.5:7b-instruct"
        self.assertEqual(saved, expected)
        self.assertEqual(state["state"], "ok")

    def test_defaults_are_written_once(self):
        """write_defaults writes a missing file, but leaves a file that already exists exactly as it is."""
        state = settings.load(self.path)
        self.assertTrue(settings.write_defaults(state)["ok"])
        write(self.path, '{"colors": {"preset": "discover"}}')
        again = settings.load(self.path)
        self.assertTrue(settings.write_defaults(again)["ok"])
        self.assertEqual(read(self.path), '{"colors": {"preset": "discover"}}')


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=b82cd682b522a4560dcc06fab23401536d6c0b2b784d881690e427820189f0fb ====
