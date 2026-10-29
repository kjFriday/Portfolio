# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_swatch.py
# About: Tests for swatch and ranking: the cube, names and families, contrast, and the JSON...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for swatch and ranking: the cube, names and families, contrast, and the JSON presets and weights."""

import json
import os
import shutil
import tempfile
import unittest

import ranking
import swatch

HERE = os.path.dirname(os.path.abspath(__file__))
COLOR_VOATS = os.path.join(HERE, "..", "color_tile_recommender")

# Color Voats' voats-sample.json, oldest first (two colors are upvoated twice).
SAMPLE = [{"color": "#3366cc", "voat": 1}, {"color": "#3399cc", "voat": 1}, {"color": "#33cccc", "voat": 1},
          {"color": "#996633", "voat": -1}, {"color": "#cc9966", "voat": -1}, {"color": "#3366cc", "voat": 1},
          {"color": "#6600ff", "voat": 1}, {"color": "#3399cc", "voat": 1}]

# Top tens worked out with Color Voats' own rankers.
NO_VOTES_TOP = "#000000 #ffffff #6600ff #009900 #ff3366 #660000 #66ff00 #000066 #9999ff #ff00ff"
SAMPLE_TOP = {
    "mixer": "#3399cc #3366cc #6600ff #33cccc #0099cc #0066cc #6699cc #6666cc #3366ff #0099ff",
    "balanced": "#3399cc #3366cc #0099cc #0066cc #6699cc #6666cc #000000 #3366ff #0099ff #3399ff",
    "popular": "#3366cc #3399cc #6600ff #33cccc #000000 #ffffff #009900 #ff3366 #660000 #66ff00",
    "discover": "#000000 #000033 #330000 #330033 #ff33ff #ff00cc #000066 #ff00ff #003300 #ffff00",
}

# Names Color Voats 0.2.0 gives these colors.
NAMES = {"#ff0000": "Red", "#660000": "Dark red", "#ff9900": "Orange", "#996633": "Brown",
         "#663300": "Dark brown", "#ffff00": "Yellow", "#999900": "Yellow", "#666600": "Olive",
         "#009900": "Green", "#003300": "Dark green", "#009999": "Teal", "#006666": "Muted teal",
         "#0000ff": "Blue", "#000066": "Dark blue", "#9900ff": "Purple", "#660099": "Dark purple",
         "#ff66cc": "Pink", "#cc0066": "Red", "#000000": "Black", "#ffffff": "White", "#999999": "Grey",
         "#333333": "Dark grey", "#cccccc": "Light grey"}


def write_json(path, data):
    handle = open(path, "w", encoding="utf-8")
    handle.write(json.dumps(data, indent=2))
    handle.close()


def read_json(path):
    handle = open(path, encoding="utf-8")
    data = json.load(handle)
    handle.close()
    return data


class CubeTests(unittest.TestCase):
    def test_216_colors_from_black_to_white(self):
        colors = swatch.palette()
        self.assertEqual(len(colors), 216)
        self.assertEqual(len(set(colors)), 216)
        self.assertEqual(colors[0], "#000000")
        self.assertEqual(colors[200], "#ff9966")
        self.assertEqual(colors[215], "#ffffff")

    def test_cube_index_is_the_place_in_the_palette(self):
        colors = swatch.palette()
        for index in range(len(colors)):
            self.assertEqual(swatch.cube_index(colors[index]), index)
        self.assertEqual(swatch.cube_index("#123456"), -1)
        self.assertEqual(swatch.cube_index("#330001"), -1)

    def test_normalize_hex(self):
        self.assertEqual(swatch.normalize_hex("#3366CC"), "#3366cc")
        self.assertEqual(swatch.normalize_hex(" 3366cc "), "#3366cc")
        for bad in ("#3366c", "#3366ccc", "#zz66cc", "", None, 336699):
            self.assertEqual(swatch.normalize_hex(bad), "")

    def test_nearest_cube_color(self):
        self.assertEqual(swatch.nearest_cube("#3467cb"), "#3366cc")
        for color in swatch.palette():
            self.assertEqual(swatch.nearest_cube(color), color)
        self.assertTrue(swatch.is_near("#3366cc", "#3467cb"))
        self.assertFalse(swatch.is_near("#3366cc", "#cc6633"))


