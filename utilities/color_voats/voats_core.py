# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: voats_core.py
# About: Color Voats' core: posts, votes, comments, saves, the store file and the feed's order.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Color Voats' core: posts, votes, comments, saves, the store file and the feed's order. No GUI here.

Every post is a color: the 216 colors of the 6x6x6 cube that come with the program (algos.palette(),
captioned with their names), plus colors you post. load_store() reads and checks the store file and
save_store() writes it through a temporary file. feed_order() puts the posts in New order, or in For you
order through a ranker: the module factory.py writes from a preset, which load_ranker() loads (writing it
first when it is missing or out of date). The window (voats_gui.py) and the self-test
(voats_selftest.py) change the store only through these functions.

Records
  Post     {"color": "#rrggbb", "caption": str, "when": float, "mine": bool}
  Vote     {"voat": 1 | -1, "when": float}                 one per post: Good is 1, Bad is -1
  Comment  {"text": str, "when": float}
  Store    {"posts": [Post] (yours only), "votes": {color: Vote}, "comments": {color: [Comment]},
            "saved": {color: when saved}}
  Voat     {"color": "#rrggbb", "voat": 1 | -1}            what a ranker reads: your votes, oldest first
  Result   {"ok": bool, "error": str, "value": any}

The built-in posts are never stored: all_posts() makes them again from the palette each time, and
the store keeps only your own posts and what you did. Every function that changes a store changes
the dict in place; the caller saves it with save_store().

Main flow of one button press (in the window)
  1. A handler calls vote(), toggle_save(), add_comment(), add_post() or a delete function.
  2. The window saves the store at once with save_store(data_path()).
  3. On Refresh, feed_order() builds the voat log (voat_log) and asks the ranker for the order.

Start reading at feed_order() and load_store().
"""

import importlib.util
import json
import math
import os
import time

import algos
import factory

APP_ID = "GenericCompany.ColorVoats"  # also setup.json's id and appUserModelId, and the data folder's name
HERE = os.path.dirname(os.path.abspath(__file__))  # presets/, weights/, rankers/ and icon/ sit beside it

DEFAULT_PRESET = "mixer"  # the preset For you uses unless --preset names another
SEED_TIME = 1793188800.0  # 2026-10-28 12:00 UTC: when the built-in colors were posted, before any of yours
CAPTION_LIMIT = 140  # characters a caption keeps; longer text is cut, not refused
COMMENT_LIMIT = 500  # characters a comment keeps
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # for when_text's dates
# each pair is (upper bound in degrees, name): a hue below the bound and at or above the previous one takes
# that name. The angle is atan2(b, a) in OKLab: pure red sits at about 29 degrees, yellow about 110,
# green about 142, blue about 264 and magenta about 328 (which this table calls pink)
HUES = ((40.0, "red"), (85.0, "orange"), (125.0, "yellow"), (170.0, "green"), (225.0, "teal"),
        (285.0, "blue"), (320.0, "purple"), (360.0, "pink"))  # OKLab hue angle -> name

# --- Results, numbers and where the store lives --------------------------------------------------


def ok_result(value):
    """A Result that worked, holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A Result that failed, with `error` saying why."""
    return {"ok": False, "error": error, "value": None}


def data_folder():
    """Where the store lives: Generic Company Inc/<APP_ID> in LOCALAPPDATA (or in the home folder when
    LOCALAPPDATA is not set). setup.json's purge removes the same folder."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def data_path():
    """The store file, social.json in data_folder(). QR Palette imports your votes from it."""
    return os.path.join(data_folder(), "social.json")


def is_number(value):
    """True for a finite int or float; a bool is not a number."""
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, float)):
        return False
    return math.isfinite(value)

# --- Words: hex codes, kept text, color names and times ------------------------------------------


def normalize_hex(text):
    """A color typed as #RRGGBB or rrggbb, as "#rrggbb"; "" when it is not one."""
    if not isinstance(text, str):
        return ""
    value = text.strip().lower()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return ""
    for character in value:
        if character not in "0123456789abcdef":
            return ""
    return "#" + value


