# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/window.py
# About: The QR Palette window: PaletteWindow, with its state, job queue, menus, status lines and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The QR Palette window: PaletteWindow, which joins the three tabs and the dialogs.

It owns the window's state, job queue, menus, status lines and smoke run.

PaletteWindow is put together from the tab classes (make_tab.py, read_tab.py, find_tab.py) and the
dialogs (dialogs.py); their methods share the window's widgets and its state dict through self. Slow
work runs as jobs (start_job: one at a time, first come, first served, off the window's thread), and
--smoke uses the window on a scratch registry, writes a JSON report and closes it. The helpers before
the class (the taskbar identity and the icon) follow QR Studio's (PROVENANCE.md).

The tabs use each other through self: Print size… asks the Make tab for chosen_level, saving and
registering refresh the Find tab's colors in use (refresh_used), the Read tab's Find it searches in the
Find tab, and Make from a list uses the Make tab's short link choice.

Who calls it: qr_palette.py starts the window with run_gui(). Main flow:
  1. run() checks the registry opens, writes settings.json's defaults when it is missing, and makes
     the state dict.
  2. It builds the menus, the two status lines and the Make, Read and Find tabs, then draws the
     board, the colors in use and the footer.
  3. A normal start lists the local models and, shortly after, offers scheduled link changes that
     are due; --smoke instead writes its report and closes.
  4. Tk's main loop runs until the window closes; a local page server still running is stopped.

Threading: Tk may only be used from the thread that made the window. A job's work() runs on a
thread of its own and never touches Tk; it leaves its outcome in state["finished"], which
poll_job() collects every 100 ms on the window's thread to call done(outcome) there.

Start reading at run(), then start_job().
"""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import app_settings
import local_inference
import localkey
import registry
import settings
import shortlinks
from common import fail, ok_result, with_registry
from finding import search
from making import make_qr
from qr_palette import (APP_ID, APP_NAME, ICON_CREDIT, ICON_FILE, __version__, color_voats_path, default_backup_path,
                        default_qr_folder, local_pages_folder)
from registry_export import export_registry
from short_link_ops import export_redirects, import_scan_file, publish_now, publish_plan
from votes import import_color_voats
from gui.dialogs import Dialogs
from gui.find_tab import FindTab
from gui.make_tab import MakeTab
from gui.read_tab import ReadTab


def windows_identity():
    """Own taskbar button (not Python's) and crisp text on scaled displays. Windows only.

    The explicit AppUserModelID makes Windows group the window under QR Palette's own taskbar button
    and icon instead of python.exe's. SetProcessDpiAwareness(1) is PROCESS_SYSTEM_DPI_AWARE: Windows
    stops stretching the window's bitmap on a scaled display, so text is drawn sharp. Both must run
    before the first window is made; an older Windows without them is left as it is."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def set_icon(window):
    """The pixel icon on the window and its dialogs -> True when it was set.

    iconbitmap(default=...) applies the .ico to this window and every Toplevel made after it. A
    missing or unreadable icon is not an error: the window keeps Tk's own."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


class PaletteWindow(MakeTab, ReadTab, FindTab, Dialogs):
    """The window. run() builds it in a fixed order (menus, status lines, Make, Read, Find), so every
    widget is created as it always was, then runs it until it closes.

    self.state holds what changes while the window is open:
      jobs     job, job_label, job_number, finished, queue
      Make     picked, order, votes, places, make_after, matrix, preview_text, preview_caption,
               preview_logo, logo, level_before_logo, short_candidate, folder
      Read     picture, picture_path, picture_source
      Find     results, models, engine, model_id, inference, remembered_model
      menus    export_folders, server, serve_index
      Tk       photos and swatches keep the PhotoImages shown, so Tk does not lose them
    """

    def __init__(self, db_path, engine, smoke_path, config, warnings):
        """Keep what the window needs; nothing is built until run().

        `db_path` is the registry file; `engine` the ECP engine (ecp.py) for the Ask box; `smoke_path`
        the --smoke report file, or "" for a normal start; `config` the Settings record of
        settings.json; `warnings` the settings problems found at start, shown once the window opens."""
        self.db_path = db_path
        self.engine = engine
        self.smoke_path = smoke_path
        self.config = config
        self.warnings = warnings

    def run(self):
        """Open the window and run it until it closes -> exit code (1 when the registry cannot be opened).

        A smoke run never writes settings.json. The window is at most 800 pixels tall, and 80 less than
        the screen, so it fits a small display with its taskbar."""
        windows_identity()
        opened = registry.connect(self.db_path, False)
        if not opened["ok"]:
            self.window = tk.Tk()
            self.window.withdraw()
            messagebox.showerror(APP_NAME, opened["error"])
            self.window.destroy()
            return 1
        registry.close(opened["value"])
        if self.smoke_path == "":
            written = settings.write_defaults(self.config)
            if not written["ok"]:
                self.warnings.append(written["error"])
        self.values = self.config["values"]
        self.preset = self.values["colors"]["preset"]
        folder = self.values["pictures"]["folder"] or default_qr_folder()

        self.state = {"job": None, "job_label": "", "job_number": 0, "finished": [], "queue": [], "picked": "",
                      "order": [], "votes": {}, "places": {}, "make_after": None, "matrix": None, "photos": {},
                      "swatches": {}, "picture": None, "picture_path": "", "picture_source": "", "results": [],
                      "folder": folder, "models": [], "engine": self.engine, "model_id": "", "inference": "checking",
                      "remembered_model": self.values["inference"]["model"], "short_candidate": "",
                      "export_folders": {}, "server": None, "serve_index": None, "preview_text": "",
                      "preview_caption": "", "preview_logo": None, "logo": None, "level_before_logo": ""}

        self.window = tk.Tk()
        self.window.title("Generic Company Inc. — QR Palette " + __version__)
        self.window.geometry("1100x" + str(min(800, self.window.winfo_screenheight() - 80)))
        self.window.minsize(940, 640)
        self.icon_set = set_icon(self.window)
        self.status = tk.StringVar(value="Ready")
        self.footer = tk.StringVar(value="")
        self.build_menu()

        self.tabs = ttk.Notebook(self.window)
        # The two status lines are packed from the bottom first, so a tall tab can never push them out of sight.
        ttk.Label(self.window, textvariable=self.footer, anchor="w", foreground="#555555").pack(side="bottom", fill="x",
                                                                                                padx=8, pady=(0, 6))
        ttk.Label(self.window, textvariable=self.status, anchor="w").pack(side="bottom", fill="x", padx=8)
        self.tabs.pack(fill="both", expand=True, padx=6, pady=6)
        self.build_make_tab()
        self.build_read_tab()
        self.build_find_tab()

        self.redraw_board()
        self.refresh_used()
        self.refresh_footer()
        if self.smoke_path == "":
            self.refresh_models()
            # after the window is up, so the question about due changes appears over it
            self.window.after(600, self.offer_due_changes)
            if len(self.warnings) > 0:
                messagebox.showwarning("Settings",
                                       "Some settings could not be used, so their defaults are in place:\n\n" +
                                       "\n".join(self.warnings[:12]) + "\n\nSettings file: " + self.config["path"])

        if self.smoke_path != "":
            self.window.after(800, self.write_smoke_report)

        self.window.mainloop()
        if self.state["server"] is not None:
            shortlinks.stop_server(self.state["server"])
        return 0

    # --- Jobs: one slow task at a time, off the window's thread; the rest wait their turn ----------
    def poll_job(self):
        """Collect finished jobs on the window's thread; call done(outcome) for the running one.

        Each finished entry is (job number, done, outcome). An entry whose number is not the current
        job's belongs to a cancelled job and is dropped. When the running job has finished, its done()
        runs and the next waiting job starts; otherwise polling goes on every 100 ms while a job runs.
        Appending and popping a list are atomic in CPython, so the list needs no lock."""
        while len(self.state["finished"]) > 0:
            number, done, outcome = self.state["finished"].pop(0)
            if number == self.state["job_number"] and self.state["job"] is not None:
                self.state["job"] = None
                done(outcome)
                self.start_next()
                return
        if self.state["job"] is not None:
            self.window.after(100, self.poll_job)

    def start_job(self, label, work, done):
        """Run work() off the window's thread and then done(outcome) on it. Jobs run one at a time, first
        come, first served: one asked for while another runs (Save while a model loads, say) waits for
        its turn instead of being refused.

        `label` names the job in the status line ("Saving"); work() must not touch Tk and returns a
        Result (an exception becomes a failed one); done(outcome) runs on the window's thread."""
        self.state["queue"].append((label, work, done))
        if self.state["job"] is not None:
            self.status.set(self.state["job_label"] + "…  then " + label.lower() + " (" +
                            str(len(self.state["queue"])) + " waiting)")
            return
        self.start_next()

    def start_next(self):
        """Start the first waiting job, unless one is running or none waits.

        Each job gets a new number, so poll_job can tell its outcome from a cancelled job's. The thread
        is a daemon, so a job still running never keeps the program open after the window closes."""
        if self.state["job"] is not None or len(self.state["queue"]) == 0:
            return
        label, work, done = self.state["queue"].pop(0)
        self.state["job_number"] = self.state["job_number"] + 1
        number = self.state["job_number"]
        self.state["job_label"] = label

        # the job's thread: run work(), turn an exception into a failed Result, hand the outcome back
        def runner():
            try:
                outcome = work()
            except Exception as error:
                outcome = fail(label + " failed: " + str(error))
            self.state["finished"].append((number, done, outcome))

        waiting = ""
        if len(self.state["queue"]) > 0:
            waiting = "  (" + str(len(self.state["queue"])) + " more waiting)"
        self.status.set(label + "…" + waiting)
        self.state["job"] = threading.Thread(target=runner, daemon=True)
        self.state["job"].start()
        self.window.after(100, self.poll_job)

    def cancel_job(self):
        """Stop waiting for the running job (its answer is ignored); the jobs waiting behind it go on.

        Known limitation: Python cannot stop a thread, so the cancelled work runs on to its end in the
        background (a model call until its timeout, say); only its outcome is dropped."""
        if self.state["job"] is not None:
            self.state["job"] = None
            self.state["job_number"] = self.state["job_number"] + 1
            self.status.set("Cancelled " + self.state["job_label"].lower())
            self.start_next()

    def save_setting(self, section, key, value):
        """Save one setting (settings.json `section`.`key` = `value`) as it changes; never in a smoke run.

        A failure to save is shown in the status line and is otherwise harmless."""
        if self.smoke_path != "":
            return
        saved = settings.save(self.config, [(section, key, value)])
        if not saved["ok"]:
            self.status.set(saved["error"])

    def refresh_footer(self):
        """Write the footer: how many codes are registered, local inference, the page server and the registry.

        Reads the registry on the window's thread (a count is quick); a registry that cannot be read
        counts as 0 codes."""
        # count the registry's records on the open connection
        def read(connection):
            return ok_result(registry.counts(connection))

        counted = with_registry(self.db_path, read)
        records = 0
        if counted["ok"]:
            records = counted["value"]["records"]
        serving = ""
        if self.state["server"] is not None:
            serving = "  ·  serving local pages at " + self.state["server"]["base"]
        self.footer.set(str(records) + " QR code(s)  ·  local inference: " + self.state["inference"] + serving +
                        "  ·  registry: " + self.db_path)

    def swatch_image(self, color):
        """A 16 x 16 PhotoImage filled with `color` ("#rrggbb"), for rows of the results tables.

        Made once per color and kept in state["swatches"]: Tk drops an image Python no longer holds."""
        if color not in self.state["swatches"]:
            image = tk.PhotoImage(width=16, height=16)
            image.put(color, to=(0, 0, 16, 16))
            self.state["swatches"][color] = image
        return self.state["swatches"][color]

    def photo_from_png(self, png):
        """PNG bytes as a Tk PhotoImage, or None for no bytes.

        Tk's PhotoImage takes in-memory picture data as base64 text, so no temporary file is needed.
        The caller must keep the image (in state["photos"]) for as long as it is shown."""
        if png == b"":
            return None
        return tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))

    # --- Menu -------------------------------------------------------------------------------------
    def build_menu(self):
        """The File and Help menus."""
        menu = tk.Menu(self.window)
        self.file_menu = tk.Menu(menu, tearoff=0)
        help_menu = tk.Menu(menu, tearoff=0)
        self.file_menu.add_command(label="Make from a list…", command=self.make_from_list)
        self.file_menu.add_command(label="Import scans…", command=self.import_scans_file)
        self.file_menu.add_command(label="Import votes from Color Voats…", command=self.import_votes)
        self.file_menu.add_command(label="Export local redirect pages…", command=lambda: self.export_pages("local"))
        self.file_menu.add_command(label="Export nonlocal redirect pages…",
                                   command=lambda: self.export_pages("nonlocal"))
        self.file_menu.add_command(label="Publish nonlocal pages…", command=self.publish_pages)
        self.file_menu.add_command(label="Serve local pages", command=self.serve_pages)
        # remembered so serve_pages can relabel this entry Serve / Stop serving
        self.state["serve_index"] = self.file_menu.index("end")
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Back up the registry…", command=self.back_up)
        self.file_menu.add_command(label="Export the registry (CSV or JSON)…", command=self.export_table)
        self.file_menu.add_command(label="Audit log…", command=lambda: self.show_audit())
        self.file_menu.add_command(label="Open settings.json", command=self.open_settings)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.window.destroy)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="File", menu=self.file_menu)
        menu.add_cascade(label="Help", menu=help_menu)
        self.window.config(menu=menu)

    def import_votes(self):
        """Import Good and Bad votes from Color Voats' social.json, then rank the board again.

        Uses Color Voats' usual file when it is there, else asks for one. Writes the registry's votes."""
        path = color_voats_path()
        if not os.path.isfile(path):
            path = filedialog.askopenfilename(title="Color Voats' social.json", filetypes=[("JSON", "*.json")])
            if not path:
                return
        brought = import_color_voats(self.db_path, path)
        if brought["ok"]:
            self.status.set("Imported " + str(brought["value"]) + " vote(s) from Color Voats")
            self.redraw_board()
        else:
            messagebox.showerror("Import votes", brought["error"])

    def show_about(self):
        """Help → About: the version, what the program does, the icon's credit and the license."""
        messagebox.showinfo("About " + APP_NAME, APP_NAME + " " + __version__ + "\n\n"
                            "Makes QR codes in recommended colors, reads them from pictures, and finds any code "
                            "again by its link or its color, with the path of its picture. Other programs can ask "
                            "through the Environment Context Protocol (ECP), with a local model only.\n\n" +
                            ICON_CREDIT + "\n\nCopyright (c) 2026 kjFriday. AGPL-3.0-only.")

    def open_settings(self):
        """Open settings.json in its usual editor (Notepad when none is set), writing it first if missing.

        Away from Windows, or when it still cannot be written, its path is shown instead. Changes are
        read at the next start only."""
        if self.config["state"] == "missing":
            settings.write_defaults(self.config)
        if os.name != "nt" or not os.path.isfile(self.config["path"]):
            messagebox.showinfo("Settings", "The settings are in\n\n" + self.config["path"])
            return
        try:
            os.startfile(self.config["path"])
        except OSError:
            subprocess.Popen(["notepad", self.config["path"]])
        self.status.set("Settings take effect the next time QR Palette starts")

    def export_pages(self, section):
        """Write the redirect pages of `section` ("local" or "nonlocal") to a folder, as a job.

        The folder offered is the last one used this session, else links.json's export_folder, else
        the home folder. Short links on other addresses are left out and counted."""
        start = (self.state["export_folders"].get(section) or app_settings.LINKS[section]["export_folder"] or
                 os.path.expanduser("~"))
        folder = filedialog.askdirectory(title="Export the " + section + " redirect pages to", initialdir=start,
                                         mustexist=False)
        if not folder:
            return
        folder = registry.display_path(folder)

        # on the window's thread when the export ends
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Export redirect pages", outcome["error"])
                return
            self.state["export_folders"][section] = folder
            message = "Wrote " + str(outcome["value"]["written"]) + " " + section + " redirect page(s) to " + folder
            if len(outcome["value"]["skipped"]) > 0:
                message = (message + "; " + str(len(outcome["value"]["skipped"])) +
                           " short link(s) on other addresses were left out")
            if section == "local":
                message = message + ". Serve the folder from this computer to try them (README.md shows how)."
            else:
                message = (message + ". Publish the folder at " +
                           shortlinks.host_of(app_settings.LINKS[section]["base"]) + ".")
            self.status.set(message)

        self.start_job("Exporting redirect pages", lambda: export_redirects(self.db_path, folder, section), done)

    def serve_pages(self):
        """Start or stop serving the local pages from this computer, so local short links work now.

        Steps:
          1. When serving, stop the server and relabel the menu entry.
          2. Check the local base address (shortlinks.serve_address); an address on the network, not
             only this computer, is served only when the person agrees.
          3. Export the local pages to their folder as a job, then start the server on them."""
        if self.state["server"] is not None:
            shortlinks.stop_server(self.state["server"])
            self.state["server"] = None
            self.file_menu.entryconfig(self.state["serve_index"], label="Serve local pages")
            self.status.set("Stopped serving the local pages")
            self.refresh_footer()
            return
        base = app_settings.LINKS["local"]["base"]
        network = False
        where = shortlinks.serve_address(base, False)
        if not where["ok"]:
            if "network" not in where["error"]:
                messagebox.showerror("Serve local pages", where["error"])
                return
            if not messagebox.askyesno("Serve local pages", "The local base " + base + " is an address on your "
                                       "network. While the pages are served, phones and computers on your network can "
                                       "open them (Windows may ask to let Python through its firewall). Serve them?"):
                return
            network = True
        folder = local_pages_folder()

        # on the window's thread once the pages are written: start the server
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Serve local pages", outcome["error"])
                return
            started = shortlinks.start_server(folder, base, network)
            if not started["ok"]:
                messagebox.showerror("Serve local pages", started["error"])
                return
            self.state["server"] = started["value"]
            self.file_menu.entryconfig(self.state["serve_index"], label="Stop serving local pages")
            self.status.set("Serving " + str(outcome["value"]["written"]) + " local page(s) at " + base + " from " +
                            folder + "; they follow your changes until you stop")
            self.refresh_footer()

        self.start_job("Exporting the local pages", lambda: export_redirects(self.db_path, folder, "local"), done)

    def refresh_served(self):
        """While the local pages are served, write them again after a change, so they stay current."""
        if self.state["server"] is None:
            return
        folder = self.state["server"]["folder"]
        self.start_job("Updating the local pages", lambda: export_redirects(self.db_path, folder, "local"),
                       lambda outcome: None)

    def back_up(self):
        """Back the registry up to a file chosen by the person, as a job (registry.backup checks the copy).

        The local key is not part of the backup; the status line says so when there is one, since
        masked codes and ID tags need it (localkey.py)."""
        suggested = default_backup_path()
        try:
            os.makedirs(os.path.dirname(suggested), exist_ok=True)
        except OSError:
            pass
        target = filedialog.asksaveasfilename(title="Back up the registry", initialdir=os.path.dirname(suggested),
                                              initialfile=os.path.basename(suggested), defaultextension=".db",
                                              filetypes=[("Registry backup", "*.db")])
        if not target:
            return
        target = registry.display_path(target)

        # on the window's thread when the backup ends
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Back up the registry", outcome["error"])
                return
            note = ""
            if os.path.isfile(localkey.key_path(self.db_path)):
                note = "  ·  qr_palette.key is not in it: keep a copy of that too, away from the backup"
            self.status.set("Backed up the registry to " + outcome["value"] + " (checked)" + note)

        self.start_job("Backing up the registry", lambda: registry.backup(self.db_path, target), done)

    def export_table(self):
        """Export the registry as CSV (one row per code) or JSON (everything), as a job.

        The format follows the file name's extension (registry_export.export_registry)."""
        path = filedialog.asksaveasfilename(title="Export the registry", initialfile="qr-palette.csv",
                                            defaultextension=".csv",
                                            filetypes=[("CSV, one row per code (spreadsheets)", "*.csv"),
                                                       ("JSON, everything", "*.json")])
        if not path:
            return
        path = registry.display_path(path)

        # on the window's thread when the export ends
        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Export the registry", outcome["error"])
                return
            self.status.set("Exported " + str(outcome["value"]["codes"]) + " code(s) and " +
                            str(outcome["value"]["short_links"]) + " short link(s) to " + outcome["value"]["path"])

        self.start_job("Exporting the registry", lambda: export_registry(self.db_path, path), done)

    def publish_pages(self):
        """Publish the nonlocal pages: first what would change, with nothing touched; then, if the person
        says so, write them, and for a Git folder commit and push.

        Two jobs in a row: publish_plan (a dry run listing pages to add, change and remove, up to five
        of each shown) and, after a yes, publish_now. A push that fails leaves the commit in place and
        says so. Side effects of the second job: files in the publish folder, a Git commit and push."""
        target = app_settings.LINKS["nonlocal"]["publish"]
        if target["kind"] == "":
            messagebox.showinfo("Publish nonlocal pages", "Say where to publish first: nonlocal.publish in links.json. "
                                "Its kind is git (a folder in a Git repository, such as one GitHub Pages serves) or "
                                "folder (a folder something else syncs), and its folder is where. README.md shows how.")
            return

        # after the dry run: show what would change and ask before publishing
        def planned(outcome):
            if not outcome["ok"]:
                self.status.set("Nothing published")
                messagebox.showerror("Publish nonlocal pages", outcome["error"])
                return
            value = outcome["value"]
            total = len(value["added"]) + len(value["changed"]) + len(value["removed"])
            if total == 0:
                self.status.set("Nothing to publish: " + target["folder"] + " already has these pages")
                return
            lines = [str(len(value["added"])) + " page(s) to add, " + str(len(value["changed"])) + " to change, " +
                     str(len(value["removed"])) + " to remove, in\n" + target["folder"]]
            for word, paths in (("add", value["added"]), ("change", value["changed"]), ("remove", value["removed"])):
                for path in paths[:5]:
                    lines.append(word + "  " + path)
            if total > 15:
                lines.append("…")
            if len(value["skipped"]) > 0:
                lines.append(str(len(value["skipped"])) + " short link(s) on other addresses are left out.")
            ask = "Write these pages there?"
            if target["kind"] == "git":
                ask = "Commit them and push the branch? (Never forced.)"
            if not messagebox.askyesno("Publish nonlocal pages", "\n".join(lines) + "\n\n" + ask):
                self.status.set("Nothing published")
                return
            self.start_job("Publishing the pages", lambda: publish_now(self.db_path), published)

        # after publishing: report the changes and, for Git, the commit and the push
        def published(outcome):
            if not outcome["ok"]:
                self.status.set("Not published")
                messagebox.showerror("Publish nonlocal pages", outcome["error"])
                return
            value = outcome["value"]
            changes = value["changes"]
            message = (str(len(changes["added"])) + " page(s) added, " + str(len(changes["changed"])) + " changed, " +
                       str(len(changes["removed"])) + " removed in " + target["folder"])
            if target["kind"] == "git":
                if value["commit"] == "":
                    message = message + "; Git saw nothing new to commit"
                elif value["pushed"]:
                    message = message + "; committed " + value["commit"] + " and pushed"
                else:
                    message = message + "; committed " + value["commit"] + " but not pushed"
                    messagebox.showerror("Publish nonlocal pages", "The pages are committed (" + value["commit"] +
                                         ") but the push failed:\n\n" + value["push_error"] +
                                         "\n\nPush that folder with your Git client.")
            self.status.set(message)

        self.start_job("Checking what would change", lambda: publish_plan(self.db_path), planned)

    def import_scans_file(self):
        """Scan counts from an analytics report or a server log. Only counts are kept.

        Runs short_link_ops.import_scan_file as a job; when results are shown in the Find tab, it
        searches again so their scan columns are current."""
        path = filedialog.askopenfilename(title="An analytics report or a server log",
                                          filetypes=[("Reports and logs", "*.csv *.log *.txt *.gz"),
                                                     ("All files", "*.*")])
        if not path:
            return
        path = registry.display_path(path)

        # on the window's thread when the import ends
        def done(outcome):
            if not outcome["ok"]:
                self.status.set("No scans imported")
                messagebox.showerror("Import scans", outcome["error"])
                return
            value = outcome["value"]
            message = ("Imported " + str(value["scans"]) + " scan(s) on " + str(value["days"]) + " code-day(s) from " +
                       os.path.basename(path) + " (" + value["source"] + ")")
            if value["ignored"] > 0:
                message = message + "; " + str(value["ignored"]) + " other line(s) ignored"
            if len(value["unknown"]) > 0:
                message = message + "; " + str(len(value["unknown"])) + " ID(s) are not short links here"
            if len(self.state["results"]) > 0:
                self.run_search(message)
            else:
                self.status.set(message)

        self.start_job("Importing scans", lambda: import_scan_file(self.db_path, path), done)

    # --- Smoke run (--smoke) --------------------------------------------------------------------
    def write_smoke_report(self):
        """--smoke: use the built window once, write a JSON report to smoke_path and close the window.

        Runs on the window's thread, without jobs, 800 ms after start. Steps:
          1. Record the app id, version, title, icon, tab names and how many tiles the board drew.
          2. Pick the best color, preview a test link, and make and register a code for it in a
             temporary folder (codec_ok says whether it was read back).
          3. Search by that color and count the registry's records.
          4. When an inference endpoint is set, list its models.
          5. Remove the temporary folder, write the report and close the window.

        The registry is the scratch one --smoke was given; the report's keys are what the smoke test
        checks."""
        report = {"app_id": APP_ID, "version": __version__, "title": self.window.title(), "icon_set": self.icon_set,
                  "tabs": [], "tiles": len(self.tiles.find_all()), "records": 0, "codec_ok": False,
                  "found_by_color": 0, "inference": {"reachable": False, "models": 0}}
        for tab_id in self.tabs.tabs():
            report["tabs"].append(self.tabs.tab(tab_id, "text"))
        work_folder = tempfile.mkdtemp(prefix="qr_palette_smoke_")
        try:
            self.state["picked"] = self.state["order"][0]
            self.link_text.set("https://example.com/smoke")
            self.refresh_preview()
            made = make_qr(self.db_path, self.link_text.get(), self.state["picked"], "M",
                           os.path.join(work_folder, "smoke.png"), 4)
            report["codec_ok"] = made["ok"]
            found = search(self.db_path, "color", self.state["picked"], False, 20)
            if found["ok"]:
                report["found_by_color"] = len(found["value"])

            # count the registry's records on the open connection
            def read(connection):
                return ok_result(registry.counts(connection)["records"])

            counted = with_registry(self.db_path, read)
            if counted["ok"]:
                report["records"] = counted["value"]
            if self.engine["endpoint"] is not None:
                listed = local_inference.list_models(self.engine["endpoint"], local_inference.LIST_TIMEOUT, "")
                report["inference"]["reachable"] = listed["ok"]
                if listed["ok"]:
                    report["inference"]["models"] = len(listed["value"])
        finally:
            shutil.rmtree(work_folder, ignore_errors=True)
        handle = open(self.smoke_path, "w", encoding="utf-8")
        json.dump(report, handle, indent=2)
        handle.close()
        self.window.destroy()


def run_gui(db_path, engine, smoke_path, config, warnings):
    """The window. `config` is the Settings record (settings.json); the window saves the preset, the
    model and the picture folder into it as they change, and nothing else. Its Ask box uses the same
    ECP engine as the MCP server, so it is planned, grounded and audited the same way."""
    return PaletteWindow(db_path, engine, smoke_path, config, warnings).run()

# ==== stamp v1 | author=kjFriday | hmac-sha256=9c5020ca3daff493dcc065802bcb283f60185f63c2fd6004bf6539a4452b8b31 ====
