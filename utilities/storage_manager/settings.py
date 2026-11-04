# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: settings.py
# About: Storage Manager core: the settings record and its JSON file.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: the settings record and its JSON file.

Settings {"shares": [Share], "last_folder": str, "recent": [str], "stale_days": int, "geometry": str}.
A missing or unreadable file gives the defaults, and a value of the wrong type keeps its default.
Where the file lives (settings_path) is in storage_manager.py, beside the APP_ID it is named after.

Who calls it: gui.py loads the settings once at start and saves them after each change (shares,
the old-files age, recent folders, the window's size and place on close); selftest.py checks a
round trip. Only records.py is imported.
"""

import json
import os

from records import error_text, failure, success


def default_settings():
    """A new Settings record with the defaults: no shares or recent folders, old files after 365 days,
    and "" for the last folder and the window geometry (Tk's "WxH+X+Y"; "" lets the window pick)."""
    return {"shares": [], "last_folder": "", "recent": [], "stale_days": 365, "geometry": ""}


def load_settings(path):
    """The Settings stored in the JSON file at path -> dict; never fails.

    Steps:
      1. Start from default_settings.
      2. A missing, unreadable or non-JSON file, or one that is not a JSON object, gives the defaults.
      3. Copy each known key whose value has exactly the default's type; unknown keys are dropped.

    Known limitation: only the top-level type is checked, so a list item of the wrong shape (a share
    without "letter", say) is passed through as is.
    """
    settings = default_settings()
    if not os.path.isfile(path):
        return settings
    try:
        handle = open(path, "r", encoding="utf-8")
        data = json.load(handle)
        handle.close()
    except (OSError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings
    # type(...) == type(...) rather than isinstance: a JSON true is a bool, which isinstance would
    # accept as an int for stale_days
    for key in settings.keys():
        if key in data and type(data[key]) == type(settings[key]):
            settings[key] = data[key]
    return settings


def save_settings(path, settings):
    """Write settings to the JSON file at path, creating its folder -> Result(None).

    An OSError gives failure with the OS message. The file is written in place, not through a temp
    file: a write cut short leaves a file that load_settings reads as the defaults.
    """
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(path, "w", encoding="utf-8")
        json.dump(settings, handle, indent=1)
        handle.close()
    except OSError as e:
        return failure(error_text(e))
    return success(None)

# ==== stamp v1 | author=kjFriday | hmac-sha256=1f742c74c75f0d00a3d5537f480fee8fde602bc079518a1bb239d7b3d1967685 ====
