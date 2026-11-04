# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: tests/test_color_voats.py
# About: Tests for the Color Voats feed's core: posts, votes, comments, saves, the store and the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Tests for voats_core.py: posts, votes, comments, saves, the store and the feed's order.

They test the Color Voats feed's core. Run from the program folder:
python -m unittest discover -s tests -p test_color_voats.py

Most tests work on a store in memory (app.empty_store()); StoreTests use a temporary folder, and
FeedTests load the default ranker, which rewrites rankers/ranker_mixer.py if it is stale.
ModuleTests only imports the entry point and the window module, without opening a window.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

import algos
import voats_core as app

LATER = app.SEED_TIME + 60.0  # a post time just after the built-in colors, so New puts it above them


def colors_of(posts):
    """The colors of a list of posts, in order."""
    colors = []
    for post in posts:
        colors.append(post["color"])
    return colors


class TextTests(unittest.TestCase):
    """The word helpers: hex codes, kept text, color names and post times."""

    def test_normalize_hex(self):
        """Case and a missing # are forgiven; wrong lengths, non-hex digits and non-strings give ""."""
        self.assertEqual(app.normalize_hex("#ABCDEF"), "#abcdef")
        self.assertEqual(app.normalize_hex(" abcdef "), "#abcdef")
        for bad in ("#12345", "#1234567", "#gggggg", "", 5, None):
            self.assertEqual(app.normalize_hex(bad), "", bad)

    def test_clean_text(self):
        """Line breaks, tabs, NUL and DEL become single spaces, long text is cut, None gives ""."""
        self.assertEqual(app.clean_text("  nice\n red\t one ", 100), "nice red one")
        self.assertEqual(app.clean_text("a\x00b\x7fc", 100), "a b c")
        self.assertEqual(len(app.clean_text("x" * 600, app.COMMENT_LIMIT)), app.COMMENT_LIMIT)
        self.assertEqual(app.clean_text(None, 100), "")

    def test_color_names(self):
        """A sample covering each branch of color_name: the greys, the hues, brown and olive, and the
        dark and light prefixes."""
        names = {"#000000": "Black", "#ffffff": "White", "#808080": "Grey", "#333333": "Dark grey",
                 "#cccccc": "Light grey", "#ff0000": "Red", "#00ff00": "Green", "#0000ff": "Blue",
                 "#ffff00": "Yellow", "#000066": "Dark blue", "#996633": "Brown", "#666600": "Olive",
                 "#00cccc": "Teal", "#ccffcc": "Light green", "#9900cc": "Purple"}
        for color in names:
            self.assertEqual(app.color_name(color), names[color], color)

    def test_every_builtin_color_has_a_name(self):
        """Every built-in post gets a non-empty, capitalized caption."""
        for color in algos.palette():
            name = app.color_name(color)
            self.assertTrue(name != "" and name[0].isupper(), color)

    def test_when_text(self):
        """Each band of when_text, a future time as "just now", and the local date after a week
        (worked out with the same local time, so the test passes in any time zone)."""
        self.assertEqual(app.when_text(1000.0, 1030.0), "just now")
        self.assertEqual(app.when_text(500.0, 100.0), "just now")
        self.assertEqual(app.when_text(0.0, 5 * 60 + 5), "5 min ago")
        self.assertEqual(app.when_text(0.0, 3 * 3600 + 10), "3 h ago")
        self.assertEqual(app.when_text(0.0, 2 * 86400 + 10), "2 d ago")
        moment = time.localtime(app.SEED_TIME)
        expected = app.MONTHS[moment.tm_mon - 1] + " " + str(moment.tm_mday) + ", " + str(moment.tm_year)
        self.assertEqual(app.when_text(app.SEED_TIME, app.SEED_TIME + 30 * 86400), expected)


