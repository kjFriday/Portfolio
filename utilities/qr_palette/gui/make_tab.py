# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/make_tab.py
# About: The Make tab: kind, link, preset and level, short links, the board of colors with votes...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The Make tab: choose what a QR code holds and its color, preview it, and save it.

It covers the kind, link, preset and level, short links, the board of colors with votes, the
preview, saving, logos and the robustness test.

MakeTab is part of PaletteWindow (window.py), so its methods reach the window's widgets, state and jobs
through self. From template… opens a dialog in dialogs.py; saving refreshes the Find tab's colors in use.

Main flow:
  1. redraw_board() ranks the usable colors for the preset and the votes (votes.board) and draws them
     as tiles; pick_tile() chooses one.
  2. Each change of text, kind, level, short link or logo calls schedule_preview(), which waits 250 ms
     for typing to pause and then runs refresh_preview().
  3. refresh_preview() builds the text the code will hold (a web link, a short link to it, or a kind's
     payload), encodes it with qr_codec and shows it with the details of the PNG to come.
  4. save_as() asks for a file and runs making.make_qr as a job: it draws, reads the file back and
     registers it.

Error-correction levels (ISO/IEC 18004): L, M, Q and H let a reader recover about 7, 15, 25 and 30
percent of the codewords. A logo hides modules in the middle of the code, so a logo forces level H.

