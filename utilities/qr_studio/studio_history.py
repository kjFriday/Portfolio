# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_history.py
# About: QR Studio's history of codes read and made, and helpers for links, saving and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's history of codes read and made, plus link, save and description helpers.

The history is a list of Entry records, newest first and at most HISTORY_LIMIT long. It is kept on this
computer only, in history.json in the data folder: LOCALAPPDATA, then Generic Company Inc, then APP_ID
(setup.json's purge names the same folder). The window reads it when it opens and saves it after every
code read or made, and when it is cleared; add_history moves a repeated code to the top instead of
listing it twice.

The helpers below the history serve the window, the command line and the self-test: is_link says which
texts may open in a browser (http and https only), save_matrix writes a code to a .png or .svg file, and
describe puts a Reading into words.

Who calls it: studio_gui.StudioWindow (all of it), qr_studio.py (save_matrix for --make) and
studio_selftest.py (add_history, is_link). It calls only the codec's records and picture writers.

Life of the history:
  1. history_path() names history.json under data_folder().
  2. load_history reads it when the window opens; a missing or broken file gives an empty list.
  3. add_history returns a new list with the code on top after every read, save or copy.
  4. save_history writes the list back (and creates the folder the first time).

Records
  Entry    {"kind": "read" | "made", "text": str, "when": float}  when: seconds since 1970, as time.time()
"""

import json
import os

from qr_codec import fail, matrix_to_image, matrix_to_svg, ok_result, write_png

APP_ID = "GenericCompany.QRStudio"  # names the data folder; also the taskbar identity and setup.json's id
HISTORY_LIMIT = 50  # entries kept; older ones fall off the end on every load, add and save


# --- History -------------------------------------------------------------------------------------

def data_folder():
    """Return the folder that holds history.json; it may not exist yet.

    LOCALAPPDATA is set on Windows; elsewhere the home folder stands in, so the tests run anywhere.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def history_path():
    """Return the full path of history.json in data_folder()."""
    return os.path.join(data_folder(), "history.json")


def load_history(path):
    """Read the history file at `path` -> [Entry], newest first, at most HISTORY_LIMIT.

    Never fails: a missing, unreadable or non-JSON file, or one that is not a list, gives []. Each
    entry is checked on its own, so one hand-edited bad entry is dropped and the rest are kept.

    Steps:
      1. Read and parse the JSON.
      2. Keep only dicts whose kind is "read" or "made" and whose text is a string.
      3. Rebuild each as a fresh Entry; a missing "when" becomes 0.0 (shown as 1970).
      4. Cut the list to HISTORY_LIMIT.

    Known limitation: a "when" that float() cannot read (a word, a list) raises ValueError or
    TypeError from step 3, outside the try, instead of dropping that entry.
    """
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
    """Write the first HISTORY_LIMIT `entries` to `path` as indented JSON -> Result path.

    Side effects: creates the folder when missing and overwrites the file. Fails with the OS error
    text. The window ignores the Result: a history that cannot be saved is not worth a dialog.
    Known limitation: the file is written in place, so a crash mid-write leaves broken JSON, which
    load_history then reads as an empty history.
    """
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
    """Return a new history with (`kind`, `text`) on top, stamped `now` (seconds since 1970).

    Newest first; the same text and kind moves to the top instead of repeating. The same text with
    the other kind stays, so a code both read and made shows twice. `entries` is not changed.
    """
    result = [{"kind": kind, "text": text, "when": now}]
    for entry in entries:
        if not (entry["kind"] == kind and entry["text"] == text):
            result.append(entry)
    return result[:HISTORY_LIMIT]


# --- Links, saving and descriptions --------------------------------------------------------------

def is_link(text):
    """Return True when `text`, trimmed, starts with http:// or https:// (any letter case).

    Only these open in a browser: a code could hold file:, javascript: or a program's own scheme,
    and opening those on a scan would run whatever the code's maker chose.
    """
    lowered = text.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def save_matrix(matrix, path, scale):
    """Write `matrix` to a .png or .svg file at `path` -> Result path.

    A name ending in .svg (any case) gets an SVG drawing; any other name gets a PNG with `scale`
    pixels per module. Both have the 4-module quiet zone ISO/IEC 18004 asks for round a code. The SVG
    ignores `scale`: its viewBox is in module units, so it scales freely. Fails with the OS error text.
    """
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
    """Return one line about a Reading, as "version 2, level M, mask 5, 0 codeword(s) corrected".

    "corrected" counts codewords that Reed-Solomon fixed across all blocks: a hint at how worn the code is.
    """
    return ("version " + str(reading["version"]) + ", level " + reading["level"] + ", mask " +
            str(reading["mask"]) + ", " + str(reading["corrected"]) + " codeword(s) corrected")

# ==== stamp v1 | author=kjFriday | hmac-sha256=e4a04f6880fc76eb89e3a28c85379b58cedea1549fb17b972830deeb4b6b8b81 ====
