# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/test_color_voats.py
# About: Tests for the Color Voats feed's core: posts, votes, comments, saves, the store and the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the Color Voats feed's core: posts, votes, comments, saves, the store and the feed's order."""

import json
import os
import shutil
import tempfile
import time
import unittest

import algos
import color_voats as app

LATER = app.SEED_TIME + 60.0


def colors_of(posts):
    colors = []
    for post in posts:
        colors.append(post["color"])
    return colors


class TextTests(unittest.TestCase):
    def test_normalize_hex(self):
        self.assertEqual(app.normalize_hex("#ABCDEF"), "#abcdef")
        self.assertEqual(app.normalize_hex(" abcdef "), "#abcdef")
        for bad in ("#12345", "#1234567", "#gggggg", "", 5, None):
            self.assertEqual(app.normalize_hex(bad), "", bad)

    def test_clean_text(self):
        self.assertEqual(app.clean_text("  nice\n red\t one ", 100), "nice red one")
        self.assertEqual(app.clean_text("a\x00b\x7fc", 100), "a b c")
        self.assertEqual(len(app.clean_text("x" * 600, app.COMMENT_LIMIT)), app.COMMENT_LIMIT)
        self.assertEqual(app.clean_text(None, 100), "")

    def test_color_names(self):
        names = {"#000000": "Black", "#ffffff": "White", "#808080": "Grey", "#333333": "Dark grey",
                 "#cccccc": "Light grey", "#ff0000": "Red", "#00ff00": "Green", "#0000ff": "Blue",
                 "#ffff00": "Yellow", "#000066": "Dark blue", "#996633": "Brown", "#666600": "Olive",
                 "#00cccc": "Teal", "#ccffcc": "Light green", "#9900cc": "Purple"}
        for color in names:
            self.assertEqual(app.color_name(color), names[color], color)

    def test_every_builtin_color_has_a_name(self):
        for color in algos.palette():
            name = app.color_name(color)
            self.assertTrue(name != "" and name[0].isupper(), color)

    def test_when_text(self):
        self.assertEqual(app.when_text(1000.0, 1030.0), "just now")
        self.assertEqual(app.when_text(500.0, 100.0), "just now")
        self.assertEqual(app.when_text(0.0, 5 * 60 + 5), "5 min ago")
        self.assertEqual(app.when_text(0.0, 3 * 3600 + 10), "3 h ago")
        self.assertEqual(app.when_text(0.0, 2 * 86400 + 10), "2 d ago")
        moment = time.localtime(app.SEED_TIME)
        expected = app.MONTHS[moment.tm_mon - 1] + " " + str(moment.tm_mday) + ", " + str(moment.tm_year)
        self.assertEqual(app.when_text(app.SEED_TIME, app.SEED_TIME + 30 * 86400), expected)


class VoteTests(unittest.TestCase):
    def test_pressing_your_vote_again_takes_it_back(self):
        store = app.empty_store()
        self.assertEqual(app.vote(store, "#ff0000", 1, 1.0), 1)
        self.assertEqual(app.my_vote(store, "#ff0000"), 1)
        self.assertEqual(app.vote(store, "#ff0000", 1, 2.0), 0)
        self.assertEqual(app.my_vote(store, "#ff0000"), 0)
        self.assertEqual(store["votes"], {})

    def test_the_other_button_switches_the_vote(self):
        store = app.empty_store()
        app.vote(store, "#ff0000", 1, 1.0)
        self.assertEqual(app.vote(store, "#ff0000", -1, 2.0), -1)
        self.assertEqual(store["votes"]["#ff0000"], {"voat": -1, "when": 2.0})

    def test_the_voat_log_is_oldest_vote_first(self):
        store = app.empty_store()
        app.vote(store, "#aa0000", 1, 3.0)
        app.vote(store, "#00aa00", -1, 1.0)
        app.vote(store, "#0000aa", 1, 2.0)
        self.assertEqual(app.voat_log(store), [{"color": "#00aa00", "voat": -1}, {"color": "#0000aa", "voat": 1},
                                               {"color": "#aa0000", "voat": 1}])
        app.vote(store, "#00aa00", 1, 4.0)
        self.assertEqual(app.voat_log(store)[-1], {"color": "#00aa00", "voat": 1})


