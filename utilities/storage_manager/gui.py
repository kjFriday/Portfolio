# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: gui.py
# About: Storage Manager window (tkinter): everything here only calls the core modules.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager window (tkinter): everything here only calls the core modules.

run_gui opens the window and runs it until it is closed. StorageWindow builds the window and holds
everything its handlers share: the settings, the results of the last analysis, the space map's state, the
job that runs and the widgets the handlers read or fill in. gui_views.py builds the ten views, one
function each; the handlers their buttons call are StorageWindow's methods, here.

The window
  top bar      the folder or drive box, Browse, Analyze, Undo last change
  status bar   the status line, the progress bar, Cancel, About (packed before the body, so a small
               window cuts the body rather than the status line)
  body         a PanedWindow: the sidebar (the VIEWS, grouped in sections, each with a short count) and
               main, whose one grid cell holds every view; show_view raises the one shown

Jobs
  run_job runs one job at a time on a worker thread that never touches Tk. The worker sends (kind,
  value) messages back through a queue, which the window reads every POLL_MS on its own thread: only
  the latest "progress" is shown, other kinds go to the job's on_message. When the worker is done, its
  Result goes to finish (or on_fail) on the window's thread. Cancel sets cancel_flag, the one-element
  list the core's functions check while they work.

storage_manager.py imports this module only when it opens the window, so --selftest, --version and the
core never load tkinter. ctypes is imported inside windows_identity. The program's name, id, version and
icon come from storage_manager.py.

