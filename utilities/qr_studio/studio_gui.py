# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_gui.py
# About: QR Studio's window: tkinter, with Read, Make and History tabs and a status line.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's window: tkinter, with Read, Make and History tabs and a status line.

The window reaches the codec and the history only through their functions, so it can be rewritten in any
toolkit. StudioWindow builds it and holds what its handlers share. Its widgets are made in the order the
window has always made them, so Tk gives them the same names and packs them the same way.

Reading a picture runs on a worker thread, so the window stays responsive. read_path starts work() on a
daemon thread, which only sets self.pending; poll_job, on the Tk thread, looks for it every POLL_DELAY
milliseconds and hands it to finish_read, which updates the widgets. While self.job is set, another Open or
Paste is ignored. In the Make tab, typing or choosing a level redraws the preview PREVIEW_DELAY milliseconds
after the last change.

What the handlers share (StudioWindow attributes)
  history        [Entry], newest first, as saved in history.json (see studio_history.py)
  matrix         the Matrix the Make tab shows, or None; Save and Copy picture use it
  photo          the PhotoImage on the Read tab's canvas (Tk forgets an image nothing holds)
  preview_photo  the PhotoImage on the Make tab's preview
  reading        the last Reading shown
  job            the reading thread while one runs, else None
  pending        (Result Reading, Image, shrink, source) as the reading thread leaves it for poll_job
  make_after     the scheduled preview redraw, or None
