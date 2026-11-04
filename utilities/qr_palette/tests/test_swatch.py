# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_swatch.py
# About: Tests for swatch and ranking: cube, names, contrast, and the JSON presets and weights.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for swatch and ranking: cube, names, contrast, and the JSON presets and weights.

Names include each color's family, the last word of its name.

swatch.py holds the 216-color cube, OKLab names and families, WCAG contrast on white (which decides
the colors a code may be drawn in) and the ranking of colors by presets. ranking.py reads the presets/
and weights/ JSON files, which mirror Color Voats' TOML files. Many expected values here were worked
out with Color Voats itself, so the two programs rank and name colors the same.

What the classes pin:
  1. CubeTests: the 216 colors, their indexes, hex parsing, nearest cube and usable colors.
  2. ContrastTests: WCAG contrast, the 118 usable colors at 3:1, and the exact line.
  3. NameTests: names and families as Color Voats gives them, and words people type.
  4. RankingTests: every shipped preset, Color Voats' rankings, the scans algo, and JSON = TOML.
  5. RankingFileTests: edited presets and weights apply at once, and mistakes are named.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import json
import os
import shutil
import tempfile
import unittest

import ranking
import swatch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/
COLOR_VOATS = os.path.join(HERE, "..", "color_voats")  # the Color Voats project beside this one, if present

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
    """Write `data` to `path` as indented JSON."""
    handle = open(path, "w", encoding="utf-8")
    handle.write(json.dumps(data, indent=2))
    handle.close()


def read_json(path):
    """The parsed JSON of a UTF-8 file."""
    handle = open(path, encoding="utf-8")
    data = json.load(handle)
    handle.close()
    return data


class CubeTests(unittest.TestCase):
    """The 6 x 6 x 6 color cube and the helpers around it."""

    def test_216_colors_from_black_to_white(self):
        """palette() lists 216 different colors, red slowest, from #000000 to #ffffff.

        Index 200 is 5 * 36 + 3 * 6 + 2 in base 6, so red ff, green 99, blue 66."""
        colors = swatch.palette()
        self.assertEqual(len(colors), 216)
        self.assertEqual(len(set(colors)), 216)
        self.assertEqual(colors[0], "#000000")
        self.assertEqual(colors[200], "#ff9966")
        self.assertEqual(colors[215], "#ffffff")

    def test_cube_index_is_the_place_in_the_palette(self):
        """cube_index is each color's place in palette(); a channel that is no multiple of 51 gives -1."""
        colors = swatch.palette()
        for index in range(len(colors)):
            self.assertEqual(swatch.cube_index(colors[index]), index)
        self.assertEqual(swatch.cube_index("#123456"), -1)
        self.assertEqual(swatch.cube_index("#330001"), -1)

    def test_normalize_hex(self):
        """Hex in either case, with or without # and spaces, becomes "#rrggbb"; wrong lengths, bad digits and non-text give ""."""
        self.assertEqual(swatch.normalize_hex("#3366CC"), "#3366cc")
        self.assertEqual(swatch.normalize_hex(" 3366cc "), "#3366cc")
        for bad in ("#3366c", "#3366ccc", "#zz66cc", "", None, 336699):
            self.assertEqual(swatch.normalize_hex(bad), "")

    def test_nearest_cube_color(self):
        """#3467cb is nearest #3366cc and near it; every cube color is its own nearest; a far color is not near."""
        self.assertEqual(swatch.nearest_cube("#3467cb"), "#3366cc")
        for color in swatch.palette():
            self.assertEqual(swatch.nearest_cube(color), color)
        self.assertTrue(swatch.is_near("#3366cc", "#3467cb"))
        self.assertFalse(swatch.is_near("#3366cc", "#cc6633"))

    def test_nearest_usable_color(self):
        """For colors too light to scan, nearest_usable gives a usable color no farther in OKLab than any other usable one.

        A usable color is its own nearest."""
        for color in ("#ffff00", "#ffffff", "#99ccff", "#ffeecc"):
            self.assertFalse(swatch.usable(color))
            near = swatch.nearest_usable(color)
            self.assertTrue(swatch.usable(near), color)
            for other in swatch.usable_colors():
                self.assertLessEqual(swatch.color_distance(swatch.oklab(color), swatch.oklab(near)),
                                     swatch.color_distance(swatch.oklab(color), swatch.oklab(other)))
        self.assertEqual(swatch.nearest_usable("#3366cc"), "#3366cc")


