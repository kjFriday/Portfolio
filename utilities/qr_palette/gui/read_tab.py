# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/read_tab.py
# About: The Read tab: open or paste a picture, read the code in it, and show its matches in the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The Read tab: open or paste a picture, read its QR code and show registry matches.

ReadTab is part of PaletteWindow (window.py). Find it switches to the Find tab and searches there. The
helpers before the class (pictures through Tk and from the clipboard) follow QR Studio's
(PROVENANCE.md); the Find tab pastes pictures with clipboard_picture too.

Main flow:
  1. Open picture… or Paste picture gives a file path (a pasted picture is first saved as a PNG in
     the temporary folder).
  2. read_path() runs a job that decodes the picture (qr_codec, or making.picture_from_image for a
     GIF Tk converted), finds the registry records holding the same text (finding.matches_for_text)
     and asks short_link_ops.tamper_verdict whether a short link only looks like one of yours.
  3. show_reading() fills the text box, the detected color, the verdict and the matches table.
  4. Register this picture…, Find it and Open link act on what was read.

Start reading at read_path().
"""

import os
import subprocess
import tempfile
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox

import payloads
import qr_codec
import registry
import swatch
from common import fail, ok_result
from finding import matches_for_text
from making import picture_from_image, preview_png, register_picture
from short_link_ops import tamper_verdict


def picture_through_tk(tk, path):
    """Any picture Tk can open (GIF, PNG, PPM) -> Result Image, by way of a temporary PPM.

    `tk` is the tkinter module (a Tk root must exist). Tk decodes the format and writes it out as a
    PPM, which qr_codec's own reader understands; the temporary file is always removed."""
    try:
        photo = tk.PhotoImage(file=path)
    except Exception:
        return fail("cannot open this picture; save it as PNG")
    handle, temporary = tempfile.mkstemp(suffix=".ppm")
    os.close(handle)
    try:
        photo.write(temporary, format="ppm")
        return qr_codec.load_image_file(temporary)
    except Exception as error:
        return fail(str(error))
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def clipboard_picture(path):
    """Save the picture on the clipboard as a PNG -> Result path. Windows only (PowerShell).

    Side effects: starts a hidden PowerShell process (at most 20 seconds) that writes `path`.
    Python's standard library cannot read a clipboard picture, so .NET's Windows Forms clipboard
    does it. The script exits with 3 when the clipboard holds no picture."""
    if os.name != "nt":
        return fail("pasting a picture needs Windows")
    # the path sits in a PowerShell single-quoted string, where a quote is escaped by doubling it
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$i = [Windows.Forms.Clipboard]::GetImage(); if ($i -eq $null) { exit 3 }; "
              "$i.Save('" + path.replace("'", "''") + "', [Drawing.Imaging.ImageFormat]::Png)")
    # -STA: the Windows Forms clipboard works only on a single-threaded apartment thread;
    # CREATE_NO_WINDOW keeps a console window from flashing up
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                              text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        return fail(str(error))
    if done.returncode != 0 or not os.path.isfile(path):
        return fail("there is no picture on the clipboard")
    return ok_result(path)


