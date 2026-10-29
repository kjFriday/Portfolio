# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/test_algos.py
# About: Tests for the Color Voats algos.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the Color Voats algos. Run: python -m unittest test_algos"""

import unittest

import algos

COLORS = algos.palette()
WEIGHTS = {"net": {"up": 1.0, "down": 1.0}, "wilson": {"z": 1.96},
           "similar": {"reach": 0.15, "up": 1.0, "down": 1.0}, "explore": {"far": 0.5}}
CHAIN = ["net", "wilson", "similar", "explore"]


def up(color):
    return {"color": color, "voat": 1}


def down(color):
    return {"color": color, "voat": -1}


def score(name, colors, voats):
    return algos.run_scorer(name, colors, voats, WEIGHTS[name])


def gap(first, second):
    return algos.distance(algos.oklab(first), algos.oklab(second))


def nearest(color):
    """The palette color nearest to `color`, other than itself."""
    best = ""
    for other in COLORS:
        if other != color and (best == "" or gap(color, other) < gap(color, best)):
            best = other
    return best


class PaletteTests(unittest.TestCase):
    def test_216_different_colors_from_black_to_white(self):
        self.assertEqual(len(COLORS), 216)
        self.assertEqual(len(set(COLORS)), 216)
        self.assertIn("#000000", COLORS)
        self.assertIn("#ffffff", COLORS)

    def test_oklab_reference_values(self):
        # The sRGB primaries and white as given in Bjorn Ottosson's OKLab post.
        references = (("#ffffff", (1.0, 0.0, 0.0)), ("#000000", (0.0, 0.0, 0.0)),
                      ("#ff0000", (0.62796, 0.22486, 0.12585)), ("#00ff00", (0.86644, -0.23389, 0.17950)),
                      ("#0000ff", (0.45201, -0.03246, -0.31153)))
        for color, expected in references:
            lab = algos.oklab(color)
            for index in range(3):
                self.assertAlmostEqual(lab[index], expected[index], places=4, msg=color)

    def test_distance_is_symmetric_and_zero_to_itself(self):
        blue = algos.oklab("#3366cc")
        ochre = algos.oklab("#cc9933")
        self.assertAlmostEqual(algos.distance(blue, ochre), algos.distance(ochre, blue))
        self.assertAlmostEqual(algos.distance(blue, blue), 0.0)

    def test_discovery_order_starts_dark_then_goes_farthest(self):
        places = algos.discovery_order(COLORS)
        self.assertEqual(sorted(places), list(range(216)))
        self.assertEqual(places[COLORS.index("#000000")], 0)
        self.assertEqual(places[COLORS.index("#ffffff")], 1)
        self.assertEqual(algos.discovery_order(COLORS), places)


class ScorerTests(unittest.TestCase):
    def test_net_counts_voats_with_their_weights(self):
        scores = algos.net(COLORS, [up("#ff0000"), up("#ff0000"), down("#00ff00")], 1.0, 2.0)
        self.assertAlmostEqual(scores[COLORS.index("#ff0000")], 2.0)
        self.assertAlmostEqual(scores[COLORS.index("#00ff00")], -2.0)
        self.assertAlmostEqual(scores[COLORS.index("#0000ff")], 0.0)

    def test_voats_on_colors_outside_the_set_are_left_out(self):
        self.assertAlmostEqual(algos.net(["#ff0000"], [up("#123456")], 1.0, 1.0)[0], 0.0)

    def test_wilson_score(self):
        red = COLORS.index("#ff0000")
        one = algos.wilson(COLORS, [up("#ff0000")], 1.96)[red]
        self.assertAlmostEqual(one, 0.20654, places=5)
        self.assertAlmostEqual(algos.wilson(COLORS, [], 1.96)[red], 0.0)
        self.assertGreater(algos.wilson(COLORS, [up("#ff0000")] * 5, 1.96)[red], one)
        self.assertLess(algos.wilson(COLORS, [up("#ff0000"), down("#ff0000")], 1.96)[red], one)

    def test_similar_pulls_only_within_reach(self):
        scores = algos.similar(COLORS, [up("#3366cc")], 0.15, 1.0, 1.0)
        self.assertAlmostEqual(scores[COLORS.index("#3366cc")], 1.0)
        pulled = 0
        for index in range(len(COLORS)):
            if gap(COLORS[index], "#3366cc") < 0.15:
                self.assertGreater(scores[index], 0.0, COLORS[index])
                pulled = pulled + 1
            else:
                self.assertAlmostEqual(scores[index], 0.0, msg=COLORS[index])
        self.assertGreater(pulled, 5)

    def test_an_upvoat_brings_its_nearest_neighbour_up_next(self):
        board = algos.order_by(COLORS, [algos.similar(COLORS, [up("#3366cc")], 0.15, 1.0, 1.0)])
        self.assertEqual(board[0], "#3366cc")
        self.assertEqual(board[1], nearest("#3366cc"))

    def test_a_downvoat_sinks_its_neighbours(self):
        board = algos.order_by(COLORS, [algos.similar(COLORS, [down("#3366cc")], 0.15, 1.0, 1.0)])
        self.assertEqual(board[-1], "#3366cc")
        self.assertEqual(board[-2], nearest("#3366cc"))

    def test_explore_ties_without_voats_and_favours_new_ground(self):
        for value in algos.explore(COLORS, [], 0.5):
            self.assertAlmostEqual(value, 0.5)
        scores = algos.explore(COLORS, [up("#000000")], 0.5)
        self.assertAlmostEqual(scores[COLORS.index("#000000")], 0.0)
        self.assertGreater(scores[COLORS.index("#ffffff")], scores[COLORS.index("#333333")])

    def test_opposite_voats_cancel(self):
        voats = [up("#cc6633"), down("#cc6633")]
        for value in algos.net(COLORS, voats, 1.0, 1.0):
            self.assertAlmostEqual(value, 0.0)
        for value in algos.similar(COLORS, voats, 0.15, 1.0, 1.0):
            self.assertAlmostEqual(value, 0.0)


