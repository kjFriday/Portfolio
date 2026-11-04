# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_palette.py
# About: Generic Company QR Palette: QR codes in recommended colors, a registry of where each one...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Generic Company QR Palette: QR codes in recommended colors, a registry of them, and ECP.

Make a QR code for a link in one of the colors that Color Voats' rankers recommend, read QR codes from
pictures, and find any code again by its link or by its color: every answer gives the color, the link
and the path of the picture file. The registry is a relational SQLite database of this program's
own. Other programs ask it through the Environment Context Protocol (ECP, see ECP.md): an MCP server
on stdin/stdout (--mcp, or --ecp, the same) with three tools. A local model is chosen first, and
inference never leaves this computer.

A code can hold a short link instead of its destination (shortlinks.py): a short address with the
address printed under the code, whose destination can change later without reprinting. Short links
come in two sections, switched in the Make tab: local (this computer or your own network, for
trying codes) and nonlocal (your internet address, for printing). The window exports each
section's redirect pages for a web server to serve.

A code can also hold a Wi-Fi network, a contact card, a calendar event and more (payloads.py), with a
logo in its middle. Whole print runs come from a list; label sheets and posters come from sheets.py. The
registry keeps each short link's history, scheduled changes and scan counts (scans.py), publish.py puts
the redirect pages where a web host serves them, and tag digits under a local key (localkey.py) tell
your printed codes from others.

Everything a user may change is plain, human-readable JSON: settings.json (in the program's data
folder, written with every setting and its default on the first run), presets/ and weights/ (how
colors are ranked), planner.json (how questions become query plans), links.json (short links) and
sheets.json (print sheets). The options below override settings.json for one run.

This file starts the program: its name, id, icon and version, where it keeps its files, the ECP engine
for a run, and the command line. The modules beside it do the work:

  the core: plain functions over plain records, which never touch the GUI
    app_settings.py     the settings in force: apply_settings puts settings.json's values in place
    common.py           the Result record and with_registry, which the core shares
    making.py           making a code, drawing it again, registering a picture; previews, robustness
    short_link_ops.py   short links: the one a code prints, changes and history, scans, pages, publishing
    batches.py          a whole print run from a list, with a report
    registry_export.py  the registry as CSV or JSON
    votes.py            votes, and the ranked board of colors
    finding.py          finding codes again, by QR code or by color
    print_advice.py     how big to print a code
  what the core builds on: qr_codec/ (the codec), swatch.py, ranking.py and algos.py (colors), registry.py,
    shortlinks.py, payloads.py, sheets.py, scans.py, publish.py, localkey.py, settings.py and textsafe.py
  ECP: ecp.py, mcp_server.py, local_inference.py and audit.py (see ECP.md)
  selftest.py           the built-in checks (--selftest)
  gui/                  the window (tkinter); it only calls the core: window.py (PaletteWindow, with its
                        state, jobs and menus), make_tab.py, read_tab.py, find_tab.py and dialogs.py

Standard library only, written to port easily like QR Studio and Color Voats: plain functions and
records, explicit loops, failures as Result records, and a core that never touches the GUI.

Usage
  python qr_palette.py                       open the window
  python qr_palette.py --settings FILE       use FILE instead of settings.json in the data folder
  python qr_palette.py --db FILE             use FILE as the registry
  python qr_palette.py --mcp [--model NAME]  serve ECP's three MCP tools on stdin/stdout; NAME is the default
                                             model for queries that name none (settings.json: inference.model)
  python qr_palette.py --ecp                 the same as --mcp
  python qr_palette.py --inference URL       the local Ollama server: http on 127.0.0.1, ::1 or localhost
  python qr_palette.py --inference-timeout S seconds a model may take to plan
  python qr_palette.py --export-redirects DIR [--section local|nonlocal]
                                             write a redirect page for every short link of the section in use
                                             (or the one given) into DIR, then exit
  python qr_palette.py --selftest            run the built-in checks and exit
  python qr_palette.py --version
  python qr_palette.py --smoke FILE          open the window on a scratch registry and default settings, use
                                             it, write a JSON report, close