class VoteTests(unittest.TestCase):
    """Good and Bad behave like any feed's buttons, and the voat log follows the votes."""

    def test_pressing_your_vote_again_takes_it_back(self):
        """Good twice ends with no vote and no entry left in the store."""
        store = app.empty_store()
        self.assertEqual(app.vote(store, "#ff0000", 1, 1.0), 1)
        self.assertEqual(app.my_vote(store, "#ff0000"), 1)
        self.assertEqual(app.vote(store, "#ff0000", 1, 2.0), 0)
        self.assertEqual(app.my_vote(store, "#ff0000"), 0)
        self.assertEqual(store["votes"], {})

    def test_the_other_button_switches_the_vote(self):
        """Bad after Good replaces the vote and its time."""
        store = app.empty_store()
        app.vote(store, "#ff0000", 1, 1.0)
        self.assertEqual(app.vote(store, "#ff0000", -1, 2.0), -1)
        self.assertEqual(store["votes"]["#ff0000"], {"voat": -1, "when": 2.0})

    def test_the_voat_log_is_oldest_vote_first(self):
        """Votes made out of time order come out sorted by time, and a switched vote moves to the end."""
        store = app.empty_store()
        app.vote(store, "#aa0000", 1, 3.0)
        app.vote(store, "#00aa00", -1, 1.0)
        app.vote(store, "#0000aa", 1, 2.0)
        self.assertEqual(app.voat_log(store), [{"color": "#00aa00", "voat": -1}, {"color": "#0000aa", "voat": 1},
                                               {"color": "#aa0000", "voat": 1}])
        app.vote(store, "#00aa00", 1, 4.0)
        self.assertEqual(app.voat_log(store)[-1], {"color": "#00aa00", "voat": 1})


class CommentTests(unittest.TestCase):
    """Adding, cleaning and deleting comments."""

    def test_comments_are_cleaned_and_kept_in_order(self):
        """A comment is cleaned like any text, later comments go after it, and a post without
        comments has an empty list."""
        store = app.empty_store()
        self.assertEqual(app.add_comment(store, "#ff0000", "  so\nred ", 1.0)["value"], {"text": "so red", "when": 1.0})
        app.add_comment(store, "#ff0000", "second", 2.0)
        self.assertEqual(app.comments_of(store, "#ff0000")[1]["text"], "second")
        self.assertEqual(app.comments_of(store, "#00ff00"), [])

    def test_empty_comments_are_refused_and_long_ones_cut(self):
        """Whitespace only is refused without touching the store; 900 characters are cut to COMMENT_LIMIT."""
        store = app.empty_store()
        self.assertFalse(app.add_comment(store, "#ff0000", " \n ", 1.0)["ok"])
        self.assertEqual(store["comments"], {})
        added = app.add_comment(store, "#ff0000", "y" * 900, 1.0)
        self.assertEqual(len(added["value"]["text"]), app.COMMENT_LIMIT)

    def test_deleting_a_comment(self):
        """Deleting by index shifts the rest down, a bad index is refused, and the last delete removes
        the post's entry."""
        store = app.empty_store()
        app.add_comment(store, "#ff0000", "one", 1.0)
        app.add_comment(store, "#ff0000", "two", 2.0)
        self.assertTrue(app.delete_comment(store, "#ff0000", 0))
        self.assertEqual(app.comments_of(store, "#ff0000"), [{"text": "two", "when": 2.0}])
        self.assertFalse(app.delete_comment(store, "#ff0000", 5))
        self.assertTrue(app.delete_comment(store, "#ff0000", 0))
        self.assertEqual(store["comments"], {})


class SaveTests(unittest.TestCase):
    """The Save button and the Saved tab's order."""

    def test_save_and_unsave(self):
        """Saves list the latest first, and Save again takes a post out."""
        store = app.empty_store()
        self.assertTrue(app.toggle_save(store, "#ff0000", 1.0))
        self.assertTrue(app.toggle_save(store, "#00ff00", 2.0))
        self.assertEqual(app.saved_colors(store), ["#00ff00", "#ff0000"])
        self.assertFalse(app.toggle_save(store, "#00ff00", 3.0))
        self.assertEqual(app.saved_colors(store), ["#ff0000"])


class PostTests(unittest.TestCase):
    """Posting your own colors and deleting them."""

    def test_posting_a_new_color(self):
        """The color is normalized and the caption cleaned; an empty caption becomes the color's
        name, and a long one is cut to CAPTION_LIMIT."""
        store = app.empty_store()
        posted = app.add_post(store, "#ABC123", "  my\nfavourite ", LATER)
        self.assertEqual(posted["value"], {"color": "#abc123", "caption": "my favourite", "when": LATER, "mine": True})
        self.assertEqual(app.add_post(store, "123abd", "", LATER)["value"]["caption"], app.color_name("#123abd"))
        self.assertEqual(len(app.add_post(store, "#0a0b0c", "z" * 300, LATER)["value"]["caption"]), app.CAPTION_LIMIT)

    def test_bad_or_repeated_colors_are_refused(self):
        """A malformed color, a built-in one (in another case) and one already posted are refused
        with messages the window shows; only the one good post is kept."""
        store = app.empty_store()
        self.assertIn("#rrggbb", app.add_post(store, "#12345", "", LATER)["error"])
        self.assertIn("already in the feed", app.add_post(store, "#FF0000", "", LATER)["error"])
        app.add_post(store, "#123456", "", LATER)
        self.assertIn("already in the feed", app.add_post(store, "#123456", "", LATER)["error"])
        self.assertEqual(len(store["posts"]), 1)

    def test_deleting_your_post_takes_its_vote_comments_and_save(self):
        """After the delete nothing of the post is left: the store is empty again."""
        store = app.empty_store()
        app.add_post(store, "#123456", "", LATER)
        app.vote(store, "#123456", 1, 1.0)
        app.add_comment(store, "#123456", "hi", 2.0)
        app.toggle_save(store, "#123456", 3.0)
        self.assertTrue(app.delete_post(store, "#123456"))
        self.assertEqual(store, app.empty_store())

    def test_built_in_posts_cannot_be_deleted(self):
        """delete_post on a built-in color fails and leaves your vote on it alone."""
        store = app.empty_store()
        app.vote(store, "#ff0000", 1, 1.0)
        self.assertFalse(app.delete_post(store, "#ff0000"))
        self.assertEqual(app.my_vote(store, "#ff0000"), 1)


