# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: tests/test_algos.py
# About: Tests for the Color Voats algos.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Tests for the Color Voats algos. Run from the program folder: python -m unittest discover -s tests -p test_algos.py

They call algos.py directly, on the 216-color palette, with hand-built voat logs:
  PaletteTests     the palette, OKLab against published reference values, distance, discovery order
  ScorerTests      net, wilson, similar and explore on small logs whose answer is known
  AggregatorTests  normalize, blend, buckets and the mixer's ties, lead and work budget
The weights are the shipped ones (weights/*.toml), so the numbers match what the app ranks with.
"""

import unittest

import algos

COLORS = algos.palette()
# the shipped weights, as weights/<algo>.toml holds them
WEIGHTS = {"net": {"up": 1.0, "down": 1.0}, "wilson": {"z": 1.96},
           "similar": {"reach": 0.15, "up": 1.0, "down": 1.0}, "explore": {"far": 0.5}}
CHAIN = ["net", "wilson", "similar", "explore"]  # the default mixer preset's chain


def up(color):
    """An upvoat on `color`."""
    return {"color": color, "voat": 1}


def down(color):
    """A downvoat on `color`."""
    return {"color": color, "voat": -1}


def score(name, colors, voats):
    """Scorer `name` with the shipped weights: the score(name, colors, voats) the mixer expects."""
    return algos.run_scorer(name, colors, voats, WEIGHTS[name])


def gap(first, second):
    """The OKLab distance between two "#rrggbb" colors."""
    return algos.distance(algos.oklab(first), algos.oklab(second))


def nearest(color):
    """The palette color nearest to `color`, other than itself."""
    best = ""
    for other in COLORS:
        if other != color and (best == "" or gap(color, other) < gap(color, best)):
            best = other
    return best


class PaletteTests(unittest.TestCase):
    """The color set and the color math every scorer stands on."""

    def test_216_different_colors_from_black_to_white(self):
        """The palette is the full 6x6x6 cube, no repeats, corners included."""
        self.assertEqual(len(COLORS), 216)
        self.assertEqual(len(set(COLORS)), 216)
        self.assertIn("#000000", COLORS)
        self.assertIn("#ffffff", COLORS)

    def test_oklab_reference_values(self):
        """oklab() matches Ottosson's published values to 4 places, which pins both matrices."""
        # The sRGB primaries and white as given in Bjorn Ottosson's OKLab post.
        references = (("#ffffff", (1.0, 0.0, 0.0)), ("#000000", (0.0, 0.0, 0.0)),
                      ("#ff0000", (0.62796, 0.22486, 0.12585)), ("#00ff00", (0.86644, -0.23389, 0.17950)),
                      ("#0000ff", (0.45201, -0.03246, -0.31153)))
        for color, expected in references:
            lab = algos.oklab(color)
            for index in range(3):
                self.assertAlmostEqual(lab[index], expected[index], places=4, msg=color)

    def test_distance_is_symmetric_and_zero_to_itself(self):
        """distance() behaves like a metric on two unrelated colors."""
        blue = algos.oklab("#3366cc")
        ochre = algos.oklab("#cc9933")
        self.assertAlmostEqual(algos.distance(blue, ochre), algos.distance(ochre, blue))
        self.assertAlmostEqual(algos.distance(blue, blue), 0.0)

    def test_discovery_order_starts_dark_then_goes_farthest(self):
        """The places are a permutation, black comes first, white (farthest from black) second, and
        a second run gives the same places."""
        places = algos.discovery_order(COLORS)
        self.assertEqual(sorted(places), list(range(216)))
        self.assertEqual(places[COLORS.index("#000000")], 0)
        self.assertEqual(places[COLORS.index("#ffffff")], 1)
        self.assertEqual(algos.discovery_order(COLORS), places)


class ScorerTests(unittest.TestCase):
    """Each scorer on small voat logs whose scores can be worked out by hand."""

    def test_net_counts_voats_with_their_weights(self):
        """Two upvoats at up 1 give 2, one downvoat at down 2 gives -2, an unvoated color 0."""
        scores = algos.net(COLORS, [up("#ff0000"), up("#ff0000"), down("#00ff00")], 1.0, 2.0)
        self.assertAlmostEqual(scores[COLORS.index("#ff0000")], 2.0)
        self.assertAlmostEqual(scores[COLORS.index("#00ff00")], -2.0)
        self.assertAlmostEqual(scores[COLORS.index("#0000ff")], 0.0)

    def test_voats_on_colors_outside_the_set_are_left_out(self):
        """A voat on a color that is not being ranked changes nothing (and does not crash tally)."""
        self.assertAlmostEqual(algos.net(["#ff0000"], [up("#123456")], 1.0, 1.0)[0], 0.0)

    def test_wilson_score(self):
        """One upvoat scores about 0.20654 at z 1.96, no voats 0, five upvoats more than one, and
        one up plus one down less than one up: certainty and share both count."""
        red = COLORS.index("#ff0000")
        one = algos.wilson(COLORS, [up("#ff0000")], 1.96)[red]
        self.assertAlmostEqual(one, 0.20654, places=5)
        self.assertAlmostEqual(algos.wilson(COLORS, [], 1.96)[red], 0.0)
        self.assertGreater(algos.wilson(COLORS, [up("#ff0000")] * 5, 1.96)[red], one)
        self.assertLess(algos.wilson(COLORS, [up("#ff0000"), down("#ff0000")], 1.96)[red], one)

    def test_similar_pulls_only_within_reach(self):
        """The voated color itself gets the full pull (1), every color inside reach some, every color
        outside exactly 0, and the reach covers more than a handful of the palette."""
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
        """Ranked by similar alone, the upvoated color is first and its nearest neighbour second."""
        board = algos.order_by(COLORS, [algos.similar(COLORS, [up("#3366cc")], 0.15, 1.0, 1.0)])
        self.assertEqual(board[0], "#3366cc")
        self.assertEqual(board[1], nearest("#3366cc"))

    def test_a_downvoat_sinks_its_neighbours(self):
        """The mirror case: the downvoated color is last and its nearest neighbour next to last."""
        board = algos.order_by(COLORS, [algos.similar(COLORS, [down("#3366cc")], 0.15, 1.0, 1.0)])
        self.assertEqual(board[-1], "#3366cc")
        self.assertEqual(board[-2], nearest("#3366cc"))

    def test_explore_ties_without_voats_and_favours_new_ground(self):
        """With no voats every color scores far (0.5); after a voat on black, black scores 0 and white
        beats the dark grey #333333 that sits near black."""
        for value in algos.explore(COLORS, [], 0.5):
            self.assertAlmostEqual(value, 0.5)
        scores = algos.explore(COLORS, [up("#000000")], 0.5)
        self.assertAlmostEqual(scores[COLORS.index("#000000")], 0.0)
        self.assertGreater(scores[COLORS.index("#ffffff")], scores[COLORS.index("#333333")])

    def test_opposite_voats_cancel(self):
        """An upvoat and a downvoat on one color, with equal weights, leave net and similar at 0 everywhere."""
        voats = [up("#cc6633"), down("#cc6633")]
        for value in algos.net(COLORS, voats, 1.0, 1.0):
            self.assertAlmostEqual(value, 0.0)
        for value in algos.similar(COLORS, voats, 0.15, 1.0, 1.0):
            self.assertAlmostEqual(value, 0.0)


class AggregatorTests(unittest.TestCase):
    """How scores become one order: scaling, blending, tie steps and the mixer's hand-offs."""

    def assert_close(self, values, expected):
        """Two float lists of the same length, equal item by item to 7 places."""
        self.assertEqual(len(values), len(expected))
        for index in range(len(values)):
            self.assertAlmostEqual(values[index], expected[index])

    def test_normalize(self):
        """Min-max scaling on an unsorted list, a flat list (all 0) and an empty one."""
        self.assert_close(algos.normalize([2.0, 4.0, 3.0]), [0.0, 1.0, 0.5])
        self.assert_close(algos.normalize([7.0, 7.0]), [0.0, 0.0])
        self.assertEqual(algos.normalize([]), [])

    def test_a_flat_list_adds_nothing_to_a_blend(self):
        """Even at weight 10, a list where every color scores 5 leaves the blend to the other list."""
        self.assert_close(algos.blend([[5.0, 5.0, 5.0], [0.0, 1.0, 2.0]], [10.0, 1.0]), [0.0, 0.5, 1.0])

    def test_buckets_tie_close_scores(self):
        """0 and 0.0004 share the first 0.001 step; 1.0 gets a higher one."""
        steps = algos.buckets([0.0, 0.0004, 1.0], 0.001)
        self.assertEqual(steps[0], steps[1])
        self.assertGreater(steps[2], steps[1])

    def test_the_mixer_hands_ties_to_the_next_scorer(self):
        """With one upvoat, net ties every other color at 0, so similar orders them: the nearest
        neighbour comes second, and the board equals sorting by both bucketed lists."""
        voats = [up("#3366cc")]
        board = algos.mixer(COLORS, voats, ["net", "similar"], 0.001, 3, 10 ** 6, score)
        self.assertEqual(board[0], "#3366cc")
        self.assertEqual(board[1], nearest("#3366cc"))
        both = [algos.buckets(score("net", COLORS, voats), 0.001), algos.buckets(score("similar", COLORS, voats), 0.001)]
        self.assertEqual(board, algos.order_by(COLORS, both))

    def test_downvoats_in_a_row_pass_the_lead_on(self):
        """At streak 3: two downvoats keep the lead, three pass it, an upvoat in the middle resets
        the run, six pass it twice, and on a chain of two it wraps back to 0."""
        self.assertEqual(algos.mixer_lead([], 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 2, 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 3, 4, 3), 1)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 2 + [up("#ffffff")] + [down("#000000")] * 2, 4, 3), 0)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 6, 4, 3), 2)
        self.assertEqual(algos.mixer_lead([down("#000000")] * 6, 2, 3), 0)

    def test_the_lead_changes_the_board(self):
        """The third downvoat in a row hands the lead from similar to explore: the upvoated blue
        stops topping the board, and the new top is a color at least far from every voat."""
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
        """With 216 colors and 2 voats similar costs 432 and net 218; a budget of 300 drops similar
        and leaves net alone, a roomy budget keeps both, and the two boards differ."""
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
        """An empty log gives every scorer a flat list, so the full chain falls through to discovery order."""
        board = algos.mixer(COLORS, [], CHAIN, 0.001, 3, 10 ** 6, score)
        places = algos.discovery_order(COLORS)
        for index in range(len(board)):
            self.assertEqual(places[COLORS.index(board[index])], index)

    def test_every_order_is_a_repeatable_permutation(self):
        """For an empty, a single and a mixed log (with a repeated voat), the board holds every color
        once and a second run returns the same board."""
        logs = [[], [up("#3366cc")], [down("#ffffff"), up("#ff9900"), up("#ff9900"), down("#003300")]]
        for voats in logs:
            board = algos.mixer(COLORS, voats, CHAIN, 0.001, 3, 10 ** 6, score)
            self.assertEqual(sorted(board), sorted(COLORS))
            self.assertEqual(algos.mixer(COLORS, voats, CHAIN, 0.001, 3, 10 ** 6, score), board)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a691565571b372287d5514ddd95c1c78647c9296983f0ad988c5eaefb4cf5180 ====
