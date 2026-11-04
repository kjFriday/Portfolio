# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: gui_views.py
# About: Storage Manager window: the ten views, one build function each.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager window: the ten views, one build function each.

Each build function takes the StorageWindow (app), adds its view with app.make_view, creates the view's
widgets, buttons and bindings, and keeps on app the widgets and variables its handlers use later (its
docstring names them). The handlers are StorageWindow's methods in gui.py, which exist before any widget
does, so a view can be handed any handler, also one that uses widgets of a view built after it.

StorageWindow.__init__ calls these in the order they appear here. That is the order the widgets have
always been created in, which their Tk names and the Tab order follow, so keep it when adding a view.
"""

import os
import tkinter as tk
from tkinter import ttk

from desktop import launch, open_folder_command
from formatting import human_count, human_size
from paths import relative_path


def build_overview(app):
    """Overview: totals, the drive, what is worth a look, and space by type.

    Keeps overview_view, overview_files, overview_sizes, overview_drive, overview_reclaim and type_table.
    Its button is added later, by add_overview_actions."""
    app.overview_view = app.make_view("overview", "Overview")
    app.overview_files = tk.StringVar(value="No folder analyzed yet.")
    app.overview_sizes = tk.StringVar(value="Sizes are space on disk: what the files take on the drive.")
    app.overview_drive = tk.StringVar(value="Choose a folder or drive above and press Analyze. Nothing is changed without asking.")
    app.overview_reclaim = tk.StringVar(value="")
    ttk.Label(app.overview_view["frame"], textvariable=app.overview_files, style="Strong.TLabel").pack(anchor="w")
    app.wrapping(ttk.Label(app.overview_view["frame"], textvariable=app.overview_sizes,
                           style="Muted.TLabel")).pack(fill="x", pady=(2, 0))
    app.wrapping(ttk.Label(app.overview_view["frame"], textvariable=app.overview_drive)).pack(fill="x", pady=(2, 0))
    ttk.Label(app.overview_view["frame"], textvariable=app.overview_reclaim).pack(anchor="w", pady=(2, 10))
    # make_view packed the actions row under the subtitle; packing it again puts it under the lines above.
    app.overview_view["actions"].pack_forget()
    app.overview_view["actions"].pack(fill="x", pady=(0, 8))
    ttk.Label(app.overview_view["frame"], text="What takes space, by type", style="Strong.TLabel").pack(anchor="w",
                                                                                                     pady=(4, 4))
    app.type_table = app.make_table(
        app.overview_view["frame"],
        [("type", "Type", 200, "w", True), ("files", "Files", 110, "e", False),
         ("size", "On disk", 110, "e", False), ("share", "Share", 90, "e", False)],
        lambda row: (row["type"], human_count(row["files"]), human_size(row["bytes"]), row["share"]),
        {"type": lambda row: row["type"].lower(), "files": lambda row: row["files"], "size": lambda row: row["bytes"]})
    app.type_table["frame"].pack(fill="both", expand=True)


def build_map_view(app):
    """Space map: a sunburst of the folders, angle by size. Click a folder to zoom in, the centre to go up.

    Keeps map_view, map_mode_var, map_info, canvas_background, map_info_label, map_table, map_canvas and
    map_menu, and binds the canvas, the list beside it and the window's Backspace."""
    app.map_view = app.make_view("map", "Space map")
    app.map_mode_var = tk.StringVar(value="folders")
    app.map_info = tk.StringVar(value="")
    app.canvas_background = app.style.lookup("TFrame", "background")
    if app.canvas_background == "":
        app.canvas_background = app.window.cget("background")
    # These two only move the map or open a folder, so they stay usable while a job runs (the map is
    # drawn before the duplicate comparison, which can take minutes).
    app.usable_when_busy[app.add_button(app.map_view, "Up one level", lambda: app.map_up(), app.map_can_go_up,
                                        False)] = True
    app.usable_when_busy[app.add_button(app.map_view, "Open this folder",
                                        lambda: launch(open_folder_command(app.map_center)), app.map_ready,
                                        False)] = True
    ttk.Label(app.map_view["actions"], text="Colour by").pack(side="left", padx=(12, 6))
    ttk.Radiobutton(app.map_view["actions"], text="Folders", value="folders", variable=app.map_mode_var,
                    command=lambda: app.map_draw()).pack(side="left")
    ttk.Radiobutton(app.map_view["actions"], text="Duplicate copies", value="duplicates", variable=app.map_mode_var,
                    command=lambda: app.map_draw()).pack(side="left", padx=(6, 0))
    # Two lines tall whatever the text, so the map does not jump while the mouse moves over it.
    map_info_holder = ttk.Frame(app.map_view["frame"], height=2 * app.line_height + 4)
    map_info_holder.pack(fill="x", pady=(0, 6))
    map_info_holder.pack_propagate(False)
    app.map_info_label = app.wrapping(ttk.Label(map_info_holder, textvariable=app.map_info))
    app.map_info_label.pack(fill="x", anchor="nw")
    map_body = ttk.Frame(app.map_view["frame"])
    map_body.pack(fill="both", expand=True)
    app.map_table = app.make_table(
        map_body,
        [("name", "Biggest here", 190, "w", True), ("size", "On disk", 85, "e", False),
         ("share", "Share", 65, "e", False)],
        lambda row: (row["label"], human_size(row["bytes"]), row["share"]),
        {"name": lambda row: row["name"].lower(), "size": lambda row: row["bytes"],
         "share": lambda row: row["bytes"]})
    # The table is packed first so that a narrow window shrinks the map, not the list.
    app.map_table["frame"].pack(side="right", fill="y", padx=(10, 0))
    app.map_canvas = tk.Canvas(map_body, background=app.canvas_background, highlightthickness=0, width=1, height=1)
    app.map_canvas.pack(side="left", fill="both", expand=True)
    app.map_menu = tk.Menu(app.window, tearoff=0)

    app.map_canvas.bind("<Motion>", app.map_hover)
    app.map_canvas.bind("<Leave>", app.map_hover)
    app.map_canvas.bind("<Button-1>", app.map_click)
    app.map_canvas.bind("<Double-1>", app.map_double_click)
    app.map_canvas.bind("<Triple-1>", app.map_triple_click)
    app.map_canvas.bind("<Button-3>", app.map_right_click)
    if app.window.tk.call("tk", "windowingsystem") == "aqua":
        # macOS: Control-click asks for the menu too, and Tk before 8.7 reports the right button as 2.
        app.map_canvas.bind("<Control-Button-1>", app.map_right_click)
        if tk.TkVersion < 8.7:
            app.map_canvas.bind("<Button-2>", app.map_right_click)
    app.map_canvas.bind("<Configure>", app.map_resized)
    app.map_table["tree"].bind("<Double-1>", app.map_table_double_click)
    app.map_table["tree"].bind("<Return>", app.map_table_open)
    app.window.bind("<BackSpace>", app.map_backspace)


