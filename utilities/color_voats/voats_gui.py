# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: voats_gui.py
# About: Color Voats' window: a tkinter feed of post cards.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Color Voats' window: a tkinter feed of post cards. Everything it changes goes through voats_core.

VoatsWindow builds the window and holds what its handlers share: the store, the ranker and its preset, the
two feeds and the widgets the handlers read. There are three tabs: Feed (For you or New, with the ranking
preset and Refresh), Saved and New post. A feed is a canvas that scrolls one frame of post cards, PAGE at a
time with Show more. A vote, save, comment or post is saved at once (keep) and redraws every card of that
color in both feeds; For you re-ranks only on Refresh or F5, a sort change or a preset change.

Records
  Card   {"color", "frame", "good", "bad", "save", "count", "comments", "entry", "comment_button"}: the
         widgets of one post card, which refresh_card redraws from the store
  Feed   {"canvas", "inner", "cards": {color: Card}, "order": [color], "shown": int, "more", "empty"}: one
         scrolling list of cards. "shown" counts the places of "order" paged in so far, deleted colors
         included; "more" is the Show more button or the caught-up note, "empty" the note for no posts
  Smoke  {"app_id", "version", "title", "icon_set", "preset", "tabs", "posts", "cards_shown", "vote_ok",
         "save_ok", "comment_ok", "saved_tab_ok", "post_ok"}: the report --smoke FILE writes