"""

import os
import shutil
import sys
import tempfile
import time

import app_settings
import ecp
import local_inference
import mcp_server
import settings
import shortlinks
from app_settings import HERE, apply_settings
from short_link_ops import export_redirects

__version__ = "0.1.0"
# The program's identity: the window title, --version, the taskbar id (APP_ID also names the data
# folder) and the icon with its credit, shown in the About box.
APP_NAME = "Generic Company QR Palette"
APP_ID = "GenericCompany.QRPalette"
ICON_FILE = os.path.join(HERE, "icon", "app.ico")
ICON_CREDIT = "Icon: drawn for this project (a pixel QR code in tile colors), AGPL-3.0 like the code."

DB_NAME = "palette.db"  # the registry's file name, in the data folder (or a smoke run's scratch folder)
FOLDER_NAME = "QR Palette"  # the folder in Pictures where new codes are saved by default
COLOR_VOATS_ID = "GenericCompany.ColorVoats"  # Color Voats' data folder, where its votes are read


# =================================================================================================
# Where the program keeps its files, and the ECP engine for a run
# =================================================================================================

def data_folder():
    """The program's data folder: %LOCALAPPDATA%\\Generic Company Inc\\<APP_ID>.

    Falls back to the home folder when LOCALAPPDATA is not set (outside Windows). Only builds the
    path; the folder is created by whoever first writes there.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def default_db_path():
    """The registry's path when neither --db nor settings.json's registry names one."""
    return os.path.join(data_folder(), DB_NAME)


def default_settings_path():
    """settings.json in the data folder, used when --settings is not given."""
    return os.path.join(data_folder(), "settings.json")


def default_audit_path():
    """The ECP audit log (one JSON record per line) when settings.json's audit.file is empty."""
    return os.path.join(data_folder(), "audit.jsonl")


def default_backup_path():
    """A new backup file name in the data folder's backups folder, stamped with the local time.

    The time to the second keeps each backup apart, and sorts the names oldest first.
    """
    return os.path.join(data_folder(), "backups", "palette-" + time.strftime("%Y%m%d-%H%M%S") + ".db")


def local_pages_folder():
    """Where the local pages are exported to be served: links.json's local export folder, else
    "local pages" in the program's data folder."""
    return app_settings.LINKS["local"]["export_folder"] or os.path.join(data_folder(), "local pages")


def color_voats_path():
    """Where Color Voats keeps its posts and votes (read here, never written)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", COLOR_VOATS_ID, "social.json")


def pictures_folder():
    """The user's Pictures folder as Windows knows it (it may be moved, for example into OneDrive),
    else ~/Pictures.

    Steps:
    1. On Windows, describe FOLDERID_Pictures as a GUID structure.
    2. Ask the shell for that known folder (SHGetKnownFolderPath), and free the string it returns.
    3. On any failure, or elsewhere, use ~/Pictures.
    """
    if os.name == "nt":
        try:
            # imported here so the module still loads where ctypes has no Windows parts
            import ctypes
            from ctypes import wintypes

            class Guid(ctypes.Structure):
                """The Windows GUID structure: field order and sizes must match the C struct."""
                _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD), ("data3", wintypes.WORD),
                            ("data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Pictures, {33E28130-4E1E-4676-835A-98395C3BC3BB}, from KnownFolders.h
            pictures = Guid(0x33E28130, 0x4E1E, 0x4676,
                            (ctypes.c_ubyte * 8)(0x83, 0x5A, 0x98, 0x39, 0x5C, 0x3B, 0xC3, 0xBB))
            found = ctypes.c_wchar_p()
            # 0 is S_OK; flags 0 and no access token ask for the current user's folder
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(pictures), 0, None, ctypes.byref(found)) == 0:
                path = found.value
                # the shell allocates the string with CoTaskMemAlloc, so the caller must free it
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path:
                    return path
        except (AttributeError, OSError, ValueError):
            pass
    return os.path.join(os.path.expanduser("~"), "Pictures")


def default_qr_folder():
    """Pictures\\QR Palette: where the Make tab saves codes when settings.json's pictures.folder is empty."""
    return os.path.join(pictures_folder(), FOLDER_NAME)


def make_engine(db_path, inference_url, timeout, values, model):
    """The ECP engine for this run, from settings.json's values (and the command line's choices).

    db_path: the registry; inference_url: the local model server; timeout: seconds a model may take
    to plan; values: settings.json's values as loaded; model: the default model for queries that name
    none. Returns the engine record (ecp.new_engine) with the preset, audit log, short-link sections
    and scans vote filled in. Nothing is opened yet.
    """
    engine = ecp.new_engine(db_path, inference_url, timeout, __version__)
    engine["default_model"] = model
    engine["preset"] = values["colors"]["preset"]
    engine["audit_file"] = values["audit"]["file"] or default_audit_path()
    engine["links"] = app_settings.LINKS
    engine["scans_vote"] = values["colors"]["scans_vote"]
    return engine


# =================================================================================================
# CLI
# =================================================================================================