def clean_text(text, limit):
    """Text as it is kept: control characters and line breaks become spaces, runs of spaces one space,
    and it is cut to `limit` characters. Control means code points 0-31 and 127 (DEL); split() then
    folds every run of whitespace, so the result has no leading, trailing or double spaces.
    Not a string gives ""."""
    if not isinstance(text, str):
        return ""
    characters = []
    for character in text:
        if ord(character) < 32 or ord(character) == 127:
            characters.append(" ")
        else:
            characters.append(character)
    return " ".join("".join(characters).split())[:limit].strip()


def color_name(color):
    """A plain name for a color, such as "Dark teal" or "Light grey", from its OKLab lightness,
    chroma (how colorful) and hue.

    Steps:
      1. Chroma is the length of (a, b): how far the color is from grey. Under 0.03 the color is a
         grey, named by lightness alone (Black, Dark grey, Grey, Light grey, White).
      2. Otherwise the hue angle picks a name from HUES.
      3. Dark orange is brown and dark yellow is olive, as people name them.
      4. A prefix by lightness and chroma: dark, light (only when pale) or muted, then capitalized.
    The thresholds are OKLab values (L 0..1, chroma about 0..0.32 for sRGB colors); the tests pin a
    sample of names. QR Palette keeps its own copy of this function, which a change here does not update.
    """
    lab = algos.oklab(color)
    lightness = lab[0]
    chroma = math.sqrt(lab[1] * lab[1] + lab[2] * lab[2])
    if chroma < 0.03:
        if lightness > 0.97:
            return "White"
        if lightness < 0.2:
            return "Black"
        if lightness > 0.75:
            return "Light grey"
        if lightness < 0.45:
            return "Dark grey"
        return "Grey"
    hue = math.degrees(math.atan2(lab[2], lab[1])) % 360.0
    name = "pink"
    for bound in HUES:
        if hue < bound[0]:
            name = bound[1]
            break
    if name == "orange" and lightness < 0.6:
        name = "brown"
    if name == "yellow" and lightness < 0.6:
        name = "olive"
    if lightness < 0.45:
        name = "dark " + name
    elif lightness > 0.8 and chroma < 0.15:
        name = "light " + name
    elif chroma < 0.08:
        name = "muted " + name
    return name.capitalize()