"""

import json
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, messagebox, ttk

import factory
from voats_core import (APP_ID, CAPTION_LIMIT, HERE, add_comment, add_post, all_posts, comments_of, delete_comment,
                        delete_post, empty_store, feed_order, load_ranker, load_store, my_vote, normalize_hex,
                        save_store, saved_colors, toggle_save, vote, when_text)

ICON_FILE = os.path.join(HERE, "icon", "app.ico")
PAGE = 20  # posts shown at a time; "Show more" adds the next page

# Sizes in pixels at 96 DPI; the window scales them to the screen.
COLUMN = 600  # width of the feed column at 96 DPI
SWATCH = 220  # height of a post's color at 96 DPI
WINDOW_HEIGHT = 860  # the window's height when the screen has room for it
SCREEN_MARGIN = 80  # screen height the window leaves free (for the taskbar)
WINDOW_MARGIN = 60  # how much wider the window is than the column (the scrollbar and the cards' margins)
MIN_WIDTH = 460  # the smallest the window can be made
MIN_HEIGHT = 420
CAPTION_MARGIN = 60  # a caption wraps this much short of the column's width
COMMENT_MARGIN = 90  # a comment wraps this much short of the column's width
SCROLL_UNIT = 20  # one scroll step of a feed

WHEEL_NOTCH = 120  # the wheel delta of one notch on Windows (macOS reports smaller deltas)
WHEEL_UNITS = 3  # scroll steps per notch
FEED_TAB = 0  # the notebook's tabs, in the order they are added
SAVED_TAB = 1
NEW_POST_TAB = 2
SMOKE_DELAY = 800  # milliseconds a --smoke run lets the window settle before it uses it

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


def run_gui(ranker, preset, data_file, smoke_path, version):
    """Open the window and run it until it closes -> exit code 0. See VoatsWindow."""
    return VoatsWindow(ranker, preset, data_file, smoke_path, version).run()


class VoatsWindow:
    """The Color Voats window over one store. Make it, then run() it."""

    def __init__(self, ranker, preset, data_file, smoke_path, version):
        """Open the window on the store in `data_file` (an empty store in memory when `smoke_path` is set,
        which also schedules the smoke run), with For you ranked by `ranker`, the module of `preset`.
        `version` goes in the title."""
        self.data_file = data_file
        self.smoke_path = smoke_path
        self.version = version
        windows_identity()  # before tk.Tk(): the taskbar identity and DPI awareness must come first
        self.store = empty_store()
        if smoke_path == "":
            self.store = load_store(data_file)
        self.ranker = ranker
        self.preset = preset
        self.feeds = []

        self.window = tk.Tk()
        self.window.title("Generic Company Inc. — Color Voats " + version)
        self.size_window()
        self.icon_set = set_icon(self.window)
        self.make_fonts()
        self.make_tabs()
        self.bind_events()
        self.refresh_feed()
        self.say("Good and Bad teach the For you ranking. Refresh to re-rank.")
        if smoke_path != "":
            self.window.after(SMOKE_DELAY, self.write_smoke_report)

    def run(self):
        """Run the window until it is closed -> exit code 0."""
        self.window.mainloop()
        return 0

    # --- Building the window ---------------------------------------------------------------------

    def size_window(self):
        """Size the window to the column and the screen. self.scale is the screen's pixels per inch over 96
        (1.0 at 100 %, 1.5 at 150 %); self.column is the feed column's width in pixels."""
        self.scale = self.window.winfo_fpixels("1i") / 96.0
        self.column = int(round(COLUMN * self.scale))
        height = min(int(round(WINDOW_HEIGHT * self.scale)),
                     self.window.winfo_screenheight() - int(round(SCREEN_MARGIN * self.scale)))
        self.window.geometry(str(self.column + int(round(WINDOW_MARGIN * self.scale))) + "x" + str(height))
        self.window.minsize(int(round(MIN_WIDTH * self.scale)), int(round(MIN_HEIGHT * self.scale)))

    def make_fonts(self):
        """Tk's default font in bold (self.bold) and one size smaller (self.small), and its fixed font (self.mono)."""
        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        self.small = tkfont.nametofont("TkDefaultFont").copy()
        size = self.small.cget("size")
        if size > 0:  # a positive Tk size is in points, a negative one in pixels: one smaller either way
            self.small.configure(size=max(1, size - 1))
        else:
            self.small.configure(size=min(-1, size + 1))
        self.mono = tkfont.nametofont("TkFixedFont")

    def make_tabs(self):
        """The status bar at the bottom and the notebook with its three tabs and their contents."""
        self.status = ttk.Label(self.window, anchor="w", padding=(10, 3))
        self.status.pack(side="bottom", fill="x")
        self.tabs = ttk.Notebook(self.window)
        self.tabs.pack(fill="both", expand=True)
        feed_tab = ttk.Frame(self.tabs)
        saved_tab = ttk.Frame(self.tabs)
        new_tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(feed_tab, text="Feed")
        self.tabs.add(saved_tab, text="Saved")
        self.tabs.add(new_tab, text="New post")
        self.make_toolbar(feed_tab)
        self.feed_view = self.make_feed(feed_tab)
        self.saved_view = self.make_feed(saved_tab)
        self.make_new_post(new_tab)

    def make_toolbar(self, parent):
        """The Feed tab's toolbar: For you or New (self.sort_choice), the ranking preset (self.preset_box,
        whose name is self.preset_choice) and Refresh."""
        toolbar = ttk.Frame(parent, padding=(10, 6))
        toolbar.pack(fill="x")
        self.sort_choice = tk.StringVar(value="for_you")
        ttk.Radiobutton(toolbar, text="For you", value="for_you", variable=self.sort_choice,
                        command=self.refresh_feed).pack(side="left")
        ttk.Radiobutton(toolbar, text="New", value="new", variable=self.sort_choice,
                        command=self.refresh_feed).pack(side="left", padx=(10, 0))
        ttk.Label(toolbar, text="Ranking").pack(side="left", padx=(18, 6))
        self.preset_choice = tk.StringVar(value=self.preset)
        self.preset_box = ttk.Combobox(toolbar, textvariable=self.preset_choice, values=factory.preset_names(HERE),
                                       state="readonly", width=12)
        self.preset_box.pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=self.refresh_feed).pack(side="right")

    def make_new_post(self, parent):
        """The New post tab: a preview of the color, the color typed or picked (self.new_color), a caption
        (self.caption_entry), Post (self.post_button) and a line for what went wrong (self.problem)."""
        ttk.Label(parent, text="Share a color", font=self.bold).pack(anchor="w", pady=(0, 10))
        self.preview = tk.Frame(parent, background=NEW_POST_COLOR, height=int(round(SWATCH * self.scale)),
                                highlightthickness=1, highlightbackground=CARD_EDGE)
        self.preview.pack(fill="x")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Color").pack(side="left")
        self.new_color = tk.StringVar(value=NEW_POST_COLOR)
        ttk.Entry(row, textvariable=self.new_color, width=10, font=self.mono).pack(side="left", padx=8)
        ttk.Button(row, text="Pick a color…", command=self.pick).pack(side="left")
        ttk.Label(parent, text="Caption").pack(anchor="w", pady=(12, 2))
        self.caption_entry = ttk.Entry(parent)
        self.caption_entry.pack(fill="x")
        ttk.Label(parent, text="Up to " + str(CAPTION_LIMIT) + " characters. Leave it empty to use the color's name.",
                  foreground=MUTED).pack(anchor="w", pady=(2, 0))
        self.post_button = ttk.Button(parent, text="Post", command=self.publish)
        self.post_button.pack(anchor="e", pady=(12, 0))
        self.problem = ttk.Label(parent, foreground=BAD_ON[1])
        self.problem.pack(anchor="w")

    def bind_events(self):
        """The color preview, the preset list, opening Saved, Enter to post, F5 and the mouse wheel."""
        self.new_color.trace_add("write", self.show_preview)
        self.preset_box.bind("<<ComboboxSelected>>", self.change_preset)
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.caption_entry.bind("<Return>", lambda event: self.publish())
        self.window.bind("<F5>", lambda event: self.refresh_feed())
        self.window.bind_all("<MouseWheel>", self.wheel)
        if self.window.tk.call("tk", "windowingsystem") == "x11":
            self.window.bind_all("<Button-4>", self.wheel)
            self.window.bind_all("<Button-5>", self.wheel)

    # --- Small helpers ---------------------------------------------------------------------------

    def say(self, text):
        """Show `text` in the status bar."""
        self.status.configure(text=text)

    def keep(self):
        """Save the store to the data file (never in a smoke run); a failure shows in the status bar."""
        if self.smoke_path != "":
            return
        saved = save_store(self.data_file, self.store)
        if not saved["ok"]:
            self.say("Could not save: " + saved["error"])

    def paint(self, button, text, colors):
        """Set a button's text and its (background, text) colors, also while it is pressed."""
        button.configure(text=text, background=colors[0], foreground=colors[1],
                         activebackground=colors[0], activeforeground=colors[1])

    def link(self, parent, text, background, command):
        """A flat button that reads like a link: small, muted text on `background`."""
        return tk.Button(parent, text=text, font=self.small, relief="flat", borderwidth=0, cursor="hand2",
                         foreground=MUTED, background=background, activebackground=background, command=command)

    # --- Post cards ------------------------------------------------------------------------------

    def make_comment(self, card, index, comment):
        """Show `comment`, number `index` of the card's post, in the card's comment section."""
        color = card["color"]
        bubble = tk.Frame(card["comments"], background=COMMENT_BACKGROUND)
        bubble.pack(fill="x", pady=(0, 6))
        top = tk.Frame(bubble, background=COMMENT_BACKGROUND)
        top.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(top, text="You", font=self.bold, background=COMMENT_BACKGROUND).pack(side="left")
        tk.Label(top, text=" · " + when_text(comment["when"], time.time()), font=self.small, foreground=MUTED,
                 background=COMMENT_BACKGROUND).pack(side="left")
        self.link(top, "Delete", COMMENT_BACKGROUND, lambda: self.remove_comment(color, index)).pack(side="right")
        tk.Label(bubble, text=comment["text"], anchor="w", justify="left", background=COMMENT_BACKGROUND,
                 wraplength=self.column - int(round(COMMENT_MARGIN * self.scale))).pack(fill="x", padx=8, pady=(2, 6))

    def refresh_card(self, card):
        """Redraw a card from the store: Good, Bad and Save, the comment count and every comment."""
        color = card["color"]
        mine = my_vote(self.store, color)
        if mine == 1:
            self.paint(card["good"], "▲ Good 1", GOOD_ON)
        else:
            self.paint(card["good"], "▲ Good 0", BUTTON_OFF)
        if mine == -1:
            self.paint(card["bad"], "▼ Bad 1", BAD_ON)
        else:
            self.paint(card["bad"], "▼ Bad 0", BUTTON_OFF)
        if color in self.store["saved"]:
            self.paint(card["save"], "Saved", SAVE_ON)
        else:
            self.paint(card["save"], "Save", BUTTON_OFF)
        comments = comments_of(self.store, color)
        if len(comments) == 1:
            card["count"].configure(text="1 comment")
        else:
            card["count"].configure(text=str(len(comments)) + " comments")
        for child in card["comments"].winfo_children():
            child.destroy()
        for index in range(len(comments)):
            self.make_comment(card, index, comments[index])

    def make_card(self, feed, post):
        """Add a card for `post` at the end of `feed`: who posted it and when, the color, its caption and
        hex code, Good, Bad and Save, the comments and a box to write one."""
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
        tk.Label(head, text=author, font=self.bold, background=CARD).pack(side="left")
        tk.Label(head, text=" · " + when_text(post["when"], time.time()), font=self.small, foreground=MUTED,
                 background=CARD).pack(side="left")
        if post["mine"]:
            self.link(head, "Delete post", CARD, lambda: self.remove_post(color)).pack(side="right")
        tk.Frame(frame, background=color, height=int(round(SWATCH * self.scale))).pack(fill="x")
        tk.Label(frame, text=post["caption"], anchor="w", justify="left", background=CARD,
                 wraplength=self.column - int(round(CAPTION_MARGIN * self.scale))).pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(frame, text=color, font=self.mono, anchor="w", foreground=MUTED, background=CARD).pack(fill="x", padx=12)
        actions = tk.Frame(frame, background=CARD)
        actions.pack(fill="x", padx=8, pady=8)
        card["good"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                 command=lambda: self.press(color, 1))
        card["bad"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                command=lambda: self.press(color, -1))
        card["save"] = tk.Button(actions, relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
                                 command=lambda: self.save_post(color))
        card["good"].pack(side="left", padx=4)
        card["bad"].pack(side="left", padx=4)
        card["save"].pack(side="left", padx=4)
        card["count"] = tk.Label(actions, font=self.small, foreground=MUTED, background=CARD)
        card["count"].pack(side="right", padx=4)
        card["comments"] = tk.Frame(frame, background=CARD)
        card["comments"].pack(fill="x", padx=12)
        write = tk.Frame(frame, background=CARD)
        write.pack(fill="x", padx=12, pady=(4, 12))
        card["entry"] = ttk.Entry(write)
        card["entry"].pack(side="left", fill="x", expand=True)
        card["comment_button"] = ttk.Button(write, text="Comment", command=lambda: self.comment(card))
        card["comment_button"].pack(side="left", padx=(6, 0))
        card["entry"].bind("<Return>", lambda event: self.comment(card))
        feed["cards"][color] = card
        self.refresh_card(card)

    # --- Feeds -----------------------------------------------------------------------------------

    def make_feed(self, parent):
        """A scrolling feed in `parent`: a canvas showing one frame of cards, centered and no wider than the
        column -> Feed record, also added to self.feeds."""
        canvas = tk.Canvas(parent, background=FEED_BACKGROUND, highlightthickness=0, borderwidth=0,
                           yscrollincrement=int(round(SCROLL_UNIT * self.scale)))
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, background=FEED_BACKGROUND)
        item = canvas.create_window(0, 0, window=inner, anchor="nw")
        feed = {"canvas": canvas, "inner": inner, "cards": {}, "order": [], "shown": 0, "more": None, "empty": None}
        inner.bind("<Configure>", lambda event: self.fit_content(canvas, event))
        canvas.bind("<Configure>", lambda event: self.fit_column(canvas, item, event))
        self.feeds.append(feed)
        return feed

    def fit_content(self, canvas, event):
        """The frame of cards changed size: let the canvas scroll over all of it."""
        canvas.configure(scrollregion=canvas.bbox("all"))

    def fit_column(self, canvas, item, event):
        """The canvas changed size: center the frame of cards (canvas item `item`), at most a column wide."""
        width = min(event.width, self.column)
        canvas.coords(item, max(0, (event.width - width) // 2), 0)
        canvas.itemconfigure(item, width=width)

    def show(self, feed, order, empty_text):
        """Fill `feed` afresh with the posts in `order`, a page at a time, or with `empty_text` when there are
        none, and scroll it to the top."""
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
        self.more(feed)
        feed["canvas"].yview_moveto(0.0)

    def more(self, feed):
        """Add the next PAGE places of the feed's order as cards (a deleted color is skipped), then Show more,
        or a caught-up note at the end."""
        posts = {}
        for post in all_posts(self.store):
            posts[post["color"]] = post
        if feed["more"] is not None:
            feed["more"].destroy()
            feed["more"] = None
        stop = min(len(feed["order"]), feed["shown"] + PAGE)
        while feed["shown"] < stop:
            color = feed["order"][feed["shown"]]
            if color in posts:
                self.make_card(feed, posts[color])
            feed["shown"] = feed["shown"] + 1
        if feed["shown"] < len(feed["order"]):
            feed["more"] = ttk.Button(feed["inner"], text="Show more", command=lambda: self.more(feed))
            feed["more"].pack(pady=16)
        elif len(feed["order"]) > 0:
            feed["more"] = tk.Label(feed["inner"], text="You're all caught up.", foreground=MUTED,
                                    background=FEED_BACKGROUND, pady=16)
            feed["more"].pack(fill="x")

    def drop_card(self, feed, color):
        """Take a deleted post out of `feed`: its place in the order (so paging carries on where it was) and
        its card."""
        if color in feed["order"]:
            if feed["order"].index(color) < feed["shown"]:
                feed["shown"] = feed["shown"] - 1
            feed["order"].remove(color)
        if color in feed["cards"]:
            feed["cards"][color]["frame"].destroy()
            del feed["cards"][color]

    def each_card(self, color):
        """Every card showing `color`, in the Feed tab and in the Saved tab."""
        cards = []
        for feed in self.feeds:
            if color in feed["cards"]:
                cards.append(feed["cards"][color])
        return cards

    # --- What the buttons and keys do ------------------------------------------------------------

    def press(self, color, voat):
        """Good (1) or Bad (-1) on a post: vote and redraw its cards; For you re-ranks on Refresh."""
        now = vote(self.store, color, voat, time.time())
        self.keep()
        for card in self.each_card(color):
            self.refresh_card(card)
        if now == 1:
            self.say("Marked Good. Refresh to see what it changes in For you.")
        elif now == -1:
            self.say("Marked Bad. Refresh to see what it changes in For you.")
        else:
            self.say("Vote taken back.")

    def save_post(self, color):
        """Save on a post: put it in Saved or take it out."""
        if toggle_save(self.store, color, time.time()):
            self.say("Saved. It's in the Saved tab.")
        else:
            self.say("Removed from Saved.")
        self.keep()
        for card in self.each_card(color):
            self.refresh_card(card)

    def comment(self, card):
        """Comment (or Enter) on a card: post what its box holds as a comment."""
        added = add_comment(self.store, card["color"], card["entry"].get(), time.time())
        if not added["ok"]:
            self.say(added["error"])
            return
        card["entry"].delete(0, "end")
        self.keep()
        for each in self.each_card(card["color"]):
            self.refresh_card(each)
        self.say("Comment posted.")

    def remove_comment(self, color, index):
        """Delete on a comment. `index` was fixed when the comment was drawn; it stays right because every
        change redraws all the comments of every card of that color."""
        if delete_comment(self.store, color, index):
            self.keep()
            for card in self.each_card(color):
                self.refresh_card(card)
            self.say("Comment deleted.")

    def remove_post(self, color):
        """Delete post on one of your posts: ask, then take it out of the store and of both feeds."""
        if not messagebox.askyesno("Delete post", "Delete your post " + color + " and its comments?", parent=self.window):
            return
        if delete_post(self.store, color):
            self.keep()
            for feed in self.feeds:
                self.drop_card(feed, color)
            self.say("Post deleted.")

    def refresh_feed(self):
        """Refresh, F5 or a sort change: rank and redraw the Feed tab. The preset list is for For you only."""
        self.show(self.feed_view, feed_order(self.store, self.sort_choice.get(), self.ranker), "No posts yet.")
        if self.sort_choice.get() == "for_you":
            self.preset_box.configure(state="readonly")
        else:
            self.preset_box.configure(state="disabled")

    def change_preset(self, event):
        """A preset picked from the list: rank For you with its ranker; when it fails to load, the list shows
        the old preset again."""
        name = self.preset_choice.get()
        if name == self.preset:
            return
        loaded = load_ranker(name)
        if not loaded["ok"]:
            self.preset_choice.set(self.preset)
            self.say(loaded["error"])
            return
        self.ranker = loaded["value"]
        self.preset = name
        self.refresh_feed()
        self.say("For you is now ranked by the " + name + " preset.")

    def refresh_saved(self):
        """Redraw the Saved tab, the most recently saved first."""
        self.show(self.saved_view, saved_colors(self.store), "Nothing saved yet. Press Save on a post to keep it here.")

    def tab_changed(self, event):
        """Another tab opened: the Saved tab is redrawn each time it opens."""
        if self.tabs.index(self.tabs.select()) == SAVED_TAB:
            self.refresh_saved()

    def wheel(self, event):
        """The mouse wheel scrolls the open tab's feed while the pointer is over it. X11 reports buttons 4 (up)
        and 5 (down), Windows deltas in multiples of WHEEL_NOTCH, macOS small deltas."""
        current = self.tabs.index(self.tabs.select())
        if current > SAVED_TAB:  # the New post tab has no feed
            return
        canvas = self.feed_view["canvas"]
        if current == SAVED_TAB:
            canvas = self.saved_view["canvas"]
        if not str(event.widget).startswith(str(canvas)):  # the pointer is not over a widget inside this canvas
            return
        if event.num == 4:
            steps = -1
        elif event.num == 5:
            steps = 1
        elif event.delta > 0:
            steps = -max(1, event.delta // WHEEL_NOTCH)
        else:
            steps = max(1, -event.delta // WHEEL_NOTCH)
        canvas.yview_scroll(steps * WHEEL_UNITS, "units")

    def show_preview(self, *arguments):
        """The color box changed: show the color once it is one."""
        color = normalize_hex(self.new_color.get())
        if color != "":
            self.preview.configure(background=color)

    def pick(self):
        """Pick a color…: choose the color in the color dialog, starting from the one typed."""
        start = normalize_hex(self.new_color.get())
        if start == "":
            start = NEW_POST_COLOR
        chosen = colorchooser.askcolor(color=start, title="Pick a color", parent=self.window)
        if chosen is not None and chosen[1] is not None:
            self.new_color.set(normalize_hex(chosen[1]))

    def publish(self):
        """Post (or Enter in the caption): post the color, then show the Feed tab sorted New, with it on top."""
        made = add_post(self.store, self.new_color.get(), self.caption_entry.get(), time.time())
        if not made["ok"]:
            self.problem.configure(text=made["error"])
            return
        self.problem.configure(text="")
        self.caption_entry.delete(0, "end")
        self.keep()
        self.sort_choice.set("new")
        self.tabs.select(FEED_TAB)
        self.refresh_feed()
        self.say("Posted " + made["value"]["color"] + ". It's at the top of New.")

    # --- The smoke run (--smoke FILE) ------------------------------------------------------------

    def write_smoke_report(self):
        """Use the window like a person would (vote, save and comment on the first post, open Saved, post a
        color), write what worked to the smoke file as JSON and close the window."""
        self.window.update()
        first = self.feed_view["order"][0]
        card = self.feed_view["cards"][first]
        card["good"].invoke()
        vote_ok = my_vote(self.store, first) == 1 and card["good"].cget("text").endswith(" 1")
        card["save"].invoke()
        save_ok = first in self.store["saved"] and card["save"].cget("text") == "Saved"
        card["entry"].insert(0, "smoke comment")
        card["comment_button"].invoke()
        comment_ok = len(comments_of(self.store, first)) == 1 and len(card["comments"].winfo_children()) == 1
        self.tabs.select(SAVED_TAB)
        self.window.update()
        saved_tab_ok = list(self.saved_view["cards"]) == [first]
        self.tabs.select(NEW_POST_TAB)
        self.window.update()
        self.new_color.set("#123456")
        self.caption_entry.insert(0, "smoke post")
        self.post_button.invoke()
        self.window.update()
        report = {"app_id": APP_ID, "version": self.version, "title": self.window.title(), "icon_set": self.icon_set,
                  "preset": self.preset, "tabs": [], "posts": len(all_posts(self.store)),
                  "cards_shown": len(self.feed_view["cards"]), "vote_ok": vote_ok, "save_ok": save_ok,
                  "comment_ok": comment_ok, "saved_tab_ok": saved_tab_ok,
                  "post_ok": self.feed_view["order"][0] == "#123456" and self.tabs.index(self.tabs.select()) == FEED_TAB}
        for tab_id in self.tabs.tabs():
            report["tabs"].append(self.tabs.tab(tab_id, "text"))
        with open(self.smoke_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        self.window.destroy()

# ==== stamp v1 | author=kjFriday | hmac-sha256=0e6600a958e31ed1cb93b11727f9ae8c2e72f8bb2244b2f51b56c21257e73e3e ====