"""

import base64
import json
import os
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from qr_codec import decode_image, encode_text, fail, load_image_file, matrix_to_image, write_png
from studio_clipboard import clipboard_image_to_png, png_to_clipboard
from studio_history import (APP_ID, HISTORY_LIMIT, add_history, describe, history_path, is_link, load_history,
                            save_history, save_matrix)

ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "app.ico")
ICON_CREDIT = "Icon: drawn for this project (a pixel QR code), AGPL-3.0 like the code."

READ_SIDE = 380  # the Read tab's picture area is this many pixels square; a bigger picture is shown shrunk
PREVIEW_SIDE = 360  # the Make tab's preview area is this many pixels square
PREVIEW_ROOM = 340  # the preview picture, quiet zone included, fits in this many pixels
QUIET_ZONE = 4  # light modules round a code, here as in the files save_matrix writes
MIN_SCALE = 1  # pixels per module for Save and Copy picture: the spin box's range and its first value
MAX_SCALE = 40
DEFAULT_SCALE = 8
POLL_DELAY = 100  # milliseconds between looks at a running read
PREVIEW_DELAY = 250  # milliseconds after the last key or level change before the preview is redrawn
SMOKE_DELAY = 800  # milliseconds a --smoke run lets the window settle before it writes its report


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


def picture_through_tk(tk, path):
    """Any picture Tk can open (GIF, PNG, PPM) -> Result Image, by way of a temporary PPM."""
    try:
        photo = tk.PhotoImage(file=path)
    except Exception:
        return fail("cannot open this picture; save it as PNG")
    handle, temporary = tempfile.mkstemp(suffix=".ppm")
    os.close(handle)
    try:
        photo.write(temporary, format="ppm")
        return load_image_file(temporary)
    except Exception as error:
        return fail(str(error))
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


class StudioWindow:
    """The QR Studio window over the saved history. Make it, then run() it."""

    def __init__(self, smoke_path, app_name, version):
        """Open the window. `smoke_path` is "" for a normal run; otherwise the window writes the smoke report
        there SMOKE_DELAY milliseconds after it opens, then closes. `app_name` goes in the About box and
        `version` in the title, the About box and the smoke report."""
        self.smoke_path = smoke_path
        self.app_name = app_name
        self.version = version
        windows_identity()  # before tk.Tk(): the taskbar identity and DPI awareness must come first
        self.path_to_history = history_path()
        self.history = load_history(self.path_to_history)
        self.matrix = None
        self.photo = None
        self.preview_photo = None
        self.reading = None
        self.job = None
        self.pending = None
        self.make_after = None

        self.window = tk.Tk()
        self.window.title("Generic Company Inc. \u2014 QR Studio " + version)
        self.window.geometry("900x620")
        self.window.minsize(720, 480)
        self.icon_set = set_icon(self.window)
        self.build_menu()

        self.tabs = ttk.Notebook(self.window)
        self.tabs.pack(fill="both", expand=True, padx=6, pady=6)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.window, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(0, 6))
        self.build_read_tab()
        self.build_make_tab()
        self.build_history_tab()
        self.refresh_history()

        if smoke_path != "":
            self.window.after(SMOKE_DELAY, self.write_smoke_report)

    def run(self):
        """Run the window until it is closed -> exit code 0."""
        self.window.mainloop()
        return 0

    def build_menu(self):
        """The menu bar: Help, with About."""
        menu = tk.Menu(self.window)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.window.config(menu=menu)

    def show_about(self):
        messagebox.showinfo("About " + self.app_name, self.app_name + " " + self.version + "\n\n"
                            "Reads QR codes from pictures and makes new ones. The QR codec is written from "
                            "scratch in standard-library Python.\n\n" + ICON_CREDIT + "\n\n"
                            "Copyright (c) 2026 kjFriday. AGPL-3.0-only.")

    def remember(self, kind, text):
        """Put a code read or made at the top of the history, save it and show it in the History tab."""
        self.history = add_history(self.history, kind, text, time.time())
        save_history(self.path_to_history, self.history)
        self.refresh_history()

    # --- Read tab ---------------------------------------------------------------------------------

    def build_read_tab(self):
        """The picture on the left (self.canvas); on the right the text found (self.result_text), a line about
        the reading (self.details) and the Copy text and Open link buttons."""
        read_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(read_tab, text="Read")
        read_bar = ttk.Frame(read_tab)
        read_bar.pack(fill="x")
        read_body = ttk.Frame(read_tab)
        read_body.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(read_body, width=READ_SIDE, height=READ_SIDE, background="#f4f4f4",
                                highlightthickness=1, highlightbackground="#c8c8c8")
        self.canvas.pack(side="left", fill="both", expand=False)
        result_side = ttk.Frame(read_body, padding=(10, 0, 0, 0))
        result_side.pack(side="left", fill="both", expand=True)
        ttk.Label(result_side, text="Text in the code").pack(anchor="w")
        self.result_text = tk.Text(result_side, height=12, wrap="word")
        self.result_text.pack(fill="both", expand=True)
        self.details = tk.StringVar(value="Open or paste a picture with a QR code in it.")
        ttk.Label(result_side, textvariable=self.details, wraplength=420, justify="left").pack(anchor="w", pady=4)
        result_buttons = ttk.Frame(result_side)
        result_buttons.pack(anchor="w")
        # The buttons come last, as they always have: the order widgets are made in decides their Tk names
        # and the order the Tab key moves through them.
        ttk.Button(read_bar, text="Open picture\u2026", command=self.open_picture).pack(side="left")
        ttk.Button(read_bar, text="Paste picture", command=self.paste_picture).pack(side="left", padx=6)
        ttk.Label(read_bar, text="PNG, GIF or PPM. Screenshots: copy, then Paste.").pack(side="left", padx=8)
        ttk.Button(result_buttons, text="Copy text", command=self.copy_reading).pack(side="left")
        ttk.Button(result_buttons, text="Open link", command=self.open_link).pack(side="left", padx=6)

    def show_reading_text(self, text):
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)

    def show_picture(self, path, image):
        """Show the picture at `path` on the canvas, shrunk by a whole factor to fit -> the scale it is shown
        at (1.0 when Tk cannot show it)."""
        self.canvas.delete("all")
        self.photo = None
        try:
            photo = tk.PhotoImage(file=path)
        except Exception:
            return 1.0
        factor = 1
        while photo.width() // factor > READ_SIDE or photo.height() // factor > READ_SIDE:
            factor = factor + 1
        if factor > 1:
            photo = photo.subsample(factor, factor)
        self.photo = photo
        self.canvas.create_image(READ_SIDE // 2, READ_SIDE // 2, image=photo)
        return 1.0 / factor

    def mark_corners(self, reading, shrink, image):
        """Ring the three finder centres of `reading` on the picture shown at scale `shrink`."""
        left = READ_SIDE // 2 - image["width"] * shrink / 2.0
        top = READ_SIDE // 2 - image["height"] * shrink / 2.0
        for corner in reading["corners"]:
            x = left + corner[0] * shrink
            y = top + corner[1] * shrink
            self.canvas.create_oval(x - 7, y - 7, x + 7, y + 7, outline="#e0302a", width=3)

    def finish_read(self, result, image, shrink, source):
        """Show what the reading thread found in the picture from `source` (a file name or "the clipboard")."""
        self.job = None
        if not result["ok"]:
            self.show_reading_text("")
            self.details.set(result["error"] + ".")
            self.status.set("Nothing read from " + source)
            return
        reading = result["value"]
        self.reading = reading
        self.show_reading_text(reading["text"])
        self.details.set("Read: " + describe(reading) + ".")
        self.mark_corners(reading, shrink, image)
        self.status.set("Read a QR code from " + source)
        self.remember("read", reading["text"])

    def poll_job(self):
        """On the Tk thread: finish the read once the reading thread has left its result, else look again."""
        if self.pending is not None:
            pending = self.pending
            self.pending = None
            self.finish_read(pending[0], pending[1], pending[2], pending[3])
            return
        self.window.after(POLL_DELAY, self.poll_job)

    def read_path(self, path, source):
        """Open the picture at `path` (the core readers first, then Tk) and look for a code in it on a thread.
        Ignored while a read is running."""
        if self.job is not None:
            return
        loaded = load_image_file(path)
        if not loaded["ok"]:
            loaded = picture_through_tk(tk, path)
        if not loaded["ok"]:
            self.details.set(loaded["error"] + ".")
            return
        image = loaded["value"]
        shrink = self.show_picture(path, image)
        self.show_reading_text("")
        self.details.set("Looking for a QR code\u2026")
        self.status.set("Reading " + source)
        self.job = threading.Thread(target=self.work, args=(image, shrink, source), daemon=True)
        self.job.start()
        self.window.after(POLL_DELAY, self.poll_job)

    def work(self, image, shrink, source):
        """The reading thread: decode the picture and leave the result for poll_job. It touches no widget."""
        self.pending = (decode_image(image), image, shrink, source)

    def open_picture(self):
        path = filedialog.askopenfilename(title="Open a picture",
                                          filetypes=[("Pictures", "*.png *.gif *.ppm *.pgm"), ("All files", "*.*")])
        if path:
            self.read_path(path, os.path.basename(path))

    def paste_picture(self):
        """Read the picture on the clipboard, by way of a PNG in the temp folder."""
        temporary = os.path.join(tempfile.gettempdir(), "qr_studio_clipboard.png")
        if os.path.isfile(temporary):
            os.remove(temporary)
        saved = clipboard_image_to_png(temporary)
        if not saved["ok"]:
            self.details.set(saved["error"] + ".")
            return
        self.read_path(temporary, "the clipboard")

    def copy_reading(self):
        text = self.result_text.get("1.0", "end-1c")
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.status.set("Copied the text")

    def open_link(self):
        """Open the text found in the browser, if it is a web link and the user agrees."""
        text = self.result_text.get("1.0", "end-1c").strip()
        if not is_link(text):
            self.details.set("Only http:// and https:// links can be opened.")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + text):
            webbrowser.open(text)

    # --- Make tab ---------------------------------------------------------------------------------

    def build_make_tab(self):
        """The text to put in a code (self.make_text), the error-correction level (self.level_box), the pixels
        per module (self.scale_choice), a line about the code (self.make_info), the Save and Copy buttons and
        the preview (self.preview)."""
        self.make_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.make_tab, text="Make")
        make_side = ttk.Frame(self.make_tab)
        make_side.pack(side="left", fill="both", expand=True)
        ttk.Label(make_side, text="Text or link to put in the code").pack(anchor="w")
        self.make_text = tk.Text(make_side, height=10, wrap="word")
        self.make_text.pack(fill="both", expand=True)
        options = ttk.Frame(make_side)
        options.pack(fill="x", pady=6)
        ttk.Label(options, text="Error correction").pack(side="left")
        self.level_choice = tk.StringVar(value="M")  # the box's variable; chosen_level reads the box itself
        self.level_box = ttk.Combobox(options, textvariable=self.level_choice,
                                      values=["L (7%)", "M (15%)", "Q (25%)", "H (30%)"], width=9, state="readonly")
        self.level_box.set("M (15%)")
        self.level_box.pack(side="left", padx=6)
        ttk.Label(options, text="Pixels per module").pack(side="left", padx=(12, 0))
        self.scale_choice = tk.IntVar(value=DEFAULT_SCALE)
        ttk.Spinbox(options, from_=MIN_SCALE, to=MAX_SCALE, textvariable=self.scale_choice,
                    width=5).pack(side="left", padx=6)
        self.make_info = tk.StringVar(value="Type something to see its code.")
        ttk.Label(make_side, textvariable=self.make_info, wraplength=420, justify="left").pack(anchor="w")
        make_buttons = ttk.Frame(make_side)
        make_buttons.pack(anchor="w", pady=6)
        self.preview = tk.Canvas(self.make_tab, width=PREVIEW_SIDE, height=PREVIEW_SIDE, background="#ffffff",
                                 highlightthickness=1, highlightbackground="#c8c8c8")
        self.preview.pack(side="left", padx=(10, 0), anchor="n")
        self.make_text.bind("<KeyRelease>", self.schedule_preview)
        self.level_box.bind("<<ComboboxSelected>>", self.schedule_preview)
        ttk.Button(make_buttons, text="Save PNG\u2026",
                   command=lambda: self.save_as(".png", "PNG picture")).pack(side="left")
        ttk.Button(make_buttons, text="Save SVG\u2026",
                   command=lambda: self.save_as(".svg", "SVG drawing")).pack(side="left", padx=6)
        ttk.Button(make_buttons, text="Copy picture", command=self.copy_picture).pack(side="left")

    def chosen_level(self):
        return self.level_box.get()[:1] or "M"

    def chosen_scale(self):
        """The pixels per module asked for, kept within MIN_SCALE..MAX_SCALE; DEFAULT_SCALE when not a number."""
        try:
            return max(MIN_SCALE, min(MAX_SCALE, int(self.scale_choice.get())))
        except (tk.TclError, ValueError):
            return DEFAULT_SCALE

    def refresh_preview(self):
        """Make the code for the text now in the Make tab, show it and say what it is (or why there is none)."""
        self.make_after = None
        text = self.make_text.get("1.0", "end-1c")
        self.preview.delete("all")
        self.preview_photo = None
        self.matrix = None
        if text == "":
            self.make_info.set("Type something to see its code.")
            return
        made = encode_text(text, self.chosen_level(), 1, -1)
        if not made["ok"]:
            self.make_info.set(made["error"] + ".")
            return
        matrix = made["value"]
        self.matrix = matrix
        scale = max(1, PREVIEW_ROOM // (matrix["size"] + 2 * QUIET_ZONE))
        png = write_png(matrix_to_image(matrix, scale, QUIET_ZONE))
        photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        self.preview_photo = photo
        self.preview.create_image(PREVIEW_SIDE // 2, PREVIEW_SIDE // 2, image=photo)
        side = (matrix["size"] + 2 * QUIET_ZONE) * self.chosen_scale()
        self.make_info.set("Version " + str(matrix["version"]) + " (" + str(matrix["size"]) + "\u00d7" +
                           str(matrix["size"]) + " modules), level " + matrix["level"] + ", mask " +
                           str(matrix["mask"]) + ". PNG will be " + str(side) + " px square.")

    def schedule_preview(self, event=None):
        """Redraw the preview PREVIEW_DELAY milliseconds from now, instead of at any time asked before."""
        if self.make_after is not None:
            self.window.after_cancel(self.make_after)
        self.make_after = self.window.after(PREVIEW_DELAY, self.refresh_preview)

    def save_as(self, extension, label):
        """Save the code shown as a file the user names (`extension` .png or .svg) and add it to the history."""
        if self.matrix is None:
            self.make_info.set("Nothing to save yet.")
            return
        path = filedialog.asksaveasfilename(title="Save QR code", defaultextension=extension,
                                            filetypes=[(label, "*" + extension)], initialfile="qr-code" + extension)
        if not path:
            return
        saved = save_matrix(self.matrix, path, self.chosen_scale())
        if saved["ok"]:
            self.status.set("Saved " + os.path.basename(path))
            self.remember("made", self.make_text.get("1.0", "end-1c"))
        else:
            messagebox.showerror("Save QR code", saved["error"])

    def copy_picture(self):
        """Put the code shown on the clipboard as a picture, by way of a PNG in the temp folder."""
        if self.matrix is None:
            self.make_info.set("Nothing to copy yet.")
            return
        temporary = os.path.join(tempfile.gettempdir(), "qr_studio_copy.png")
        saved = save_matrix(self.matrix, temporary, self.chosen_scale())
        if saved["ok"]:
            saved = png_to_clipboard(temporary)
        if saved["ok"]:
            self.status.set("Copied the picture")
            self.remember("made", self.make_text.get("1.0", "end-1c"))
        else:
            self.make_info.set(saved["error"] + ".")

    # --- History tab ------------------------------------------------------------------------------

    def build_history_tab(self):
        """The list of codes read and made (self.table, whose row ids are indexes into self.history) and its
        Make again, Copy text and Clear history buttons."""
        history_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(history_tab, text="History")
        self.table = ttk.Treeview(history_tab, columns=("when", "kind", "text"), show="headings", height=14)
        self.table.heading("when", text="When")
        self.table.heading("kind", text="")
        self.table.heading("text", text="Text")
        self.table.column("when", width=140, stretch=False)
        self.table.column("kind", width=60, stretch=False)
        self.table.column("text", width=600)
        self.table.pack(fill="both", expand=True)
        history_buttons = ttk.Frame(history_tab)
        history_buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(history_buttons, text="Make again", command=self.make_again).pack(side="left")
        ttk.Button(history_buttons, text="Copy text", command=self.copy_entry).pack(side="left", padx=6)
        ttk.Button(history_buttons, text="Clear history", command=self.clear_history).pack(side="left")
        ttk.Label(history_tab, text="Kept on this computer only, newest first, up to " + str(HISTORY_LIMIT) +
                  ".").pack(anchor="w")

    def refresh_history(self):
        """Fill the History tab from self.history."""
        for item in self.table.get_children():
            self.table.delete(item)
        for index in range(len(self.history)):
            entry = self.history[index]
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry["when"]))
            line = entry["text"].replace("\n", " ")
            self.table.insert("", "end", iid=str(index), values=(when, entry["kind"], line))

    def selected_entry(self):
        """The Entry of the row selected in the History tab, or None."""
        chosen = self.table.selection()
        if len(chosen) == 0:
            return None
        return self.history[int(chosen[0])]

    def make_again(self):
        """Put the selected entry's text in the Make tab, show that tab and its code."""
        entry = self.selected_entry()
        if entry is None:
            return
        self.make_text.delete("1.0", "end")
        self.make_text.insert("1.0", entry["text"])
        self.tabs.select(self.make_tab)
        self.refresh_preview()

    def copy_entry(self):
        entry = self.selected_entry()
        if entry is not None:
            self.window.clipboard_clear()
            self.window.clipboard_append(entry["text"])
            self.status.set("Copied the text")

    def clear_history(self):
        if messagebox.askyesno("Clear history", "Forget every read and made code in the list?"):
            self.history = []
            save_history(self.path_to_history, [])
            self.refresh_history()

    # --- Smoke run --------------------------------------------------------------------------------

    def write_smoke_report(self):
        """The --smoke run: check the codec, fill the preview, write the JSON report to self.smoke_path and close.
        Keys: app_id, version, title, icon_set, tabs, codec_ok, preview_version."""
        made = encode_text("smoke", "M", 1, -1)["value"]
        reading = decode_image(matrix_to_image(made, 3, QUIET_ZONE))
        self.make_text.insert("1.0", "https://example.com/smoke")
        self.refresh_preview()
        report = {"app_id": APP_ID, "version": self.version, "title": self.window.title(), "icon_set": self.icon_set,
                  "tabs": [], "codec_ok": reading["ok"] and reading["value"]["text"] == "smoke",
                  "preview_version": self.matrix["version"] if self.matrix else 0}
        for tab_id in self.tabs.tabs():
            report["tabs"].append(self.tabs.tab(tab_id, "text"))
        handle = open(self.smoke_path, "w", encoding="utf-8")
        json.dump(report, handle, indent=2)
        handle.close()
        self.window.destroy()

# ==== stamp v1 | author=kjFriday | hmac-sha256=b2c79037503af094f5973248cc7f32d291cc2292174bdec64608844fff76fc2f ====