class CommentTests(unittest.TestCase):
    def test_comments_are_cleaned_and_kept_in_order(self):
        store = app.empty_store()
        self.assertEqual(app.add_comment(store, "#ff0000", "  so\nred ", 1.0)["value"], {"text": "so red", "when": 1.0})
        app.add_comment(store, "#ff0000", "second", 2.0)
        self.assertEqual(app.comments_of(store, "#ff0000")[1]["text"], "second")
        self.assertEqual(app.comments_of(store, "#00ff00"), [])

    def test_empty_comments_are_refused_and_long_ones_cut(self):
        store = app.empty_store()
        self.assertFalse(app.add_comment(store, "#ff0000", " \n ", 1.0)["ok"])
        self.assertEqual(store["comments"], {})
        added = app.add_comment(store, "#ff0000", "y" * 900, 1.0)
        self.assertEqual(len(added["value"]["text"]), app.COMMENT_LIMIT)

    def test_deleting_a_comment(self):
        store = app.empty_store()
        app.add_comment(store, "#ff0000", "one", 1.0)
        app.add_comment(store, "#ff0000", "two", 2.0)
        self.assertTrue(app.delete_comment(store, "#ff0000", 0))
        self.assertEqual(app.comments_of(store, "#ff0000"), [{"text": "two", "when": 2.0}])
        self.assertFalse(app.delete_comment(store, "#ff0000", 5))
        self.assertTrue(app.delete_comment(store, "#ff0000", 0))
        self.assertEqual(store["comments"], {})


class SaveTests(unittest.TestCase):
    def test_save_and_unsave(self):
        store = app.empty_store()
        self.assertTrue(app.toggle_save(store, "#ff0000", 1.0))
        self.assertTrue(app.toggle_save(store, "#00ff00", 2.0))
        self.assertEqual(app.saved_colors(store), ["#00ff00", "#ff0000"])
        self.assertFalse(app.toggle_save(store, "#00ff00", 3.0))
        self.assertEqual(app.saved_colors(store), ["#ff0000"])


