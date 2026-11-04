# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_history.py
# About: QR Studio's history of codes read and made, and helpers for links, saving and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's history of codes read and made, and helpers for links, saving and descriptions.

The history is a list of Entry records, newest first and at most HISTORY_LIMIT long. It is kept on this
computer only, in history.json in the data folder: LOCALAPPDATA, then Generic Company Inc, then APP_ID
(setup.json's purge names the same folder). The window reads it when it opens and saves it after every
code read or made, and when it is cleared; add_history moves a repeated code to the top instead of
listing it twice.

The helpers below the history serve the window, the command line and the self-test: is_link says which
texts may open in a browser (http and https only), save_matrix writes a code to a .png or .svg file, and
describe puts a Reading into words.

Records
  Entry    {"kind": "read" | "made", "text": str, "when": float}  when: seconds since 1970, as time.time()
"""

import json
import os

from qr_codec import fail, matrix_to_image, matrix_to_svg, ok_result, write_png

APP_ID = "GenericCompany.QRStudio"  # names the data folder; also the taskbar identity and setup.json's id
HISTORY_LIMIT = 50


# --- History -------------------------------------------------------------------------------------

def data_folder():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def history_path():
    return os.path.join(data_folder(), "history.json")


def load_history(path):
    try:
        handle = open(path, "r", encoding="utf-8")
        entries = json.load(handle)
        handle.close()
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    clean = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("kind") in ("read", "made") and isinstance(entry.get("text"), str):
            clean.append({"kind": entry["kind"], "text": entry["text"], "when": float(entry.get("when", 0))})
    return clean[:HISTORY_LIMIT]


def save_history(path, entries):
    folder = os.path.dirname(path)
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(path, "w", encoding="utf-8")
        json.dump(entries[:HISTORY_LIMIT], handle, indent=2)
        handle.close()
    except OSError as error:
        return fail(str(error))
    return ok_result(path)


def add_history(entries, kind, text, now):
    """Newest first; the same text and kind moves to the top instead of repeating."""
    result = [{"kind": kind, "text": text, "when": now}]
    for entry in entries:
        if not (entry["kind"] == kind and entry["text"] == text):
            result.append(entry)
    return result[:HISTORY_LIMIT]


# --- Links, saving and descriptions --------------------------------------------------------------

def is_link(text):
    lowered = text.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def save_matrix(matrix, path, scale):
    """Write a .png or .svg file -> Result path."""
    try:
        if path.lower().endswith(".svg"):
            handle = open(path, "w", encoding="utf-8")
            handle.write(matrix_to_svg(matrix, 4))
        else:
            handle = open(path, "wb")
            handle.write(write_png(matrix_to_image(matrix, scale, 4)))
        handle.close()
    except OSError as error:
        return fail(str(error))
    return ok_result(path)


def describe(reading):
    return ("version " + str(reading["version"]) + ", level " + reading["level"] + ", mask " +
            str(reading["mask"]) + ", " + str(reading["corrected"]) + " codeword(s) corrected")

# ==== stamp v1 | author=kjFriday | hmac-sha256=e4a04f6880fc76eb89e3a28c85379b58cedea1549fb17b972830deeb4b6b8b81 ====
