# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: gui/__init__.py
# About: The window (tkinter): the Make, Read and Find tabs and the menus.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The window (tkinter): the Make, Read and Find tabs and the menus. It only calls the core modules.

window.py holds PaletteWindow (its state, job queue, menus, status lines and the --smoke run) and
run_gui; make_tab.py, read_tab.py and find_tab.py hold the tabs, and dialogs.py the larger dialogs.

qr_palette.main imports this package only when it opens the window (from gui import run_gui), because
the window takes the program's name, version, icon and data folders from qr_palette.py. So --mcp,
--selftest and the tests never load tkinter.
"""

from gui.window import run_gui

# the one name the package exports: qr_palette.main calls run_gui to open the window
__all__ = ["run_gui"]

# ==== stamp v1 | author=kjFriday | hmac-sha256=df5e14b7cb71cb090891c2c2c50bcc4ae5e91584fdcebfc72eb1a908a5bce923 ====
