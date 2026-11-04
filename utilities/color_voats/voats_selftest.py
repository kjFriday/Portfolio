# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: voats_selftest.py
# About: Color Voats' self-test: a quick pass over algos, the factory and the core.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Color Voats' self-test: a quick pass over algos, the factory and the core.

Run by `python color_voats.py --selftest`; the full suites are in tests/. Each check prints
"  ok   <what>" or "  FAIL <what>" under a group heading (algos, factory, feed, words), then a summary
line, and selftest() returns the exit code: 0 when every check passed, 1 otherwise. Like a launch, the
self-test loads the default ranker through load_ranker, which rewrites rankers/ranker_mixer.py when it is
out of date (after "every ranker is up to date" has reported it). It also writes and removes a store file
in a temporary folder.
"""

import os
import tempfile

import algos
import factory
from voats_core import (DEFAULT_PRESET, HERE, SEED_TIME, add_comment, add_post, color_name, empty_store, feed_order,
                        load_ranker, load_store, save_store, saved_colors, toggle_save, vote, when_text)


def check(condition, message, failures):
    """Print one check as ok or FAIL; a failed check's `message` is added to `failures`."""
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    """Run every check -> 0 when all passed, 1 when any failed.

    Steps:
      1. algos: the palette, OKLab white, one Wilson score and the mixer's lead rule.
      2. factory: the default preset exists, every ranker is current, and the default ranker loads
         (which rewrites it when stale, so the order of these two checks matters).
      3. feed: votes, comments, saves and posts on a store in memory, both feed orders, and a save
         and load round trip through a temporary folder.
      4. words: color names and post times.
    A check that cannot run because an earlier one failed (For you without a ranker) is skipped.
    """
    failures = []
    colors = algos.palette()
    print("algos")
    check(len(colors) == 216 and len(set(colors)) == 216, "216 different colors", failures)
    white = algos.oklab("#ffffff")
    check(abs(white[0] - 1.0) < 1e-6 and abs(white[1]) < 1e-6 and abs(white[2]) < 1e-6, "white is L 1, a 0, b 0", failures)
    # one upvoat out of one at 95 % confidence: (1 + 1.9208 - 1.96 * 0.98) / 4.8416, about 0.2065
    one_up = algos.wilson(["#ff0000"], [{"color": "#ff0000", "voat": 1}], 1.96)[0]
    check(abs(one_up - 0.2065) < 0.001, "Wilson score of one upvoat", failures)
    three_down = [{"color": "#000000", "voat": -1}] * 3
    check(algos.mixer_lead(three_down, 4, 3) == 1, "three downvoats in a row pass the lead on", failures)

    print("factory")
    names = factory.preset_names(HERE)
    check(DEFAULT_PRESET in names, "the default preset is there", failures)
    problems = factory.check(HERE, names)
    check(len(problems) == 0, "every ranker is up to date " + "; ".join(problems), failures)
    loaded = load_ranker(DEFAULT_PRESET)
    check(loaded["ok"], "the default ranker loads " + loaded["error"], failures)

    print("feed")
    store = empty_store()
    check(vote(store, "#ff0000", 1, 1.0) == 1 and vote(store, "#ff0000", 1, 2.0) == 0, "Good twice takes it back", failures)
    vote(store, "#ff0000", 1, 3.0)  # Good again, so the next press has a vote to switch
    check(vote(store, "#ff0000", -1, 4.0) == -1, "Bad switches a Good vote", failures)
    check(add_comment(store, "#ff0000", "  nice\n red ", 5.0)["value"]["text"] == "nice red", "comments are cleaned", failures)
    check(not add_comment(store, "#ff0000", "   ", 5.0)["ok"], "an empty comment is refused", failures)
    check(toggle_save(store, "#ff0000", 6.0) and saved_colors(store) == ["#ff0000"], "saving a post", failures)
    posted = add_post(store, "#123456", "", SEED_TIME + 60.0)
    check(posted["ok"] and posted["value"]["caption"] == color_name("#123456"), "posting a new color", failures)
    check(not add_post(store, "#FF0000", "again", SEED_TIME + 120.0)["ok"], "a color already in the feed is refused", failures)
    check(feed_order(store, "new", None)[0] == "#123456", "New puts the newest post first", failures)
    if loaded["ok"]:
        # 216 built-in colors plus the posted one; the only vote left is Bad on red, so it sinks last
        order = feed_order(store, "for_you", loaded["value"])
        check(len(order) == 217 and order[-1] == "#ff0000", "For you puts a Bad post last", failures)
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "social.json")
    check(save_store(path, store)["ok"] and load_store(path) == store, "the store round trip", failures)
    os.remove(path)
    os.rmdir(folder)

    print("words")
    check(color_name("#000000") == "Black" and color_name("#ff0000") == "Red", "color names", failures)
    check(when_text(100.0, 130.0) == "just now" and when_text(0.0, 7200.0) == "2 h ago", "post times", failures)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1

# ==== stamp v1 | author=kjFriday | hmac-sha256=0b7d1df88ceed613631e718f6a141d5489b1267b263a74656be5c3fb8734105b ====
