# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: records.py
# About: Storage Manager core: Result records, cancelling, progress, and the keys of every record.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: Result records, cancelling, progress, and the keys of every record.

Core functions report failure with a Result instead of raising across layers, can be stopped through a
cancel_flag (a list holding one bool, set from another thread) and report progress through a plain
callback. Every record the core passes around is a dict with fixed keys:

Records
  Result     {"ok": bool, "error": str, "value": any}
  FileInfo   {"path": str, "size": int, "disk": int, "modified": float, "link": str or None}
              size: the file's size; disk: the space it takes on disk (see disk_from_listing), 0 for a
              second name of a hard-linked file counted under another name; link: "volume:file id" for
              a file with more than one name (hard links), "" for a file with one, None when not known
              (a Windows folder listing does not say; find_duplicates_in reads it where it matters)
  Hashed     {"digest": str, "link": str or None}       link: as in FileInfo, None when not read
  Walk       {"files": [FileInfo], "trash": [FileInfo], "empty_dirs": [str], "errors": [str],
              "dir_count": int, "links_checked": bool}
              trash: files in our trash folders; links_checked: the listing told which names are one file
  ScanReport {"root": str, "file_count": int, "dir_count": int, "total_bytes": int, "file_bytes": int,
              "saved": {"compressed": int, "no_data": int, "links": int}, "trash": [FileInfo],
              "trash_bytes": int, "links_checked": bool,
              "drive_free": int, "drive_total": int, "by_type": {name: {"files": int, "bytes": int}},
              "largest": [FileInfo], "stale": [FileInfo], "empty_dirs": [str], "errors": [str],
              "files": [FileInfo]}
              Bytes are space on disk (total_bytes, by_type, trash_bytes); file_bytes adds up the file
              sizes, and saved says where the two differ (see disk_summary)
  Duplicates {"groups": [[FileInfo]], "linked": [FileInfo]}
              linked: names found to be hard links while comparing (a Windows listing does not say),
              with their link; all but the first name of each file take no space (disk 0)
  Move       {"source": str, "target": str}             target "" removes an empty folder
  Copy       {"source": str, "target": str, "size": int}
  Share      {"name": str, "unc": str, "letter": str}
  ShareState {"reachable": bool, "total": int, "used": int, "free": int, "error": str}
  Node       {"name": str, "path": str, "kind": "folder"|"trash", "bytes": int, "files": int, "trash": int,
              "wasted": int, "children": {name: Node}, "file_list": [FileInfo], "folder_list": [Node],
              "item_files": int, "wasted_paths": {path: int}}
              bytes: space on disk; trash: the part of it in trash folders; a "trash" Node is one of our
              trash folders, shown as one slice (no children, no file_list); file_list: files directly in
              it that take space, folder_list: subfolders that take space, both biggest first; item_files:
              files in those slices (files taking no space directly in it are not); wasted_paths: the
              extra duplicate copies directly in it and the bytes each would free
  Arc        {"path": str, "name": str, "kind": "folder"|"file"|"trash"|"rest", "depth": int, "start": float,
              "extent": float, "bytes": int, "size": int, "files": int, "wasted": int, "trash": int,
              "branch": int, "modified": float}
              bytes: space on disk; size: a file's size (0 for the other kinds)

Who uses it: every core module (scanning, duplicates, moves, organize, backup, shares, settings, desktop,
windows_calls) builds its Results here; gui.py reads them and owns the cancel flags and the progress
callback. It imports nothing.

Progress
  Long functions take progress(text, done, total, unit), or None. unit is "files", "bytes" or
  "items"; total 0 means not known yet. It is called from the worker thread.
"""


def make_result(ok, value, error):
    """Build a Result record: ok says whether it worked, value is the payload, error the message.

    Callers use success or failure; this is the one place the Result keys are spelled out.
    """
    return {"ok": ok, "value": value, "error": error}


def success(value):
    """A Result that worked and carries value, with an empty error."""
    return make_result(True, value, "")


def failure(error):
    """A Result that failed with the message error (shown to the user as is) and no value."""
    return make_result(False, None, error)


def is_cancelled(cancel_flag):
    """cancel_flag is a list holding one bool, so a worker can be stopped from another thread."""
    if cancel_flag is None:
        return False
    return cancel_flag[0]


def report_progress(progress, text, done, total, unit):
    """Call the progress callback with (text, done, total, unit) when there is one; None skips it.

    Runs on the worker thread like its caller; the GUI's callback only posts the values to its queue.
    """
    if progress is not None:
        progress(text, done, total, unit)


def error_text(error):
    """The OS message for an OSError, without the path Python appends (callers add the path)."""
    if error.strerror:
        return error.strerror
    return str(error)

# ==== stamp v1 | author=kjFriday | hmac-sha256=3cfef2fbc9eccd9b0851b123514e820441373cb220f276111575b224cae3f79b ====
