# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/dialogs.py
# About: The window's larger dialogs: the audit log, print size, make from a list and link from a...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The window's larger dialogs: the audit log, print size, make from a list and link from a template.

Dialogs is part of PaletteWindow (window.py). Print size and Make from a list read the Make tab's error
correction level (chosen_level), and Make from a list starts with its short link section.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import app_settings
import audit
import payloads
import registry
import shortlinks
import textsafe
from batches import make_batch, read_batch_csv
from print_advice import MIN_CAPTION_MM, MIN_MODULE_MM, print_advice


class Dialogs:
    """The dialogs opened from the menus and the Make tab (a part of PaletteWindow)."""

    def show_audit(self):
        """The audit log, newest first: any line in full, the chain checked, and its fingerprint to keep
        somewhere else (so lines cut off the end would show even if the anchor beside it went too)."""
        path = self.state["engine"]["audit_file"]
        dialog = tk.Toplevel(self.window)
        dialog.title("Audit log")
        dialog.geometry("940x600")
        dialog.transient(self.window)
        top = ttk.Frame(dialog, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=path, foreground="#555555").pack(anchor="w")
        bar = ttk.Frame(top)
        bar.pack(anchor="w", pady=(6, 0))
        outcome_text = tk.StringVar(value="")
        ttk.Label(top, textvariable=outcome_text, wraplength=900, justify="left").pack(anchor="w", pady=(6, 0))
        table = ttk.Treeview(dialog, columns=("time", "tool", "result", "model", "rows", "ms"), show="tree headings",
                             height=14)
        table.heading("#0", text="Line")
        table.column("#0", width=60, stretch=False)
        for name, title, width in (("time", "Time (UTC)", 180), ("tool", "Tool", 180), ("result", "Result", 140),
                                   ("model", "Model", 170), ("rows", "Rows", 50), ("ms", "ms", 70)):
            table.heading(name, text=title)
            table.column(name, width=width, stretch=name == "model")
        table.pack(fill="both", expand=True, padx=8)
        detail = tk.Text(dialog, height=10, wrap="word")
        detail.pack(fill="x", padx=8, pady=8)
        records = []

        def alive():
            return dialog.winfo_exists()

        def load():
            records.clear()
            records.extend(audit.read_records(path, 500))
            for item in table.get_children():
                table.delete(item)
            for index in range(len(records) - 1, -1, -1):
                record = records[index]
                table.insert("", "end", iid=str(index), text=str(record.get("audit_id", "?")),
                             values=(record.get("ts", ""), record.get("tool", ""), record.get("result_kind", ""),
                                     str(record.get("model_id", "")).split("@")[0], record.get("row_count", ""),
                                     record.get("elapsed_ms", "")))
            if len(records) == 0:
                outcome_text.set("The audit log is empty.")
            else:
                outcome_text.set("The last " + str(len(records)) + " line(s), newest first. Click one to read it.")

        def show_line(event=None):
            chosen = table.selection()
            if len(chosen) == 0:
                return
            detail.config(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", json.dumps(records[int(chosen[0])], indent=2, ensure_ascii=False))
            detail.config(state="disabled")

        def check():
            def done(outcome):
                if not alive():
                    return
                if outcome["ok"]:
                    outcome_text.set("The chain is whole: " + str(outcome["value"]) + " line(s), and it still reaches "
                                     "its anchor.")
                else:
                    outcome_text.set("Problem: " + outcome["error"])

            self.start_job("Checking the audit log", lambda: audit.verify(path), done)

        def copy_fingerprint():
            found = audit.fingerprint(path)
            if not found["ok"]:
                outcome_text.set(found["error"])
                return
            text = audit.fingerprint_text(found["value"])
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            outcome_text.set("Copied fingerprint " + text[:20] + "…  Keep it somewhere else (a note, an email to "
                             "yourself); Check a kept fingerprint… compares the log with it later.")

        def check_kept():
            text = simpledialog.askstring("Check a kept fingerprint", "Paste a fingerprint you kept (a line number, "
                                          "a colon and 64 hex digits):", parent=dialog)
            if not text:
                return

            def done(outcome):
                if not alive():
                    return
                if outcome["ok"]:
                    outcome_text.set("It matches: line " + text.strip().split(":")[0] + " is as it was written, and "
                                     "the chain is whole (" + str(outcome["value"]) + " lines).")
                else:
                    outcome_text.set("Problem: " + outcome["error"])

            self.start_job("Checking the fingerprint", lambda: audit.check_fingerprint(path, text), done)

        ttk.Button(bar, text="Check the chain", command=check).pack(side="left")
        ttk.Button(bar, text="Copy fingerprint", command=copy_fingerprint).pack(side="left", padx=6)
        ttk.Button(bar, text="Check a kept fingerprint…", command=check_kept).pack(side="left")
        ttk.Button(bar, text="Refresh", command=load).pack(side="left", padx=6)
        table.bind("<<TreeviewSelect>>", show_line)
        load()

    def print_size(self):
        """Advice on how big to print the code in the preview, for a scanning distance."""
        text = self.state["preview_text"]
        if text == "":
            self.status.set("Type a link first: the advice is for the code in the preview")
            return
        caption = self.state["preview_caption"]
        logo_version = 0
        if self.state["preview_logo"] is not None:
            logo_version = self.state["matrix"]["version"]
        dialog = tk.Toplevel(self.window)
        dialog.title("Print size")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="For the code holding " + textsafe.clean(payloads.one_line(payloads.stored_form(text)[0]),
                                                                      80)).grid(row=0, column=0, columnspan=2, sticky="w")
        width_text = tk.StringVar(value="3")
        distance_text = tk.StringVar(value="0.3")
        ttk.Label(body, text="Printed width of the picture (cm)").grid(row=1, column=0, sticky="w", pady=(8, 2))
        width_entry = ttk.Entry(body, textvariable=width_text, width=8)
        width_entry.grid(row=1, column=1, sticky="w", pady=(8, 2))
        ttk.Label(body, text="Scanning distance (m)").grid(row=2, column=0, sticky="w")
        distance_entry = ttk.Entry(body, textvariable=distance_text, width=8)
        distance_entry.grid(row=2, column=1, sticky="w")
        answer = tk.StringVar(value="")
        ttk.Label(body, textvariable=answer, justify="left", wraplength=620).grid(row=3, column=0, columnspan=2,
                                                                                 sticky="w", pady=8)

        def update(event=None):
            try:
                width = float(width_text.get().replace(",", "."))
                distance = float(distance_text.get().replace(",", "."))
            except ValueError:
                answer.set("Type two numbers, such as 3 and 0.3.")
                return
            advice = print_advice(text, width, distance, caption, logo_version)
            if not advice["ok"]:
                answer.set(advice["error"] + ".")
                return
            lines = ["Modules need " + str(advice["value"]["need_mm"]) + " mm or more here (rules of thumb: at least " +
                     str(MIN_MODULE_MM) + " mm to print well, and the code at least a tenth as wide as the distance)."]
            for row in advice["value"]["levels"]:
                line = "Level " + row["level"]
                if row["level"] == self.chosen_level():
                    line = line + " (chosen)"
                line = line + ": version " + str(row["version"]) + ", modules " + str(row["module_mm"]) + " mm, "
                if row["fits"]:
                    line = line + "fits"
                else:
                    line = line + "too small: print it at least " + str(row["min_width_cm"]) + " cm wide"
                if row["caption_mm"] is not None:
                    line = line + "; address letters " + str(row["caption_mm"]) + " mm"
                    if row["caption_mm"] < MIN_CAPTION_MM:
                        line = line + " (too small to read)"
                lines.append(line)
            answer.set("\n".join(lines))

        width_entry.bind("<KeyRelease>", update)
        distance_entry.bind("<KeyRelease>", update)
        ttk.Button(body, text="Close", command=dialog.destroy).grid(row=4, column=1, sticky="e")
        update()

    def make_from_list(self):
        """A whole print run from a CSV: the rows are counted first, then made as one job, with a report."""
        dialog = tk.Toplevel(self.window)
        dialog.title("Make from a list")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        source_text = tk.StringVar(value="")
        folder_text = tk.StringVar(value=self.state["folder"])
        kind_choice = tk.StringVar(value="png")
        short_on = tk.BooleanVar(value=False)
        section_on = tk.StringVar(value=self.section_choice.get())
        snap_on = tk.BooleanVar(value=False)
        summary = tk.StringVar(value="Choose a CSV whose first row names its columns: link and color, and optionally "
                                     "label and file.")
        rows = []
        progress = {"done": 0, "total": 0, "stop": False, "running": False}

        def alive():
            return dialog.winfo_exists()

        def choose_source():
            path = filedialog.askopenfilename(title="A list of codes", parent=dialog,
                                              filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
            if not path:
                return
            path = registry.display_path(path)

            def done(outcome):
                self.status.set("Ready")
                if not alive():
                    return
                del rows[:]
                make_button.config(state="disabled")
                if not outcome["ok"]:
                    summary.set(outcome["error"] + ".")
                    return
                source_text.set(path)
                rows.extend(outcome["value"])
                problems = []
                for row in rows:
                    if row["problem"] != "":
                        problems.append(row)
                said = str(len(rows)) + " row(s): " + str(len(rows) - len(problems)) + " ready"
                if len(problems) > 0:
                    said = (said + ", " + str(len(problems)) + " with a problem (the first, row " +
                            str(problems[0]["row"]) + ": " + problems[0]["problem"] + ")")
                summary.set(said + ".")
                if len(problems) < len(rows):
                    make_button.config(state="normal")

            self.start_job("Reading the list", lambda: read_batch_csv(path), done)

        def choose_folder():
            chosen = filedialog.askdirectory(title="Save the pictures in", parent=dialog, mustexist=False,
                                             initialdir=folder_text.get())
            if chosen:
                folder_text.set(registry.display_path(chosen))

        def watch(done_rows, total):
            progress["done"] = done_rows
            progress["total"] = total
            return progress["stop"]

        def tick():
            if progress["running"] and alive():
                summary.set("Making code " + str(progress["done"] + 1) + " of " + str(progress["total"]) + "…")
                dialog.after(200, tick)

        def make():
            target = folder_text.get().strip()
            if target == "":
                summary.set("Choose a folder for the pictures.")
                return
            section = ""
            if short_on.get():
                section = section_on.get()
            chosen_rows = list(rows)
            kind = kind_choice.get()
            level = self.chosen_level()
            snap = snap_on.get()
            progress["stop"] = False
            progress["running"] = True
            make_button.config(state="disabled")
            stop_button.config(state="normal")

            def done(outcome):
                progress["running"] = False
                if alive():
                    stop_button.config(state="disabled")
                    make_button.config(state="normal")
                if not outcome["ok"]:
                    self.status.set("Nothing made")
                    messagebox.showerror("Make from a list", outcome["error"])
                    return
                value = outcome["value"]
                self.state["folder"] = target
                said = "Made " + str(value["made"]) + " code(s), skipped " + str(value["skipped"])
                if value["stopped"]:
                    said = said + " (stopped)"
                said = said + ". Report: " + value["report"]
                self.status.set(said)
                if alive():
                    summary.set(said)
                self.refresh_footer()
                self.refresh_used()
                if section == "local":
                    self.refresh_served()
                if messagebox.askyesno("Make from a list", said + "\n\nOpen the folder?"):
                    try:
                        os.startfile(target)
                    except (AttributeError, OSError) as error:
                        self.status.set(str(error))

            self.start_job("Making codes", lambda: make_batch(self.db_path, chosen_rows, target, kind, level,
                                                              app_settings.DEFAULT_SCALE, section, snap, watch), done)
            tick()

        def stop():
            progress["stop"] = True
            summary.set("Stopping after this code…")

        ttk.Label(body, text="List").grid(row=0, column=0, sticky="w")
        ttk.Entry(body, textvariable=source_text, width=56, state="readonly").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Choose…", command=choose_source).grid(row=0, column=2)
        ttk.Label(body, textvariable=summary, wraplength=560, justify="left").grid(row=1, column=0, columnspan=3,
                                                                                   sticky="w", pady=6)
        ttk.Label(body, text="Folder").grid(row=2, column=0, sticky="w")
        ttk.Entry(body, textvariable=folder_text, width=56).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Choose…", command=choose_folder).grid(row=2, column=2)
        kinds = ttk.Frame(body)
        kinds.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(kinds, text="Pictures").pack(side="left")
        ttk.Radiobutton(kinds, text="PNG", variable=kind_choice, value="png").pack(side="left", padx=6)
        ttk.Radiobutton(kinds, text="SVG", variable=kind_choice, value="svg").pack(side="left")
        ttk.Label(kinds, text="Error correction " + self.chosen_level() + ", as in the Make tab.",
                  foreground="#555555").pack(side="left", padx=12)
        shorts = ttk.Frame(body)
        shorts.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(shorts, text="Short links, printed as", variable=short_on).pack(side="left")
        for name in shortlinks.SECTIONS:
            ttk.Radiobutton(shorts, text=name, value=name, variable=section_on).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(body,
                        text="A color too light to scan: use the nearest that scans (otherwise the row is skipped)",
                        variable=snap_on).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(10, 0))
        make_button = ttk.Button(buttons, text="Make the codes", command=make, state="disabled")
        make_button.pack(side="left")
        stop_button = ttk.Button(buttons, text="Stop", command=stop, state="disabled")
        stop_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left")

    def from_template(self):
        """A small dialog that builds the link from one of links.json's templates."""
        names = sorted(app_settings.LINKS["templates"])
        dialog = tk.Toplevel(self.window)
        dialog.title("Link from a template")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Template").grid(row=0, column=0, sticky="w")
        chooser = ttk.Combobox(body, values=names, state="readonly", width=24)
        chooser.grid(row=0, column=1, sticky="w", pady=4)
        pattern_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=pattern_text, foreground="#555555").grid(row=1, column=0, columnspan=2, sticky="w")
        fields = ttk.Frame(body)
        fields.grid(row=2, column=0, columnspan=2, sticky="we", pady=6)
        result_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=result_text, wraplength=440, justify="left").grid(row=3, column=0, columnspan=2,
                                                                                       sticky="w")
        entries = {}

        def filled():
            typed = {}
            for name in entries:
                typed[name] = entries[name].get()
            return shortlinks.fill_template(app_settings.LINKS["templates"][chooser.get()], typed)

        def update(event=None):
            outcome = filled()
            result_text.set(outcome["value"] if outcome["ok"] else outcome["error"])

        def choose(event=None):
            for child in fields.winfo_children():
                child.destroy()
            entries.clear()
            pattern = app_settings.LINKS["templates"][chooser.get()]
            pattern_text.set(pattern)
            names_in_order = shortlinks.template_fields(pattern)
            for row in range(len(names_in_order)):
                ttk.Label(fields, text=names_in_order[row]).grid(row=row, column=0, sticky="w", padx=(0, 8))
                entry = ttk.Entry(fields, width=40)
                entry.grid(row=row, column=1, pady=2)
                entry.bind("<KeyRelease>", update)
                entries[names_in_order[row]] = entry
            update()

        def use():
            outcome = filled()
            if not outcome["ok"]:
                result_text.set(outcome["error"])
                return
            self.link_text.set(outcome["value"])
            dialog.destroy()
            self.refresh_preview()

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Use this link", command=use).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", choose)
        chooser.set(names[0])
        choose()
        dialog.grab_set()

# ==== stamp v1 | author=kjFriday | hmac-sha256=bc2204f3aaab83d03fbd72fd50d2c73cad4b4c395facdbb3d23147103d0bcc5f ====
