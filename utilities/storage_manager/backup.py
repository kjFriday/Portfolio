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
"""

import os
import shutil

from paths import relative_path
from records import error_text, failure, is_cancelled, report_progress, success
from scanning import walk_tree


def move_source(move):
    return move["source"]


def plan_sync(source_root, target_root, cancel_flag, progress):
    """One-way copy plan: files missing in the target, or different there (size, or newer by > 2 s).

    Source and target are each listed once and compared in memory, so a network share is not
    asked about every file separately. -> Result(list of Copy)
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
    if existing is None:
        return True
    if existing["size"] != info["size"]:
        return True
    return info["modified"] > existing["modified"] + 2  # 2 s slack for FAT/SMB time rounding


def apply_copies(copies, cancel_flag, progress):
    """Copy files, keeping their times -> Result({"done": int, "errors": [str], "moved": []})."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=b6365ad4d94a1e4655319a1ec5fa38cd414028169dcd121295048b0379c1c916 ====