class ContrastTests(unittest.TestCase):
    def test_black_on_white_is_21_and_symmetric(self):
        self.assertAlmostEqual(swatch.contrast("#000000", "#ffffff"), 21.0, places=9)
        self.assertAlmostEqual(swatch.contrast("#ffffff", "#000000"), 21.0, places=9)
        self.assertAlmostEqual(swatch.contrast("#3366cc", "#3366cc"), 1.0, places=9)

    def test_118_cube_colors_are_usable(self):
        self.assertEqual(len(swatch.usable_colors()), 118)

    def test_the_line_is_compared_exactly(self):
        self.assertLess(swatch.contrast("#0099ff", swatch.WHITE), 3.0)  # 2.9998
        self.assertFalse(swatch.usable("#0099ff"))
        self.assertGreater(swatch.contrast("#6699cc", swatch.WHITE), 3.0)  # 3.003
        self.assertTrue(swatch.usable("#6699cc"))
        self.assertTrue(swatch.usable("#cc66ff"))
        self.assertFalse(swatch.usable("#ffff00"))
        self.assertFalse(swatch.usable(swatch.WHITE))

    def test_the_line_follows_the_setting(self):
        saved = swatch.MIN_CONTRAST
        try:
            swatch.MIN_CONTRAST = 4.5
            self.assertEqual(len(swatch.usable_colors()), 77)
        finally:
            swatch.MIN_CONTRAST = saved


class NameTests(unittest.TestCase):
    def test_names_match_color_voats(self):
        for color in NAMES:
            self.assertEqual(swatch.color_name(color), NAMES[color], color)

    def test_the_family_is_the_last_word(self):
        self.assertEqual(swatch.family("#006666"), "teal")
        self.assertEqual(swatch.family("#cccccc"), "grey")
        self.assertEqual(swatch.family("#663300"), "brown")
        for color in swatch.palette():
            self.assertIn(swatch.family(color), swatch.FAMILIES, color)

    def test_words_people_type(self):
        cases = {"blue": "blue", "Blues": "blue", "GRAY": "grey", "greys": "grey", "navy": "blue",
                 "cyan": "teal", "magenta": "pink", "violets": "purple", "chartreuse": "", "": "", "s": ""}
        for word in cases:
            self.assertEqual(swatch.family_of_word(word), cases[word], word)


