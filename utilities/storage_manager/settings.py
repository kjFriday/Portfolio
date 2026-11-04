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
"""

import json
import os

from records import error_text, failure, success


def default_settings():
    return {"shares": [], "last_folder": "", "recent": [], "stale_days": 365, "geometry": ""}


def load_settings(path):
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
    for key in settings.keys():
        if key in data and type(data[key]) == type(settings[key]):
            settings[key] = data[key]
    return settings


def save_settings(path, settings):
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=faaa3614db759535b7c42550b7ead284c162cb3d676f6b4dc9f146ea5cd12b3d ====
