# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: organize.py
# About: Storage Manager core: sort the files directly in a folder into subfolders by type or date.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: sort the files directly in a folder into subfolders by type or date.

TYPE_FOLDERS also names the types in the scan report's summary (see summarize_types in scanning.py).

Who calls it: gui.py's Organize view runs plan_organize on a worker thread for the preview, then hands
the Moves to apply_moves in moves.py (which also makes them undoable). scanning.py uses type_folder_for.

Flow of plan_organize
  1. List the folder once; keep plain files only (no folders, no links followed, not the undo log).
  2. Sort them by name so the plan, and the " (2)" numbering, is the same on every run.
  3. Pick each file's subfolder: its type (TYPE_FOLDERS) or its month ("YYYY-MM" of the modified time).
  4. Give each target a free name (unique_target) and return the list of Moves; nothing moves here.
"""

import os
import time

from paths import UNDO_LOG_NAME
from records import error_text, failure, is_cancelled, success

# Extension (lower case, with dot) -> folder name used by organize and the type summary.
TYPE_FOLDERS = {
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images", ".bmp": "Images",
    ".webp": "Images", ".svg": "Images", ".heic": "Images", ".tif": "Images", ".tiff": "Images",
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents", ".txt": "Documents",
    ".md": "Documents", ".rtf": "Documents", ".odt": "Documents", ".xls": "Documents",
    ".xlsx": "Documents", ".csv": "Documents", ".ppt": "Documents", ".pptx": "Documents",
    ".mp4": "Video", ".mkv": "Video", ".avi": "Video", ".mov": "Video", ".wmv": "Video", ".webm": "Video",
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio", ".ogg": "Audio", ".m4a": "Audio",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".exe": "Programs", ".msi": "Programs", ".bat": "Programs", ".ps1": "Programs",
    ".py": "Code", ".js": "Code", ".go": "Code", ".rs": "Code", ".c": "Code", ".cpp": "Code",
    ".h": "Code", ".java": "Code", ".cs": "Code", ".html": "Code", ".css": "Code", ".json": "Code",
}
# Folder for any extension not listed above, including files with none.
OTHER_FOLDER = "Other"


def type_folder_for(path):
    """The type folder name for path's extension (case ignored), or OTHER_FOLDER when it is not listed."""
    extension = os.path.splitext(path)[1].lower()
    if extension in TYPE_FOLDERS:
        return TYPE_FOLDERS[extension]
    return OTHER_FOLDER


def date_folder_for(modified):
    """The month folder name "YYYY-MM" for a modified time (seconds since the epoch), in local time."""
    return time.strftime("%Y-%m", time.localtime(modified))


def entry_name(item):
    """Sort key for plan_organize's items: the file name."""
    return item["name"]


def plan_organize(root, mode, cancel_flag):
    """Moves that sort the files directly inside root into subfolders.

    mode is "type" or "date". Only top-level files move, so running it twice does nothing new.
    cancel_flag (see is_cancelled) stops the planning with failure("cancelled"). Reads the folder only.
    -> Result(list of Move); failure when root is not a folder, the mode is unknown or the listing fails.
    """
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    if mode != "type" and mode != "date":
        return failure("unknown mode: " + mode)
    try:
        iterator = os.scandir(root)
    except OSError as e:
        return failure(error_text(e))
    items = []
    try:
        for entry in iterator:
            if entry.name == UNDO_LOG_NAME:
                continue
            # a file that vanishes or cannot be read between listing and stat is left where it is
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                modified = entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            items.append({"name": entry.name, "path": entry.path, "modified": modified})
    finally:
        iterator.close()
    items.sort(key=entry_name)
    moves = []
    taken = {}
    for item in items:
        if is_cancelled(cancel_flag):
            return failure("cancelled")
        if mode == "type":
            folder = type_folder_for(item["path"])
        else:
            folder = date_folder_for(item["modified"])
        target = unique_target(os.path.join(root, folder, item["name"]), taken)
        # lower case, because Windows treats names that differ only in case as the same file
        taken[target.lower()] = True
        moves.append({"source": item["path"], "target": target})
    return success(moves)


def unique_target(target, taken):
    """target, or target with " (2)", " (3)"... when the name is already used.

    Used means it exists on disk or is a key of taken, the lower-case targets already planned in this
    run. The number goes before the extension ("a.txt" -> "a (2).txt"), as Windows Explorer does.
    """
    if not os.path.exists(target) and target.lower() not in taken:
        return target
    stem, extension = os.path.splitext(target)
    number = 2
    while True:
        candidate = stem + " (" + str(number) + ")" + extension
        if not os.path.exists(candidate) and candidate.lower() not in taken:
            return candidate
        number = number + 1

# ==== stamp v1 | author=kjFriday | hmac-sha256=a4a254ea7bb47e93fd3f3ca52dfcf31e79e5ceceb25ca8aec1096fe6087e729e ====