class AggregatorTests(unittest.TestCase):
    def assert_close(self, values, expected):
        self.assertEqual(len(values), len(expected))
        for index in range(len(values)):
            self.assertAlmostEqual(values[index], expected[index])

    def test_normalize(self):
        self.assert_close(algos.normalize([2.0, 4.0, 3.0]), [0.0, 1.0, 0.5])
        self.assert_close(algos.normalize([7.0, 7.0]), [0.0, 0.0])
        self.assertEqual(algos.normalize([]), [])

    def test_a_flat_list_adds_nothing_to_a_blend(self):
        self.assert_close(algos.blend([[5.0, 5.0, 5.0], [0.0, 1.0, 2.0]], [10.0, 1.0]), [0.0, 0.5, 1.0])

    def test_buckets_tie_close_scores(self):
        steps = algos.buckets([0.0, 0.0004, 1.0], 0.001)
        self.assertEqual(steps[0], steps[1])
        self.assertGreater(steps[2], steps[1])

    def test_the_mixer_hands_ties_to_the_next_scorer(self):
        voats = [up("#3366cc")]
        board = algos.mixer(COLORS, voats, ["net", "similar"], 0.001, 3, 10 ** 6, score)
        self.assertEqual(board[0], "#3366cc")
        self.assertEqual(board[1], nearest("#3366cc"))
        both = [algos.buckets(score("net", COLORS, voats), 0.001), algos.buckets(score("similar", COLORS, voats), 0.001)]
        self.assertEqual(board, algos.order_by(COLORS, both))

    def test_downvoats_in_a_row_pass_the_lead_on(self):
        self.assertEqual(algos.mixer_lead([], 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 2, 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 3, 4, 3), 1)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 2 + [up("#ffffff")] + [down("#000000")] * 2, 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 6, 4, 3), 2)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 6, 2, 3), 0)

    def test_the_lead_changes_the_board(self):
        chain = ["similar", "explore"]
        two = [up("#3366cc"), down("#ff0000"), down("#ffff00")]
        three = two + [down("#00ff00")]
        led_by_similar = algos.mixer(COLORS, two, chain, 0.001, 3, 10 ** 6, score)
        led_by_explore = algos.mixer(COLORS, three, chain, 0.001, 3, 10 ** 6, score)
        self.assertEqual(led_by_similar[0], "#3366cc")
        self.assertNotEqual(led_by_explore[0], "#3366cc")
        first = COLORS.index(led_by_explore[0])
        self.assertAlmostEqual(algos.explore(COLORS, three, 0.5)[first], 0.5)

    def test_a_scorer_over_the_work_budget_is_skipped(self):
        voats = [up("#3366cc"), up("#cc3366")]
        self.assertEqual(algos.cost("similar", 216, 2), 432)
        self.assertEqual(algos.cost("net", 216, 2), 218)
        tight = algos.mixer(COLORS, voats, ["similar", "net"], 0.001, 3, 300, score)
        roomy = algos.mixer(COLORS, voats, ["similar", "net"], 0.001, 3, 10 ** 6, score)
        net_steps = algos.buckets(score("net", COLORS, voats), 0.001)
        similar_steps = algos.buckets(score("similar", COLORS, voats), 0.001)
        self.assertEqual(tight, algos.order_by(COLORS, [net_steps]))
        self.assertEqual(roomy, algos.order_by(COLORS, [similar_steps, net_steps]))
        self.assertNotEqual(tight, roomy)

    def test_without_voats_every_scorer_stalls_into_discovery_order(self):
        board = algos.mixer(COLORS, [], CHAIN, 0.001, 3, 10 ** 6, score)
        places = algos.discovery_order(COLORS)
        for index in range(len(board)):
            self.assertEqual(places[COLORS.index(board[index])], index)

    def test_every_order_is_a_repeatable_permutation(self):
        logs = [[], [up("#3366cc")], [down("#ffffff"), up("#ff9900"), up("#ff9900"), down("#003300")]]
        for voats in logs:
            board = algos.mixer(COLORS, voats, CHAIN, 0.001, 3, 10 ** 6, score)
            self.assertEqual(sorted(board), sorted(COLORS))
            self.assertEqual(algos.mixer(COLORS, voats, CHAIN, 0.001, 3, 10 ** 6, score), board)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=2187844f7a2b66f96872cbcf52643f3aadfeb1117bf1ffdc834837a97c63f0f4 ====
