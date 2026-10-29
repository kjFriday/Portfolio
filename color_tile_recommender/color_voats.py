# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/color_voats.py
# About: Generic Company Color Voats: a social feed of colors, ranked for you by your Good and Bad...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Generic Company Color Voats: a social feed of colors, ranked for you by your Good and Bad votes.

Every post is a color: the 216 colors of the 6x6x6 cube that come with the program, plus colors you
post yourself. A post shows its color, hex code, when it was posted and a caption, with Good, Bad and
Save buttons and a comment section. The Feed tab is sorted For you, by a ranker that factory.py
generates from a preset and its algos' weights, or by New. The Saved tab holds the posts you saved,
and the New post tab shares a color of your own. Everything stays on this computer.

Records
  Post     {"color": "#rrggbb", "caption": str, "when": float, "mine": bool}
  Vote     {"voat": 1 | -1, "when": float}                 one per post: Good is 1, Bad is -1
  Comment  {"text": str, "when": float}
  Store    {"posts": [Post] (yours only), "votes": {color: Vote}, "comments": {color: [Comment]},
            "saved": {color: when saved}}
  Voat     {"color": "#rrggbb", "voat": 1 | -1}            what a ranker reads: your votes, oldest first
  Result   {"ok": bool, "error": str, "value": any}

Usage
  python color_voats.py                   open the window (For you ranked by the "mixer" preset)
  python color_voats.py --preset NAME     rank For you with presets/NAME
  python color_voats.py --data FILE       keep posts, votes, comments and saves in FILE
  python color_voats.py --selftest        run the built-in checks and exit
  python color_voats.py --version
  python color_voats.py --smoke FILE      open the window, use it in memory, write a JSON report, close
"""

import importlib.util
import json
import math
import os
import sys
import tempfile
import time

import algos
import factory

__version__ = "0.2.0"
APP_NAME = "Generic Company Color Voats"
APP_ID = "GenericCompany.ColorVoats"
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FILE = os.path.join(HERE, "icon", "app.ico")

DEFAULT_PRESET = "mixer"
SEED_TIME = 1793188800.0  # 2026-10-28 12:00 UTC: when the built-in colors were posted, before any of yours
CAPTION_LIMIT = 140
COMMENT_LIMIT = 500
PAGE = 20  # posts shown at a time; "Show more" adds the next page
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HUES = ((40.0, "red"), (85.0, "orange"), (125.0, "yellow"), (170.0, "green"), (225.0, "teal"),
        (285.0, "blue"), (320.0, "purple"), (360.0, "pink"))  # OKLab hue angle -> name

COLUMN = 600  # width of the feed column at 96 DPI
SWATCH = 220  # height of a post's color at 96 DPI
FEED_BACKGROUND = "#eef0f3"
CARD = "#ffffff"
CARD_EDGE = "#dadde1"
COMMENT_BACKGROUND = "#f0f2f5"
MUTED = "#65676b"
NEW_POST_COLOR = "#5b8def"
BUTTON_OFF = ("#eef0f3", "#1c1e21")  # (background, text)
GOOD_ON = ("#dcf4e2", "#14662c")
BAD_ON = ("#fde4e2", "#a3231b")
SAVE_ON = ("#e3ecfd", "#1d4ed8")

# =================================================================================================
# CORE: posts, votes, comments, saves and the feed's order. No GUI here.
# =================================================================================================


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def data_folder():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def data_path():
    return os.path.join(data_folder(), "social.json")


def is_number(value):
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, float)):
        return False
    return math.isfinite(value)


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
    and it is cut to `limit` characters."""
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
    chroma (how colorful) and hue."""
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
    """How long ago, the way feeds say it: just now, 5 min ago, 3 h ago, 2 d ago, then the date."""
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


def empty_store():
    return {"posts": [], "votes": {}, "comments": {}, "saved": {}}


def builtin_posts():
    """The 216 colors that come with the program, each captioned with its name."""
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
    (unknown colors, wrong types, empty text) are dropped."""
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
    """Write the store through a temporary file, so a failed write never leaves half a file."""
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
    """Your votes as the voat log a ranker reads, oldest first."""
    rows = []
    for color in store["votes"]:
        rows.append([store["votes"][color]["when"], color])
    rows.sort()
    log = []
    for row in rows:
        log.append({"color": row[1], "voat": store["votes"][row[1]]["voat"]})
    return log