class RankingTests(unittest.TestCase):
    def test_the_shipped_presets(self):
        self.assertEqual(swatch.presets(), ["balanced", "discover", "mixer", "popular"])
        for name in swatch.presets():
            preset = ranking.read_preset(swatch.RANKING_ROOT, name)
            self.assertTrue(preset["ok"], preset["error"])
            self.assertNotEqual(preset["value"]["about"], "")

    def test_every_preset_ranks_every_color_once(self):
        for name in swatch.presets():
            ranked = swatch.rank_colors(name, SAMPLE)
            self.assertTrue(ranked["ok"], ranked["error"])
            self.assertEqual(sorted(ranked["value"]), sorted(swatch.palette()))

    def test_no_votes_is_discovery_order(self):
        for name in swatch.presets():
            self.assertEqual(" ".join(swatch.rank_colors(name, [])["value"][:10]), NO_VOTES_TOP, name)

    def test_the_sample_matches_color_voats(self):
        for name in SAMPLE_TOP:
            self.assertEqual(" ".join(swatch.rank_colors(name, SAMPLE)["value"][:10]), SAMPLE_TOP[name], name)

    def test_unknown_presets(self):
        self.assertIn("missing presets/loudest.json", swatch.rank_colors("loudest", [])["error"])
        self.assertFalse(swatch.rank_colors("../algos", [])["ok"])

    def test_board_and_places(self):
        order = swatch.rank_colors("mixer", SAMPLE)["value"]
        board = swatch.usable_board(order)
        self.assertEqual(len(board), 118)
        self.assertEqual(board[0], "#3399cc")
        places = swatch.rank_places(order)
        self.assertEqual(places["#3399cc"], 1)
        self.assertEqual(places[order[215]], 216)

    def test_the_json_matches_color_voats_toml(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("reading TOML needs Python 3.11")
        if not os.path.isdir(COLOR_VOATS):
            self.skipTest("Color Voats is not next to this project")
        for folder in ("presets", "weights"):
            for name in sorted(os.listdir(os.path.join(HERE, folder))):
                mine = read_json(os.path.join(HERE, folder, name))
                del mine["about"]
                handle = open(os.path.join(COLOR_VOATS, folder, name[:-5] + ".toml"), "rb")
                theirs = tomllib.load(handle)
                handle.close()
                self.assertEqual(mine, theirs, folder + "/" + name)


class RankingFileTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="qr_palette_ranking_")
        shutil.copytree(os.path.join(HERE, "presets"), os.path.join(self.root, "presets"))
        shutil.copytree(os.path.join(HERE, "weights"), os.path.join(self.root, "weights"))
        self.saved = swatch.RANKING_ROOT
        swatch.RANKING_ROOT = self.root

    def tearDown(self):
        swatch.RANKING_ROOT = self.saved
        shutil.rmtree(self.root, ignore_errors=True)

    def change(self, folder, name, data):
        write_json(os.path.join(self.root, folder, name + ".json"), data)

    def reset(self):
        for folder in ("presets", "weights"):
            shutil.rmtree(os.path.join(self.root, folder), ignore_errors=True)
            shutil.copytree(os.path.join(HERE, folder), os.path.join(self.root, folder))

    def error(self, name):
        result = ranking.read_preset(self.root, name)
        self.assertFalse(result["ok"])
        return result["error"]

    def test_an_edit_applies_at_once(self):
        before = swatch.rank_colors("mixer", SAMPLE)["value"]
        self.change("weights", "net", {"about": "downvoats count ten times", "up": 1.0, "down": 10.0})
        self.change("presets", "mixer", {"algo": "net"})
        after = swatch.rank_colors("mixer", SAMPLE)["value"]
        self.assertNotEqual(before, after)
        self.assertEqual(sorted(after[214:]), ["#996633", "#cc9966"])  # the downvoated colors sink to the end
        self.assertEqual(ranking.read_preset(self.root, "mixer")["value"]["about"], "")

    def test_a_new_preset_is_found(self):
        self.change("presets", "only_wilson", {"about": "Wilson score alone", "algo": "wilson"})
        self.assertIn("only_wilson", swatch.presets())
        self.assertEqual(swatch.rank_colors("only_wilson", SAMPLE)["value"][0], "#3366cc")

    def test_mistakes_name_the_file_and_the_problem(self):
        cases = (
            ("weights", "net", {"up": 1.0}, "missing weight 'down'"),
            ("weights", "net", {"up": 1.0, "down": "x"}, "must be a number"),
            ("weights", "net", {"up": 1.0, "down": 1.0, "sideways": 2}, "unknown weight 'sideways'"),
            ("weights", "similar", {"reach": -1, "up": 1.0, "down": 1.0}, "must be above 0"),
            ("presets", "mixer", {"algo": "loudest"}, "unknown algo"),
            ("presets", "mixer", {"algo": "blend"}, "blend needs an object"),
            ("presets", "mixer", {"algo": "mixer", "uses": ["net", "net"]}, "listed twice"),
            ("presets", "mixer", {"algo": "wilson", "uses": ["net"]}, "only blend and mixer take uses"),
            ("presets", "mixer", {"algo": "mixer", "uses": ["net"], "colour": 1}, "unknown key 'colour'"),
            ("presets", "mixer", {"about": 5, "algo": "net"}, "about must be text"),
        )
        for folder, name, data, words in cases:
            self.reset()
            self.change(folder, name, data)
            if folder == "weights":
                self.change("presets", "mixer", {"algo": name})
            self.assertIn(words, self.error("mixer"), (folder, name, data))
        handle = open(os.path.join(self.root, "presets", "broken.json"), "w", encoding="utf-8")
        handle.write("{not json")
        handle.close()
        self.assertIn("presets/broken.json", self.error("broken"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a37b3cf0a01a71d4652cfe596895b9e194ef89ff0ca1490d8ab608da06db96f7 ====