class ReadTab:
    """The Read tab's widgets and actions (a part of PaletteWindow)."""

    def build_read_tab(self):
        """Create the Read tab's widgets and bind them."""
        read_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(read_tab, text="Read")
        read_bar = ttk.Frame(read_tab)
        read_bar.pack(fill="x")
        read_body = ttk.Frame(read_tab)
        read_body.pack(fill="both", expand=True, pady=(8, 0))
        self.picture_canvas = tk.Canvas(read_body, width=380, height=380, background="#f4f4f4", highlightthickness=1,
                                        highlightbackground="#c8c8c8")
        self.picture_canvas.pack(side="left", anchor="n")
        read_side = ttk.Frame(read_body, padding=(12, 0, 0, 0))
        read_side.pack(side="left", fill="both", expand=True)
        ttk.Label(read_side, text="Text in the code").pack(anchor="w")
        self.read_text = tk.Text(read_side, height=5, wrap="word")
        self.read_text.pack(fill="x")
        self.read_details = tk.StringVar(value="Open or paste a picture with a QR code in it.")
        ttk.Label(read_side, textvariable=self.read_details, wraplength=520, justify="left").pack(anchor="w", pady=4)
        detected_row = ttk.Frame(read_side)
        detected_row.pack(anchor="w")
        self.detected_swatch = tk.Canvas(detected_row, width=22, height=22, highlightthickness=1,
                                         highlightbackground="#c8c8c8")
        self.detected_swatch.pack(side="left")
        self.detected_text = tk.StringVar(value="")
        ttk.Label(detected_row, textvariable=self.detected_text).pack(side="left", padx=6)
        self.verdict_text = tk.StringVar(value="")
        self.verdict_label = ttk.Label(read_side, textvariable=self.verdict_text, wraplength=520, justify="left")
        self.verdict_label.pack(anchor="w", pady=(4, 0))
        ttk.Label(read_side, text="In the registry").pack(anchor="w", pady=(10, 0))
        self.read_table = ttk.Treeview(read_side, columns=("hex", "path"), show="tree headings", height=6)
        self.read_table.heading("#0", text="Color")
        self.read_table.heading("hex", text="Hex")
        self.read_table.heading("path", text="Path")
        self.read_table.column("#0", width=150, stretch=False)
        self.read_table.column("hex", width=80, stretch=False)
        self.read_table.column("path", width=360)
        self.read_table.pack(fill="both", expand=True)
        read_buttons = ttk.Frame(read_side)
        read_buttons.pack(anchor="w", pady=6)
        ttk.Button(read_bar, text="Open picture…", command=self.open_picture).pack(side="left")
        ttk.Button(read_bar, text="Paste picture", command=self.paste_picture).pack(side="left", padx=6)
        ttk.Label(read_bar, text="PNG, SVG (made here), GIF or PPM.").pack(side="left", padx=8)
        ttk.Button(read_buttons, text="Register this picture…", command=self.register_shown).pack(side="left")
        ttk.Button(read_buttons, text="Find it", command=self.find_read_text).pack(side="left", padx=6)
        ttk.Button(read_buttons, text="Open link", command=self.open_read_link).pack(side="left")

    def show_reading(self, outcome):
        """Show a finished read_path job: clear the tab, then fill it from `outcome`.

        `outcome` is a Result {"picture": Picture, "matches": [Shown], "verdict": {"line", "warning"}};
        a failure shows its message. Steps:
          1. Clear the picture, swatch, verdict, text and matches; forget the last picture.
          2. Show the decoded text, its kind (when not a plain link), the detected color and the
             tamper verdict (red when it warns).
          3. Show the picture itself when Tk can open it (PNG or GIF), shrunk to fit 380 pixels;
             otherwise a preview drawn again from the decoded text.
          4. List the registry matches."""
        self.picture_canvas.delete("all")
        self.detected_swatch.delete("all")
        self.detected_text.set("")
        self.verdict_text.set("")
        self.read_text.delete("1.0", "end")
        for item in self.read_table.get_children():
            self.read_table.delete(item)
        self.state["picture"] = None
        if not outcome["ok"]:
            self.read_details.set(outcome["error"] + ".")
            self.status.set("Nothing read from " + self.state["picture_source"])
            return
        picture = outcome["value"]["picture"]
        self.state["picture"] = picture
        reading = picture["reading"]
        self.read_text.insert("1.0", reading["text"])
        kind = payloads.kind_of(reading["text"])
        self.read_details.set("Read: " + qr_codec.describe(reading) + "." +
                              (" Kind: " + payloads.TITLES[kind] + "." if kind not in ("", "link") else ""))
        self.detected_swatch.create_rectangle(0, 0, 24, 24, fill=picture["color"], outline="")
        self.detected_text.set("detected ≈ " + picture["color"] + " (" + swatch.color_name(picture["color"]) + ")")
        self.verdict_text.set(outcome["value"]["verdict"]["line"])
        self.verdict_label.config(foreground="#b00020" if outcome["value"]["verdict"]["warning"] else "")
        png = preview_png(reading["text"], picture["color"], reading["level"], reading["version"])
        photo = None
        if picture["format"] != "svg" and self.state["picture_path"].lower().endswith((".png", ".gif")):
            try:
                photo = tk.PhotoImage(file=self.state["picture_path"])
                # Tk can shrink a picture only by a whole factor (subsample keeps every n-th pixel)
                factor = 1
                while photo.width() // factor > 380 or photo.height() // factor > 380:
                    factor = factor + 1
                if factor > 1:
                    photo = photo.subsample(factor, factor)
            except Exception:
                photo = None
        if photo is None:
            photo = self.photo_from_png(png)
        # kept in state: Tk shows a PhotoImage only while Python holds a reference to it
        self.state["photos"]["picture"] = photo
        if photo is not None:
            self.picture_canvas.create_image(190, 190, image=photo)
        for shown in outcome["value"]["matches"]:
            self.read_table.insert("", "end", iid="r" + str(shown["id"]), text=" " + shown["name"],
                                   image=self.swatch_image(shown["hex"]), values=(shown["hex"], shown["path"]))
        found = len(outcome["value"]["matches"])
        self.status.set("Read a QR code from " + self.state["picture_source"] + "; " + str(found) + " in the registry")

    def read_path(self, path, source):
        """Read the QR code in the picture at `path` as a job, then show it (show_reading).

        `source` names it in messages: the file's name, or "the clipboard" for a pasted picture, which
        is never matched by its path (it is a temporary file). A GIF is converted through Tk here, on
        the window's thread, since Tk must not be used from a job's thread."""
        self.state["picture_path"] = path
        self.state["picture_source"] = source
        image = None
        if path.lower().endswith(".gif"):
            loaded = picture_through_tk(tk, path)
            if not loaded["ok"]:
                self.read_details.set(loaded["error"] + ".")
                return
            image = loaded["value"]

        # runs off the window's thread: decode, find matches, judge the link
        def work():
            if image is not None:
                picture = picture_from_image(image)
            else:
                picture = qr_codec.read_qr_file(path)
            if not picture["ok"]:
                return picture
            own_path = ""
            if source != "the clipboard":
                own_path = path
            matches = matches_for_text(self.db_path, picture["value"]["reading"]["text"], own_path)
            if not matches["ok"]:
                return matches
            return ok_result({"picture": picture["value"], "matches": matches["value"],
                              "verdict": tamper_verdict(self.db_path, picture["value"]["reading"]["text"])})

        self.start_job("Reading " + source, work, self.show_reading)

    def open_picture(self):
        """Ask for a picture file and read it."""
        path = filedialog.askopenfilename(title="Open a QR code picture",
                                          filetypes=[("Pictures", "*.png *.svg *.gif *.ppm *.pgm"),
                                                     ("All files", "*.*")])
        if path:
            self.read_path(registry.display_path(path), os.path.basename(path))

    def paste_picture(self):
        """Save the clipboard's picture to a temporary PNG and read it.

        Any old file of that name is removed first, so a failed paste never reads the last one."""
        temporary = os.path.join(tempfile.gettempdir(), "qr_palette_clipboard.png")
        if os.path.isfile(temporary):
            os.remove(temporary)
        saved = clipboard_picture(temporary)
        if not saved["ok"]:
            self.read_details.set(saved["error"] + ".")
            return
        self.read_path(temporary, "the clipboard")

    def register_shown(self):
        """Add the picture just read to the registry, after asking for its color.

        Only a PNG or SVG file can be registered (registry.FORMATS), and never a pasted picture, which
        has no file of its own. The detected color is offered; the person may correct it, since a
        printed or photographed code rarely keeps its exact color. Registering runs as a job
        (making.register_picture) and refreshes the footer and the colors in use."""
        picture = self.state["picture"]
        if picture is None:
            self.status.set("Read a picture first")
            return
        if self.state["picture_source"] == "the clipboard":
            messagebox.showinfo("Register", "A pasted picture has no file of its own. Save it as a PNG, then open it.")
            return
        if picture["format"] not in registry.FORMATS:
            messagebox.showinfo("Register", "Only PNG and SVG pictures can be registered. Save it as PNG first.")
            return
        ask = tk.Toplevel(self.window)
        ask.title("Register this picture")
        ask.transient(self.window)
        ttk.Label(ask, text="The color of this QR code (detected ≈ " + picture["color"] + "):",
                  padding=10).pack(anchor="w")
        value = tk.StringVar(value=picture["color"])
        ttk.Entry(ask, textvariable=value, width=12).pack(anchor="w", padx=10)

        # the Register button: check the color, close the dialog, register as a job
        def confirm():
            color = swatch.normalize_hex(value.get())
            if color == "":
                messagebox.showerror("Register", "Type the color as #rrggbb.", parent=ask)
                return
            ask.destroy()

            # on the window's thread when registering ends
            def done(outcome):
                if not outcome["ok"]:
                    messagebox.showerror("Register", outcome["error"])
                    return
                self.status.set("Registered " + self.state["picture_path"])
                self.refresh_footer()
                self.refresh_used()

            self.start_job("Registering", lambda: register_picture(self.db_path, self.state["picture_path"], color),
                           done)

        ttk.Button(ask, text="Register", command=confirm).pack(anchor="e", padx=10, pady=10)

    def find_read_text(self):
        """Find it: search the Find tab by the text in the box (which the person may have edited)."""
        text = self.read_text.get("1.0", "end-1c").strip()
        if text != "":
            self.selector.set("qr_code")
            self.show_selector()
            self.find_text.set(text)
            self.tabs.select(self.find_tab)
            self.run_search()

    def open_read_link(self):
        """Open the text in the box in the browser, only when it is an http(s) link and the person agrees."""
        text = self.read_text.get("1.0", "end-1c").strip()
        if not qr_codec.is_link(text):
            self.read_details.set("Only http:// and https:// links can be opened.")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + text):
            webbrowser.open(text)

# ==== stamp v1 | author=kjFriday | hmac-sha256=4f5576b2b407b1e4fc97675b0e7388a63647d8e8c8deea18f3fbe261654edaf5 ====