def comments_of(store, color):
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
    """Delete comment number `index` (oldest first) of a post -> True when there was one."""
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
    """Your saved colors, the most recently saved first."""
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


def feed_order(store, sort, ranker):
    """The feed's colors in order: "new" is newest first; "for_you" is the ranker's order for your votes."""
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
    """Generate rankers/ranker_<name>.py when it is missing or out of date, then load it -> Result module."""
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

# =================================================================================================
# SELF-TEST: a quick pass over the core. `python color_voats.py --selftest` (the full suites are test_*.py)
# =================================================================================================


def check(condition, message, failures):
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    failures = []
    colors = algos.palette()
    print("algos")
    check(len(colors) == 216 and len(set(colors)) == 216, "216 different colors", failures)
    white = algos.oklab("#ffffff")
    check(abs(white[0] - 1.0) < 1e-6 and abs(white[1]) < 1e-6 and abs(white[2]) < 1e-6, "white is L 1, a 0, b 0", failures)
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
    vote(store, "#ff0000", 1, 3.0)
    check(vote(store, "#ff0000", -1, 4.0) == -1, "Bad switches a Good vote", failures)
    check(add_comment(store, "#ff0000", "  nice\n red ", 5.0)["value"]["text"] == "nice red", "comments are cleaned", failures)
    check(not add_comment(store, "#ff0000", "   ", 5.0)["ok"], "an empty comment is refused", failures)
    check(toggle_save(store, "#ff0000", 6.0) and saved_colors(store) == ["#ff0000"], "saving a post", failures)
    posted = add_post(store, "#123456", "", SEED_TIME + 60.0)
    check(posted["ok"] and posted["value"]["caption"] == color_name("#123456"), "posting a new color", failures)
    check(not add_post(store, "#FF0000", "again", SEED_TIME + 120.0)["ok"], "a color already in the feed is refused", failures)
    check(feed_order(store, "new", None)[0] == "#123456", "New puts the newest post first", failures)
    if loaded["ok"]:
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

# =================================================================================================
# GUI: tkinter. A feed of post cards; everything it changes goes through the core above.
# =================================================================================================


def windows_identity():
    """Own taskbar button (not Python's) and crisp text on scaled displays. Windows only."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def set_icon(window):
    """The pixel icon on the window and its dialogs -> True when it was set."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