class ContrastTests(unittest.TestCase):
    """WCAG 2.x contrast against white, which decides the usable colors."""

    def test_black_on_white_is_21_and_symmetric(self):
        """Black on white is 21:1 either way round, the most WCAG contrast gives; a color on itself is 1:1."""
        self.assertAlmostEqual(swatch.contrast("#000000", "#ffffff"), 21.0, places=9)
        self.assertAlmostEqual(swatch.contrast("#ffffff", "#000000"), 21.0, places=9)
        self.assertAlmostEqual(swatch.contrast("#3366cc", "#3366cc"), 1.0, places=9)

    def test_118_cube_colors_are_usable(self):
        """At the default 3:1, 118 of the 216 cube colors are usable."""
        self.assertEqual(len(swatch.usable_colors()), 118)

    def test_the_line_is_compared_exactly(self):
        """Contrast is compared unrounded: #0099ff at 2.9998 is out, #6699cc at 3.003 is in.

        Rounding to one decimal would let #0099ff through as 3.0."""
        self.assertLess(swatch.contrast("#0099ff", swatch.WHITE), 3.0)  # 2.9998
        self.assertFalse(swatch.usable("#0099ff"))
        self.assertGreater(swatch.contrast("#6699cc", swatch.WHITE), 3.0)  # 3.003
        self.assertTrue(swatch.usable("#6699cc"))
        self.assertTrue(swatch.usable("#cc66ff"))
        self.assertFalse(swatch.usable("#ffff00"))
        self.assertFalse(swatch.usable(swatch.WHITE))

    def test_the_line_follows_the_setting(self):
        """Raising MIN_CONTRAST to 4.5 (settings.json's colors.minimum_contrast) leaves 77 usable colors; it is put back after."""
        saved = swatch.MIN_CONTRAST
        try:
            swatch.MIN_CONTRAST = 4.5
            self.assertEqual(len(swatch.usable_colors()), 77)
        finally:
            swatch.MIN_CONTRAST = saved


class NameTests(unittest.TestCase):
    """Color names and families."""

    def test_names_match_color_voats(self):
        """Every color in NAMES gets the name Color Voats 0.2.0 gives it (#cc0066 really is "Red" there)."""
        for color in NAMES:
            self.assertEqual(swatch.color_name(color), NAMES[color], color)

    def test_the_family_is_the_last_word(self):
        """A family is the last word of the name, and every cube color's family is one of FAMILIES."""
        self.assertEqual(swatch.family("#006666"), "teal")
        self.assertEqual(swatch.family("#cccccc"), "grey")
        self.assertEqual(swatch.family("#663300"), "brown")
        for color in swatch.palette():
            self.assertIn(swatch.family(color), swatch.FAMILIES, color)

    def test_words_people_type(self):
        """family_of_word takes any case, plurals and FAMILY_WORDS (gray, navy, cyan, magenta); other words give "".

        "s" alone is no plural of anything."""
        cases = {"blue": "blue", "Blues": "blue", "GRAY": "grey", "greys": "grey", "navy": "blue",
                 "cyan": "teal", "magenta": "pink", "violets": "purple", "chartreuse": "", "": "", "s": ""}
        for word in cases:
            self.assertEqual(swatch.family_of_word(word), cases[word], word)


