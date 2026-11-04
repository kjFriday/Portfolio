# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: backup.py
# About: Storage Manager core: one-way backup of a folder, copying only new or changed files.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: one-way backup of a folder, copying only new or changed files.

Source and target are each listed once and compared in memory, so a network share is not asked about
every file separately.

What it is for: the Network shares view's "Back up a folder" action (gui.py backup_to_share) plans
with plan_sync on one job, asks the user, then copies with apply_copies on a second job. The self-test
(selftest.py) runs both on a temp tree. It calls walk_tree (scanning.py) to list both trees,
relative_path (paths.py) to line them up, and the Result helpers in records.py.

Main flow:
  1. plan_sync lists the source, then the target when it exists, with walk_tree.
  2. It keys every target file by its path relative to the target root, case-folded where the OS
     folds case (os.path.normcase), and asks needs_copy about each source file.
  3. The result is a list of Copy records (see records.py), sorted by source path.
  4. apply_copies copies them with shutil.copy2, creating folders as needed, and reports progress
     in bytes.

The backup is one way and only adds or overwrites: nothing in the target is ever deleted, and files
in the source's trash folders (and the undo log) are not copied, as walk_tree keeps them out of its
file list.
"""

import os
import shutil

from paths import relative_path
from records import error_text, failure, is_cancelled, report_progress, success
from scanning import walk_tree


def move_source(move):
    """Sort key: the source path of a Move or Copy record, so a plan lists files in path order."""
    return move["source"]


def plan_sync(source_root, target_root, cancel_flag, progress):
    """One-way copy plan: files missing in the target, or different there (size, or newer by > 2 s).

    Source and target are each listed once and compared in memory, so a network share is not
    asked about every file separately. -> Result(list of Copy)

    source_root, target_root: folders; the target need not exist yet (then every file is copied).
    cancel_flag and progress are passed to walk_tree, so a cancel gives failure("cancelled") and
    progress hears "Reading folders" for each tree in turn. Fails when source_root is not a folder.
    Nothing is written: this only plans.

    Steps:
      1. List the source; list the target too when it exists.
      2. Key each target file by its relative path, normcased so "A.TXT" matches "a.txt" on Windows.
      3. For each source file, look up the target file under the same key and keep the ones
         needs_copy says are missing or different. The target path keeps the source's own spelling.
      4. Sort by source path, so the plan (and the copying order) is the same every time.
    """
    if not os.path.isdir(source_root):
        return failure("not a folder: " + source_root)
    source = walk_tree(source_root, cancel_flag, progress)
    if not source["ok"]:
        return source
    existing = {}
    if os.path.isdir(target_root):
        target = walk_tree(target_root, cancel_flag, progress)
        if not target["ok"]:
            return target
        for info in target["value"]["files"]:
            existing[os.path.normcase(relative_path(target_root, info["path"]))] = info
    copies = []
    for info in source["value"]["files"]:
        relative = relative_path(source_root, info["path"])
        key = os.path.normcase(relative)
        have = None
        if key in existing:
            have = existing[key]
        if needs_copy(info, have):
            copies.append({"source": info["path"], "target": os.path.join(target_root, relative), "size": info["size"]})
    copies.sort(key=move_source)
    return success(copies)


def needs_copy(info, existing):
    """Whether source FileInfo info must be copied over existing, the target's FileInfo (None: missing).

    True when the target lacks the file, its size differs, or the source was changed more than 2 s
    after the target. A target that is newer, or older by 2 s or less, is left alone: the backup never
    copies a file back in time on a time difference alone.
    """
    if existing is None:
        return True
    if existing["size"] != info["size"]:
        return True
    # FAT and exFAT keep modification times to 2 s, and some SMB servers round them, so a fresh
    # copy can look up to 2 s older than its source
    return info["modified"] > existing["modified"] + 2  # 2 s slack for FAT/SMB time rounding


def apply_copies(copies, cancel_flag, progress):
    """Copy files, keeping their times -> Result({"done": int, "errors": [str], "moved": []}).

    copies: Copy records from plan_sync. Writes files and creates folders under the target; an
    existing target file is overwritten. done counts files copied; each failure becomes "source:
    message" in errors and the copying goes on. "moved" is always empty: it is there so the GUI's
    report_apply reads the same keys as after apply_moves. A cancel (checked before each file) stops
    early and still returns success with what was done so far. progress hears "Copying" in bytes after
    each file, failed ones included, so a run with errors still ends at the total.

    Steps:
      1. Add up the sizes for the progress total.
      2. For each copy: create its parent folder once (made remembers the ones already done), then
         shutil.copy2, which copies the data and the modification time, so the next plan_sync sees
         the file as up to date.
    """
    errors = []
    count = 0
    total = 0
    for copy in copies:
        total = total + copy["size"]
    done_bytes = 0
    made = {}
    for copy in copies:
        if is_cancelled(cancel_flag):
            break
        try:
            parent = os.path.dirname(copy["target"])
            if parent not in made:
                os.makedirs(parent, exist_ok=True)
                made[parent] = True
            shutil.copy2(copy["source"], copy["target"])
            count = count + 1
        except OSError as e:
            errors.append(copy["source"] + ": " + error_text(e))
        done_bytes = done_bytes + copy["size"]
        report_progress(progress, "Copying", done_bytes, total, "bytes")
    return success({"done": count, "errors": errors, "moved": []})

# ==== stamp v1 | author=kjFriday | hmac-sha256=1ba291c29d171544955279d27c6fbbcbba1dd861b38290dde5d1932a452ee06d ====
