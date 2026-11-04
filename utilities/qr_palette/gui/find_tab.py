# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/find_tab.py
# About: The Find tab: find codes by QR code, color or picture, ask a local model, and act on the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The Find tab: find codes by QR code, color or picture, ask a local model, and act on the results
(open, copy, change destination, redraw, forget, print a sheet, short link history).

FindTab is part of PaletteWindow (window.py). Its Ask box uses the same ECP engine as the MCP server.
"""

import json
import os
import subprocess
import tempfile
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox, simpledialog

import app_settings
import ecp
import payloads
import qr_codec
import registry
import sheets
import shortlinks
import swatch
import textsafe
from app_settings import HERE
from common import ok_result, with_registry
from finding import destination, matches_for_text, reveal_command_line, search, shown_from_record
from making import forget_record, preview_png, redraw_record
from print_advice import MIN_MODULE_MM
from qr_palette import APP_NAME, __version__
from short_link_ops import (apply_due_changes, cancel_link_change, due_link_changes, link_history, retarget_link,
                            schedule_link_change, short_note, undo_link_change)
from gui.read_tab import clipboard_picture


class FindTab:
    """The Find tab's widgets and actions (a part of PaletteWindow)."""

    def build_find_tab(self):
        """Create the Find tab's widgets and bind them."""
        self.find_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.find_tab, text="Find")
        self.selector = tk.StringVar(value="qr_code")
        self.selector_row = ttk.Frame(self.find_tab)
        self.selector_row.pack(fill="x")
        ttk.Label(self.selector_row, text="Find by").pack(side="left")
        self.qr_row = ttk.Frame(self.find_tab)
        self.color_row = ttk.Frame(self.find_tab)
        self.find_text = tk.StringVar(value="")
        ttk.Label(self.qr_row, text="Link or path").pack(side="left")
        find_entry = ttk.Entry(self.qr_row, textvariable=self.find_text, width=60)
        find_entry.pack(side="left", padx=6)
        self.color_text = tk.StringVar(value="")
        self.near_choice = tk.BooleanVar(value=False)
        ttk.Label(self.color_row, text="Color").pack(side="left")
        color_entry = ttk.Entry(self.color_row, textvariable=self.color_text, width=10)
        color_entry.pack(side="left", padx=6)
        ttk.Checkbutton(self.color_row, text="near", variable=self.near_choice).pack(side="left")
        ttk.Label(self.color_row, text="or family").pack(side="left", padx=(12, 0))
        self.family_box = ttk.Combobox(self.color_row, values=[""] + list(swatch.FAMILIES), width=9, state="readonly")
        self.family_box.pack(side="left", padx=6)
        self.used_canvas = tk.Canvas(self.find_tab, height=26, highlightthickness=0, cursor="hand2")
        ask_row = ttk.Frame(self.find_tab)
        ttk.Label(ask_row, text="Ask (local model)").pack(side="left")
        self.model_box = ttk.Combobox(ask_row, values=[], width=24, state="readonly")
        self.model_box.pack(side="left", padx=6)
        self.question = tk.StringVar(value="")
        question_entry = ttk.Entry(ask_row, textvariable=self.question, width=26)
        question_entry.pack(side="left", padx=6, fill="x", expand=True)  # narrow windows keep the buttons whole
        self.plan_text = tk.StringVar(value="Pick a local model to ask in plain English, e.g. \"blue codes that link "
                                            "to the shop\".")
        self.results = ttk.Treeview(self.find_tab, columns=("hex", "link", "scans", "path", "exists"),
                                    show="tree headings", height=8)
        self.results.heading("#0", text="Color")
        self.results.heading("hex", text="Hex")
        self.results.heading("link", text="Link")
        self.results.heading("scans", text="Scans (30 d)")
        self.results.heading("path", text="Path")
        self.results.heading("exists", text="File")
        self.results.column("#0", width=140, stretch=False)
        self.results.column("hex", width=74, stretch=False)
        self.results.column("link", width=290)
        self.results.column("scans", width=104, stretch=False)
        self.results.column("path", width=300)
        self.results.column("exists", width=60, stretch=False)
        detail = ttk.Frame(self.find_tab)
        self.detail_preview = tk.Canvas(detail, width=170, height=170, background="#ffffff", highlightthickness=1,
                                        highlightbackground="#c8c8c8")
        self.detail_preview.pack(side="left")
        detail_side = ttk.Frame(detail, padding=(10, 0, 0, 0))
        detail_side.pack(side="left", fill="both", expand=True)
        self.detail_text = tk.StringVar(value="Select a result to see it here.")
        ttk.Label(detail_side, textvariable=self.detail_text, wraplength=700, justify="left").pack(anchor="w")
        detail_buttons = ttk.Frame(detail_side)
        detail_buttons.pack(anchor="w", pady=8)
        self.client_info = {"name": APP_NAME + " window", "version": __version__}
        radio_bar = ttk.Frame(self.selector_row)
        radio_bar.pack(side="left", padx=6)
        ttk.Radiobutton(radio_bar, text="QR code", variable=self.selector, value="qr_code",
                        command=self.show_selector).pack(side="left")
        ttk.Radiobutton(radio_bar, text="Color", variable=self.selector, value="color",
                        command=self.show_selector).pack(side="left", padx=6)
        ttk.Button(self.selector_row, text="Find", command=self.run_search).pack(side="left", padx=6)
        ttk.Button(self.qr_row, text="Open picture…",
                   command=lambda: self.find_from_picture(False)).pack(side="left", padx=6)
        ttk.Button(self.qr_row, text="Paste picture", command=lambda: self.find_from_picture(True)).pack(side="left")
        self.used_canvas.pack(fill="x", pady=(2, 6))
        ask_row.pack(fill="x", pady=4)
        ttk.Button(ask_row, text="Refresh", command=self.refresh_models).pack(side="left")
        ttk.Button(ask_row, text="Ask", command=self.ask).pack(side="left", padx=6)
        ttk.Button(ask_row, text="Cancel", command=self.cancel_job).pack(side="left")
        ttk.Label(self.find_tab, textvariable=self.plan_text, wraplength=1040, justify="left",
                  foreground="#333333").pack(anchor="w", pady=(0, 6))
        self.results.pack(fill="both", expand=True)
        detail.pack(fill="x", pady=(8, 0))
        ttk.Button(detail_buttons, text="Open picture", command=self.open_shown_picture).pack(side="left")
        ttk.Button(detail_buttons, text="Show in folder", command=self.reveal_shown).pack(side="left", padx=6)
        ttk.Button(detail_buttons, text="Copy path", command=lambda: self.copy_shown("path")).pack(side="left")
        ttk.Button(detail_buttons, text="Copy link", command=lambda: self.copy_shown("link")).pack(side="left", padx=6)
        ttk.Button(detail_buttons, text="Open link", command=self.open_shown_link).pack(side="left")
        detail_changes = ttk.Frame(detail_side)  # these act on every selected result
        detail_changes.pack(anchor="w")
        ttk.Button(detail_changes, text="Change destination…", command=self.change_destination).pack(side="left")
        ttk.Button(detail_changes, text="Redraw…", command=self.redraw_shown).pack(side="left", padx=6)
        ttk.Button(detail_changes, text="Forget record", command=self.forget_shown).pack(side="left")
        ttk.Button(detail_changes, text="Print sheet…", command=self.print_shown).pack(side="left", padx=6)
        ttk.Button(detail_changes, text="History…", command=self.show_history).pack(side="left")
        ttk.Label(detail_changes, text="Ctrl+click picks several.", foreground="#555555").pack(side="left", padx=6)
        self.results.bind("<<TreeviewSelect>>", self.show_detail)
        find_entry.bind("<Return>", lambda event: self.run_search())
        color_entry.bind("<Return>", lambda event: self.run_search())
        self.family_box.bind("<<ComboboxSelected>>", self.pick_family)
        question_entry.bind("<Return>", lambda event: self.ask())
        self.model_box.bind("<<ComboboxSelected>>", self.choose_model)
        self.used_canvas.bind("<Button-1>", self.pick_used)
        self.show_selector()

    def show_selector(self):
        self.qr_row.pack_forget()
        self.color_row.pack_forget()
        if self.selector.get() == "qr_code":
            self.qr_row.pack(fill="x", pady=4, after=self.selector_row)
        else:
            self.color_row.pack(fill="x", pady=4, after=self.selector_row)

    def show_results(self, shown_list, note):
        self.state["results"] = shown_list
        for item in self.results.get_children():
            self.results.delete(item)
        for index in range(len(shown_list)):
            shown = shown_list[index]
            exists = {True: "yes", False: "missing", None: "?"}[shown["exists"]]
            link = payloads.one_line(destination(shown))
            if shown["short_code"] != "":
                section = shortlinks.section_of(app_settings.LINKS, shown["link"])
                link = link + "   (" + (section + " " if section != "" else "") + "short " + shown["short_code"] + ")"
            scanned = ""
            if shown["scans"] is not None:
                scanned = str(shown["scans"]["total"]) + " (" + str(shown["scans"]["recent"]) + ")"
            self.results.insert("", "end", iid=str(index), text=" " + shown["name"],
                                image=self.swatch_image(shown["hex"]),
                                values=(shown["hex"], link, scanned, shown["path"], exists))
        self.detail_preview.delete("all")
        self.detail_text.set("Select a result to see it here.")
        self.status.set(note)

    def run_search(self, note=""):
        """Find by QR code or color. `note`, when given, is shown instead of the count, so a change
        that searches again to show its result keeps its own message."""
        by = self.selector.get()
        if by == "qr_code":
            value = self.find_text.get()
            near = False
        else:
            value = self.color_text.get().strip() or self.family_box.get()
            near = self.near_choice.get()

        def done(outcome):
            if not outcome["ok"]:
                self.show_results([], outcome["error"])
                return
            self.plan_text.set("Found by " + {"qr_code": "QR code", "color": "color"}[by] + ": " + value)
            self.show_results(outcome["value"], note or str(len(outcome["value"])) + " QR code(s) found")

        self.start_job("Searching", lambda: search(self.db_path, by, value, near, registry.MAX_LIMIT), done)

    def pick_used(self, event):
        for item in self.used_canvas.find_overlapping(event.x, event.y, event.x, event.y):
            color = self.used_canvas.gettags(item)
            if len(color) > 0 and color[0].startswith("#"):
                self.selector.set("color")
                self.show_selector()
                self.color_text.set(color[0])
                self.family_box.set("")
                self.run_search()
                return

    def refresh_used(self):
        def read(connection):
            return ok_result(registry.colors_in_use(connection))

        used = with_registry(self.db_path, read)
        self.used_canvas.delete("all")
        if not used["ok"]:
            return
        left = 0
        self.used_canvas.create_text(left, 13, text="In use:", anchor="w")
        left = 52
        for entry in used["value"][:30]:
            self.used_canvas.create_rectangle(left, 3, left + 20, 23, fill=entry["hex"], outline="#888888",
                                              tags=(entry["hex"],))
            left = left + 24

    def selected_shown(self):
        chosen = self.results.selection()
        if len(chosen) == 0:
            return None
        return self.state["results"][int(chosen[0])]

    def show_detail(self, event=None):
        shown = self.selected_shown()
        self.detail_preview.delete("all")
        if shown is None:
            return
        caption = ""
        if shown["short_code"] != "":
            caption = shortlinks.caption(shown["link"])
        photo = None
        masked = payloads.is_masked(shown["link"])
        if not masked:  # a masked code cannot be drawn from what the registry keeps
            photo = self.photo_from_png(preview_png(shown["link"], shown["hex"], shown["ec_level"], shown["version"],
                                                    caption))
        self.state["photos"]["detail"] = photo
        if photo is not None:
            factor = 1
            while photo.width() // factor > 168:
                factor = factor + 1
            if factor > 1:
                photo = photo.subsample(factor, factor)
                self.state["photos"]["detail"] = photo
            self.detail_preview.create_image(86, 86, image=photo)
        logo_note = ""
        if shown["has_logo"]:
            logo_note = "\nIts picture has a logo the registry does not keep: this preview shows the code without it."
        more = logo_note
        if len(self.results.selection()) > 1:
            more = (logo_note + "\n…and " + str(len(self.results.selection()) - 1) + " more selected: Change "
                    "destination…, Redraw…, Forget record and Print sheet… act on them all.")
        if shown["short_code"] != "":
            self.detail_text.set(shown["name"] + "  " + shown["hex"] + "\nLink: " +
                                 textsafe.clean(shown["target"], 300) +
                                 "\nPrinted as: " + shown["link"] + short_note(shown) +
                                 "\nPath: " + shown["path"] + self.history_note(shown) + more)
        else:
            note = ""
            if masked:
                note = "\nThe registry keeps this code without its password: open the picture to see it."
            self.detail_text.set(shown["name"] + "  " + shown["hex"] + "\nHolds: " +
                                 textsafe.clean(payloads.one_line(shown["link"]), 300) + "\nPath: " + shown["path"] +
                                 note + more)

    def history_note(self, shown):
        """A short link's scans, last change and next scheduled change, as lines for the detail."""
        lines = ""
        if shown["scans"] is not None:
            lines = ("\nScans: " + str(shown["scans"]["total"]) + " in all, " + str(shown["scans"]["recent"]) +
                     " in the last " + str(registry.RECENT_DAYS) + " days")
        known = link_history(self.db_path, shown["short_code"])
        if known["ok"]:
            if len(known["value"]["changes"]) > 0:
                last = known["value"]["changes"][0]
                lines = (lines + "\nChanged " + last["changed"][:10] + ", from " +
                         textsafe.clean(last["old_target"], 120) + " (History… has them all)")
            if len(known["value"]["coming"]) > 0:
                next_one = known["value"]["coming"][0]
                lines = lines + "\nGoes to " + textsafe.clean(next_one["target"], 120) + " from " + next_one["from_day"]
        return lines

    def open_shown_picture(self):
        shown = self.selected_shown()
        if shown is None:
            return
        if not os.path.isfile(shown["path"]):
            self.status.set("The picture is not at " + shown["path"] + " any more")
            return
        try:
            os.startfile(shown["path"])
        except (AttributeError, OSError) as error:
            self.status.set(str(error))

    def reveal_shown(self):
        shown = self.selected_shown()
        if shown is None:
            return
        if os.name != "nt":
            self.status.set("Show in folder needs Windows")
            return
        try:
            subprocess.Popen(reveal_command_line(shown["path"]))
        except OSError as error:
            self.status.set(str(error))

    def copy_shown(self, key):
        shown = self.selected_shown()
        if shown is None:
            return
        self.window.clipboard_clear()
        if key == "link":
            self.window.clipboard_append(destination(shown))
        else:
            self.window.clipboard_append(shown[key])
        self.status.set("Copied the " + key)

    def open_shown_link(self):
        shown = self.selected_shown()
        if shown is None:
            return
        link = destination(shown)
        if not qr_codec.is_link(link):
            self.status.set("Only http:// and https:// links can be opened")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + link):
            webbrowser.open(link.strip())

    def selected_all(self):
        """Every selected result (Ctrl+click or Shift+click picks several)."""
        chosen = []
        for item in self.results.selection():
            chosen.append(self.state["results"][int(item)])
        return chosen

    def change_destination(self):
        """Send the selected short links somewhere else (all of them to the same place)."""
        codes = []
        first = None
        for shown in self.selected_all():
            if shown["short_code"] != "" and shown["short_code"] not in codes:
                codes.append(shown["short_code"])
                if first is None:
                    first = shown
        if first is None:
            self.status.set("Pick a code with a short link: a code that holds its link itself cannot be sent elsewhere")
            return
        question = "Where should " + first["link"] + " send people?"
        if len(codes) > 1:
            question = "Where should these " + str(len(codes)) + " short links send people?"
        link = simpledialog.askstring("Change destination", question + "\nPrinted codes keep working; export the "
                                      "redirect pages again to publish it.", initialvalue=first["target"],
                                      parent=self.window)
        if link is None:
            return

        def work():
            for code in codes:
                changed = retarget_link(self.db_path, code, link)
                if not changed["ok"]:
                    return changed
            return ok_result(len(codes))

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Change destination", outcome["error"])
                return
            self.run_search(str(outcome["value"]) + " short link(s) now send people to " + link.strip() +
                            "  ·  export the redirect pages again to publish it")
            self.refresh_served()

        self.start_job("Changing the destination", work, done)

    def redraw_shown(self):
        """Draw the selected codes again, in another color or size, over their own files."""
        chosen = self.selected_all()
        if len(chosen) == 0:
            return
        color = simpledialog.askstring("Redraw", "Redraw " + str(len(chosen)) + " picture(s) in which color?\n"
                                       "#rrggbb, or leave it empty to keep each code's own color.",
                                       initialvalue=self.state["picked"], parent=self.window)
        if color is None:
            return
        scale = simpledialog.askinteger("Redraw", "Pixels per module for PNG pictures (1-40):",
                                        initialvalue=app_settings.DEFAULT_SCALE, minvalue=1, maxvalue=40,
                                        parent=self.window)
        if scale is None:
            return
        jobs = []
        for shown in chosen:
            jobs.append((shown["id"], color.strip() or shown["hex"]))

        def work():
            redrawn = 0
            problems = []
            for number, hex_value in jobs:
                outcome = redraw_record(self.db_path, number, hex_value, scale)
                if outcome["ok"]:
                    redrawn = redrawn + 1
                else:
                    problems.append(outcome["error"])
            return ok_result({"redrawn": redrawn, "problems": problems})

        def done(outcome):
            message = "Redrew " + str(outcome["value"]["redrawn"]) + " picture(s), each read back first"
            if len(outcome["value"]["problems"]) > 0:
                message = message + "; " + str(len(outcome["value"]["problems"])) + " not: " + outcome["value"]["problems"][0]
            self.run_search(message)
            self.refresh_used()

        self.start_job("Redrawing", work, done)

    def forget_shown(self):
        chosen = self.selected_all()
        if len(chosen) == 0:
            return
        question = "Remove this record from the registry? The picture file stays where it is.\n\n" + chosen[0]["path"]
        if len(chosen) > 1:
            question = ("Remove these " + str(len(chosen)) + " records from the registry? The picture files stay where "
                        "they are.")
        if not messagebox.askyesno("Forget record", question):
            return
        numbers = []
        for shown in chosen:
            numbers.append(shown["id"])

        def work():
            removed = 0
            for number in numbers:
                outcome = forget_record(self.db_path, number)
                if not outcome["ok"]:
                    return outcome
                if outcome["value"]:
                    removed = removed + 1
            return ok_result(removed)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Forget record", outcome["error"])
                return
            remaining = []
            for other in self.state["results"]:
                if other["id"] not in numbers:
                    remaining.append(other)
            self.show_results(remaining, str(outcome["value"]) + " record(s) removed; the files were not touched")
            self.refresh_footer()
            self.refresh_used()

        self.start_job("Forgetting", work, done)

    def show_history(self):
        """A short link's history, with Undo last change, and its changes to come, with Schedule a change."""
        shown = self.selected_shown()
        if shown is None or shown["short_code"] == "":
            self.status.set("Pick a code with a short link: a code that holds its link itself has no history")
            return
        code = shown["short_code"]
        dialog = tk.Toplevel(self.window)
        dialog.title("Short link history")
        dialog.geometry("760x470")
        dialog.transient(self.window)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Printed as " + shown["link"] + short_note(shown)).pack(anchor="w")
        now_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=now_text, wraplength=730, justify="left").pack(anchor="w", pady=(2, 8))
        ttk.Label(body, text="Changes to come").pack(anchor="w")
        coming = ttk.Treeview(body, columns=("day", "target"), show="headings", height=3, selectmode="browse")
        coming.heading("day", text="From")
        coming.heading("target", text="Goes to")
        coming.column("day", width=100, stretch=False)
        coming.column("target", width=620)
        coming.pack(fill="x")
        ttk.Label(body, text="Where it has gone, newest first").pack(anchor="w", pady=(8, 0))
        past = ttk.Treeview(body, columns=("when", "old", "new"), show="headings", height=7)
        past.heading("when", text="Changed (UTC)")
        past.heading("old", text="From")
        past.heading("new", text="To")
        past.column("when", width=170, stretch=False)
        past.column("old", width=275)
        past.column("new", width=275)
        past.pack(fill="both", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(8, 0))
        record = {"target": shown["target"], "changes": []}

        def alive():
            return dialog.winfo_exists()

        def fill(outcome):
            self.status.set("Ready")
            if not alive():
                return
            if not outcome["ok"]:
                now_text.set(outcome["error"])
                return
            record["changes"] = outcome["value"]["changes"]
            for table in (coming, past):
                for item in table.get_children():
                    table.delete(item)
            for change in outcome["value"]["coming"]:
                coming.insert("", "end", iid=str(change["id"]), values=(change["from_day"], change["target"]))
            for change in record["changes"]:
                past.insert("", "end", values=(change["changed"], change["old_target"], change["new_target"]))
            if len(record["changes"]) > 0:
                record["target"] = record["changes"][0]["new_target"]
            now_text.set("Sends people to " + record["target"])

        def load():
            self.start_job("Reading the history", lambda: link_history(self.db_path, code), fill)

        def changed(outcome, message):
            if not outcome["ok"]:
                messagebox.showerror("Short link history", outcome["error"], parent=dialog if alive() else self.window)
                self.status.set("Nothing changed")
                return
            self.status.set(message)
            self.refresh_served()
            if len(self.state["results"]) > 0:
                self.run_search(message)
            if alive():
                load()

        def undo():
            if len(record["changes"]) == 0:
                self.status.set("This short link has not been changed yet")
                return
            back = record["changes"][0]["old_target"]
            if not messagebox.askyesno("Undo last change", "Send " + shown["link"] + " back to\n\n" + back + " ?",
                                       parent=dialog):
                return
            self.start_job("Undoing the change", lambda: undo_link_change(self.db_path, code),
                           lambda outcome: changed(outcome, "Sent back to " + back +
                                                   "  ·  export the redirect pages again to publish it"))

        def schedule():
            day = simpledialog.askstring("Schedule a change", "From which day? (YYYY-MM-DD)", parent=dialog)
            if day is None:
                return
            day = day.strip()
            if not registry.is_day(day):
                messagebox.showerror("Schedule a change", "A day is written YYYY-MM-DD, such as 2026-12-01.",
                                     parent=dialog)
                return
            link = simpledialog.askstring("Schedule a change", "Where should it send people from " + day + "?",
                                          initialvalue=record["target"], parent=dialog)
            if link is None:
                return
            self.start_job("Scheduling the change", lambda: schedule_link_change(self.db_path, code, link, day),
                           lambda outcome: changed(outcome, "From " + day + " it sends people to " + link.strip() +
                                                   "  ·  exports from that day on use it"))

        def cancel():
            chosen = coming.selection()
            if len(chosen) == 0:
                self.status.set("Pick the change to cancel first")
                return
            number = int(chosen[0])
            self.start_job("Cancelling the change", lambda: cancel_link_change(self.db_path, number),
                           lambda outcome: changed(outcome, "The scheduled change was cancelled"))

        ttk.Button(buttons, text="Undo last change", command=undo).pack(side="left")
        ttk.Button(buttons, text="Schedule a change…", command=schedule).pack(side="left", padx=6)
        ttk.Button(buttons, text="Cancel the scheduled change", command=cancel).pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=6)
        load()

    def offer_due_changes(self):
        """On start: changes scheduled for a day that has come are offered, never made unasked."""
        today = registry.today_text()
        due = due_link_changes(self.db_path, today)
        if not due["ok"] or len(due["value"]) == 0:
            return
        lines = []
        for change in due["value"][:8]:
            lines.append(change["from_day"] + "  " + change["code"] + " goes to " +
                         textsafe.clean(change["target"], 80))
        if not messagebox.askyesno("Scheduled changes", str(len(due["value"])) + " scheduled change(s) of "
                                   "destination are due:\n\n" + "\n".join(lines) + "\n\nApply them now? Exports "
                                   "already use them; applying writes them into the registry and each link's history."):
            return

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Scheduled changes", outcome["error"])
                return
            self.status.set("Applied " + str(outcome["value"]) + " scheduled change(s)  ·  export the redirect "
                            "pages again to publish them")
            self.refresh_served()

        self.start_job("Applying the scheduled changes", lambda: apply_due_changes(self.db_path, today), done)

    def print_shown(self):
        """The selected codes on a sheet of labels or as posters (sheets.json), as a PDF or SVG."""
        chosen = self.selected_all()
        if len(chosen) == 0:
            self.status.set("Select the codes to print first (Ctrl+click or Shift+click picks several)")
            return
        loaded = sheets.load_sheets(os.path.join(HERE, "sheets.json"))
        layouts = loaded["sheets"]["layouts"]
        names = sorted(layouts)
        dialog = tk.Toplevel(self.window)
        dialog.title("Print sheet")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=str(len(chosen)) + " code(s) selected. Layout (sheets.json):").grid(row=0, column=0,
                                                                                                 sticky="w")
        chooser = ttk.Combobox(body, values=names, state="readonly", width=40)
        chooser.set(names[0])
        chooser.grid(row=1, column=0, sticky="w", pady=4)
        about = tk.StringVar(value="")
        ttk.Label(body, textvariable=about, wraplength=420, justify="left", foreground="#555555").grid(row=2, column=0,
                                                                                                       sticky="w")

        def show_about_layout(event=None):
            layout = layouts[chooser.get()]
            per_page = layout["columns"] * layout["rows"]
            pages = sheets.page_count(layout, len(chosen))
            about.set(layout["about"] + " " + str(per_page) + " per page: " + str(pages) + " page(s).")

        def make():
            layout = layouts[chooser.get()]
            path = filedialog.asksaveasfilename(title="Save the sheet", initialfile="qr-sheet.pdf",
                                                defaultextension=".pdf", parent=dialog,
                                                filetypes=[("PDF", "*.pdf"), ("SVG drawing, one per page", "*.svg")])
            if not path:
                return
            path = registry.display_path(path)
            dialog.destroy()
            numbers = []
            for shown in chosen:
                numbers.append(shown["id"])

            def done(outcome):
                if not outcome["ok"]:
                    messagebox.showerror("Print sheet", outcome["error"])
                    return
                value = outcome["value"]
                message = ("Printed " + str(value["codes"]) + " code(s) on " + str(value["pages"]) + " page(s): " +
                           value["files"][0])
                if len(value["skipped"]) > 0:
                    message = message + "; left out " + str(len(value["skipped"])) + ": " + value["skipped"][0]
                if value["without_logo"] > 0:
                    message = message + "; " + str(value["without_logo"]) + " drawn without their logos"
                if value["smallest_module_mm"] < MIN_MODULE_MM:
                    message = (message + "; modules come out as small as " + str(value["smallest_module_mm"]) +
                               " mm, under the " + str(MIN_MODULE_MM) + " mm most printers and cameras handle well")
                self.status.set(message)
                try:
                    os.startfile(value["files"][0])
                except (AttributeError, OSError) as error:
                    self.status.set(message + " (cannot open it: " + str(error) + ")")

            self.start_job("Printing the sheet", lambda: sheets.print_sheet(self.db_path, numbers, layout, path), done)

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Make the sheet…", command=make).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", show_about_layout)
        show_about_layout()
        if len(loaded["warnings"]) > 0:
            self.status.set(loaded["warnings"][0])

    def find_from_picture(self, paste):
        if paste:
            temporary = os.path.join(tempfile.gettempdir(), "qr_palette_clipboard.png")
            if os.path.isfile(temporary):
                os.remove(temporary)
            saved = clipboard_picture(temporary)
            if not saved["ok"]:
                self.status.set(saved["error"])
                return
            path = temporary
        else:
            path = filedialog.askopenfilename(title="Find a QR code by its picture",
                                              filetypes=[("Pictures", "*.png *.svg *.ppm *.pgm"), ("All files", "*.*")])
            if not path:
                return
            path = registry.display_path(path)

        def work():
            picture = qr_codec.read_qr_file(path)
            if not picture["ok"]:
                return picture
            own_path = path
            if paste:
                own_path = ""
            matches = matches_for_text(self.db_path, picture["value"]["reading"]["text"], own_path)
            if not matches["ok"]:
                return matches
            return ok_result({"text": picture["value"]["reading"]["text"], "matches": matches["value"]})

        def done(outcome):
            if not outcome["ok"]:
                self.show_results([], outcome["error"])
                return
            self.find_text.set(outcome["value"]["text"])
            self.plan_text.set("Found by the QR code in the picture: " + textsafe.clean(outcome["value"]["text"], 120))
            self.show_results(outcome["value"]["matches"], str(len(outcome["value"]["matches"])) +
                              " QR code(s) hold this text")

        self.start_job("Reading the picture", work, done)

    def refresh_models(self):
        def done(result):
            if not result["ok"]:
                self.state["inference"] = "not available"
                self.model_box.config(values=[])
                self.plan_text.set("Local inference is not available (" + result["kind"] + ": " + result["detail"] +
                                   "). Finding by QR code or color still works.")
            else:
                names = []
                for model in result["value"]["models"]:
                    names.append(model["name"])
                self.state["models"] = result["value"]["models"]
                self.model_box.config(values=names)
                self.state["inference"] = str(len(names)) + " model(s) on Ollama"
                if not result["value"]["cloud_disabled"]:
                    self.state["inference"] = self.state["inference"] + ", cloud features on"
                remembered = self.state.get("remembered_model", "")
                if remembered in names and self.model_box.get() == "":
                    self.model_box.set(remembered)
                    self.choose_model()
                    self.refresh_footer()
                    return
            self.refresh_footer()
            self.status.set("Ready")

        self.start_job("Listing local models",
                       lambda: ecp.list_models(self.state["engine"],
                                               ecp.new_call("window_list_models", self.client_info, None)), done)

    def choose_model(self, event=None):
        name = self.model_box.get()
        if name == "":
            return

        def done(result):
            if not result["ok"]:
                self.state["model_id"] = ""
                self.plan_text.set("Cannot use " + name + " (" + result["kind"] + ": " + result["detail"] + ")")
                return
            self.state["model_id"] = result["value"]["model_id"]
            self.save_setting("inference", "model", name)
            note = ""
            for model in self.state["models"]:
                if model["name"] == name and model["note"] != "":
                    note = " (" + model["note"] + ")"
            self.plan_text.set("Selected " + name + note + ", pinned to its digest. Ask away.")
            self.status.set("Ready")

        self.start_job("Loading " + name,
                       lambda: ecp.select_model(self.state["engine"], name,
                                                ecp.new_call("window_select_model", self.client_info, None)),
                       done)

    def ask(self):
        text = self.question.get().strip()
        if text == "":
            return
        if self.state["model_id"] == "":
            self.plan_text.set("Pick a local model first.")
            return

        def done(result):
            if not result["ok"]:
                self.show_results([], result["kind"] + ": " + result["detail"])
                self.plan_text.set("Ask failed (" + result["kind"] + "): " + result["detail"])
                return
            answer = result["value"]
            shown_list = []
            for record in answer["records"]:
                shown_list.append(shown_from_record(record))
            used = answer["plan_used"]
            plan = {}
            for key in ecp.PLAN_FIELDS:
                plan[key] = used[key]
            lines = "Plan (" + used["planner"] + "): " + json.dumps(plan) + "  —  " + answer["summary"]
            if len(used["clamped"]) > 0:
                lines = lines + "\nChanged by grounding: " + "; ".join(used["clamped"])
            self.plan_text.set(lines + "\nAudit line " + str(answer["audit_id"]))
            self.show_results(shown_list, answer["summary"])

        model_id = self.state["model_id"]
        self.start_job("Asking " + model_id.split("@")[0],
                       lambda: ecp.query(self.state["engine"], text, model_id,
                                         ecp.new_call("window_ask", self.client_info, None)), done)

    def pick_family(self, event=None):
        self.color_text.set("")
        self.run_search()

# ==== stamp v1 | author=kjFriday | hmac-sha256=8134f7b473b455d64ed81eaedbb71d070653bd9b2f478ffe4a6d9580e0e7d3e3 ====
