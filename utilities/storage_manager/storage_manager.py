# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: storage_manager.py
# About: Generic Company Storage Manager: entry point, name, version and command line.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Generic Company Storage Manager: entry point, name, version and command line.

The program organizes and cleans local drives, and handles network shares.
Python 3 standard library only. This file starts the program: it holds the program's name, id, icon
and version, where its settings live, and the command line. The modules beside it do the work:

  the core: plain functions over plain records, which never touch the GUI
    records.py        the Result record, cancelling, progress, and the keys of every record
    paths.py          path tests, the names given to things on disk, which names are one file
    scanning.py       walk_tree reads a folder tree once; the ScanReport sums it up
    duplicates.py     identical files, compared step by step, and the copy to keep
    moves.py          moves to the trash: planning them, carrying them out, undo
    space_map.py      the space map: folder tree, sunburst layout, colours
    organize.py       sorting a folder's files into subfolders by type or date
    backup.py         one-way backup to another folder or a share
    shares.py         network shares: check, map, disconnect
    desktop.py        drives, the system file manager, starting programs, typed folders
    settings.py       the settings record and its file
    formatting.py     sizes, counts, dates and plurals in words
  windows_calls.py    the two Windows calls the walk makes (the only ones that need ctypes)
  selftest.py         the built-in checks (--selftest)
  gui.py              the window (tkinter); it only calls the core
  gui_views.py        the window's views, one build function each

Written to be easy to port to another language:
  * Plain functions and plain records (dicts with fixed keys, listed in records.py).
  * Explicit loops; no decorators, generators, comprehension chains or dynamic attributes.
  * The core never touches the GUI. Port it first, then rewrite gui.py in any toolkit.
  * Core functions report failure with a Result record instead of raising across layers.

Speed
  * Folders are read once with os.scandir, which returns sizes, times and (on Windows) file
    attributes with the listing, without opening each file. Empty folders are found in the same pass.
  * Space on disk costs nothing more where the listing says it: cloud-only files take 0, and on
    macOS and Linux the listing's stat has the allocated blocks and the link count. Only compressed
    and sparse files on a local Windows drive cost one call each (GetCompressedFileSizeW, on
    HASH_WORKERS threads); on a network share they count at their size, as a call per file would be
    a round trip to the server.
  * Duplicates are narrowed step by step (size, then both ends of large files, then a full
    SHA-256) and files are read on HASH_WORKERS threads at once. Which names are one file (hard links)
    is read from the handle opened for the ends of a large file, and looked up only for files whose
    whole contents matched: not for every file of the same size.
  * A backup lists source and target once and compares them in memory.

Usage
  python storage_manager.py              open the window
  python storage_manager.py --selftest   run the built-in checks and exit
  python storage_manager.py --version
  python storage_manager.py --smoke FILE open the window, write a JSON report to FILE, close
  python storage_manager.py --folder PATH [--view KEY]
                                         analyze PATH straight away (KEY: a sidebar entry, e.g. duplicates or map)

Main flow: run as a script, the bottom block sets up the import machinery and calls main, which
handles --version and --selftest itself and hands everything else to gui.run_gui. main's return
value is the exit code: 0 ok, 1 a self-test check failed, 2 an option without its value.
"""

import os
import sys

# The program's identity: version (shown by --version and About), display name, the id the settings
# folder and the Windows taskbar grouping are named after, the window icon and its licence credit.
__version__ = "0.4.0"
APP_NAME = "Generic Company Storage Manager"
APP_ID = "GenericCompany.Storage"
ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "app.ico")
ICON_CREDIT = ("Icon: drive_network.png from the Silk icon set by Mark James (famfamfam.com/lab/icons/silk), "
               "CC BY 2.5 (creativecommons.org/licenses/by/2.5). Changed: enlarged by whole pixels.")


def settings_path():
    """Where the settings file lives: %LOCALAPPDATA%\\Generic Company Inc\\<APP_ID>\\settings.json
    on Windows, ~/.config/Generic Company Inc/<APP_ID>/settings.json where LOCALAPPDATA is not set.
    Only builds the path; settings.save_settings creates the folder."""
    base = os.environ.get("LOCALAPPDATA", "")
    if base == "":
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Generic Company Inc", APP_ID, "settings.json")


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing."""
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    """Run the program for the command-line arguments (sys.argv without the program) -> exit code.

    Steps:
      1. --version prints the name and version; --selftest runs selftest.selftest. Both return at once.
      2. Read --smoke, --folder and --view; any of them given without a value is an error (2).
      3. Open the window with gui.run_gui and return what it returns.
    """
    # selftest.py and gui.py import from this module, so each is imported where it is needed, once this
    # module has finished loading, rather than at the top.
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        from selftest import selftest
        return selftest()
    smoke_path = option_value(arguments, "--smoke")
    start_folder = option_value(arguments, "--folder")
    start_view = option_value(arguments, "--view")
    if smoke_path is None or start_folder is None or start_view is None:
        print("--smoke, --folder and --view each need a value")
        return 2
    from gui import run_gui
    return run_gui(smoke_path, start_folder, start_view)


if __name__ == "__main__":
    # A run writes nothing beside the program: the modules it imports are compiled in memory rather
    # than cached in a __pycache__ folder here. An uninstaller removes only the files it installed, so
    # such a folder would stay behind, and setup would then refuse the folder as not empty.
    sys.dont_write_bytecode = True
    # gui.py and selftest.py import from storage_manager: let them find this copy rather than load
    # the file a second time under that name.
    sys.modules["storage_manager"] = sys.modules[__name__]
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=9e62465df474e603ba21f79134794b77d49443c983da132117f61f2071fa95d8 ====