def add_overview_actions(app):
    """The Overview's button, Open trash folder. It is made after the space map, where it always was."""
    app.add_button(app.overview_view, "Open trash folder", lambda: launch(open_folder_command(app.trash_folder())),
                   lambda: app.trash_folder() != "" and os.path.isdir(app.trash_folder()), False)


def build_largest_view(app):
    """Largest files. Keeps largest_view and largest_table; Delete moves the rows to the trash."""
    app.largest_view = app.make_view("largest", "Largest files")
    app.largest_table = app.make_table(app.largest_view["frame"], app.file_columns, app.file_values, app.file_sorts)
    app.add_button(app.largest_view, "Move to trash", lambda: app.trash_rows(app.largest_table),
                   lambda: app.has_rows(app.largest_table), True)
    app.add_button(app.largest_view, "Show in folder", lambda: app.reveal_first(app.largest_table),
                   lambda: app.has_selection(app.largest_table), False)
    app.largest_table["frame"].pack(fill="both", expand=True)
    app.primary["largest"] = lambda: app.trash_rows(app.largest_table)


def build_old_view(app):
    """Old files, with the number of days beside the buttons. Keeps old_view, old_table and days_var;
    Delete moves the rows to the trash."""
    app.old_view = app.make_view("old", "Old files")
    app.old_table = app.make_table(app.old_view["frame"], app.file_columns, app.file_values, app.file_sorts)
    app.add_button(app.old_view, "Move to trash", lambda: app.trash_rows(app.old_table),
                   lambda: app.has_rows(app.old_table), True)
    app.add_button(app.old_view, "Show in folder", lambda: app.reveal_first(app.old_table),
                   lambda: app.has_selection(app.old_table), False)
    ttk.Label(app.old_view["actions"], text="Not changed for").pack(side="left", padx=(12, 4))
    app.days_var = tk.IntVar(value=app.old_days)
    days_box = ttk.Spinbox(app.old_view["actions"], from_=1, to=20000, increment=30, textvariable=app.days_var,
                           width=7, command=lambda: app.change_days())
    days_box.pack(side="left")
    ttk.Label(app.old_view["actions"], text="days").pack(side="left", padx=(4, 0))
    days_box.bind("<Return>", lambda event: app.change_days())
    days_box.bind("<FocusOut>", lambda event: app.change_days())
    app.old_table["frame"].pack(fill="both", expand=True)
    app.primary["old"] = lambda: app.trash_rows(app.old_table)