Start reading at refresh_preview().
"""

import os
import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import app_settings
import payloads
import qr_codec
import registry
import shortlinks
import swatch
import textsafe
from making import PREVIEW, fitted_png, make_qr, robustness_score, slug, suggested_name
from qr_palette import default_qr_folder
from short_link_ops import fresh_code, plan_short_link, short_request
from votes import board, vote_color

# The board of colors in the Make tab: tiles of TILE pixels, GAP pixels apart, COLUMNS to a row.
TILE = 30
GAP = 4
COLUMNS = 14


class MakeTab:
    """The Make tab's widgets and actions (a part of PaletteWindow)."""

    def build_make_tab(self):
        """Create the Make tab's widgets and bind them.

        Reads self.preset and self.values (settings) for the starting preset and level, and
        app_settings.LINKS for the short-link choices. The board's canvas is sized for every usable
        color: ceil(colors / COLUMNS) rows of tiles. Widgets are created in a fixed order, which sets
        the order Tab moves through them."""
        make_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(make_tab, text="Make")
        self.make_bar = ttk.Frame(make_tab)
        self.make_bar.pack(fill="x")
        ttk.Label(self.make_bar, text="Kind").pack(side="left")
        self.kind_names = {}
        for name in payloads.KINDS:
            self.kind_names[payloads.TITLES[name]] = name
        self.kind_box = ttk.Combobox(self.make_bar, values=list(self.kind_names), width=14, state="readonly")
        self.kind_box.set(payloads.TITLES["link"])
        self.kind_box.pack(side="left", padx=(6, 12))
        ttk.Label(self.make_bar, text="Link").pack(side="left")
        self.link_text = tk.StringVar(value="")
        self.link_entry = ttk.Entry(self.make_bar, textvariable=self.link_text, width=40)
        self.link_entry.pack(side="left", padx=6)
        self.kind_form = ttk.Frame(make_tab)
        self.kind_fields = {}
        ttk.Label(self.make_bar, text="Preset").pack(side="left", padx=(12, 0))
        self.preset_box = ttk.Combobox(self.make_bar, values=swatch.presets(), width=10, state="readonly")
        self.preset_box.set(self.preset)
        self.preset_box.pack(side="left", padx=6)
        ttk.Label(self.make_bar, text="Error correction").pack(side="left", padx=(12, 0))
        self.level_names = {"L": "L (7%)", "M": "M (15%)", "Q": "Q (25%)", "H": "H (30%)"}
        self.level_box = ttk.Combobox(self.make_bar, values=["L (7%)", "M (15%)", "Q (25%)", "H (30%)"], width=8,
                                      state="readonly")
        self.level_box.set(self.level_names[self.values["pictures"]["error_correction"]])
        self.level_box.pack(side="left", padx=6)
        short_bar = ttk.Frame(make_tab)
        short_bar.pack(fill="x", pady=(6, 0))
        self.short_choice = tk.BooleanVar(value=app_settings.LINKS["short_by_default"])
        self.section_choice = tk.StringVar(value=app_settings.LINK_SECTION)
        self.link_only = []  # what applies only to web links: a Kind other than Web link turns these off
        self.link_only.append(ttk.Checkbutton(short_bar, text="Short link, printed as", variable=self.short_choice,
                                              command=lambda: self.schedule_preview()))
        self.link_only[0].pack(side="left")
        for section in shortlinks.SECTIONS:
            self.link_only.append(ttk.Radiobutton(short_bar, text=section + "  " + app_settings.LINKS[section]["base"] +
                                                  "…", value=section, variable=self.section_choice,
                                                  command=lambda: self.change_section()))
            self.link_only[len(self.link_only) - 1].pack(side="left", padx=(10, 0))
        if len(app_settings.LINKS["templates"]) > 0:
            self.link_only.append(ttk.Button(short_bar, text="From template…", command=lambda: self.from_template()))
            self.link_only[len(self.link_only) - 1].pack(side="left", padx=16)
        make_body = ttk.Frame(make_tab)
        make_body.pack(fill="both", expand=True, pady=(8, 0))
        tile_side = ttk.Frame(make_body)
        tile_side.pack(side="left", fill="y")
        ttk.Label(tile_side, text="Colors that scan, best first for the preset and your votes").pack(anchor="w")
        rows_needed = (len(swatch.usable_colors()) + COLUMNS - 1) // COLUMNS
        self.tiles = tk.Canvas(tile_side, width=COLUMNS * (TILE + GAP) + GAP, height=rows_needed * (TILE + GAP) + GAP,
                               background="#f4f4f4", highlightthickness=1, highlightbackground="#c8c8c8",
                               cursor="hand2")
        self.tiles.pack(anchor="w", pady=4)
        self.picked_text = tk.StringVar(value="Click a color for the code.")
        ttk.Label(tile_side, textvariable=self.picked_text).pack(anchor="w")
        vote_bar = ttk.Frame(tile_side)
        vote_bar.pack(anchor="w", pady=4)
        good_button = ttk.Button(vote_bar, text="Good", width=10)
        bad_button = ttk.Button(vote_bar, text="Bad", width=10)
        good_button.pack(side="left")
        bad_button.pack(side="left", padx=6)
        ttk.Label(tile_side, text="One vote per color; press it again to take it back.",
                  foreground="#555555").pack(anchor="w")
        preview_side = ttk.Frame(make_body, padding=(16, 0, 0, 0))
        preview_side.pack(side="left", fill="both", expand=True)
        self.preview = tk.Canvas(preview_side, width=PREVIEW + 20, height=PREVIEW + 20, background="#ffffff",
                                 highlightthickness=1, highlightbackground="#c8c8c8")
        self.preview.pack(anchor="nw")
        save_bar = ttk.Frame(preview_side)  # right under the preview, so a long note below never hides it
        save_bar.pack(anchor="w", pady=(6, 0))
        logo_bar = ttk.Frame(preview_side)
        logo_bar.pack(anchor="w", pady=(6, 0))
        self.logo_text = tk.StringVar(value="No logo")
        self.make_info = tk.StringVar(value="Type a link and pick a color.")
        ttk.Label(preview_side, textvariable=self.make_info, wraplength=560, justify="left").pack(anchor="w", pady=4)
        self.tiles.bind("<Button-1>", self.pick_tile)
        self.kind_box.bind("<<ComboboxSelected>>", self.change_kind)
        self.link_entry.bind("<KeyRelease>", self.schedule_preview)
        self.level_box.bind("<<ComboboxSelected>>", self.schedule_preview)
        self.preset_box.bind("<<ComboboxSelected>>", self.change_preset)
        good_button.config(command=lambda: self.cast_vote(1))
        bad_button.config(command=lambda: self.cast_vote(-1))
        ttk.Button(save_bar, text="Save PNG…", command=lambda: self.save_as("png")).pack(side="left")
        ttk.Button(save_bar, text="Save SVG…", command=lambda: self.save_as("svg")).pack(side="left", padx=6)
        ttk.Button(save_bar, text="Print size…", command=self.print_size).pack(side="left", padx=(12, 0))
        ttk.Button(save_bar, text="Test robustness", command=self.test_robustness).pack(side="left", padx=6)
        ttk.Button(logo_bar, text="Logo…", command=self.choose_logo).pack(side="left")
        ttk.Button(logo_bar, text="No logo", command=self.clear_logo).pack(side="left", padx=6)
        ttk.Label(logo_bar, textvariable=self.logo_text, foreground="#555555").pack(side="left", padx=6)

    def chosen_level(self):
        """The error-correction level chosen: "L", "M", "Q" or "H" (the first letter of the box), else "M"."""
        return self.level_box.get()[:1] or "M"

    def chosen_kind(self):
        """The kind of code chosen, as a payloads.KINDS name such as "link" (the box shows its title)."""
        return self.kind_names[self.kind_box.get()]

    def form_values(self):
        """The kind form's fields now -> {field key: text}, for payloads.build."""
        values_now = {}
        for key in self.kind_fields:
            values_now[key] = self.kind_fields[key].get()
        return values_now

    def change_kind(self, event=None):
        """A small form for the kind of code chosen, in place of the Link box; a web link has none.

        The fields come from payloads.FIELDS (key, label, hidden, choices), laid out three to a row;
        a hidden field (a password) shows "*". Short-link controls apply only to web links, so they
        are turned off for every other kind."""
        kind = self.chosen_kind()
        for child in self.kind_form.winfo_children():
            child.destroy()
        self.kind_fields.clear()
        fields = payloads.FIELDS[kind]
        for index in range(len(fields)):
            key, label, hidden, choices = fields[index]
            row = index // 3
            column = 2 * (index % 3)
            ttk.Label(self.kind_form, text=label).grid(row=row, column=column, sticky="w",
                                                       padx=(0 if column == 0 else 16, 6), pady=2)
            if choices is not None:
                field = ttk.Combobox(self.kind_form, values=list(choices), state="readonly", width=12)
                field.set(choices[0])
                field.bind("<<ComboboxSelected>>", self.schedule_preview)
                field.grid(row=row, column=column + 1, sticky="w", pady=2)
            else:
                field = ttk.Entry(self.kind_form, width=26, show="*" if hidden else "")
                field.bind("<KeyRelease>", self.schedule_preview)
                field.grid(row=row, column=column + 1, sticky="w", pady=2)
            self.kind_fields[key] = field
        if kind == "link":
            self.kind_form.pack_forget()
            self.link_entry.config(state="normal")
            for widget in self.link_only:
                widget.config(state="normal")
        else:
            self.kind_form.pack(fill="x", pady=(6, 0), after=self.make_bar)
            self.link_entry.config(state="disabled")
            for widget in self.link_only:
                widget.config(state="disabled")
        self.refresh_preview()

    def tile_box(self, index):
        """The board pixels of tile `index` -> (left, top, right, bottom), filling rows left to right."""
        column = index % COLUMNS
        row = index // COLUMNS
        left = GAP + column * (TILE + GAP)
        top = GAP + row * (TILE + GAP)
        return left, top, left + TILE, top + TILE

    def draw_tiles(self):
        """Draw the board: the colors in ranked order, the picked one outlined, a "+" or "−" on voted ones."""
        self.tiles.delete("all")
        for index in range(len(self.state["order"])):
            color = self.state["order"][index]
            box = self.tile_box(index)
            outline = ""
            width = 0
            if color == self.state["picked"]:
                outline = "#111111"
                width = 3
            self.tiles.create_rectangle(box[0], box[1], box[2], box[3], fill=color, outline=outline, width=width)
            mark = self.state["votes"].get(color, 0)
            if mark != 0:
                symbol = "+"
                if mark < 0:
                    symbol = "−"
                self.tiles.create_text(box[2] - 6, box[1] + 7, text=symbol, fill="#ffffff",
                                       font=("Segoe UI", 9, "bold"))

    def redraw_board(self):
        """Rank the colors again for the preset and the votes (votes.board), then draw the board.

        Runs on the window's thread: ranking reads the registry's votes and is quick."""
        ranked = board(self.db_path, self.preset_box.get())
        if not ranked["ok"]:
            self.status.set(ranked["error"])
            return
        self.state["order"] = ranked["value"]["order"]
        self.state["votes"] = ranked["value"]["votes"]
        self.state["places"] = ranked["value"]["places"]
        self.draw_tiles()
        self.show_picked()

    def show_picked(self):
        """Describe the picked color under the board: name, hex, rank, contrast with white and the vote.

        Contrast is the WCAG ratio (swatch.contrast), from 1:1 to 21:1; dark modules on white need a
        high one to scan."""
        color = self.state["picked"]
        if color == "":
            self.picked_text.set("Click a color for the code.")
            return
        vote_now = {1: "  ·  you said Good", -1: "  ·  you said Bad"}.get(self.state["votes"].get(color, 0), "")
        self.picked_text.set(swatch.color_name(color) + "  " + color + "  ·  rank " +
                             str(self.state["places"].get(color)) + "  ·  contrast " +
                             ("%.1f" % swatch.contrast(color, swatch.WHITE)) + ":1" + vote_now)

    def pick_tile(self, event):
        """A click on the board: pick the color under the pointer (a click in a gap does nothing)."""
        index = -1
        for candidate in range(len(self.state["order"])):
            box = self.tile_box(candidate)
            if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                index = candidate
        if index < 0:
            return
        self.state["picked"] = self.state["order"][index]
        self.draw_tiles()
        self.show_picked()
        self.refresh_preview()

    def cast_vote(self, voat):
        """Vote Good (`voat` 1) or Bad (-1) for the picked color, then rank the board again.

        The same vote twice takes it back (votes.vote_color answers 0). Writes the registry's votes."""
        if self.state["picked"] == "":
            self.status.set("Pick a color first")
            return
        cast = vote_color(self.db_path, self.state["picked"], voat)
        if not cast["ok"]:
            self.status.set(cast["error"])
            return
        self.status.set({1: "Good vote saved", -1: "Bad vote saved", 0: "Vote taken back"}[cast["value"]] + " for " +
                        self.state["picked"])
        self.redraw_board()

    def refresh_preview(self):
        """Draw the code the current choices would save, and say what it holds and how big it will be.

        Runs on the window's thread (encoding one code is quick). Any problem is shown in the info
        line and leaves the preview empty. Steps:
          1. Clear the preview and what it remembered for Test robustness.
          2. The text: the typed link, or the chosen kind's payload (payloads.build; a masked one says
             the registry keeps it without its password).
          3. For a short link, check the destination, then plan the short link (short_link_ops): the
             one made before for this link in this color, else a new ID kept ready in
             state["short_candidate"] so the preview shows the ID that Save will use.
          4. Encode: with a logo, qr_codec.place_logo picks a level H code with room for it; without,
             the smallest version at the chosen level, with the best of the eight masks (-1).
          5. Show it fitted to the preview, and read the saved PNG's size from its header."""
        self.state["make_after"] = None
        self.preview.delete("all")
        self.state["photos"]["preview"] = None
        self.state["matrix"] = None
        self.state["preview_text"] = ""
        self.state["preview_logo"] = None
        kind = self.chosen_kind()
        lead = ""
        if kind == "link":
            text = textsafe.clean(self.link_text.get(), None).strip()
            if text == "":
                self.make_info.set("Type a link and pick a color.")
                return
        else:
            built = payloads.build(kind, self.form_values())
            if not built["ok"]:
                self.make_info.set(built["error"].capitalize() + ".")
                return
            text = built["value"]["text"]
            lead = "Holds: " + textsafe.clean(payloads.one_line(built["value"]["stored"]), 240) + "\n"
            if built["value"]["masked"]:
                lead = lead + "The password goes in the code and its picture; the registry keeps it masked.\n"
        color = self.state["picked"] or qr_codec.INK
        caption = ""
        if kind == "link" and self.short_choice.get():
            checked = shortlinks.check_target(text)
            if not checked["ok"]:
                self.make_info.set(checked["error"] + ".")
                return
            if self.state["short_candidate"] == "":
                self.state["short_candidate"] = fresh_code(self.db_path, app_settings.LINKS["id_digits"])
            section = self.section_choice.get()
            planned = plan_short_link(self.db_path, checked["value"], color,
                                      short_request(self.state["short_candidate"], section))
            if not planned["ok"]:
                self.make_info.set(planned["error"] + ".")
                return
            if not planned["value"]["made"]:
                self.state["short_candidate"] = planned["value"]["code"]
            text = planned["value"]["url"]
            caption = shortlinks.caption(text)
            lead = "Prints " + text + " (" + section + "), which sends people to " + checked["value"] + ".\n"
            if planned["value"]["made"]:
                lead = lead + "Made before for this link in this color. "
            if section == "local":
                lead = lead + "Local: works only where you serve the local pages.\n"
            elif shortlinks.is_placeholder(app_settings.LINKS["nonlocal"]["base"]):
                lead = lead + "Set your own nonlocal address in links.json before printing.\n"
            elif planned["value"]["made"]:
                lead = lead + "\n"
        placed_logo = None
        if self.state["logo"] is not None:
            placed = qr_codec.place_logo(text, self.state["logo"])
            if not placed["ok"]:
                self.make_info.set(placed["error"] + ".")
                return
            matrix = placed["value"]["matrix"]
            placed_logo = placed["value"]["logo"]
            size = matrix["size"]
            lead = lead + ("The logo's square covers " + str(100 * placed_logo["box"][2] * placed_logo["box"][2] //
                                                             (size * size)) + "% of the modules.\n")
        else:
            made = qr_codec.encode_text(text, self.chosen_level(), 1, -1)
            if not made["ok"]:
                self.make_info.set(made["error"] + ".")
                return
            matrix = made["value"]
        self.state["matrix"] = matrix
        self.state["preview_text"] = text
        self.state["preview_caption"] = caption
        self.state["preview_logo"] = placed_logo
        photo = self.photo_from_png(fitted_png(matrix, color, caption, PREVIEW, placed_logo))
        self.state["photos"]["preview"] = photo
        self.preview.create_image((PREVIEW + 20) // 2, (PREVIEW + 20) // 2, image=photo)
        # a PNG starts with an 8-byte signature and the IHDR chunk (4-byte length, "IHDR"), so bytes
        # 16-24 are its width and height as big-endian 32-bit ints
        width, height = struct.unpack(">II", qr_codec.matrix_to_color_png(matrix, app_settings.DEFAULT_SCALE, 4, color,
                                                                          caption)[16:24])
        hint = ""
        if self.state["picked"] == "":
            hint = " Pick a color to save it."
        self.make_info.set(lead + "Version " + str(matrix["version"]) + ", level " + matrix["level"] +
                           ". PNG will be " + str(width) + " × " + str(height) + " px." + hint)

    def test_robustness(self):
        """How much wear the code in the preview survives, as a job: decoding is slow in pure Python.

        Tests exactly what the preview shows (its matrix, text, color, caption and logo), copied
        before the job starts so later typing cannot change what is being tested."""
        if self.state["matrix"] is None:
            self.status.set("Type a link first: the test is for the code in the preview")
            return
        matrix = self.state["matrix"]
        text = self.state["preview_text"]
        color = self.state["picked"] or qr_codec.INK
        caption = self.state["preview_caption"]
        logo = self.state["preview_logo"]

        # on the window's thread when the test ends
        def done(outcome):
            if not outcome["ok"]:
                self.status.set("Robustness: " + outcome["error"])
                return
            self.status.set("Robustness of the code in the preview: " + qr_codec.describe_score(outcome["value"]))

        self.start_job("Testing robustness", lambda: robustness_score(matrix, text, color, caption, logo), done)

    def choose_logo(self):
        """Ask for a small picture to put in the middle of the code, read it as a job, and use it.

        A picture over qr_codec.MAX_LOGO_SIDE pixels a side is refused. With a logo the level is
        locked at H (the most error correction, to make up for the hidden modules); the level chosen
        before is remembered so No logo can put it back."""
        path = filedialog.askopenfilename(title="A small picture for the middle of the code",
                                          filetypes=[("PNG pictures", "*.png"), ("All files", "*.*")])
        if not path:
            return
        path = registry.display_path(path)

        # on the window's thread when the picture has been read
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Logo", outcome["error"])
                self.status.set("No logo chosen")
                return
            image = outcome["value"]
            if image["width"] > qr_codec.MAX_LOGO_SIDE or image["height"] > qr_codec.MAX_LOGO_SIDE:
                messagebox.showerror("Logo", "Pick a picture at most " + str(qr_codec.MAX_LOGO_SIDE) +
                                     " pixels a side.")
                self.status.set("No logo chosen")
                return
            if self.state["logo"] is None:
                self.state["level_before_logo"] = self.level_box.get()
            self.state["logo"] = image
            self.logo_text.set(os.path.basename(path) + "  (level H)")
            self.level_box.set(self.level_names["H"])
            self.level_box.config(state="disabled")
            self.status.set("Logo: " + os.path.basename(path))
            self.refresh_preview()

        self.start_job("Reading the logo", lambda: qr_codec.load_image_file(path), done)

    def clear_logo(self):
        """Drop the logo, unlock the level and put back the level chosen before it."""
        if self.state["logo"] is None:
            return
        self.state["logo"] = None
        self.logo_text.set("No logo")
        self.status.set("No logo")
        self.level_box.config(state="readonly")
        self.level_box.set(self.state["level_before_logo"])
        self.refresh_preview()

    def schedule_preview(self, event=None):
        """Redraw the preview 250 ms after the last change (a debounce), so typing stays quick.

        Each call cancels the redraw already waiting and schedules a new one with Tk's after()."""
        if self.state["make_after"] is not None:
            self.window.after_cancel(self.state["make_after"])
        self.state["make_after"] = self.window.after(250, self.refresh_preview)

    def change_section(self):
        """Local or nonlocal: picking one ticks Short link, and the choice is remembered."""
        self.save_setting("links", "use", self.section_choice.get())
        self.short_choice.set(True)
        self.schedule_preview()

    def save_as(self, kind):
        """Save the code as a `kind` ("png" or "svg") file and register it, as a job.

        Steps:
          1. Build the text as the preview does; a color must be picked.
          2. Make sure the pictures folder exists (else start in the home folder) and suggest a file
             name from the text, or from the kind's name, and the color.
          3. Ask where to save; for a short link, use the ID the preview showed.
          4. Run making.make_qr as a job: it draws the file, reads it back to prove it scans and
             registers it.
          5. When done: remember the folder (saved in settings unless it is the default), use a new
             short-link ID next time, refresh served pages, the footer and the colors in use."""
        code_kind = self.chosen_kind()
        name = ""
        if code_kind == "link":
            text = textsafe.clean(self.link_text.get(), None).strip()
        else:
            built = payloads.build(code_kind, self.form_values())
            if not built["ok"]:
                self.make_info.set(built["error"].capitalize() + ".")
                return
            text = built["value"]["text"]
            name = built["value"]["name"]
        if text == "" or self.state["picked"] == "":
            self.make_info.set("Type a link and pick a color first.")
            return
        try:
            os.makedirs(self.state["folder"], exist_ok=True)
        except OSError:
            self.state["folder"] = os.path.expanduser("~")
        label = {"png": "PNG picture", "svg": "SVG drawing"}[kind]
        initial = suggested_name(text, self.state["picked"], kind)
        if name != "":
            initial = slug(name) + "-" + self.state["picked"][1:] + "." + kind
        path = filedialog.asksaveasfilename(title="Save QR code", initialdir=self.state["folder"], initialfile=initial,
                                            defaultextension="." + kind, filetypes=[(label, "*." + kind)])
        if not path:
            return
        color = self.state["picked"]
        level = self.chosen_level()
        short = None
        if code_kind == "link" and self.short_choice.get():
            if self.state["short_candidate"] == "":
                self.state["short_candidate"] = fresh_code(self.db_path, app_settings.LINKS["id_digits"])
            short = short_request(self.state["short_candidate"], self.section_choice.get())
        logo = self.state["logo"]

        # on the window's thread when saving ends
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Save QR code", outcome["error"])
                self.status.set("Not saved")
                return
            self.state["folder"] = os.path.dirname(outcome["value"]["path"])
            if os.path.normcase(self.state["folder"]) != os.path.normcase(default_qr_folder()):
                self.save_setting("pictures", "folder", self.state["folder"])
            message = "Saved and registered: " + outcome["value"]["path"]
            if outcome["value"]["short_code"] != "":
                if outcome["value"]["short_code"] == self.state["short_candidate"]:
                    self.state["short_candidate"] = ""  # used: the next new short link gets a new ID
                message = (message + "  ·  " + short["section"] + " short link " + outcome["value"]["short_code"] +
                           " sends people to " + outcome["value"]["target"] + " (File → Export " + short["section"] +
                           " redirect pages… publishes it)")
                self.refresh_served()
            if payloads.is_masked(outcome["value"]["link"]):
                message = message + "  ·  the password is in the picture only, not in the registry"
            self.status.set(message)
            self.refresh_footer()
            self.refresh_used()

        self.start_job("Saving",
                       lambda: make_qr(self.db_path, text, color, level, path, app_settings.DEFAULT_SCALE, short, logo,
                                       code_kind != "link"), done)

    def change_preset(self, event=None):
        """Use another color preset: remember it, give it to the ECP engine, and rank the board again."""
        self.save_setting("colors", "preset", self.preset_box.get())
        self.state["engine"]["preset"] = self.preset_box.get()
        self.redraw_board()

# ==== stamp v1 | author=kjFriday | hmac-sha256=ae1d1924edd6e1c3ba2ce54e3c1cbcc69fc00f2c8d0f6beb2a097c690776a6e6 ====