def when_text(then, now):
    """How long ago, the way feeds say it: just now, 5 min ago, 3 h ago, 2 d ago, then the date.

    `then` and `now` are seconds since the epoch. A time in the future also reads "just now" (a
    clock set back must not show a negative age). From a week on it is the local date, "Oct 28, 2026".
    """
    seconds = now - then
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return str(int(seconds // 60)) + " min ago"
    if seconds < 86400:
        return str(int(seconds // 3600)) + " h ago"
    if seconds < 7 * 86400:
        return str(int(seconds // 86400)) + " d ago"
    moment = time.localtime(then)
    return MONTHS[moment.tm_mon - 1] + " " + str(moment.tm_mday) + ", " + str(moment.tm_year)

# --- The store -----------------------------------------------------------------------------------


def empty_store():
    """A store with no posts, votes, comments or saves of yours."""
    return {"posts": [], "votes": {}, "comments": {}, "saved": {}}


def builtin_posts():
    """The 216 colors that come with the program, each captioned with its name, in palette order and all
    posted at SEED_TIME. Made afresh on every call; they are never written to the store."""
    posts = []
    for color in algos.palette():
        posts.append({"color": color, "caption": color_name(color), "when": SEED_TIME, "mine": False})
    return posts


def all_posts(store):
    """Every post: the built-in colors, then yours, oldest first."""
    posts = builtin_posts()
    for post in store["posts"]:
        posts.append(post)
    return posts


def load_store(path):
    """The store in `path`, checked: a missing or broken file is an empty store, and bad entries
    (unknown colors, wrong types, empty text) are dropped.

    The file is hand-editable JSON, so nothing in it is trusted. Steps:
      1. Read and parse it; any read or parse error, or a top level that is not an object, gives an
         empty store.
      2. Posts: keep each one with a valid new color and a numeric time. A color that is built in or
         already posted is skipped (each color is posted once); the caption is cleaned, or becomes
         the color's name when empty. Kept posts are marked "mine".
      3. Votes, comments and saves: keep only entries on known colors (built-in or a kept post),
         with the right types: a vote of exactly 1 or -1 (an int, so True is refused), comments with
         text left after cleaning, saves with a numeric time.
    Keys are normalized, so "#FF0000" in the file becomes "#ff0000".
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return empty_store()
    store = empty_store()
    if not isinstance(data, dict):
        return store
    known = {}
    for color in algos.palette():
        known[color] = True
    posts = data.get("posts")
    if isinstance(posts, list):
        for post in posts:
            if not isinstance(post, dict) or not is_number(post.get("when")):
                continue
            color = normalize_hex(post.get("color"))
            if color == "" or color in known:
                continue
            caption = clean_text(post.get("caption"), CAPTION_LIMIT)
            if caption == "":
                caption = color_name(color)
            known[color] = True
            store["posts"].append({"color": color, "caption": caption, "when": float(post["when"]), "mine": True})
    votes = data.get("votes")
    if isinstance(votes, dict):
        for key in votes:
            color = normalize_hex(key)
            vote = votes[key]
            # type() is int, not isinstance: JSON true would otherwise pass as the vote 1
            if color in known and isinstance(vote, dict) and type(vote.get("voat")) is int:
                if (vote["voat"] == 1 or vote["voat"] == -1) and is_number(vote.get("when")):
                    store["votes"][color] = {"voat": vote["voat"], "when": float(vote["when"])}
    comments = data.get("comments")
    if isinstance(comments, dict):
        for key in comments:
            color = normalize_hex(key)
            if color not in known or not isinstance(comments[key], list):
                continue
            kept = []
            for comment in comments[key]:
                if isinstance(comment, dict) and is_number(comment.get("when")):
                    text = clean_text(comment.get("text"), COMMENT_LIMIT)
                    if text != "":
                        kept.append({"text": text, "when": float(comment["when"])})
            if len(kept) > 0:
                store["comments"][color] = kept
    saved = data.get("saved")
    if isinstance(saved, dict):
        for key in saved:
            color = normalize_hex(key)
            if color in known and is_number(saved[key]):
                store["saved"][color] = float(saved[key])
    return store


def save_store(path, store):
    """Write the store through a temporary file, so a failed write never leaves half a file -> Result path.

    Steps: make the folder if needed, write JSON to <path>.tmp, then os.replace() it over `path`.
    os.replace is atomic on one volume, so a reader sees the old file or the new one, never a mix.
    Errors: an OSError (no folder rights, disk full) becomes a failed Result; the old file stays.
    """
    folder = os.path.dirname(path)
    try:
        if folder != "" and not os.path.isdir(folder):
            os.makedirs(folder)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=1)
        os.replace(temporary, path)
    except OSError as error:
        return fail(str(error))
    return ok_result(path)

# --- Votes, comments, saves and posts ------------------------------------------------------------


def my_vote(store, color):
    """Your vote on a post: 1 for Good, -1 for Bad, 0 for none."""
    vote = store["votes"].get(color)
    if vote is None:
        return 0
    return vote["voat"]


def vote(store, color, voat, now):
    """Press Good (1) or Bad (-1) on a post, as on any feed: pressing your vote again takes it back,
    and pressing the other one switches it. Changes `store`; returns your vote now (0 for none)."""
    if my_vote(store, color) == voat:
        del store["votes"][color]
        return 0
    store["votes"][color] = {"voat": voat, "when": now}
    return voat


def voat_log(store):
    """Your votes as the voat log a ranker reads, oldest first.

    Sorted by vote time, then by color for equal times, so the log is the same on every run. Order
    matters: the mixer reads downvoat streaks from it. A switched vote counts from when it was switched.
    """
    rows = []
    for color in store["votes"]:
        rows.append([store["votes"][color]["when"], color])
    rows.sort()
    log = []
    for row in rows:
        log.append({"color": row[1], "voat": store["votes"][row[1]]["voat"]})
    return log


def comments_of(store, color):
    """The comments on a post, oldest first ([] when it has none)."""
    return store["comments"].get(color, [])


def add_comment(store, color, text, now):
    """Add your comment to a post -> Result comment. Empty text is refused; long text is cut."""
    cleaned = clean_text(text, COMMENT_LIMIT)
    if cleaned == "":
        return fail("Write something first.")
    comment = {"text": cleaned, "when": now}
    if color not in store["comments"]:
        store["comments"][color] = []
    store["comments"][color].append(comment)
    return ok_result(comment)


def delete_comment(store, color, index):
    """Delete comment number `index` (oldest first) of a post -> True when there was one. A post left
    with no comments loses its entry, so the store holds no empty lists."""
    comments = store["comments"].get(color, [])
    if index < 0 or index >= len(comments):
        return False
    del comments[index]
    if len(comments) == 0:
        del store["comments"][color]
    return True


def toggle_save(store, color, now):
    """Save a post to your collection, or take it out again -> True when it is saved now."""
    if color in store["saved"]:
        del store["saved"][color]
        return False
    store["saved"][color] = now
    return True


def saved_colors(store):
    """Your saved colors, the most recently saved first (the time is negated so an ascending sort puts
    the newest first; equal times fall back to the color)."""
    rows = []
    for color in store["saved"]:
        rows.append([-store["saved"][color], color])
    rows.sort()
    colors = []
    for row in rows:
        colors.append(row[1])
    return colors


def add_post(store, text, caption, now):
    """Post a color of your own -> Result post. The color must be new to the feed; an empty caption
    becomes the color's name."""
    color = normalize_hex(text)
    if color == "":
        return fail("Type a color as #rrggbb, or pick one.")
    for post in all_posts(store):
        if post["color"] == color:
            return fail(color + " is already in the feed.")
    cleaned = clean_text(caption, CAPTION_LIMIT)
    if cleaned == "":
        cleaned = color_name(color)
    post = {"color": color, "caption": cleaned, "when": now, "mine": True}
    store["posts"].append(post)
    return ok_result(post)


def delete_post(store, color):
    """Delete one of your own posts with its vote, comments and save -> True when it was yours."""
    kept = []
    found = False
    for post in store["posts"]:
        if post["color"] == color:
            found = True
        else:
            kept.append(post)
    if not found:
        return False
    store["posts"] = kept
    for part in ("votes", "comments", "saved"):
        if color in store[part]:
            del store[part][color]
    return True

# --- The feed's order and its ranker -------------------------------------------------------------


def feed_order(store, sort, ranker):
    """The feed's colors in order: "new" is newest first; "for_you" is the ranker's order for your votes.

    `ranker` is a module from load_ranker (only its rank(voats, colors) is used); it may be None for
    "new". Any sort other than "for_you" is New. In New, posts with the same time (all the built-in
    colors share SEED_TIME) keep palette order, because the row's second element is the post's index.
    """
    posts = all_posts(store)
    if sort == "for_you":
        colors = []
        for post in posts:
            colors.append(post["color"])
        return ranker.rank(voat_log(store), colors)
    rows = []
    for index in range(len(posts)):
        rows.append([-posts[index]["when"], index])
    rows.sort()
    ordered = []
    for row in rows:
        ordered.append(posts[row[1]]["color"])
    return ordered


def load_ranker(name):
    """Generate rankers/ranker_<name>.py when it is missing or out of date, then load it -> Result module.
    This writes into rankers/ beside the program: app launches, preset switches, --selftest and the tests
    all rewrite a stale ranker this way.

    The ranker is loaded by file path as module "ranker_<name>" (rankers/ is not a package), and it is
    not added to sys.modules, so loading it again after a rewrite gives the new code. Any error while
    running the module's top level becomes a failed Result naming the file.
    """
    made = factory.ensure(HERE, name)
    if not made["ok"]:
        return made
    path = made["value"]["path"]
    try:
        spec = importlib.util.spec_from_file_location("ranker_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:
        return fail(path + ": " + str(error))
    return ok_result(module)

# ==== stamp v1 | author=kjFriday | hmac-sha256=84a7e7645ba38c12f0f6dda6427ffbd0447551137d0bf615720beef22360cbcd ====