def build_duplicates_view(app):
    """Duplicates: a tree of groups and their copies. Keeps duplicates_view, dup_tree and dup_note_var;
    Delete moves the extra copies to the trash."""
    app.duplicates_view = app.make_view("duplicates", "Duplicates")
    dup_holder = ttk.Frame(app.duplicates_view["frame"])
    app.dup_tree = ttk.Treeview(dup_holder, columns=("size", "modified", "action"), show="tree headings",
                                selectmode="extended")
    app.dup_tree.heading("#0", text="File", anchor="w")
    app.dup_tree.column("#0", width=340, stretch=True)
    app.dup_tree.heading("size", text="On disk", anchor="e")
    app.dup_tree.column("size", width=90, anchor="e", stretch=False)
    app.dup_tree.heading("modified", text="Changed", anchor="e")
    app.dup_tree.column("modified", width=100, anchor="e", stretch=False)
    app.dup_tree.heading("action", text="")
    app.dup_tree.column("action", width=150, anchor="w", stretch=False)
    app.dup_tree.tag_configure("group", font=app.strong_font)
    app.dup_tree.tag_configure("keep", foreground="#2e7d32")
    app.dup_tree.tag_configure("trash", foreground="#a33a1a")
    dup_bar = ttk.Scrollbar(dup_holder, orient="vertical", command=app.dup_tree.yview)
    app.dup_tree.configure(yscrollcommand=dup_bar.set)
    app.dup_note_var = tk.StringVar(value="")
    app.wrapping(ttk.Label(dup_holder, textvariable=app.dup_note_var, style="Muted.TLabel")).pack(side="bottom",
                                                                                                fill="x", pady=(4, 0))
    app.dup_tree.pack(side="left", fill="both", expand=True)
    dup_bar.pack(side="left", fill="y")
    app.dup_tree.bind("<<TreeviewSelect>>", lambda event: app.refresh_buttons())
    app.add_button(app.duplicates_view, "Move extra copies to trash", lambda: app.trash_duplicates(), app.has_groups,
                   True)
    app.add_button(app.duplicates_view, "Keep selected copy", lambda: app.keep_selected(),
                   lambda: len(app.selected_copies()) > 0, False)
    app.add_button(app.duplicates_view, "Show in folder", lambda: app.reveal_copy(),
                   lambda: len(app.selected_copies()) > 0, False)
    dup_holder.pack(fill="both", expand=True)
    app.primary["duplicates"] = lambda: app.trash_duplicates()


def build_empty_view(app):
    """Empty folders. Keeps empty_view and empty_table; Delete removes the folders."""
    app.empty_view = app.make_view("empty", "Empty folders")
    app.empty_table = app.make_table(app.empty_view["frame"], [("path", "Folder", 700, "w", True)],
                                     lambda row: (app.rel(row),), {"path": app.text_key})
    app.add_button(app.empty_view, "Remove", lambda: app.remove_empty(), lambda: app.has_rows(app.empty_table), True)
    app.add_button(app.empty_view, "Show in folder", lambda: app.reveal_first(app.empty_table),
                   lambda: app.has_selection(app.empty_table), False)
    app.empty_table["frame"].pack(fill="both", expand=True)
    app.primary["empty"] = lambda: app.remove_empty()


def build_errors_view(app):
    """Unreadable: the paths that could not be read, and why. Keeps errors_view and error_table."""
    app.errors_view = app.make_view("errors", "Unreadable")
    app.error_table = app.make_table(app.errors_view["frame"], [("path", "Path and problem", 700, "w", True)],
                                     lambda row: (row,), {"path": app.text_key})
    app.error_table["frame"].pack(fill="both", expand=True)