class StoreTests(unittest.TestCase):
    """Saving and loading the store file, in a temporary folder."""

    def setUp(self):
        """A fresh temporary folder; the store path is one level deeper, in a folder not made yet."""
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "deeper", "social.json")

    def tearDown(self):
        """Remove the temporary folder and everything in it."""
        shutil.rmtree(self.folder)

    def write(self, data):
        """Write `data` to the store path: a string as is, anything else as JSON."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))

    def test_round_trip_makes_the_folder(self):
        """A store with one of everything loads back equal, save_store makes the missing folder, and
        no .tmp file is left behind."""
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
        """No file, bad JSON, a JSON list and a JSON string all load as an empty store."""
        self.assertEqual(app.load_store(self.path), app.empty_store())
        for text in ("{not json", "[]", '"text"'):
            self.write(text)
            self.assertEqual(app.load_store(self.path), app.empty_store(), text)

    def test_bad_entries_are_dropped(self):
        """One file with every kind of bad entry: a repeated or built-in post, a string time, a bad
        color, a non-object; votes of True and 2 and on an unknown color; blank and non-text
        comments; a string save time. Only the good entries survive, keys normalized."""
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
    """The feed's posts and its two orders, New and For you."""

    def test_all_posts_are_the_built_in_colors_then_yours(self):
        """216 built-in posts (black first, captioned and dated SEED_TIME) and then your one."""
        store = app.empty_store()
        app.add_post(store, "#123456", "mine", LATER)
        posts = app.all_posts(store)
        self.assertEqual(len(posts), 217)
        self.assertEqual(posts[0], {"color": "#000000", "caption": "Black", "when": app.SEED_TIME, "mine": False})
        self.assertEqual(posts[-1]["color"], "#123456")
        self.assertTrue(posts[-1]["mine"])

    def test_new_is_newest_first(self):
        """Two of your posts a minute apart come first, newest on top, then the built-in colors;
        nothing is lost or repeated."""
        store = app.empty_store()
        app.add_post(store, "#123456", "", LATER)
        app.add_post(store, "#654321", "", LATER + 60.0)
        order = app.feed_order(store, "new", None)
        self.assertEqual(order[:3], ["#654321", "#123456", "#000000"])
        self.assertEqual(sorted(order), sorted(colors_of(app.all_posts(store))))

    def test_a_post_made_now_tops_new(self):
        """A post with the real clock time beats SEED_TIME, as it does in the window."""
        store = app.empty_store()
        app.add_post(store, "#123456", "", time.time())
        self.assertEqual(app.feed_order(store, "new", None)[0], "#123456")

    def test_for_you_follows_the_ranker_and_your_votes(self):
        """With the default ranker, an upvoated post of yours tops For you, a downvoated built-in color
        ends it, and the order is exactly the ranker's for the voat log."""
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
        """load_ranker fails with a message naming the missing preset file, and writes nothing."""
        loaded = app.load_ranker("nothing_here")
        self.assertFalse(loaded["ok"])
        self.assertIn("presets/nothing_here", loaded["error"])


class ModuleTests(unittest.TestCase):
    """The modules no other test imports still load."""

    def test_the_entry_and_window_modules_import(self):
        """No other test loads the window module: importing it catches a file that no longer compiles."""
        import color_voats  # noqa: F401
        import voats_gui  # noqa: F401


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=be49688e6dcbe7f8e3ec6ad04681b3145a0a9bfa1529ec65bff83a769785a84c ====