def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing.

    Only the first `name` counts. The value is taken as given, even when it starts with "--".
    """
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    """Run the program for the command line arguments (without the program name) -> exit status.

    0 when done, 1 when exporting redirect pages fails, 2 for a usage or settings error; otherwise the
    status of the self-test, the MCP server or the window. Side effects depend on the mode: printing,
    writing redirect pages, serving stdin/stdout, or opening the window. A smoke run works in a
    scratch folder that is removed at the end.

    Steps:
    1. --version and --selftest answer at once.
    2. Read every option that takes a value; a missing value is a usage error.
    3. For --smoke, make a scratch folder so the run never touches your settings, registry or audit log.
    4. Load settings.json (--settings, the scratch copy, or the data folder's) and put it in force.
    5. Choose the registry: --db, the scratch copy, settings.json's registry, then the default.
    6. --export-redirects: write the section's redirect pages and stop.
    7. Check --inference-timeout and the inference address (--inference, else settings.json).
    8. --mcp/--ecp: serve the MCP tools on stdin/stdout; otherwise open the window.
    """
    # selftest.py and gui/ import from this module, so each is imported where it is needed, once this
    # module has finished loading, rather than at the top.
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        from selftest import selftest
        return selftest()
    values = {}
    for name in ("--db", "--inference", "--inference-timeout", "--model", "--smoke", "--settings", "--export-redirects",
                 "--section"):
        value = option_value(arguments, name)
        if value is None:
            print(name + " needs a value")
            return 2
        values[name] = value
    scratch = ""
    if values["--smoke"] != "":
        scratch = tempfile.mkdtemp(prefix="qr_palette_smoke_")
    settings_path = values["--settings"]
    if settings_path == "" and scratch != "":
        settings_path = os.path.join(scratch, "settings.json")  # a smoke run never touches your settings
    if settings_path == "":
        settings_path = default_settings_path()
    config = settings.load(os.path.abspath(settings_path))
    warnings = config["warnings"] + apply_settings(config["values"])
    serving = "--ecp" in arguments or "--mcp" in arguments
    # the MCP server owns stdout for its protocol, so its warnings go to stderr; the window shows its own
    if serving:
        for warning in warnings:
            sys.stderr.write("warning: " + warning + "\n")
    db_path = values["--db"]
    if db_path == "" and scratch != "":
        db_path = os.path.join(scratch, DB_NAME)
    if db_path == "":
        db_path = config["values"]["registry"] or default_db_path()
    db_path = os.path.abspath(db_path)
    if values["--export-redirects"] != "":
        for warning in warnings:
            sys.stderr.write("warning: " + warning + "\n")
        section = values["--section"] or app_settings.LINK_SECTION
        if section not in shortlinks.SECTIONS:
            print("--section is local or nonlocal")
            return 2
        exported = export_redirects(db_path, os.path.abspath(values["--export-redirects"]), section)
        if not exported["ok"]:
            print(exported["error"])
            return 1
        print("wrote " + str(exported["value"]["written"]) + " " + section + " redirect page(s) to " +
              exported["value"]["folder"])
        if len(exported["value"]["skipped"]) > 0:
            print("skipped (another address or no longer a valid link): " + ", ".join(exported["value"]["skipped"]))
        return 0
    timeout = 0.0
    if values["--inference-timeout"] != "":
        try:
            timeout = float(values["--inference-timeout"])
        except ValueError:
            timeout = -1.0  # out of range, so the check below reports it
        # "not 0 < t <= 3600" also refuses NaN, for which every comparison is false
        if not 0 < timeout <= 3600:
            print("--inference-timeout needs a number of seconds (up to 3600)")
            return 2
    inference_url = values["--inference"]
    if inference_url != "" and not local_inference.parse_endpoint(inference_url)["ok"]:
        print(local_inference.parse_endpoint(inference_url)["error"])
        return 2
    if inference_url == "":
        inference_url = config["values"]["inference"]["url"]
        if serving and not local_inference.parse_endpoint(inference_url)["ok"]:
            print("settings: inference.url: " + local_inference.parse_endpoint(inference_url)["error"])
            return 2
    model = values["--model"] or config["values"]["inference"]["model"]
    # timeout 0.0 means "not given": the server and the window each have their own default
    if serving:
        engine = make_engine(db_path, inference_url, timeout or app_settings.PROTOCOL_TIMEOUT, config["values"], model)
        return mcp_server.serve_stdio(mcp_server.new_server(engine))
    try:
        engine = make_engine(db_path, inference_url, timeout or app_settings.WINDOW_TIMEOUT, config["values"], model)
        if scratch != "":
            engine["audit_file"] = os.path.join(scratch, "audit.jsonl")  # nor your audit log
        from gui import run_gui
        return run_gui(db_path, engine, values["--smoke"], config, warnings)
    finally:
        if scratch != "":
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    # gui/, selftest.py and registry_export.py import from qr_palette: let them find this copy rather
    # than load the file a second time under that name.
    sys.modules["qr_palette"] = sys.modules[__name__]
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=a56603c0d7e4e2e0e348519ed07a9e3ef99ebf35f94247c5014395138f3196e8 ====