def build_organize_view(app):
    """Organize: a preview of the moves, then Apply. Keeps organize_view, org_mode and org_table."""
    app.organize_view = app.make_view("organize", "Organize")
    app.org_mode = tk.StringVar(value="type")
    app.org_table = app.make_table(app.organize_view["frame"],
                                   [("from", "File", 360, "w", True), ("to", "Moves to", 360, "w", True)],
                                   lambda row: (os.path.basename(row["source"]),
                                                relative_path(app.org_root, row["target"])),
                                   {"from": lambda row: row["source"].lower(), "to": lambda row: row["target"].lower()})
    app.add_button(app.organize_view, "Preview", lambda: app.preview_organize(), lambda: True, False)
    app.add_button(app.organize_view, "Apply", lambda: app.apply_organize(), lambda: len(app.org_moves) > 0, True)
    ttk.Radiobutton(app.organize_view["actions"], text="By type", variable=app.org_mode, value="type",
                    command=lambda: app.clear_organize()).pack(side="left", padx=(12, 4))
    ttk.Radiobutton(app.organize_view["actions"], text="By year-month", variable=app.org_mode, value="date",
                    command=lambda: app.clear_organize()).pack(side="left")
    app.org_table["frame"].pack(fill="both", expand=True)


def build_network_view(app):
    """Network shares: the saved shares and what was found out about them. Keeps network_view, net_rows
    (one {"share", "status", "free", "total"} per share, in the settings' order) and net_table."""
    app.network_view = app.make_view("network", "Network shares")
    app.network_view["subtitle"].set("Saved shares. Passwords are never stored; Windows asks for them when mapping if needed.")
    app.net_rows = []
    app.net_table = app.make_table(
        app.network_view["frame"],
        [("name", "Name", 140, "w", False), ("unc", "Share", 240, "w", True), ("letter", "Letter", 60, "center", False),
         ("status", "Status", 260, "w", True), ("free", "Free", 90, "e", False), ("total", "Total", 90, "e", False)],
        lambda row: (row["share"]["name"], row["share"]["unc"], row["share"]["letter"] or "\u2014",
                     row["status"], row["free"], row["total"]),
        {})
    app.add_button(app.network_view, "Add share\u2026", lambda: app.add_share_dialog(), lambda: True, True)
    app.add_button(app.network_view, "Check all", lambda: app.check_shares(), lambda: len(app.net_rows) > 0, False)
    app.add_button(app.network_view, "Analyze", lambda: app.analyze_share(), lambda: app.has_selection(app.net_table),
                   False)
    app.add_button(app.network_view, "Map", lambda: app.map_selected(), lambda: app.has_selection(app.net_table), False)
    app.add_button(app.network_view, "Disconnect", lambda: app.unmap_selected(),
                   lambda: app.has_selection(app.net_table), False)
    app.add_button(app.network_view, "Back up a folder here\u2026", lambda: app.backup_to_share(),
                   lambda: app.has_selection(app.net_table), False)
    app.add_button(app.network_view, "Remove", lambda: app.remove_share(), lambda: app.has_selection(app.net_table),
                   False)
    app.net_table["frame"].pack(fill="both", expand=True)


def build_activity_view(app):
    """Activity: everything done in this session. Keeps activity_view and log_text, which log() writes to."""
    app.activity_view = app.make_view("activity", "Activity")
    app.activity_view["subtitle"].set("Everything done in this session.")
    log_holder = ttk.Frame(app.activity_view["frame"])
    app.log_text = tk.Text(log_holder, wrap="none", height=10, state="disabled", relief="flat", padx=6, pady=6)
    log_bar = ttk.Scrollbar(log_holder, orient="vertical", command=app.log_text.yview)
    app.log_text.configure(yscrollcommand=log_bar.set)
    app.log_text.pack(side="left", fill="both", expand=True)
    log_bar.pack(side="left", fill="y")
    app.add_button(app.activity_view, "Clear", app.clear_log, lambda: True, False)
    log_holder.pack(fill="both", expand=True)

# ==== stamp v1 | author=kjFriday | hmac-sha256=b5e66ae1a5d97fee415fc34e4e80e561b6a4198e9d6da52606a8e4cbe0b3c362 ====