class RankingTests(unittest.TestCase):
    """rank_colors over the shipped presets and weights."""

    def test_the_shipped_presets(self):
        """The five shipped presets are found, in name order, and each reads with an "about" text."""
        self.assertEqual(swatch.presets(), ["balanced", "discover", "mixer", "popular", "scans"])
        for name in swatch.presets():
            preset = ranking.read_preset(swatch.RANKING_ROOT, name)
            self.assertTrue(preset["ok"], preset["error"])
            self.assertNotEqual(preset["value"]["about"], "")

    def test_every_preset_ranks_every_color_once(self):
        """Every preset's ranking is a permutation of the 216 cube colors."""
        for name in swatch.presets():
            ranked = swatch.rank_colors(name, SAMPLE)
            self.assertTrue(ranked["ok"], ranked["error"])
            self.assertEqual(sorted(ranked["value"]), sorted(swatch.palette()))

    def test_no_votes_is_discovery_order(self):
        """With no votes every preset falls back to the same discovery order Color Voats shows."""
        for name in swatch.presets():
            self.assertEqual(" ".join(swatch.rank_colors(name, [])["value"][:10]), NO_VOTES_TOP, name)

    def test_the_sample_matches_color_voats(self):
        """With Color Voats' sample votes, each preset's top ten is Color Voats' own."""
        for name in SAMPLE_TOP:
            self.assertEqual(" ".join(swatch.rank_colors(name, SAMPLE)["value"][:10]), SAMPLE_TOP[name], name)

    def test_scans_lift_a_color_only_when_they_are_given(self):
        """The scans preset follows scans when they are given, and is the discovery order without them (None or {}).

        Presets that do not use the scans algo (mixer, balanced) rank the same with or without scans."""
        scans = {"#3366cc": {"scans": 400, "links": 2}, "#006633": {"scans": 10, "links": 1}}
        without = swatch.rank_colors("scans", [])["value"]
        self.assertEqual(" ".join(without[:10]), NO_VOTES_TOP)
        self.assertEqual(swatch.rank_colors("scans", [], {})["value"], without)
        ranked = swatch.rank_colors("scans", [], scans)["value"]
        self.assertEqual(ranked[:2], ["#3366cc", "#006633"])
        self.assertEqual(sorted(ranked), sorted(swatch.palette()))
        for name in ("mixer", "balanced"):  # presets without the scans algo do not change
            self.assertEqual(swatch.rank_colors(name, SAMPLE, scans)["value"], swatch.rank_colors(name, SAMPLE)["value"])

    def test_one_lucky_code_does_not_outrank_a_proven_color(self):
        """scans_scores divides scans by links plus 2 prior links (at a prior rate of 0), so many links outweigh one lucky code.

        30 scans on 1 link score 30 / 3 = 10; 80 scans on 4 links score 80 / 6, about 13.3, and win;
        a color with no scans scores 0."""
        colors = ["#111111", "#222222", "#333333"]
        scores = ranking.scans_scores(colors, {"#111111": {"scans": 30, "links": 1},
                                               "#222222": {"scans": 80, "links": 4}}, 2, 0)
        self.assertEqual(scores, [10.0, 80 / 6.0, 0.0])

    def test_the_mixer_keeps_its_own_chain(self):
        """A mixer preset may not use scans: the error points to a blend instead.

        The preset is written into a scratch copy of the ranking folders, so the shipped files are
        never touched."""
        root = tempfile.mkdtemp(prefix="qr_palette_mixer_")
        try:
            shutil.copytree(os.path.join(HERE, "weights"), os.path.join(root, "weights"))
            os.makedirs(os.path.join(root, "presets"))
            handle = open(os.path.join(root, "presets", "mine.json"), "w", encoding="utf-8")
            handle.write(json.dumps({"algo": "mixer", "uses": ["wilson", "scans"]}))
            handle.close()
            self.assertIn("put scans in a blend", ranking.read_preset(root, "mine")["error"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_unknown_presets(self):
        """A missing preset names its file; a name that climbs out of presets/ is refused."""
        self.assertIn("missing presets/loudest.json", swatch.rank_colors("loudest", [])["error"])
        self.assertFalse(swatch.rank_colors("../algos", [])["ok"])

    def test_board_and_places(self):
        """The board keeps the 118 usable colors in ranked order; places number all 216 from 1."""
        order = swatch.rank_colors("mixer", SAMPLE)["value"]
        board = swatch.usable_board(order)
        self.assertEqual(len(board), 118)
        self.assertEqual(board[0], "#3399cc")
        places = swatch.rank_places(order)
        self.assertEqual(places["#3399cc"], 1)
        self.assertEqual(places[order[215]], 216)

    def test_the_json_matches_color_voats_toml(self):
        """Every preset and weight JSON file holds the same data as Color Voats' TOML file of that name, "about" aside.

        Skipped on a Python without tomllib (before 3.11) or without Color Voats beside this project;
        scans.json is QR Palette's own."""
        try:
            import tomllib
        except ImportError:
            self.skipTest("reading TOML needs Python 3.11")
        if not os.path.isdir(COLOR_VOATS):
            self.skipTest("Color Voats is not next to this project")
        for folder in ("presets", "weights"):
            for name in sorted(os.listdir(os.path.join(HERE, folder))):
                if name == "scans.json":
                    continue  # QR Palette's own: Color Voats has no scans
                mine = read_json(os.path.join(HERE, folder, name))
                del mine["about"]
                # name[:-5] drops ".json"
                handle = open(os.path.join(COLOR_VOATS, folder, name[:-5] + ".toml"), "rb")
                theirs = tomllib.load(handle)
                handle.close()
                self.assertEqual(mine, theirs, folder + "/" + name)


class RankingFileTests(unittest.TestCase):
    """Ranking from an editable copy of presets/ and weights/, pointed to by swatch.RANKING_ROOT."""

    def setUp(self):
        """Copy the shipped presets and weights into a temporary root and point swatch at it."""
        self.root = tempfile.mkdtemp(prefix="qr_palette_ranking_")
        shutil.copytree(os.path.join(HERE, "presets"), os.path.join(self.root, "presets"))
        shutil.copytree(os.path.join(HERE, "weights"), os.path.join(self.root, "weights"))
        self.saved = swatch.RANKING_ROOT
        swatch.RANKING_ROOT = self.root

    def tearDown(self):
        """Point swatch back at the shipped folders and remove the copy."""
        swatch.RANKING_ROOT = self.saved
        shutil.rmtree(self.root, ignore_errors=True)

    def change(self, folder, name, data):
        """Replace `folder`/`name`.json in the copy with `data`."""
        write_json(os.path.join(self.root, folder, name + ".json"), data)

    def reset(self):
        """Copy the shipped presets and weights over the copy again."""
        for folder in ("presets", "weights"):
            shutil.rmtree(os.path.join(self.root, folder), ignore_errors=True)
            shutil.copytree(os.path.join(HERE, folder), os.path.join(self.root, folder))

    def error(self, name):
        """Read preset `name` from the copy, which must fail -> its error."""
        result = ranking.read_preset(self.root, name)
        self.assertFalse(result["ok"])
        return result["error"]

    def test_an_edit_applies_at_once(self):
        """An edited weight file and preset change the next ranking with no restart; a preset without "about" reads as "".

        With downvoats counting ten times, the two downvoated sample colors sink to the end."""
        before = swatch.rank_colors("mixer", SAMPLE)["value"]
        self.change("weights", "net", {"about": "downvoats count ten times", "up": 1.0, "down": 10.0})
        self.change("presets", "mixer", {"algo": "net"})
        after = swatch.rank_colors("mixer", SAMPLE)["value"]
        self.assertNotEqual(before, after)
        self.assertEqual(sorted(after[214:]), ["#996633", "#cc9966"])  # the downvoated colors sink to the end
        self.assertEqual(ranking.read_preset(self.root, "mixer")["value"]["about"], "")

    def test_a_new_preset_is_found(self):
        """A new file in presets/ is a new preset at once; Wilson score alone puts #3366cc first."""
        self.change("presets", "only_wilson", {"about": "Wilson score alone", "algo": "wilson"})
        self.assertIn("only_wilson", swatch.presets())
        self.assertEqual(swatch.rank_colors("only_wilson", SAMPLE)["value"][0], "#3366cc")

    def test_mistakes_name_the_file_and_the_problem(self):
        """Each mistake in a weight or preset file gives an error naming the problem; a file that is not JSON names its path.

        The copy is reset before each case, and a broken weight file is reached through a mixer
        preset that uses that algo alone."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=8b9b982c281063dfacfcdf7ebedc819377d83605872b032316ca1e46ae98aa2b ====