Start reading at StorageWindow.__init__ and run_job, then analyze: one analysis shows how a job's
messages fill the views. Changes on disk all go through apply_and_forget (or apply_organize) and undo.
"""

import json
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import gui_views
from backup import apply_copies, plan_sync
from desktop import add_recent, launch, list_drives, normalize_folder, open_folder_command, reveal_command
from duplicates import (duplicate_savings, find_duplicates_in, group_savings, keeper_index, plan_duplicate_removal,
                        remove_from_groups)
from formatting import disk_note, human_count, human_date, human_size, plural
from moves import apply_moves, plan_empty_dir_removal, plan_trash, select_empty_dirs, undo_last, undo_log_path
from organize import plan_organize
from paths import TRASH_DIR_NAME, in_trash_folder, is_inside, relative_path
from records import failure, is_cancelled, success
from scanning import count_links_once, file_disk, file_size, remove_from_report, scan, stale_files, total_disk
from settings import load_settings, save_settings
from shares import check_share, map_share, share_path, unc_host, unmap_share, valid_letter
from space_map import (MAP_DEPTH, MAP_MIN_DEGREES, MAP_MIN_PIXELS, arc_color, build_folder_tree, find_node,
                       layout_sunburst, map_entries, map_item_count, mark_wasted, ring_min_angles, ring_points,
                       shift_kept_copy)
from storage_manager import APP_ID, APP_NAME, ICON_CREDIT, ICON_FILE, __version__, settings_path

LARGEST_COUNT = 100           # files listed under "Largest files"
MAX_ROWS = 2000               # rows a list shows; actions still apply to every row
RECENT_LIMIT = 10             # folders the folder box remembers

# Timing, in milliseconds.
POLL_MS = 100                 # how often the window reads a running job's messages
PROGRESS_STEP_MS = 15         # the progress bar moves a step this often while a job's size is not known
MAP_REDRAW_MS = 60            # the map is drawn again once its canvas has kept one size this long
START_DELAY_MS = 100          # --folder: the analysis starts this long after the window is built
SMOKE_DELAY_MS = 800          # --smoke: the report is written this long after the window is built...
SMOKE_RETRY_MS = 200          # ...or, while a job runs, this long after it last looked

# The space map's drawing.
MAP_HOLE = 0.2                # radius of the centre circle, as a share of the map's radius
MAP_SMALLEST_RADIUS = 60      # pixels; a smaller map is not drawn
MAP_FEWEST_RINGS = 3          # shallow folders get wider rings instead of a small map in a big canvas
MAP_POINT_STEP = 2.0          # at most this many degrees between two points of a slice's outline


def windows_identity():
    """Own taskbar button (not Python's) and crisp text on scaled displays. Windows only."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # the AppUserModelID groups the window under its own taskbar button and icon instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        # 1 = PROCESS_SYSTEM_DPI_AWARE: Tk draws at the display's scale instead of being stretched (blurry)
        # by Windows; it must run before the first window is made, so before tk.Tk()
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        # older Windows without shcore.dll (before 8.1): the window still works, only less crisp
        pass


def set_icon(window):
    """The pixel icon on the window and its dialogs -> True when it was set."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        # default= applies the .ico to every toplevel made later too, such as the share dialog
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


# Sidebar: (key, label, section). Sections group the entries; "" is top level.
VIEWS = [
    ("overview", "Overview", ""),
    ("map", "Space map", ""),
    ("largest", "Largest files", "Clean up"),
    ("old", "Old files", "Clean up"),
    ("duplicates", "Duplicates", "Clean up"),
    ("empty", "Empty folders", "Clean up"),
    ("errors", "Unreadable", "Clean up"),
    ("organize", "Organize", "Tools"),
    ("network", "Network shares", "Tools"),
    ("activity", "Activity", "Tools"),
]


def run_gui(smoke_path, start_folder, start_view):
    """Open the window and run it until it is closed -> 0, the exit code.

    smoke_path: where --smoke writes its report ("" for none); start_folder: a folder to analyze at once
    ("" for none); start_view: the VIEWS key to show first (anything else keeps the Overview)."""
    app = StorageWindow(smoke_path)
    app.start(start_folder, start_view)
    app.window.mainloop()
    return 0


class StorageWindow:
    """The Storage Manager window and everything its handlers share.

    __init__ builds the window part by part, in the order its widgets have always been created (their Tk
    names and the Tab order follow it): the top bar, the status bar, the sidebar, then the views
    (gui_views.py), then the bindings. start() fills it in. Handlers read the state attributes listed in
    __init__ and the widgets the builders keep: each build function's docstring names those.

    A view is {"frame", "subtitle", "actions"} (make_view); a table is the record make_table returns.
    Buttons are enabled by predicates (add_button, refresh_buttons). refresh_all pushes the results into
    the sidebar and every view; the space map draws itself when it is shown (map_draw).
    """

    def __init__(self, smoke_path):
        """Build the whole window, empty; start() fills it in.

        smoke_path: where --smoke writes its report, "" for a normal run. Reads the settings file. Creates
        the Tk root, so it must run on the thread that will run mainloop.

        Steps:
          1. Load the settings and set up the shared state (listed below, one line each).
          2. Make the Tk window with the saved size, the icon and the styles.
          3. Build the top bar, status bar and sidebar, then the views (gui_views.py), in the fixed order.
          4. Bind the window's events.
        """
        self.smoke_path = smoke_path  # where --smoke writes its report; "" for a normal run
        self.path_to_settings = settings_path()
        self.settings = load_settings(self.path_to_settings)
        # The state the handlers share.
        self.busy = False             # a job runs (run_job)
        self.cancel_flag = [False]    # Cancel sets it; the running job's core functions check it
        self.root = ""                # folder the results below belong to
        self.report = None            # ScanReport of the last analysis
        self.groups = None            # duplicate groups; None until compared
        self.dup_note = ""            # shown instead of duplicate counts while comparing or after a cancel
        self.keep = {}                # path -> True: copies the user chose to keep
        self.org_moves = []           # the Organize preview's moves
        self.org_root = ""            # the folder they were planned in
        self.old_days = self.settings["stale_days"]
        self.view = "overview"        # the VIEWS key shown
        self.map_tree = None          # Node tree of the report; None after files were moved (rebuilt when shown)
        self.map_pending = False      # the analysis is still building the tree
        self.map_wasted_ok = False    # map_tree's wasted bytes match the current groups and keep choices
        self.map_center = ""          # folder in the middle of the space map
        self.map_items = {}           # canvas item -> Arc
        self.map_hover_item = None    # canvas item under the mouse
        self.map_redraw = None        # pending after() id while the canvas is being resized
        self.map_serial = 0           # counts trees, so the list beside the map knows when it is out of date
        self.map_table_key = None     # (map_serial, centre path) the "Biggest here" list shows
        self.map_scanning = False     # an analysis is reading folders (before its first results)
        self.map_pressed = None       # canvas item the last click landed on
        self.map_build_error = ""     # why the last background build of the map failed; "" when it did not
        self.buttons = []             # (button, predicate): enabled when idle and predicate() is true
        self.usable_when_busy = {}    # button -> True: also enabled while a job runs
        self.views = {}               # view key -> view (make_view)
        self.primary = {}             # view key -> action for the Delete key

        windows_identity()
        self.window = tk.Tk()
        self.window.title("Generic Company Inc. \u2014 Storage Manager " + __version__)
        if self.settings["geometry"] != "":
            self.window.geometry(self.settings["geometry"])
        else:
            self.window.geometry("1120x700")
        self.window.minsize(880, 540)
        self.icon_set = set_icon(self.window)
        self.make_styles()

        self.build_top_bar()
        self.build_status_bar()
        self.build_sidebar()
        self.log_text = None  # the Activity view's text; log() writes nothing until it is built
        # "On disk" is what moving a file away (and emptying the trash) frees; "File size" is what Explorer
        # shows as Size. They differ for compressed, sparse and cloud-only files and for hard links.
        self.file_columns = [("path", "File", 320, "w", True), ("disk", "On disk", 90, "e", False),
                             ("size", "File size", 90, "e", False), ("modified", "Changed", 100, "e", False)]
        self.file_sorts = {"path": self.path_key, "disk": file_disk, "size": file_size,
                           "modified": lambda row: row["modified"]}
        gui_views.build_overview(self)
        gui_views.build_map_view(self)
        gui_views.add_overview_actions(self)
        gui_views.build_largest_view(self)
        gui_views.build_old_view(self)
        gui_views.build_duplicates_view(self)
        gui_views.build_empty_view(self)
        gui_views.build_errors_view(self)
        gui_views.build_organize_view(self)
        gui_views.build_network_view(self)
        gui_views.build_activity_view(self)
        self.bind_events()

    # --- building the window -----------------------------------------------------------------------
    def make_styles(self):
        """Fonts and ttk styles. The fonts are kept on the window: a Font copy deletes its Tk font when
        the Python object goes."""
        self.base_font = tkfont.nametofont("TkDefaultFont")
        self.line_height = self.base_font.metrics("linespace")
        size = self.base_font.cget("size")
        self.title_font = self.base_font.copy()
        # Tk font sizes are points when positive and pixels when negative, so "bigger" is size - 5 there
        if size < 0:
            self.title_font.configure(size=size - 5, weight="bold")
        else:
            self.title_font.configure(size=size + 5, weight="bold")
        self.strong_font = self.base_font.copy()
        self.strong_font.configure(weight="bold")
        self.style = ttk.Style(self.window)
        self.style.configure("Treeview", rowheight=self.line_height + 8)
        self.style.configure("Side.Treeview", rowheight=self.line_height + 14)
        self.style.configure("Title.TLabel", font=self.title_font)
        self.style.configure("Strong.TLabel", font=self.strong_font)
        self.style.configure("Muted.TLabel", foreground="#6b6b6b")
        self.style.configure("Primary.TButton", font=self.strong_font)

    def build_top_bar(self):
        """Top bar: what to look at. Keeps folder_var, folder_box and the Browse, Analyze and Undo buttons."""
        top = ttk.Frame(self.window, padding=(10, 10, 10, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Folder or drive").pack(side="left")
        self.folder_var = tk.StringVar(value=self.settings["last_folder"])
        self.folder_box = ttk.Combobox(top, textvariable=self.folder_var)
        self.folder_box.pack(side="left", fill="x", expand=True, padx=8)
        self.browse_button = ttk.Button(top, text="Browse\u2026", command=lambda: self.browse())
        self.browse_button.pack(side="left")
        self.analyze_button = ttk.Button(top, text="Analyze", style="Primary.TButton", command=lambda: self.analyze())
        self.analyze_button.pack(side="left", padx=6)
        self.undo_button = ttk.Button(top, text="Undo last change", command=lambda: self.undo())
        self.undo_button.pack(side="left")

    def build_status_bar(self):
        """Bottom bar: what is happening. Keeps status_var, cancel_button and progress."""
        bottom = ttk.Frame(self.window, padding=(10, 4, 10, 8))
        bottom.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Pick a folder or drive and press Analyze (or Enter).")
        # Right-hand widgets are packed first so a long status line is cut, not the buttons.
        ttk.Button(bottom, text="About", command=lambda: self.about()).pack(side="right", padx=(6, 0))
        self.cancel_button = ttk.Button(bottom, text="Cancel", state="disabled", command=lambda: self.cancel())
        self.cancel_button.pack(side="right")
        self.progress = ttk.Progressbar(bottom, length=220, mode="determinate", maximum=100)
        self.progress.pack(side="right", padx=8)
        ttk.Label(bottom, textvariable=self.status_var, width=1).pack(side="left", fill="x", expand=True)

    def build_sidebar(self):
        """Body: the sidebar and the selected view. Keeps main (where make_view puts the views) and sidebar."""
        body = ttk.PanedWindow(self.window, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10)
        side = ttk.Frame(body)
        self.main = ttk.Frame(body, padding=(14, 0, 0, 0))
        body.add(side, weight=0)
        body.add(self.main, weight=1)
        self.main.rowconfigure(0, weight=1)
        self.main.columnconfigure(0, weight=1)

        self.sidebar = ttk.Treeview(side, columns=("info",), show="tree", selectmode="browse",
                                    style="Side.Treeview")
        self.sidebar.column("#0", width=170, stretch=True)
        self.sidebar.column("info", width=150, anchor="e", stretch=False)
        self.sidebar.pack(fill="both", expand=True)
        self.sidebar.tag_configure("section", font=self.strong_font)
        # each view is a sidebar row whose iid is its VIEWS key; a section is a bold parent row
        # ("section-clean-up") made the first time one of its views needs it
        for entry in VIEWS:
            parent = ""
            if entry[2] != "":
                parent = "section-" + entry[2].lower().replace(" ", "-")
                if not self.sidebar.exists(parent):
                    self.sidebar.insert("", "end", iid=parent, text=entry[2], open=True, tags=("section",))
            self.sidebar.insert(parent, "end", iid=entry[0], text=entry[1], values=("",))

    def bind_events(self):
        """The sidebar, the folder box's list, double-clicks on the lists and the keys of the whole window.
        (The space map binds its own, in gui_views.build_map_view.)"""
        self.sidebar.bind("<<TreeviewSelect>>", self.on_sidebar)
        self.folder_box.configure(postcommand=lambda: self.folder_box.configure(values=self.folder_choices()))
        for table in (self.largest_table, self.old_table, self.empty_table):
            self.double_click(table)
        self.dup_tree.bind("<Double-1>", lambda event: self.reveal_copy())
        self.folder_box.bind("<Return>", lambda event: self.analyze())
        self.window.bind("<F5>", lambda event: self.analyze())
        self.window.bind("<Control-z>", lambda event: self.undo())
        self.window.bind("<Delete>", self.on_delete)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def start(self, start_folder, start_view):
        """Fill the window in and show it as the command line asks: start_view first, start_folder
        analyzed once the window is up, and with --smoke the report written soon after."""
        self.rebuild_shares()
        self.clear_organize()
        self.show_view("overview")
        self.refresh_all()
        self.log(APP_NAME + " " + __version__ + " started")
        self.folder_box.focus_set()

        if start_view in self.views:
            self.show_view(start_view)
        if start_folder != "":
            self.folder_var.set(start_folder)
            self.window.after(START_DELAY_MS, self.analyze)

        if self.smoke_path != "":
            self.window.after(SMOKE_DELAY_MS, self.write_smoke_report)

    # --- small helpers -------------------------------------------------------------------------------
    def log(self, message):
        """Add a time-stamped line to the Activity view and scroll to it. Tk thread only.

        The text widget stays disabled so the user cannot type in it; it is enabled just for the insert.
        """
        if self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", time.strftime("%H:%M:%S") + "  " + message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def wrapping(self, label):
        """Let a label wrap to whatever width it is given instead of being cut off."""
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(event.width - 4, 100)))
        return label

    def rel(self, path):
        """path as the lists show it: relative to the analyzed folder, or whole before any analysis."""
        if self.root == "":
            return path
        return relative_path(self.root, path)

    def ask(self, question):
        """Ask a yes/no question in a modal dialog over the window -> True for Yes."""
        return messagebox.askyesno(APP_NAME, question, parent=self.window)

    def refresh_buttons(self):
        """Enable or disable every button for the current state.

        A view button is enabled when no job runs (or it is in usable_when_busy) and its predicate is
        true; a predicate that raises (say, a widget not filled in yet) counts as false. Browse and Analyze
        need no job running, Undo also needs an undo log in the analyzed folder, Cancel needs a job.
        """
        busy = self.busy
        for pair in self.buttons:
            enabled = False
            if not busy or pair[0] in self.usable_when_busy:
                try:
                    enabled = pair[1]()
                except Exception:
                    enabled = False
            if enabled:
                pair[0].configure(state="normal")
            else:
                pair[0].configure(state="disabled")
        idle = "disabled" if busy else "normal"
        self.analyze_button.configure(state=idle)
        self.browse_button.configure(state=idle)
        if not busy and self.root != "" and os.path.isfile(undo_log_path(self.root)):
            self.undo_button.configure(state="normal")
        else:
            self.undo_button.configure(state="disabled")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def show_progress(self, item):
        """Show a progress report, item = (text, done, total, unit) as in records.py, in the status bar.

        With a known total the bar fills to done/total and the line says "done of total"; with total 0
        the bar bounces (indeterminate mode) and the line counts what is done so far.
        """
        text = item[0]
        done = item[1]
        total = item[2]
        unit = item[3]
        if total > 0:
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress.configure(value=100.0 * done / total)
            if unit == "bytes":
                amount = human_size(done) + " of " + human_size(total)
            else:
                amount = human_count(done) + " of " + human_count(total)
            self.status_var.set(text + "\u2026 " + amount)
        else:
            if str(self.progress.cget("mode")) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(PROGRESS_STEP_MS)
            self.status_var.set(text + "\u2026 " + human_count(done) + " " + unit)

    def run_job(self, label, work, finish, on_message, on_fail):
        """Run work(post) on a worker thread. post(kind, value) sends messages back; the window polls
        for them, so Tk is only touched from its own thread. finish(result) runs on success.

        label: the job's name for the status line and the Activity log. work(post) runs on the worker
        thread and returns a Result; an exception becomes failure("unexpected error: ..."). on_message(kind,
        value) gets every message but "progress", on the Tk thread (None ignores them). on_fail(result)
        runs on failure, after the error is shown and logged (None for nothing more). Does nothing while
        another job runs.

        Steps:
          1. Mark the window busy, clear the cancel flag, start the bar bouncing and disable the buttons.
          2. Start the worker as a daemon thread (closing the window does not wait for it).
          3. Every POLL_MS, poll drains the queue and shows the newest progress, until the worker is done.
          4. Then show the outcome, call finish or on_fail, and enable the buttons again.
        """
        if self.busy:
            return
        self.busy = True
        self.cancel_flag[0] = False
        messages = queue.Queue()
        holder = {"result": None, "done": False}

        def post(kind, value):
            """Queue a (kind, value) message for the Tk thread; safe to call from the worker."""
            messages.put((kind, value))

        def worker():
            """Run work on the worker thread and leave its Result in holder; never touches Tk."""
            try:
                result = work(post)
            except Exception as e:  # keep the window alive whatever happens in a job
                result = failure("unexpected error: " + str(e))
            holder["result"] = result
            holder["done"] = True

        def poll():
            """Read the job's messages on the Tk thread; reschedule itself until the job is done, then end it."""
            # "done" is read before the queue is emptied: once it is true every message is already queued,
            # so none is left unread when the job ends.
            finished = holder["done"]
            latest = None
            while True:
                try:
                    item = messages.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "progress":
                    latest = item[1]
                elif on_message is not None:
                    on_message(item[0], item[1])
            if not finished:
                if latest is not None:
                    self.show_progress(latest)
                self.window.after(POLL_MS, poll)
                return
            self.busy = False
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            result = holder["result"]
            if result["ok"]:
                self.status_var.set(label + " \u2014 done")
                finish(result)
            else:
                self.status_var.set(label + " \u2014 " + result["error"])
                self.log("  " + result["error"])
                if on_fail is not None:
                    on_fail(result)
            self.refresh_buttons()
            # A map that had to wait for this job (it builds its tree as a job of its own) is drawn now.
            if (not self.busy and self.view == "map" and self.report is not None
                    and self.map_tree is None and not self.map_pending and self.map_build_error == ""):
                self.map_draw()

        self.status_var.set(label + "\u2026")
        self.log(label)
        self.progress.configure(mode="indeterminate")
        self.progress.start(PROGRESS_STEP_MS)
        self.refresh_buttons()
        threading.Thread(target=worker, daemon=True).start()
        self.window.after(POLL_MS, poll)

    def progress_sender(self, post):
        """A progress callback for the core (see records.py) that posts each report as a "progress" message."""
        def send(text, done, total, unit):
            """Post one progress report; runs on the worker thread."""
            post("progress", (text, done, total, unit))
        return send

    def cancel(self):
        """Ask the running job to stop: set the shared cancel flag; the core functions check it as they go."""
        self.cancel_flag[0] = True
        self.status_var.set("Cancelling\u2026")
        self.log("cancel requested")

    def report_apply(self, result, verb):
        """Log and show the outcome of apply_moves or apply_copies: verb ("Moved", "Copied"...) and counts.

        Each error goes to the Activity log; the status line only counts them.
        """
        info = result["value"]
        self.log("  " + verb + " " + plural(info["done"], "item"))
        for error in info["errors"]:
            self.log("  error: " + error)
        message = verb + " " + plural(info["done"], "item")
        if len(info["errors"]) > 0:
            message = message + ", " + plural(len(info["errors"]), "error") + " (see Activity)"
        self.status_var.set(message)

    # --- views: the parts they share ---------------------------------------------------------------
    def make_view(self, key, title):
        """Add a view under key: a frame in main's one grid cell with a title, a subtitle and an actions row.

        -> view {"frame", "subtitle" (a StringVar), "actions" (the frame add_button fills)}. Every view
        shares the cell; show_view raises the one shown.
        """
        frame = ttk.Frame(self.main)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
        subtitle = tk.StringVar(value="")
        self.wrapping(ttk.Label(frame, textvariable=subtitle, style="Muted.TLabel")).pack(fill="x", pady=(2, 8))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 8))
        view = {"frame": frame, "subtitle": subtitle, "actions": actions}
        self.views[key] = view
        return view

    def add_button(self, view, text, command, predicate, primary_style):
        """Add a button to view's actions row, left to right in call order -> the ttk.Button.

        command runs on click; predicate() -> bool says when it is enabled (see refresh_buttons);
        primary_style draws it bold, for the view's main action.
        """
        style_name = "Primary.TButton" if primary_style else "TButton"
        button = ttk.Button(view["actions"], text=text, command=command, style=style_name)
        button.pack(side="left", padx=(0, 6))
        self.buttons.append((button, predicate))
        return button

    def make_table(self, parent, columns, values, sort_keys):
        """A sortable list with a scrollbar and a note line under it -> the table record.

        columns: list of (key, heading, width in pixels, anchor "w"/"e"/"center", stretch). values(row) ->
        tuple for a row, one text per column. sort_keys: column key -> sort key function of a row;
        clicking a heading not in it does nothing. The caller packs table["frame"].

        The table record: {"tree": the Treeview, "frame": its holder, "rows": the rows in shown order,
        "values", "sort_keys", "sorted_by": key or "", "descending": bool, "note": StringVar under the
        list, "extra_note": a note of the table's own that fill_table puts back}. A row's iid is its
        index in rows, so picked_rows can map the selection back.
        """
        holder = ttk.Frame(parent)
        keys = []
        for column in columns:
            keys.append(column[0])
        tree = ttk.Treeview(holder, columns=keys, show="headings", selectmode="extended")
        table = {"tree": tree, "frame": holder, "rows": [], "values": values, "sort_keys": sort_keys,
                 "sorted_by": "", "descending": False, "note": tk.StringVar(value=""), "extra_note": ""}
        for column in columns:
            tree.heading(column[0], text=column[1], anchor=column[3],
                         command=lambda key=column[0]: self.sort_table(table, key))
            tree.column(column[0], width=column[2], anchor=column[3], stretch=column[4])
        bar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        self.wrapping(ttk.Label(holder, textvariable=table["note"], style="Muted.TLabel")).pack(side="bottom", fill="x",
                                                                                              pady=(4, 0))
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda event: self.refresh_buttons())
        return table

    def fill_table(self, table, rows):
        """Replace a table's rows; only the first MAX_ROWS are shown, but table["rows"] keeps them all.

        A cut list says so in its note; otherwise the note is the table's extra_note.
        """
        tree = table["tree"]
        tree.delete(*tree.get_children())
        table["rows"] = rows
        shown = len(rows)
        if shown > MAX_ROWS:
            shown = MAX_ROWS
        index = 0
        while index < shown:
            tree.insert("", "end", iid=str(index), values=table["values"](rows[index]))
            index = index + 1
        if len(rows) > shown:
            table["note"].set("Showing the first " + human_count(shown) + " of " + human_count(len(rows))
                              + ". With nothing selected, actions apply to all of them.")
        else:
            table["note"].set(table["extra_note"])  # a note of the table's own that sorting must keep

    def sort_table(self, table, key):
        """Sort a table by the column key (a heading click): a second click on it reverses the order."""
        if key not in table["sort_keys"]:
            return
        if table["sorted_by"] == key:
            table["descending"] = not table["descending"]
        else:
            # Sizes, dates, counts and shares start with the biggest; the other columns start from A.
            table["descending"] = (key == "size" or key == "disk" or key == "modified" or key == "files"
                                   or key == "share")
        table["sorted_by"] = key
        rows = list(table["rows"])
        rows.sort(key=table["sort_keys"][key], reverse=table["descending"])
        self.fill_table(table, rows)

    def picked_rows(self, table):
        """Selected rows, or every row when nothing is selected."""
        chosen = table["tree"].selection()
        if len(chosen) == 0:
            return list(table["rows"])
        rows = []
        for iid in chosen:
            rows.append(table["rows"][int(iid)])
        return rows

    def has_rows(self, table):
        """Button predicate: the table has rows (shown or not)."""
        return len(table["rows"]) > 0

    def has_selection(self, table):
        """Button predicate: at least one row of the table is selected."""
        return len(table["tree"].selection()) > 0

    def path_key(self, row):
        """Sort key for a FileInfo row: its path, case ignored."""
        return row["path"].lower()

    def text_key(self, row):
        """Sort key for a row that is a plain string (a folder or an error line), case ignored."""
        return row.lower()

    def file_values(self, row):
        """The texts of a FileInfo row in a file list: path below the analyzed folder, on disk, size, changed."""
        name = self.rel(row["path"])
        if row["link"] is not None and row["link"] != "":
            name = name + "  (hard link)"  # one of several names: its space shows under the first one
        return (name, human_size(row["disk"]), human_size(row["size"]), human_date(row["modified"]))

    def reveal_first(self, table):
        """Open Explorer (or the platform's file manager) with the first picked row selected.

        Rows are FileInfo dicts or plain path strings; with nothing selected it is the table's first row.
        Starts a process through desktop.launch.
        """
        rows = self.picked_rows(table)
        if len(rows) > 0:
            target = rows[0]
            if isinstance(target, dict):
                target = target["path"]
            launch(reveal_command(target))

    def double_click(self, table):
        """Make a double-click on the table show the picked file in its folder."""
        table["tree"].bind("<Double-1>", lambda event: self.reveal_first(table))

    # --- Overview ------------------------------------------------------------------------------------
    def trash_folder(self):
        """The analyzed folder's own trash folder, "" before any analysis. It may not exist yet."""
        if self.root == "":
            return ""
        return os.path.join(self.root, TRASH_DIR_NAME)

    # --- Space map: a sunburst of the folders, angle by size -----------------------------------------
    # The map's state: map_tree is built by the analysis (its worker posts "tree") or, after files were
    # moved, by map_build_tree, a job of its own started the next time the map is shown; map_pending is
    # set while either is under way. Its duplicate marks are added lazily (map_prepare, map_wasted_ok).
    # Every new tree goes through set_map_tree. The list beside the map is refilled only when the tree or
    # the folder in the middle changed (map_serial, map_table_key).
    def map_ready(self):
        """Button predicate: there is a map tree and nothing is rebuilding it."""
        return self.map_tree is not None and not self.map_pending

    def map_can_go_up(self):
        """Button predicate: the map is ready and its centre is below the analyzed folder."""
        return self.map_ready() and self.map_center_node() is not self.map_tree

    def map_center_node(self):
        """The Node in the middle of the map; when map_center is no longer in the tree (it was moved
        away), the tree's root, and map_center is reset to the analyzed folder."""
        node = find_node(self.map_tree, self.root, self.map_center)
        if node is None:
            node = self.map_tree
            self.map_center = self.root
        return node

    def set_map_tree(self, tree):
        """Every new tree goes through here: its duplicate marks are due and the list beside the map
        is refilled at the next draw."""
        self.map_tree = tree
        self.map_serial = self.map_serial + 1
        self.map_wasted_ok = False
        self.map_build_error = ""
        if tree is None:
            self.set_side("map", "")
        else:
            self.set_side("map", plural(len(tree["folder_list"]), "folder"))

    def map_prepare(self):
        """Make map_tree match the report and the duplicate groups. The analysis builds the tree on its
        worker thread; when there is none (after files were moved) map_build_tree builds one in the
        background, so the window never waits for it."""
        report = self.report
        if report is None or self.map_pending:
            return
        if self.map_tree is None:
            if self.map_build_error == "":
                self.map_build_tree()
            return
        if not self.map_wasted_ok and self.groups is not None:
            mark_wasted(self.map_tree, self.root, self.groups, self.keep)
            self.map_wasted_ok = True

    def map_build_tree(self):
        """Build the tree and its duplicate marks as a job, only when the map needs them. A job already
        running goes first; the map is drawn when it ends (see run_job)."""
        if self.busy or self.report is None:
            return
        root = self.root
        files = self.report["files"]
        trash = self.report["trash"]
        groups = self.groups
        keep = self.keep  # not changed while a job runs: "Keep selected copy" waits for it
        before = self.status_var.get()
        self.map_pending = True

        def work(post):
            """Worker thread: build the Node tree from the copied lists and mark the duplicate copies."""
            tree = build_folder_tree(root, files, trash)
            if groups is not None:
                mark_wasted(tree, root, groups, keep)
            return success(tree)

        def finish(result):
            """Tk thread: take the new tree and draw it if the map is still shown."""
            self.map_pending = False
            self.set_map_tree(result["value"])
            # The marks match only if the groups are still the ones the job was given.
            self.map_wasted_ok = groups is not None and groups is self.groups
            self.status_var.set(before)  # keep the message of the action that made the map out of date
            if self.view == "map":
                self.map_draw()

        def on_fail(result):
            """Tk thread: keep the reason, so the map says it and is not rebuilt again and again."""
            self.map_pending = False
            self.map_build_error = result["error"]
            if self.view == "map":
                self.map_draw()

        self.run_job("Drawing the map", work, finish, None, on_fail)

    def map_name(self, path):
        """path as the info line shows it: relative to the folder in the middle of the map, which is
        shorter than relative to the analyzed folder."""
        centre = self.map_center
        text = path
        if is_inside(centre, path):
            text = relative_path(centre, path)
        if text == "":
            text = os.path.basename(path.rstrip("\\/"))
            if text == "":
                text = path
        return text

    def fit_middle(self, text, font, room):
        """text, shortened in the middle with "…" until it is at most room pixels wide in font."""
        if room <= 0 or font.measure(text) <= room:
            return text
        low = 0
        high = len(text)
        while low < high:  # the longest kept length that still fits
            middle = (low + high + 1) // 2
            head = middle // 2
            candidate = text[0:head] + "…" + text[len(text) - (middle - head):]
            if font.measure(candidate) <= room:
                low = middle
            else:
                high = middle - 1
        head = low // 2
        return text[0:head] + "…" + text[len(text) - (low - head):]

    def fit_text(self, text, font, room):
        """text, cut with "…" until it is at most room pixels wide in font ("" if not even that fits)."""
        if font.measure(text) <= room:
            return text
        cut = len(text) - 1
        while cut > 0 and font.measure(text[0:cut] + "…") > room:
            cut = cut - 1
        if cut == 0:
            return ""
        return text[0:cut] + "…"

    def duplicates_state(self):
        """"ready"; "reading" (a new analysis is reading folders); "comparing" (the analysis is still
        comparing files); or "missing" (the comparison was cancelled or failed)."""
        if self.map_scanning:
            return "reading"
        if self.groups is not None:
            return "ready"
        if self.dup_note.startswith("comparing"):
            return "comparing"
        return "missing"

    def map_arc_text(self, arc, node):
        """Two lines: the name, shortened to fit one line, then the numbers. So a long path can never push
        the size or the duplicate status out of the two-line box."""
        name = arc["name"]
        if arc["kind"] == "folder" or arc["kind"] == "file":
            name = self.map_name(arc["path"])
        elif arc["kind"] == "trash":
            name = "Trash folder: " + self.map_name(arc["path"])
        elif arc["kind"] == "rest":
            name = name + " in " + self.map_name(arc["path"])
        room = 0
        try:
            room = int(str(self.map_info_label.cget("wraplength"))) - 8
        except (ValueError, tk.TclError):
            room = 0
        if room < 100:
            room = self.map_info_label.winfo_width() - 8
        name = self.fit_middle(name, self.base_font, room)
        share = 0.0
        if node["bytes"] > 0:
            share = 100.0 * arc["bytes"] / node["bytes"]
        details = human_size(arc["bytes"]) + " on disk  ·  %.1f %%" % share
        if arc["kind"] == "file":
            if arc["size"] != arc["bytes"]:
                details = details + "  ·  file size " + human_size(arc["size"])
            details = details + "  ·  changed " + human_date(arc["modified"])
        elif arc["kind"] == "trash":
            # Moved here by this program: still on the drive, and never compared again.
            return (name + "\n" + details + "  ·  " + plural(arc["files"], "file")
                    + "  ·  freed when the folder is deleted")
        else:
            details = details + "  ·  " + plural(arc["files"], "file")
            if arc["trash"] > 0:
                details = details + "  ·  " + human_size(arc["trash"]) + " in the trash"
        if self.map_mode_var.get() == "duplicates":
            status = self.duplicates_state()
            if status == "reading" or status == "comparing":
                details = details + "  ·  duplicates not compared yet"
            elif status == "missing":
                details = details + "  ·  duplicates were not compared"
            elif arc["kind"] == "file":
                if arc["wasted"] > 0:
                    details = details + "  ·  an extra duplicate copy"
                else:
                    details = details + "  ·  not an extra copy"
            else:
                details = details + "  ·  " + human_size(arc["wasted"]) + " in duplicate copies"
        return name + "\n" + details

    def map_default_text(self, node):
        """Kept short: the line above the map is two lines tall, also in the narrowest window."""
        up = ""
        if self.map_can_go_up():
            up = ", the centre or Backspace to go up"
        if self.map_mode_var.get() == "duplicates":
            status = self.duplicates_state()
            if status == "reading":
                return "Reading folders again; duplicates are compared after that."
            if status == "comparing":
                return "Duplicates are still being compared; the map turns red where copies are found."
            if status == "missing":
                note = self.dup_note
                if note == "":
                    note = "not compared"
                return "Duplicates were " + note + ". Analyze again to compare them and see where copies are."
            return ("Red marks duplicate copies: the redder, the more of the slice they take. Click a folder to zoom in"
                    + up + ".")
        return "Point at a slice for details. Click a folder to zoom in" + up + ". Right-click for more."

    def map_draw(self):
        """Draw the map of the folder in the middle (or say why there is none), with the line above it and
        the list beside it. Rings are folder levels: the centre circle is MAP_HOLE of the radius, the rings
        share the rest, and a canvas too small for a MAP_SMALLEST_RADIUS map shows no map."""
        self.map_canvas.delete("all")
        self.map_items = {}
        self.map_hover_item = None
        self.map_prepare()
        width = self.map_canvas.winfo_width()
        height = self.map_canvas.winfo_height()
        tree = self.map_tree
        if tree is None or self.report is None or self.map_pending:
            waiting = "Analyze a folder to see where its space goes."
            if self.map_pending:
                waiting = "Drawing the map…"
            elif self.report is None and self.map_scanning:
                waiting = "Reading folders…"
            elif self.report is not None and self.map_build_error != "":
                waiting = "The map could not be drawn: " + self.map_build_error
            elif self.report is not None and self.busy:
                waiting = "The map is drawn when the current task ends."
            self.map_canvas.create_text(width / 2, height / 2, text=waiting, fill="#6b6b6b", font=self.base_font)
            self.map_view["subtitle"].set("")
            self.map_info.set("")
            self.map_fill_table(None)
            self.refresh_buttons()
            return
        node = self.map_center_node()
        mode = self.map_mode_var.get()
        subtitle = node["path"] + "  ·  " + human_size(node["bytes"]) + " on disk in " + plural(node["files"], "file")
        if node["trash"] > 0:
            subtitle = subtitle + ", " + human_size(node["trash"]) + " of it in the trash folder"
        self.map_view["subtitle"].set(subtitle)
        self.map_info.set(self.map_default_text(node))
        self.map_fill_table(node)
        self.refresh_buttons()
        radius = (min(width, height) - 16) / 2.0
        if radius < MAP_SMALLEST_RADIUS:
            return
        cx = width / 2.0
        cy = height / 2.0
        hole = radius * MAP_HOLE
        # Slices must be wide enough to see; the angle that takes depends on the ring's radius. Six
        # rings is the most there can be, so these angles are safe however many rings are drawn.
        min_angles = ring_min_angles(MAP_DEPTH, hole, (radius - hole) / MAP_DEPTH, MAP_MIN_PIXELS, MAP_MIN_DEGREES)
        arcs = layout_sunburst(node, MAP_DEPTH, min_angles)
        rings = MAP_FEWEST_RINGS
        for arc in arcs:
            if arc["depth"] > rings:
                rings = arc["depth"]
        ring = (radius - hole) / rings
        for arc in arcs:
            inner = hole + (arc["depth"] - 1) * ring
            points = ring_points(cx, cy, inner, inner + ring, arc["start"], arc["extent"], MAP_POINT_STEP)
            item = self.map_canvas.create_polygon(points, fill=arc_color(arc, mode, rings),
                                                  outline=self.canvas_background, width=1)
            self.map_items[item] = arc
        self.map_canvas.create_oval(cx - hole, cy - hole, cx + hole, cy + hole, fill="#ffffff", outline="#c8c8c8",
                                    tags=("centre",))
        # The labels fit inside the hole and cannot be clicked: only the hole itself means "go up".
        room = 2 * hole - 8
        label = self.fit_text(node["name"], self.strong_font, room)
        size_text = human_size(node["bytes"])
        if self.base_font.measure(size_text) > room:
            size_text = ""  # a cut number reads wrong; the line above the map shows it anyway
        self.map_canvas.create_text(cx, cy - self.line_height / 2, text=label, font=self.strong_font,
                                    tags=("centre",), state="disabled")
        self.map_canvas.create_text(cx, cy + self.line_height / 2, text=size_text, fill="#6b6b6b",
                                    font=self.base_font, tags=("centre",), state="disabled")

    def map_fill_table(self, node):
        """Fill "Biggest here" for the folder in the middle; skipped when it already shows that folder of
        this tree (a resize or a colour change does not change it)."""
        key = None
        if node is not None:
            key = (self.map_serial, node["path"])
        if key == self.map_table_key:
            return
        self.map_table_key = key
        rows = []
        self.map_table["extra_note"] = ""
        if node is not None:
            # Rows are plain copies: the table must not keep the tree (and every file record) alive.
            for entry in map_entries(node, MAX_ROWS):
                share = 0.0
                if node["bytes"] > 0:
                    share = 100.0 * entry["bytes"] / node["bytes"]
                label = entry["name"]
                if entry["kind"] == "trash":
                    label = "Trash folder"
                rows.append({"kind": entry["kind"], "name": entry["name"], "label": label, "path": entry["path"],
                             "bytes": entry["bytes"], "share": "%.1f %%" % share})
            count = map_item_count(node)
            if count > len(rows):
                self.map_table["extra_note"] = ("The biggest " + human_count(len(rows)) + " of " + human_count(count)
                                                + ".")
        self.fill_table(self.map_table, rows)
        tree_widget = self.map_table["tree"]
        if len(rows) > 0:
            # Refilling drops the keyboard position; put it back on the first row so Down and Enter work.
            tree_widget.focus("0")
            try:
                focused = self.window.focus_get()
            except (KeyError, tk.TclError):  # focus in a widget tkinter does not know, e.g. a list popup
                focused = None
            if focused == tree_widget:
                tree_widget.selection_set("0")

    def map_target(self, event):
        """The Arc under the mouse, "centre", or None."""
        found = self.map_canvas.find_withtag("current")
        # Tk's "current" tag marks the topmost canvas item under the mouse (disabled items are skipped)
        if len(found) == 0:
            return None
        if found[0] in self.map_items:
            return self.map_items[found[0]]
        if "centre" in self.map_canvas.gettags(found[0]):
            return "centre"
        return None

    def map_hover(self, event):
        """Mouse moved over (or left) the map: outline the slice under it and describe it in the info line.

        Off any slice, the info line goes back to the default help text and the cursor is a hand only
        over a centre that can go up. Nothing changes while the pointer stays on the same slice.
        """
        found = self.map_canvas.find_withtag("current")
        item = None
        if len(found) > 0 and found[0] in self.map_items:
            item = found[0]
        if item == self.map_hover_item:
            return
        if self.map_hover_item is not None:
            self.map_canvas.itemconfigure(self.map_hover_item, outline=self.canvas_background, width=1)
        self.map_hover_item = item
        if self.map_tree is None:
            return
        if item is None:
            self.map_canvas.configure(cursor="hand2" if self.map_target(event) == "centre" and self.map_can_go_up()
                                      else "")
            self.map_info.set(self.map_default_text(self.map_center_node()))
            return
        arc = self.map_items[item]
        self.map_canvas.itemconfigure(item, outline="#202020", width=2)
        self.map_canvas.tag_raise(item)
        self.map_canvas.tag_raise("centre")  # keep the centre's labels readable over the outline
        self.map_canvas.configure(cursor="hand2" if arc["kind"] == "folder" else "")
        self.map_info.set(self.map_arc_text(arc, self.map_center_node()))

    def map_zoom(self, path):
        """Put the folder path in the middle of the map and draw it again."""
        self.map_center = path
        self.map_draw()

    def map_zoom_from_menu(self, path):
        """Zoom to path from the right-click menu, giving the canvas the keyboard focus first."""
        self.map_canvas.focus_set()  # so the Backspace the info line mentions goes up, as after a click
        self.map_zoom(path)

    def map_up(self):
        """Move the map's centre up one folder, never above the analyzed folder."""
        if not self.map_can_go_up():
            return
        root = self.root
        parent = os.path.dirname(self.map_center)
        # dirname keeps the separator of a share root (\\nas\media\), so compare without separators.
        if not is_inside(root, parent) or len(parent.rstrip("\\/")) <= len(root.rstrip("\\/")):
            parent = root
        self.map_zoom(parent)

    def map_click(self, event):
        """A click on the map: the centre goes up a level, a folder slice zooms in, anything else does nothing.

        Remembers the item clicked in map_pressed, which map_double_click compares against.
        """
        self.map_canvas.focus_set()  # so Backspace goes up a level instead of editing the folder box
        found = self.map_canvas.find_withtag("current")
        self.map_pressed = found[0] if len(found) > 0 else None
        target = self.map_target(event)
        if target == "centre":
            self.map_up()
        elif target is not None and target["kind"] == "folder":
            self.map_zoom(target["path"])

    def map_double_click(self, event):
        """Show a file in its folder. Only when the first click left the map as it was: after a zoom
        (new canvas items) the pointer is over something else, which the user never pointed at. Quick
        clicks on the centre still each go up a level."""
        if self.map_target(event) == "centre":
            self.map_up()
            return
        found = self.map_canvas.find_withtag("current")
        if len(found) == 0 or found[0] != self.map_pressed:
            return
        target = self.map_target(event)
        if target is not None and target["kind"] == "file":
            launch(reveal_command(target["path"]))

    def map_triple_click(self, event):
        """A third quick click on the map; Tk sends it instead of another double-click."""
        # A third quick click: up again on the centre, nothing elsewhere (the file was shown already).
        if self.map_target(event) == "centre":
            self.map_up()

    def map_right_click(self, event):
        """Pop up the map's menu for the slice or centre under the mouse: Zoom in (folders), open, show."""
        target = self.map_target(event)
        if target is None:
            return
        if target == "centre":
            path = self.map_center
            kind = "centre"
        else:
            path = target["path"]
            kind = target["kind"]
        # A file is never handed to the file manager to open (that would run it): only its folder.
        folder = path
        if kind == "file":
            folder = os.path.dirname(path)
        self.map_menu.delete(0, "end")
        if kind == "folder":
            self.map_menu.add_command(label="Zoom in", command=lambda: self.map_zoom_from_menu(path))
        self.map_menu.add_command(label="Open its folder" if kind == "file" else "Open folder",
                                  command=lambda: launch(open_folder_command(folder)))
        self.map_menu.add_command(label="Show in its folder", command=lambda: launch(reveal_command(path)))
        self.map_menu.tk_popup(event.x_root, event.y_root)

    def map_resized(self, event):
        """The canvas changed size: draw again once it has kept one size for MAP_REDRAW_MS.

        Dragging a window edge sends a stream of <Configure> events; each one cancels the pending redraw
        and schedules a new one (a debounce), so the map is drawn once the drag pauses.
        """
        if self.map_redraw is not None:
            self.window.after_cancel(self.map_redraw)
        self.map_redraw = self.window.after(MAP_REDRAW_MS, self.map_resize_done)

    def map_resize_done(self):
        """The debounced redraw after a resize; only draws while the map is the view shown."""
        self.map_redraw = None
        if self.view == "map":
            self.map_draw()

    def map_table_open(self, event):
        """Enter (or a double-click) on "Biggest here": zoom into a folder row, show any other row in its folder.

        Needs a selected row: picked_rows alone would fall back to every row.
        """
        rows = self.picked_rows(self.map_table)
        if len(self.map_table["tree"].selection()) == 0 or len(rows) == 0:
            return
        if rows[0]["kind"] == "folder":
            self.map_zoom(rows[0]["path"])
        else:
            launch(reveal_command(rows[0]["path"]))  # select the file in its folder; never open it

    def map_table_double_click(self, event):
        """A double-click on "Biggest here" opens the row like Enter does."""
        # Only a double-click on a row: not on a heading, a column divider or the empty space below.
        if self.map_table["tree"].identify_region(event.x, event.y) == "cell":
            self.map_table_open(event)

    def map_backspace(self, event):
        """Backspace anywhere in the window goes up a level on the map, while the map is shown.

        The binding is on the whole window, so text fields are skipped: there Backspace deletes text.
        """
        if self.view != "map":
            return
        if isinstance(event.widget, (ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Entry, tk.Text)):
            return
        self.map_up()

    # --- Old files -------------------------------------------------------------------------------------
    def change_days(self):
        """Take the Old files day count from its box: save it in the settings and list the old files again.

        Text that is not a number puts the last good value back; 0 or less, or no change, does nothing.
        Writes the settings file.
        """
        try:
            days = int(self.days_var.get())
        except (ValueError, tk.TclError):
            self.days_var.set(self.old_days)
            return
        if days < 1 or days == self.old_days:
            return
        self.old_days = days
        self.settings["stale_days"] = days
        save_settings(self.path_to_settings, self.settings)
        if self.report is not None:
            self.report["stale"] = stale_files(self.report["files"], days, time.time())
            self.refresh_all()

    # --- Duplicates: the tree's rows are "g<N>" for group N and "g<N>:<i>" for its copy i --------------
    def has_groups(self):
        """Button predicate: the comparison ran and found at least one group of duplicates."""
        return self.groups is not None and len(self.groups) > 0

    def selected_group_numbers(self):
        """Group numbers with a selected row, the group's own row or one of its copies -> dict N -> True.

        "g12" and "g12:3" both give 12: the part before ":" without its "g".
        """
        numbers = {}
        for iid in self.dup_tree.selection():
            numbers[int(iid.split(":")[0][1:])] = True
        return numbers

    def selected_copies(self):
        """(group number, index) of each selected file row."""
        pairs = []
        for iid in self.dup_tree.selection():
            if ":" in iid:
                parts = iid.split(":")
                pairs.append((int(parts[0][1:]), int(parts[1])))
        return pairs

    def keep_selected(self):
        """Make each selected copy the one its group keeps, then refresh the Duplicates view.

        A group keeps one copy: choosing one drops any earlier choice in the same group from keep.
        """
        groups = self.groups
        for pair in self.selected_copies():
            group = groups[pair[0]]
            kept_before = group[keeper_index(group, self.keep)]
            for info in group:
                if info["path"] in self.keep:
                    del self.keep[info["path"]]
            self.keep[group[pair[1]]["path"]] = True
            if self.map_tree is not None and self.map_wasted_ok:
                # Move this group's marks on the map now; recounting every copy would freeze the window.
                shift_kept_copy(self.map_tree, self.root, kept_before, group[pair[1]])
        self.refresh_duplicates()

    def trash_duplicates(self):
        """After asking, move every copy but the kept one to the trash, for the selected groups or all.

        Moves files on a worker thread (apply_and_forget); undoable.
        """
        groups = self.groups
        numbers = self.selected_group_numbers()
        chosen = []
        index = 0
        while index < len(groups):
            if len(numbers) == 0 or index in numbers:
                chosen.append(groups[index])
            index = index + 1
        moves = plan_duplicate_removal(self.root, chosen, self.keep)
        savings = duplicate_savings(chosen, self.keep)
        scope = "selected groups" if len(numbers) > 0 else "all groups"
        if not self.ask("Move " + plural(len(moves), "extra copy") + " from " + scope + " to the trash folder?\n\n"
                        "One copy of each file stays. Deleting the trash folder then frees "
                        + human_size(savings["bytes"]) + " on disk. Undo is available."):
            return
        self.apply_and_forget("Moving duplicates to the trash", moves, "Moved")

    def reveal_copy(self):
        """Show the first selected copy in its folder; a selected group row alone does nothing."""
        pairs = self.selected_copies()
        if len(pairs) > 0:
            launch(reveal_command(self.groups[pairs[0][0]][pairs[0][1]]["path"]))

    # --- Empty folders ---------------------------------------------------------------------------------
    def remove_empty(self):
        """After asking, remove the picked empty folders and the empty folders inside them; undoable."""
        chosen = {}
        for folder in self.picked_rows(self.empty_table):
            chosen[folder] = True
        folders = select_empty_dirs(self.report["empty_dirs"], chosen, self.root)
        if not self.ask("Remove " + plural(len(folders), "empty folder")
                        + "?\n\nThey hold no files. Undo is available."):
            return
        self.apply_and_forget("Removing empty folders", plan_empty_dir_removal(folders), "Removed")

    # --- Organize --------------------------------------------------------------------------------------
    def clear_organize(self):
        """Drop the Organize preview (a mode change makes it stale) and show the view's help line."""
        self.org_moves = []
        self.fill_table(self.org_table, [])
        self.organize_view["subtitle"].set("Sorts the files directly inside the folder into subfolders. "
                                           "Folders are left alone.")
        self.refresh_buttons()

    def preview_organize(self):
        """Plan the Organize moves for the folder in the folder box, as a job, and list them. Moves nothing.

        The folder and mode are read now, on the Tk thread; the job only gets plain values.
        """
        folder = self.current_folder()
        if folder == "":
            return
        mode = self.org_mode.get()

        def finish(result):
            """Tk thread: keep the plan for Apply, list it and say how many files go into how many folders."""
            self.org_moves = result["value"]
            self.org_root = folder
            self.fill_table(self.org_table, result["value"])
            targets = {}
            for move in result["value"]:
                targets[os.path.dirname(move["target"])] = True
            self.organize_view["subtitle"].set(plural(len(result["value"]), "file") + " would move into "
                                               + plural(len(targets), "folder") + " in " + folder)

        self.run_job("Planning", lambda post: plan_organize(folder, mode, self.cancel_flag), finish, None, None)

    def apply_organize(self):
        """After asking, carry out the previewed Organize moves as a job; undoable from that folder."""
        moves = self.org_moves
        root = self.org_root
        if not self.ask("Move " + plural(len(moves), "file") + " into subfolders of " + root
                        + "?\n\nUndo is available."):
            return

        def finish(result):
            """Tk thread: report, clear the preview, and analyze again when the results show that folder."""
            self.report_apply(result, "Moved")
            self.clear_organize()
            # the new analysis starts from the event loop, after run_job's poll has finished with this job
            if self.report is not None and os.path.normcase(self.root) == os.path.normcase(root):
                self.window.after(10, self.analyze)

        self.run_job("Organizing", lambda post: apply_moves(root, moves, self.cancel_flag, self.progress_sender(post)),
                     finish, None, None)

    # --- Network shares --------------------------------------------------------------------------------
    def rebuild_shares(self):
        """Refill the list from the settings, keeping what was last found out about each share."""
        old_rows = {}
        for row in self.net_rows:
            old_rows[row["share"]["unc"].lower()] = row
        del self.net_rows[:]
        for share in self.settings["shares"]:
            key = share["unc"].lower()
            if key in old_rows:
                old_rows[key]["share"] = share
                self.net_rows.append(old_rows[key])
            else:
                self.net_rows.append({"share": share, "status": "not checked", "free": "", "total": ""})
        self.fill_table(self.net_table, list(self.net_rows))
        self.refresh_buttons()

    def selected_share(self):
        """The Share record of the first selected row in the Network list, or None."""
        chosen = self.net_table["tree"].selection()
        if len(chosen) == 0:
            return None
        return self.net_table["rows"][int(chosen[0])]["share"]

    def add_share_dialog(self):
        """Open the modal Add network share dialog: share path, name and drive letter.

        Add (or Enter) checks the fields and, when they are good, saves the share in the settings file
        and refills the list; a bad field shows its problem in red and keeps the dialog open. No password
        is asked or stored. grab_set makes the dialog modal: the main window takes no input until it closes.
        """
        dialog = tk.Toplevel(self.window)
        dialog.title("Add network share")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=14)
        form.pack(fill="both", expand=True)
        unc_var = tk.StringVar()
        name_var = tk.StringVar()
        letter_var = tk.StringVar()
        problem = tk.StringVar(value="")
        ttk.Label(form, text="Share path").grid(row=0, column=0, sticky="w", pady=3)
        unc_entry = ttk.Entry(form, textvariable=unc_var, width=36)
        unc_entry.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(form, text="e.g. \\\\nas01\\media", style="Muted.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Name").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=name_var, width=36).grid(row=2, column=1, sticky="we", pady=3)
        ttk.Label(form, text="Drive letter").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=letter_var, width=6).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(form, textvariable=problem, foreground="#a33a1a").grid(row=4, column=0, columnspan=2, sticky="w")
        row = ttk.Frame(form)
        row.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def save():
            """Check the fields; save the new share and close the dialog, or show what is wrong."""
            unc = unc_var.get().strip()
            letter = letter_var.get().strip().upper()
            # "z" is accepted for "Z:"
            if len(letter) == 1:
                letter = letter + ":"
            if unc_host(unc) == "":
                problem.set("The share path must look like \\\\host\\share.")
                return
            if not valid_letter(letter):
                problem.set("The drive letter must be D: to Z:, or empty.")
                return
            name = name_var.get().strip()
            if name == "":
                name = unc_host(unc)
            self.settings["shares"].append({"name": name, "unc": unc, "letter": letter})
            save_settings(self.path_to_settings, self.settings)
            self.log("added share " + name + " (" + unc + ")")
            dialog.destroy()
            self.rebuild_shares()

        ttk.Button(row, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(row, text="Add", style="Primary.TButton", command=save).pack(side="right", padx=6)
        dialog.bind("<Return>", lambda event: save())
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        unc_entry.focus_set()
        dialog.grab_set()

    def check_shares(self):
        """Check every saved share as a job (ping the host, read the space) and show the outcome per row.

        Each check runs OS commands and can take seconds; Cancel stops between shares.
        """
        rows = list(self.net_rows)

        def work(post):
            """Worker thread: check the shares in order -> Result(list of (row, ShareState))."""
            results = []
            for row in rows:
                if is_cancelled(self.cancel_flag):
                    break
                results.append((row, check_share(row["share"])))
            return success(results)

        def finish(result):
            """Tk thread: write each share's status and space into its row, log it and refill the list."""
            for pair in result["value"]:
                row = pair[0]
                found = pair[1]
                if found["reachable"]:
                    row["status"] = "online"
                    row["free"] = human_size(found["free"])
                    row["total"] = human_size(found["total"])
                else:
                    row["status"] = found["error"]
                    row["free"] = ""
                    row["total"] = ""
                self.log("  " + row["share"]["name"] + ": " + row["status"])
            self.fill_table(self.net_table, list(self.net_rows))

        self.run_job("Checking shares", work, finish, None, None)

    def analyze_share(self):
        """Put the selected share's path (its drive letter when it has one) in the folder box and analyze it."""
        share = self.selected_share()
        if share is not None:
            self.folder_var.set(share_path(share))
            self.analyze()

    def map_selected(self):
        """Map the selected share to its drive letter ("net use", Windows) as a job, then check the shares."""
        share = self.selected_share()
        if share is None:
            return
        self.run_job("Mapping " + share["unc"], lambda post: map_share(share), lambda result: self.check_shares_later(),
                     None, None)

    def unmap_selected(self):
        """After asking, disconnect the selected share's drive letter as a job, then check the shares."""
        share = self.selected_share()
        if share is None or not self.ask("Disconnect " + share_path(share) + "?"):
            return
        self.run_job("Disconnecting " + share["unc"], lambda post: unmap_share(share),
                     lambda result: self.check_shares_later(), None, None)

    def check_shares_later(self):
        """Start check_shares from the event loop: called from a job's finish, while run_job still ends that job."""
        self.window.after(10, self.check_shares)

    def remove_share(self):
        """Remove the selected share from the saved list (settings file); nothing is disconnected."""
        share = self.selected_share()
        if share is None:
            return
        self.settings["shares"].remove(share)
        save_settings(self.path_to_settings, self.settings)
        self.log("removed share " + share["name"] + " from the list")
        self.rebuild_shares()

    def backup_to_share(self):
        """Back up a folder the user picks to a folder of the same name on the selected share.

        Steps:
          1. Ask for the folder; the target is the share's path plus the folder's name.
          2. A job compares the two (plan_sync) and lists the files that are new or changed.
          3. After the user confirms the count and size, a second job copies them (apply_copies).
        Nothing in the target is deleted.
        """
        share = self.selected_share()
        if share is None:
            return
        start = self.settings["last_folder"] if self.settings["last_folder"] != "" else None
        folder = filedialog.askdirectory(parent=self.window, initialdir=start,
                                         title="Folder to back up to " + share["name"])
        if not folder:
            return
        folder = os.path.normpath(folder)
        target = os.path.join(share_path(share), os.path.basename(folder))

        def finish(result):
            """Tk thread: say when there is nothing to copy, else ask and start the copying job."""
            copies = result["value"]
            total = 0
            for copy in copies:
                total = total + copy["size"]
            if len(copies) == 0:
                self.status_var.set(target + " is already up to date")
                self.log("  up to date")
                return
            if not self.ask("Copy " + plural(len(copies), "new or changed file") + " (" + human_size(total) + ") to "
                            + target + "?\n\nNothing in the target is deleted."):
                return
            self.run_job("Backing up to " + target,
                         lambda post: apply_copies(copies, self.cancel_flag, self.progress_sender(post)),
                         lambda copy_result: self.report_apply(copy_result, "Copied"), None, None)

        self.run_job("Comparing " + folder + " with " + target,
                     lambda post: plan_sync(folder, target, self.cancel_flag, self.progress_sender(post)), finish,
                     None, None)

    # --- Activity --------------------------------------------------------------------------------------
    def clear_log(self):
        """Empty the Activity view (the Clear button)."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # --- refreshing the views from the state -----------------------------------------------------------
    def set_side(self, key, text):
        """Set the short count shown beside a view's name in the sidebar."""
        self.sidebar.set(key, "info", text)

    def refresh_all(self):
        """Push the current report and duplicate groups into the sidebar and every view.

        With no report, clears the sidebar counts and the map. Otherwise: the sidebar counts, the
        Overview (totals, drive, trash, what is worth a look, space by type), the file lists, then the
        Duplicates view (refresh_duplicates) and the buttons. Tk thread only.
        """
        report = self.report
        if report is None:
            for entry in VIEWS:
                self.set_side(entry[0], "")
            self.set_map_tree(None)
            if self.view == "map":
                self.map_draw()
            self.refresh_buttons()
            return
        stale_total = total_disk(report["stale"])
        self.set_side("overview", human_size(report["total_bytes"]))
        self.set_side("largest", human_size(report["largest"][0]["disk"]) if len(report["largest"]) > 0 else "")
        self.set_side("old", human_count(len(report["stale"])) + " \u00b7 " + human_size(stale_total))
        self.set_side("empty", human_count(len(report["empty_dirs"])))
        self.set_side("errors", human_count(len(report["errors"])))
        if self.groups is None:
            self.set_side("duplicates", self.dup_note)
        else:
            savings = duplicate_savings(self.groups, self.keep)
            self.set_side("duplicates", human_count(savings["copies"]) + " \u00b7 " + human_size(savings["bytes"]))

        # Overview
        self.overview_files.set(plural(report["file_count"], "file") + " \u00b7 " + human_size(report["total_bytes"])
                                + " on disk in " + plural(report["dir_count"], "folder"))
        self.overview_sizes.set(disk_note(report, report["links_checked"] or self.groups is not None))
        drive = ""
        if report["drive_total"] > 0:
            drive = "Drive: " + human_size(report["drive_free"]) + " free of " + human_size(report["drive_total"]) + "."
        if len(report["trash"]) > 0:
            # Moving to the trash frees nothing yet: say where that space still is.
            drive = (drive + " The trash folder holds " + human_size(report["trash_bytes"]) + " in "
                     + plural(len(report["trash"]), "file") + " moved there; delete it to free that space.").strip()
        self.overview_drive.set(drive)
        parts = []
        if self.groups is not None:
            savings = duplicate_savings(self.groups, self.keep)
            if savings["copies"] > 0:
                parts.append(human_size(savings["bytes"]) + " in " + plural(savings["copies"], "duplicate copy"))
        if len(report["stale"]) > 0:
            parts.append(human_size(stale_total) + " in " + plural(len(report["stale"]), "old file"))
        if len(report["empty_dirs"]) > 0:
            parts.append(plural(len(report["empty_dirs"]), "empty folder"))
        if len(parts) > 0:
            self.overview_reclaim.set("Worth a look: " + "  \u00b7  ".join(parts))
        else:
            self.overview_reclaim.set("Nothing obvious to clean up.")
        type_rows = []
        for name in report["by_type"]:
            entry = report["by_type"][name]
            share = 0.0
            if report["total_bytes"] > 0:
                share = 100.0 * entry["bytes"] / report["total_bytes"]
            type_rows.append({"type": name, "files": entry["files"], "bytes": entry["bytes"],
                              "share": "%.1f %%" % share})
        type_rows.sort(key=lambda row: row["bytes"], reverse=True)
        self.fill_table(self.type_table, type_rows)
        self.overview_view["subtitle"].set(report["root"])

        # Lists
        self.fill_table(self.largest_table, list(report["largest"]))
        self.largest_view["subtitle"].set("The " + plural(len(report["largest"]), "file")
                                          + " that take the most space on disk. Select some, or act on all.")
        self.fill_table(self.old_table, list(report["stale"]))
        self.old_view["subtitle"].set(plural(len(report["stale"]), "file") + " (" + human_size(stale_total)
                                      + " on disk) not changed for " + plural(self.old_days, "day") + ".")
        empty_rows = list(report["empty_dirs"])
        empty_rows.sort(key=self.text_key)
        self.fill_table(self.empty_table, empty_rows)
        self.empty_view["subtitle"].set(plural(len(report["empty_dirs"]), "folder")
                                        + " with nothing in them, including nested ones.")
        self.fill_table(self.error_table, list(report["errors"]))
        self.errors_view["subtitle"].set(plural(len(report["errors"]), "path")
                                         + " could not be read (no rights, in use, or gone).")
        self.refresh_duplicates()
        self.refresh_buttons()

    def refresh_duplicates(self):
        """Refill the Duplicates tree: a bold row per group, then its copies, green for the kept one.

        Groups come biggest saving first (as find_duplicates_in returns them); rows stop near MAX_ROWS,
        always after a whole group. Without groups it says why (dup_note) instead.
        """
        # The space map shows the duplicate copies too; redraw it now if it is on screen. (Its marks are
        # only recomputed where the groups or the kept copies change, which sets map_wasted_ok.)
        if self.view == "map":
            self.map_draw()
        self.dup_tree.delete(*self.dup_tree.get_children())
        groups = self.groups
        if groups is None:
            self.duplicates_view["subtitle"].set(self.dup_note if self.dup_note != ""
                                                 else "Analyze a folder to compare its files.")
            self.dup_note_var.set("")
            self.refresh_buttons()
            return
        savings = duplicate_savings(groups, self.keep)
        self.duplicates_view["subtitle"].set(plural(len(groups), "file") + " stored more than once. Moving the extra "
                                             "copies to the trash folder and deleting it frees "
                                             + human_size(savings["bytes"]) + " on disk. "
                                             "Green is kept, red goes to the trash.")
        rows = 0
        number = 0
        linked = False
        while number < len(groups) and rows < MAX_ROWS:
            group = groups[number]
            keeper = keeper_index(group, self.keep)
            parent = "g" + str(number)
            self.dup_tree.insert("", "end", iid=parent, open=True, tags=("group",),
                                 text=os.path.basename(group[0]["path"]) + "  \u00b7  " + plural(len(group), "copy")
                                 + "  \u00b7  " + human_size(group_savings(group, self.keep)) + " to free",
                                 values=("", "", ""))
            index = 0
            while index < len(group):
                info = group[index]
                tag = "keep" if index == keeper else "trash"
                action = "keep" if index == keeper else "to trash"
                if info["link"] is not None and info["link"] != "":
                    action = action + " (hard link)"  # other names keep its data: moving it frees nothing
                    linked = True
                self.dup_tree.insert(parent, "end", iid=parent + ":" + str(index), text=self.rel(info["path"]),
                                     tags=(tag,),
                                     values=(human_size(info["disk"]), human_date(info["modified"]), action))
                index = index + 1
            rows = rows + len(group) + 1
            number = number + 1
        if number < len(groups):
            note = ("Showing the " + human_count(number) + " groups that save the most, of " + human_count(len(groups))
                    + ". With nothing selected, actions apply to all of them.")
        else:
            note = "Select rows to act on some groups only. \u201cKeep selected copy\u201d changes which one stays."
        if linked:
            note = note + " A hard link is a file with other names as well: moving one name frees nothing."
        self.dup_note_var.set(note)
        self.refresh_buttons()

    def show_view(self, key):
        """Show the view key: raise its frame over the others in main's cell and select it in the sidebar.

        The map is drawn on showing, since it is not kept up to date while hidden.
        """
        self.view = key
        self.views[key]["frame"].tkraise()
        if key == "map":
            self.map_draw()
        if tuple(self.sidebar.selection()) != (key,):
            self.sidebar.selection_set(key)

    def on_sidebar(self, event):
        """Sidebar selection changed: show that view. show_view selecting the row again fires this too,
        which the key != self.view check turns into nothing."""
        chosen = self.sidebar.selection()
        if len(chosen) == 0:
            return
        key = chosen[0]
        if key not in self.views:
            # A section heading: show its first entry instead.
            children = self.sidebar.get_children(key)
            if len(children) > 0:
                self.sidebar.selection_set(children[0])
            return
        if key != self.view:
            self.show_view(key)

    # --- the main actions ------------------------------------------------------------------------------
    def folder_choices(self):
        """The folder box's list, built each time it opens: recent folders, the drives, then the saved
        shares, each once (case ignored)."""
        choices = []
        seen = {}
        candidates = list(self.settings["recent"])
        for drive in list_drives():
            candidates.append(drive)
        for share in self.settings["shares"]:
            candidates.append(share_path(share))
        for item in candidates:
            key = os.path.normcase(item)
            if key not in seen:
                seen[key] = True
                choices.append(item)
        return choices

    def browse(self):
        """Pick a folder in the system folder dialog, starting at the one in the box, and analyze it."""
        start = self.folder_var.get().strip()
        chosen = filedialog.askdirectory(parent=self.window, initialdir=start if start != "" else None)
        if chosen:
            self.folder_var.set(os.path.normpath(chosen))
            self.analyze()

    def current_folder(self):
        """The folder in the folder box, checked and remembered -> the folder, or "" (and a message)."""
        folder = normalize_folder(self.folder_var.get())
        if folder == "" or not os.path.isdir(folder):
            self.status_var.set("Choose an existing folder or drive first.")
            self.folder_box.focus_set()
            return ""
        self.folder_var.set(folder)
        self.settings["last_folder"] = folder
        self.settings["recent"] = add_recent(self.settings["recent"], folder, RECENT_LIMIT)
        save_settings(self.path_to_settings, self.settings)
        return folder

    def analyze(self):
        """Analyze the folder in the box. The worker posts "scan" when the folders are read (the lists
        fill in), then "tree" for the map, then compares the files and returns the duplicate groups.

        Steps (worker thread):
          1. scan reads the folders -> ScanReport; posted as "scan".
          2. build_folder_tree makes the map's Node tree; posted as "tree".
          3. find_duplicates_in compares the files (the slow part) -> groups.
          4. When that comparison found hard links the listing hid, count_links_once makes a corrected
             report and the tree is built again; both go back with the groups.
        On the Tk thread, on_message takes "scan" and "tree" as they come and finish takes the rest. A
        failed or cancelled comparison keeps the report and says the duplicates were not compared.
        """
        if self.busy:
            return
        root = self.current_folder()
        if root == "":
            return
        days = self.old_days
        cancel_flag = self.cancel_flag

        def work(post):
            """Worker thread: scan, post the report and tree, compare -> Result({"groups", "report", "tree"})."""
            send = self.progress_sender(post)
            scanned = scan(root, LARGEST_COUNT, days, time.time(), cancel_flag, send)
            if not scanned["ok"]:
                return scanned
            report = scanned["value"]
            post("scan", report)
            post("tree", build_folder_tree(root, report["files"], report["trash"]))
            compared = find_duplicates_in(report["files"], cancel_flag, send)
            if not compared["ok"]:
                return compared
            found = {"groups": compared["value"]["groups"], "report": None, "tree": None}
            if len(compared["value"]["linked"]) > 0:
                # Hard links the listing did not show (Windows): count each such file once. Done here, on
                # the worker, so the window never waits for the new report and map.
                fixed = count_links_once(report, compared["value"]["linked"], LARGEST_COUNT, days, time.time())
                found["report"] = fixed
                found["tree"] = build_folder_tree(root, fixed["files"], fixed["trash"])
            return success(found)

        def on_message(kind, value):
            """Tk thread: "scan" makes the new report current and fills the views; "tree" gives the map its tree.

            The queue keeps their order, so "scan" (which clears the old tree) is always handled first.
            """
            if kind == "tree":
                self.set_map_tree(value)
                self.map_pending = False
                if self.view == "map":
                    self.map_draw()
            if kind == "scan":
                self.root = root
                self.report = value
                self.groups = None
                self.keep = {}
                self.set_map_tree(None)
                self.map_pending = True
                self.map_scanning = False
                self.map_center = root
                self.dup_note = "comparing\u2026"
                self.refresh_all()
                self.log("  " + plural(value["file_count"], "file") + ", " + human_size(value["total_bytes"])
                         + " on disk")
                if len(value["trash"]) > 0:
                    self.log("  trash folder: " + plural(len(value["trash"]), "file") + ", "
                             + human_size(value["trash_bytes"]))
                if self.view in ("network", "organize", "activity"):
                    self.show_view("overview")

        def finish(result):
            """Tk thread: take the corrected report and tree when there are any, then the duplicate groups."""
            found = result["value"]
            if found["report"] is not None:
                counted_once = found["report"]["saved"]["links"] - self.report["saved"]["links"]
                self.report = found["report"]
                if self.old_days != days:  # changed while the files were compared
                    self.report["stale"] = stale_files(self.report["files"], self.old_days, time.time())
                self.set_map_tree(found["tree"])
                self.map_pending = False
                self.log("  hard links counted once: " + human_size(counted_once) + " less on disk")
            self.groups = found["groups"]
            self.dup_note = ""
            self.map_wasted_ok = False
            self.refresh_all()
            savings = duplicate_savings(found["groups"], self.keep)
            self.log("  " + plural(savings["copies"], "duplicate copy") + ", " + human_size(savings["bytes"])
                     + " to free")
            self.status_var.set("Analyzed " + root + " \u2014 " + plural(self.report["file_count"], "file") + ", "
                                + human_size(savings["bytes"]) + " in duplicate copies")

        def on_fail(result):
            """Tk thread: the scan or the comparison failed or was cancelled; keep what arrived and say why."""
            self.map_scanning = False
            if self.map_pending:  # the tree never arrived; build it here when the map is shown
                self.map_pending = False
                if self.view == "map":
                    self.map_draw()
            if self.report is not None and self.root == root:
                self.dup_note = "not compared (" + result["error"] + ")"
                self.refresh_all()
            elif self.view == "map":
                self.map_draw()

        self.map_scanning = True
        self.run_job("Analyzing " + root, work, finish, on_message, on_fail)
        if self.view == "map" and self.report is None:
            self.map_draw()  # "Reading folders…" instead of "Analyze a folder" while the first walk runs

    def apply_and_forget(self, label, moves, verb):
        """Apply moves, then drop the moved paths from the results instead of analyzing again.

        label: the job's name; verb: the past tense report_apply shows ("Moved", "Removed"). Moves files
        on a worker thread and writes the undo log (apply_moves).
        """
        root = self.root

        def finish(result):
            """Tk thread: report, then take what moved out of the report, the groups and the map."""
            self.report_apply(result, verb)
            gone = {}
            for move in result["value"]["moved"]:
                target = ""
                if move["target"] != "" and in_trash_folder(move["target"]):
                    target = move["target"]  # still on the drive: counted in the trash from now on
                gone[move["source"]] = target
            files_before = self.report["file_count"]
            self.report = remove_from_report(self.report, gone, LARGEST_COUNT, self.old_days, time.time())
            if self.groups is not None:
                self.groups = remove_from_groups(self.groups, gone)
            if self.report["file_count"] < files_before:
                # The map is out of date. It is rebuilt in the background the next time it is shown, so a
                # move costs nothing more for someone who never opens the map.
                self.set_map_tree(None)
            self.refresh_all()

        self.run_job(label, lambda post: apply_moves(root, moves, self.cancel_flag, self.progress_sender(post)),
                     finish, None, None)

    def trash_rows(self, table):
        """After asking, move a file list's picked rows (selected, or all) to the trash folder; undoable."""
        rows = self.picked_rows(table)
        if len(rows) == 0:
            return
        scope = "selected " if self.has_selection(table) else ""
        if not self.ask("Move " + plural(len(rows), scope + "file") + " (" + human_size(total_disk(rows))
                        + " on disk) to the trash folder in " + self.root + "?\n\n"
                        "They stay on the drive until you delete the trash folder. Undo is available."):
            return
        self.apply_and_forget("Moving files to the trash", plan_trash(self.root, rows), "Moved")

    def undo(self):
        """After asking, reverse the last batch in the analyzed folder's undo log as a job, then analyze again.

        Ignored while a job runs or when that folder has no undo log (Ctrl+Z reaches here even then).
        """
        root = self.root
        if self.busy or root == "" or not os.path.isfile(undo_log_path(root)):
            return
        if not self.ask("Undo the last change made in " + root + "?"):
            return

        def finish(result):
            """Tk thread: report and analyze again, since files came back that the results do not list."""
            self.report_apply(result, "Restored")
            self.window.after(10, self.analyze)

        self.run_job("Undoing the last change", lambda post: undo_last(root), finish, None, None)

    def about(self):
        """Show the About box: name, version, license and the icon's credit."""
        messagebox.showinfo("About", APP_NAME + " " + __version__ + "\n\nGeneric Company Inc. is fictional.\n"
                            "License: AGPL-3.0.\n\n" + ICON_CREDIT, parent=self.window)

    def on_delete(self, event):
        """The Delete key runs the shown view's main action (primary), which asks first.

        Skipped in text fields (where Delete edits text), while a job runs and before any analysis.
        """
        if isinstance(event.widget, (ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Entry, tk.Text)):
            return
        if self.busy or self.report is None:
            return
        if self.view in self.primary:
            self.primary[self.view]()

    def close(self):
        """Closing the window: ask a running job to stop, save the window's size and place, and close.

        The worker is a daemon thread, so the process does not wait for it to notice the cancel.
        """
        self.cancel_flag[0] = True
        self.settings["geometry"] = self.window.geometry()
        save_settings(self.path_to_settings, self.settings)
        self.window.destroy()

    def write_smoke_report(self):
        """--smoke: once no job runs, write what the window shows to smoke_path as JSON and close."""
        if self.busy:
            self.window.after(SMOKE_RETRY_MS, self.write_smoke_report)
            return
        report = {"app_id": APP_ID, "version": __version__, "title": self.window.title(), "icon_set": self.icon_set,
                  "views": [], "shares": len(self.settings["shares"]), "folder": self.root,
                  "view": self.view, "status": self.status_var.get(), "sidebar": {}}
        for entry in VIEWS:
            report["views"].append(entry[1])
            report["sidebar"][entry[0]] = self.sidebar.set(entry[0], "info")
        handle = open(self.smoke_path, "w", encoding="utf-8")
        json.dump(report, handle, indent=2)
        handle.close()
        self.window.destroy()

# ==== stamp v1 | author=kjFriday | hmac-sha256=4f103ee45ca877cd9c2e2720c1c3b7993ed6f0671be1ac7a9bdaa0e48014f51d ====