class PostTests(unittest.TestCase):
    def test_posting_a_new_color(self):
        store = app.empty_store()
        posted = app.add_post(store, "#ABC123", "  my\nfavourite ", LATER)
        self.assertEqual(posted["value"], {"color": "#abc123", "caption": "my favourite", "when": LATER, "mine": True})
        self.assertEqual(app.add_post(store, "123abd", "", LATER)["value"]["caption"], app.color_name("#123abd"))
        self.assertEqual(len(app.add_post(store, "#0a0b0c", "z" * 300, LATER)["value"]["caption"]), app.CAPTION_LIMIT)

    def test_bad_or_repeated_colors_are_refused(self):
        store = app.empty_store()
        self.assertIn("#rrggbb", app.add_post(store, "#12345", "", LATER)["error"])
        self.assertIn("already in the feed", app.add_post(store, "#FF0000", "", LATER)["error"])
        app.add_post(store, "#123456", "", LATER)
        self.assertIn("already in the feed", app.add_post(store, "#123456", "", LATER)["error"])
        self.assertEqual(len(store["posts"]), 1)

    def test_deleting_your_post_takes_its_vote_comments_and_save(self):
        store = app.empty_store()
        app.add_post(store, "#123456", "", LATER)
        app.vote(store, "#123456", 1, 1.0)
        app.add_comment(store, "#123456", "hi", 2.0)
        app.toggle_save(store, "#123456", 3.0)
        self.assertTrue(app.delete_post(store, "#123456"))
        self.assertEqual(store, app.empty_store())

    def test_built_in_posts_cannot_be_deleted(self):
        store = app.empty_store()
        app.vote(store, "#ff0000", 1, 1.0)
        self.assertFalse(app.delete_post(store, "#ff0000"))
        self.assertEqual(app.my_vote(store, "#ff0000"), 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "deeper", "social.json")

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))

    def test_round_trip_makes_the_folder(self):
        store = app.empty_store()
        app.add_post(store, "#123456", "mine", LATER)
        app.vote(store, "#123456", 1, 1.0)
        app.vote(store, "#ff0000", -1, 2.0)
        app.add_comment(store, "#ff0000", "too loud", 3.0)
        app.toggle_save(store, "#123456", 4.0)
        self.assertTrue(app.save_store(self.path, store)["ok"])
        self.assertEqual(app.load_store(self.path), store)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_a_missing_or_broken_file_is_an_empty_store(self):
        self.assertEqual(app.load_store(self.path), app.empty_store())
        for text in ("{not json", "[]", '"text"'):
            self.write(text)
            self.assertEqual(app.load_store(self.path), app.empty_store(), text)

    def test_bad_entries_are_dropped(self):
        self.write({"posts": [{"color": "#123456", "caption": "  mine \n", "when": 10.0},
                              {"color": "#123456", "caption": "twice", "when": 11.0},
                              {"color": "#ff0000", "caption": "built in already", "when": 12.0},
                              {"color": "#abcdef", "caption": "", "when": "soon"},
                              {"color": "nope", "when": 13.0}, "text"],
                    "votes": {"#123456": {"voat": 1, "when": 1.0}, "#FF0000": {"voat": -1, "when": 2.0},
                              "#00ff00": {"voat": True, "when": 3.0}, "#0000ff": {"voat": 2, "when": 4.0},
                              "#fedcba": {"voat": 1, "when": 5.0}},
                    "comments": {"#123456": [{"text": " hi ", "when": 1.0}, {"text": "   ", "when": 2.0},
                                             {"text": 5, "when": 3.0}, "x"],
                                 "#ff0000": "not a list", "#fedcba": [{"text": "lost", "when": 1.0}]},
                    "saved": {"#123456": 4.0, "#ff0000": "yesterday", "#fedcba": 1.0}})
        self.assertEqual(app.load_store(self.path),
                         {"posts": [{"color": "#123456", "caption": "mine", "when": 10.0, "mine": True}],
                          "votes": {"#123456": {"voat": 1, "when": 1.0}, "#ff0000": {"voat": -1, "when": 2.0}},
                          "comments": {"#123456": [{"text": "hi", "when": 1.0}]},
                          "saved": {"#123456": 4.0}})


class FeedTests(unittest.TestCase):
    def test_all_posts_are_the_built_in_colors_then_yours(self):
        store = app.empty_store()
        app.add_post(store, "#123456", "mine", LATER)
        posts = app.all_posts(store)
        self.assertEqual(len(posts), 217)
        self.assertEqual(posts[0], {"color": "#000000", "caption": "Black", "when": app.SEED_TIME, "mine": False})
        self.assertEqual(posts[-1]["color"], "#123456")
        self.assertTrue(posts[-1]["mine"])

    def test_new_is_newest_first(self):
        store = app.empty_store()
        app.add_post(store, "#123456", "", LATER)
        app.add_post(store, "#654321", "", LATER + 60.0)
        order = app.feed_order(store, "new", None)
        self.assertEqual(order[:3], ["#654321", "#123456", "#000000"])
        self.assertEqual(sorted(order), sorted(colors_of(app.all_posts(store))))

    def test_a_post_made_now_tops_new(self):
        store = app.empty_store()
        app.add_post(store, "#123456", "", time.time())
        self.assertEqual(app.feed_order(store, "new", None)[0], "#123456")

    def test_for_you_follows_the_ranker_and_your_votes(self):
        ranker = app.load_ranker(app.DEFAULT_PRESET)["value"]
        store = app.empty_store()
        app.add_post(store, "#123456", "", LATER)
        app.vote(store, "#123456", 1, 1.0)
        app.vote(store, "#ff0000", -1, 2.0)
        order = app.feed_order(store, "for_you", ranker)
        self.assertEqual(order[0], "#123456")
        self.assertEqual(order[-1], "#ff0000")
        self.assertEqual(order, ranker.rank(app.voat_log(store), colors_of(app.all_posts(store))))

    def test_an_unknown_preset_is_an_error(self):
        loaded = app.load_ranker("nothing_here")
        self.assertFalse(loaded["ok"])
        self.assertIn("presets/nothing_here", loaded["error"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a3ae4cd0f1774a43667c5effe002da1e0f47eab4897c7dbc9ba6ab015af97a63 ====
