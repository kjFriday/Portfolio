# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/test_color_voats.py
# About: Tests for the Color Voats window's core: the voat log, the board and loading a ranker.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the Color Voats window's core: the voat log, the board and loading a ranker."""

import json
import os
import shutil
import tempfile
import unittest

import algos
import color_voats as app


class VoatLogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "deeper", "voats.json")

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_round_trip_makes_the_folder(self):
        voats = app.add_voat(app.add_voat([], "#ff0000", 1), "#00ff00", -1)
        self.assertTrue(app.save_voats(self.path, voats)["ok"])
        self.assertEqual(app.load_voats(self.path), voats)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_a_missing_or_broken_log_is_empty(self):
        self.assertEqual(app.load_voats(self.path), [])
        for text in ("{not json", '{"color": "#ff0000", "voat": 1}', "[]"):
            self.write(text)
            self.assertEqual(app.load_voats(self.path), [], text)

    def test_bad_entries_are_dropped(self):
        entries = [{"color": "#FF0000", "voat": 1}, {"color": "#ff0000", "voat": True},
                   {"color": "#ff0000", "voat": 2}, {"color": "#ff00", "voat": 1}, {"color": "#gg0000", "voat": -1},
                   {"color": 5, "voat": 1}, "#ff0000", {"color": "#00ff00", "voat": -1}]
        self.write(json.dumps(entries))
        self.assertEqual(app.load_voats(self.path), [{"color": "#ff0000", "voat": 1}, {"color": "#00ff00", "voat": -1}])

    def test_undo_takes_the_last_voat_back(self):
        voats = app.add_voat(app.add_voat([], "#ff0000", 1), "#00ff00", -1)
        self.assertEqual(app.undo_voat(voats), [{"color": "#ff0000", "voat": 1}])
        self.assertEqual(app.undo_voat([]), [])
        self.assertEqual(len(voats), 2)


class BoardTests(unittest.TestCase):
    def test_board_size(self):
        self.assertEqual(app.board_size(216, 18, 36, 4), [18 * 36 + 19 * 4, 12 * 36 + 13 * 4])
        self.assertEqual(app.board_size(19, 18, 10, 2), [18 * 10 + 19 * 2, 2 * 10 + 3 * 2])

    def test_every_pixel_of_a_tile_finds_it(self):
        for index in range(216):
            box = app.tile_box(index, 18, 36, 4)
            for point in ([box[0], box[1]], [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2], [box[2] - 1, box[3] - 1]):
                self.assertEqual(app.tile_at(point[0], point[1], 216, 18, 36, 4), index)

    def test_gaps_and_points_off_the_board_are_no_tile(self):
        box = app.tile_box(0, 18, 36, 4)
        size = app.board_size(216, 18, 36, 4)
        for point in ([0, 0], [box[2], box[1]], [box[0], box[3]], [-5, 10], [10, -5], [size[0] + 10, 10], [10, size[1] + 10]):
            self.assertEqual(app.tile_at(point[0], point[1], 216, 18, 36, 4), -1, point)
        empty = app.tile_box(19, 18, 36, 4)
        self.assertEqual(app.tile_at(empty[0] + 1, empty[1] + 1, 19, 18, 36, 4), -1)


class RankerTests(unittest.TestCase):
    def test_the_default_ranker_loads_and_ranks_every_color(self):
        loaded = app.load_ranker(app.DEFAULT_PRESET)
        self.assertTrue(loaded["ok"], loaded["error"])
        colors = algos.palette()
        board = loaded["value"].rank([{"color": "#336699", "voat": 1}], colors)
        self.assertEqual(sorted(board), sorted(colors))
        self.assertEqual(board[0], "#336699")

    def test_an_unknown_preset_is_an_error(self):
        loaded = app.load_ranker("nothing_here")
        self.assertFalse(loaded["ok"])
        self.assertIn("presets/nothing_here", loaded["error"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=61655826a9df7e55659194ecdb0b6cc2e48243e6a79dda160152e935e4443824 ====