def run_gui(ranker, preset, data_file, smoke_path):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import colorchooser, messagebox, ttk

    windows_identity()
    store = empty_store()
    if smoke_path == "":
        store = load_store(data_file)
    state = {"ranker": ranker, "preset": preset}
    feeds = []

    window = tk.Tk()
    window.title("Generic Company Inc. — Color Voats " + __version__)
    scale = window.winfo_fpixels("1i") / 96.0
    column = int(round(COLUMN * scale))
    height = min(int(round(860 * scale)), window.winfo_screenheight() - int(round(80 * scale)))
    window.geometry(str(column + int(round(60 * scale))) + "x" + str(height))
    window.minsize(int(round(460 * scale)), int(round(420 * scale)))
    icon_set = set_icon(window)

    bold = tkfont.nametofont("TkDefaultFont").copy()
    bold.configure(weight="bold")
    small = tkfont.nametofont("TkDefaultFont").copy()
    size = small.cget("size")
    if size > 0:
        small.configure(size=max(1, size - 1))
    else:
        small.configure(size=min(-1, size + 1))
    mono = tkfont.nametofont("TkFixedFont")

    def say(text):
        status.configure(text=text)

    def keep():
        if smoke_path != "":
            return
        saved = save_store(data_file, store)
        if not saved["ok"]:
            say("Could not save: " + saved["error"])

    def paint(button, text, colors):
        button.configure(text=text, background=colors[0], foreground=colors[1],
                         activebackground=colors[0], activeforeground=colors[1])

    def link(parent, text, background, command):
        return tk.Button(parent, text=text, font=small, relief="flat", borderwidth=0, cursor="hand2",
                         foreground=MUTED, background=background, activebackground=background, command=command)

    def make_comment(card, index, comment):
        color = card["color"]
        bubble = tk.Frame(card["comments"], background=COMMENT_BACKGROUND)
        bubble.pack(fill="x", pady=(0, 6))
        top = tk.Frame(bubble, background=COMMENT_BACKGROUND)
        top.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(top, text="You", font=bold, background=COMMENT_BACKGROUND).pack(side="left")
        tk.Label(top, text=" · " + when_text(comment["when"], time.time()), font=small, foreground=MUTED,
                 background=COMMENT_BACKGROUND).pack(side="left")
        link(top, "Delete", COMMENT_BACKGROUND, lambda: remove_comment(color, index)).pack(side="right")
        tk.Label(bubble, text=comment["text"], anchor="w", justify="left", background=COMMENT_BACKGROUND,
                 wraplength=column - int(round(90 * scale))).pack(fill="x", padx=8, pady=(2, 6))

    def refresh_card(card):
        color = card["color"]
        mine = my_vote(store, color)
        if mine == 1:
            paint(card["good"], "▲ Good 1", GOOD_ON)
        else:
            paint(card["good"], "▲ Good 0", BUTTON_OFF)
        if mine == -1:
            paint(card["bad"], "▼ Bad 1", BAD_ON)
        else:
            paint(card["bad"], "▼ Bad 0", BUTTON_OFF)
        if color in store["saved"]:
            paint(card["save"], "Saved", SAVE_ON)
        else:
            paint(card["save"], "Save", BUTTON_OFF)
        comments = comments_of(store, color)
        if len(comments) == 1:
            card["count"].configure(text="1 comment")
        else:
            card["count"].configure(text=str(len(comments)) + " comments")
        for child in card["comments"].winfo_children():
            child.destroy()
        for index in range(len(comments)):
            make_comment(card, index, comments[index])

    def make_card(feed, post):
        color = post["color"]
        card = {"color": color}
        frame = tk.Frame(feed["inner"], background=CARD, highlightthickness=1, highlightbackground=CARD_EDGE)
        frame.pack(fill="x", padx=12, pady=(12, 0))
        card["frame"] = frame
        head = tk.Frame(frame, background=CARD)
        head.pack(fill="x", padx=12, pady=(10, 8))
        author = "Color Voats"
        if post["mine"]:
            author = "You"
        tk.Label(head, text=author, font=bold, background=CARD).pack(side="left")
        tk.Label(head, text=" · " + when_text(post["when"], time.time()), font=small, foreground=MUTED,
                 background=CARD).pack(side="left")
        if post["mine"]:
            link(head, "Delete post", CARD, lambda: remove_post(color)).pack(side="right")
        tk.Frame(frame, background=color, height=int(round(SWATCH * scale))).pack(fill="x")
        tk.Label(frame, text=post["caption"], anchor="w", justify="left", background=CARD,
                 wraplength=column - int(round(60 * scale))).pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(frame, text=color, font=mono, anchor="w", foreground=MUTED, background=CARD).pack(fill="x", padx=12)
        actions = tk.Frame(frame, background=CARD)
        actions.pack(fill="x", padx=8, pady=8)
        card["good"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                 command=lambda: press(color, 1))
        card["bad"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                command=lambda: press(color, -1))
        card["save"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                 command=lambda: save_post(color))
        card["good"].pack(side="left", padx=4)
        card["bad"].pack(side="left", padx=4)
        card["save"].pack(side="left", padx=4)
        card["count"] = tk.Label(actions, font=small, foreground=MUTED, background=CARD)
        card["count"].pack(side="right", padx=4)
        card["comments"] = tk.Frame(frame, background=CARD)
        card["comments"].pack(fill="x", padx=12)
        write = tk.Frame(frame, background=CARD)
        write.pack(fill="x", padx=12, pady=(4, 12))
        card["entry"] = ttk.Entry(write)
        card["entry"].pack(side="left", fill="x", expand=True)
        card["post"] = ttk.Button(write, text="Comment", command=lambda: comment(card))
        card["post"].pack(side="left", padx=(6, 0))
        card["entry"].bind("<Return>", lambda event: comment(card))
        feed["cards"][color] = card
        refresh_card(card)

    def make_feed(parent):
        canvas = tk.Canvas(parent, background=FEED_BACKGROUND, highlightthickness=0, borderwidth=0,
                           yscrollincrement=int(round(20 * scale)))
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, background=FEED_BACKGROUND)
        item = canvas.create_window(0, 0, window=inner, anchor="nw")
        feed = {"canvas": canvas, "inner": inner, "cards": {}, "order": [], "shown": 0, "more": None, "empty": None}

        def fit_content(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_column(event):
            width = min(event.width, column)
            canvas.coords(item, max(0, (event.width - width) // 2), 0)
            canvas.itemconfigure(item, width=width)

        inner.bind("<Configure>", fit_content)
        canvas.bind("<Configure>", fit_column)
        feeds.append(feed)
        return feed

    def show(feed, order, empty_text):
        for color in feed["cards"]:
            feed["cards"][color]["frame"].destroy()
        feed["cards"] = {}
        for key in ("more", "empty"):
            if feed[key] is not None:
                feed[key].destroy()
                feed[key] = None
        feed["order"] = list(order)
        feed["shown"] = 0
        if len(order) == 0:
            feed["empty"] = tk.Label(feed["inner"], text=empty_text, foreground=MUTED, background=FEED_BACKGROUND, pady=40)
            feed["empty"].pack(fill="x")
        more(feed)
        feed["canvas"].yview_moveto(0.0)

    def more(feed):
        posts = {}
        for post in all_posts(store):
            posts[post["color"]] = post
        if feed["more"] is not None:
            feed["more"].destroy()
            feed["more"] = None
        stop = min(len(feed["order"]), feed["shown"] + PAGE)
        while feed["shown"] < stop:
            color = feed["order"][feed["shown"]]
            if color in posts:
                make_card(feed, posts[color])
            feed["shown"] = feed["shown"] + 1
        if feed["shown"] < len(feed["order"]):
            feed["more"] = ttk.Button(feed["inner"], text="Show more", command=lambda: more(feed))
            feed["more"].pack(pady=16)
        elif len(feed["order"]) > 0:
            feed["more"] = tk.Label(feed["inner"], text="You're all caught up.", foreground=MUTED,
                                    background=FEED_BACKGROUND, pady=16)
            feed["more"].pack(fill="x")

    def drop_card(feed, color):
        if color in feed["order"]:
            if feed["order"].index(color) < feed["shown"]:
                feed["shown"] = feed["shown"] - 1
            feed["order"].remove(color)
        if color in feed["cards"]:
            feed["cards"][color]["frame"].destroy()
            del feed["cards"][color]

    def each_card(color):
        cards = []
        for feed in feeds:
            if color in feed["cards"]:
                cards.append(feed["cards"][color])
        return cards

    def press(color, voat):
        now = vote(store, color, voat, time.time())
        keep()
        for card in each_card(color):
            refresh_card(card)
        if now == 1:
            say("Marked Good. Refresh to see what it changes in For you.")
        elif now == -1:
            say("Marked Bad. Refresh to see what it changes in For you.")
        else:
            say("Vote taken back.")

    def save_post(color):
        if toggle_save(store, color, time.time()):
            say("Saved. It's in the Saved tab.")
        else:
            say("Removed from Saved.")
        keep()
        for card in each_card(color):
            refresh_card(card)

    def comment(card):
        added = add_comment(store, card["color"], card["entry"].get(), time.time())
        if not added["ok"]:
            say(added["error"])
            return
        card["entry"].delete(0, "end")
        keep()
        for each in each_card(card["color"]):
            refresh_card(each)
        say("Comment posted.")

    def remove_comment(color, index):
        if delete_comment(store, color, index):
            keep()
            for card in each_card(color):
                refresh_card(card)
            say("Comment deleted.")

    def remove_post(color):
        if not messagebox.askyesno("Delete post", "Delete your post " + color + " and its comments?", parent=window):
            return
        if delete_post(store, color):
            keep()
            for feed in feeds:
                drop_card(feed, color)
            say("Post deleted.")

    def refresh_feed():
        show(feed_view, feed_order(store, sort_choice.get(), state["ranker"]), "No posts yet.")
        if sort_choice.get() == "for_you":
            presets.configure(state="readonly")
        else:
            presets.configure(state="disabled")

    def change_preset(event):
        name = preset_choice.get()
        if name == state["preset"]:
            return
        loaded = load_ranker(name)
        if not loaded["ok"]:
            preset_choice.set(state["preset"])
            say(loaded["error"])
            return
        state["ranker"] = loaded["value"]
        state["preset"] = name
        refresh_feed()
        say("For you is now ranked by the " + name + " preset.")

    def refresh_saved():
        show(saved_view, saved_colors(store), "Nothing saved yet. Press Save on a post to keep it here.")

    def tab_changed(event):
        if tabs.index(tabs.select()) == 1:
            refresh_saved()

    def wheel(event):
        current = tabs.index(tabs.select())
        if current > 1:
            return
        canvas = feed_view["canvas"]
        if current == 1:
            canvas = saved_view["canvas"]
        if not str(event.widget).startswith(str(canvas)):
            return
        if event.num == 4:
            steps = -1
        elif event.num == 5:
            steps = 1
        elif event.delta > 0:
            steps = -max(1, event.delta // 120)
        else:
            steps = max(1, -event.delta // 120)
        canvas.yview_scroll(steps * 3, "units")

    def show_preview(*arguments):
        color = normalize_hex(new_color.get())
        if color != "":
            preview.configure(background=color)

    def pick():
        start = normalize_hex(new_color.get())
        if start == "":
            start = NEW_POST_COLOR
        chosen = colorchooser.askcolor(color=start, title="Pick a color", parent=window)
        if chosen is not None and chosen[1] is not None:
            new_color.set(normalize_hex(chosen[1]))

    def publish():
        made = add_post(store, new_color.get(), caption_entry.get(), time.time())
        if not made["ok"]:
            problem.configure(text=made["error"])
            return
        problem.configure(text="")
        caption_entry.delete(0, "end")
        keep()
        sort_choice.set("new")
        tabs.select(0)
        refresh_feed()
        say("Posted " + made["value"]["color"] + ". It's at the top of New.")

    status = ttk.Label(window, anchor="w", padding=(10, 3))
    status.pack(side="bottom", fill="x")
    tabs = ttk.Notebook(window)
    tabs.pack(fill="both", expand=True)
    feed_tab = ttk.Frame(tabs)
    saved_tab = ttk.Frame(tabs)
    new_tab = ttk.Frame(tabs, padding=16)
    tabs.add(feed_tab, text="Feed")
    tabs.add(saved_tab, text="Saved")
    tabs.add(new_tab, text="New post")

    bar = ttk.Frame(feed_tab, padding=(10, 6))
    bar.pack(fill="x")
    sort_choice = tk.StringVar(value="for_you")
    ttk.Radiobutton(bar, text="For you", value="for_you", variable=sort_choice, command=refresh_feed).pack(side="left")
    ttk.Radiobutton(bar, text="New", value="new", variable=sort_choice, command=refresh_feed).pack(side="left", padx=(10, 0))
    ttk.Label(bar, text="Ranking").pack(side="left", padx=(18, 6))
    preset_choice = tk.StringVar(value=preset)
    presets = ttk.Combobox(bar, textvariable=preset_choice, values=factory.preset_names(HERE), state="readonly", width=12)
    presets.pack(side="left")
    ttk.Button(bar, text="Refresh", command=refresh_feed).pack(side="right")
    feed_view = make_feed(feed_tab)
    saved_view = make_feed(saved_tab)

    ttk.Label(new_tab, text="Share a color", font=bold).pack(anchor="w", pady=(0, 10))
    preview = tk.Frame(new_tab, background=NEW_POST_COLOR, height=int(round(SWATCH * scale)),
                       highlightthickness=1, highlightbackground=CARD_EDGE)
    preview.pack(fill="x")
    row = ttk.Frame(new_tab)
    row.pack(fill="x", pady=(12, 0))
    ttk.Label(row, text="Color").pack(side="left")
    new_color = tk.StringVar(value=NEW_POST_COLOR)
    ttk.Entry(row, textvariable=new_color, width=10, font=mono).pack(side="left", padx=8)
    ttk.Button(row, text="Pick a color…", command=pick).pack(side="left")
    ttk.Label(new_tab, text="Caption").pack(anchor="w", pady=(12, 2))
    caption_entry = ttk.Entry(new_tab)
    caption_entry.pack(fill="x")
    ttk.Label(new_tab, text="Up to " + str(CAPTION_LIMIT) + " characters. Leave it empty to use the color's name.",
              foreground=MUTED).pack(anchor="w", pady=(2, 0))
    post_button = ttk.Button(new_tab, text="Post", command=publish)
    post_button.pack(anchor="e", pady=(12, 0))
    problem = ttk.Label(new_tab, foreground=BAD_ON[1])
    problem.pack(anchor="w")

    new_color.trace_add("write", show_preview)
    presets.bind("<<ComboboxSelected>>", change_preset)
    tabs.bind("<<NotebookTabChanged>>", tab_changed)
    caption_entry.bind("<Return>", lambda event: publish())
    window.bind("<F5>", lambda event: refresh_feed())
    window.bind_all("<MouseWheel>", wheel)
    if window.tk.call("tk", "windowingsystem") == "x11":
        window.bind_all("<Button-4>", wheel)
        window.bind_all("<Button-5>", wheel)
    refresh_feed()
    say("Good and Bad teach the For you ranking. Refresh to re-rank.")

    if smoke_path != "":
        def write_smoke_report():
            window.update()
            first = feed_view["order"][0]
            card = feed_view["cards"][first]
            card["good"].invoke()
            vote_ok = my_vote(store, first) == 1 and card["good"].cget("text").endswith(" 1")
            card["save"].invoke()
            save_ok = first in store["saved"] and card["save"].cget("text") == "Saved"
            card["entry"].insert(0, "smoke comment")
            card["post"].invoke()
            comment_ok = len(comments_of(store, first)) == 1 and len(card["comments"].winfo_children()) == 1
            tabs.select(1)
            window.update()
            saved_tab_ok = list(saved_view["cards"]) == [first]
            tabs.select(2)
            window.update()
            new_color.set("#123456")
            caption_entry.insert(0, "smoke post")
            post_button.invoke()
            window.update()
            report = {"app_id": APP_ID, "version": __version__, "title": window.title(), "icon_set": icon_set,
                      "preset": state["preset"], "tabs": [], "posts": len(all_posts(store)),
                      "cards_shown": len(feed_view["cards"]), "vote_ok": vote_ok, "save_ok": save_ok,
                      "comment_ok": comment_ok, "saved_tab_ok": saved_tab_ok,
                      "post_ok": feed_view["order"][0] == "#123456" and tabs.index(tabs.select()) == 0}
            for tab_id in tabs.tabs():
                report["tabs"].append(tabs.tab(tab_id, "text"))
            with open(smoke_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
            window.destroy()

        window.after(800, write_smoke_report)

    window.mainloop()
    return 0


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing."""
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        return selftest()
    preset = option_value(arguments, "--preset")
    data_file = option_value(arguments, "--data")
    smoke_path = option_value(arguments, "--smoke")
    if preset is None or data_file is None or smoke_path is None:
        print("--preset needs a name, --data and --smoke a file")
        return 2
    if preset == "":
        preset = DEFAULT_PRESET
    if data_file == "":
        data_file = data_path()
    loaded = load_ranker(preset)
    if not loaded["ok"]:
        print(loaded["error"], file=sys.stderr)
        return 1
    return run_gui(loaded["value"], preset, data_file, smoke_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=5e385a80752eb664ab593bc782b9265d1a9aab74505ec0ef1dc79527b45477a0 ====
