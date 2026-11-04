# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: moves.py
# About: Storage Manager core: plan moves to the trash, carry them out, and undo them.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: plan moves to the trash, carry them out, and undo them.

Nothing is deleted: files go to the trash folder inside the analyzed folder, keeping their relative
paths, and only empty folders are removed. apply_moves records each batch it carried out in the undo
log in that folder, a list of {"time", "moves": [Move]}, and undo_last reverses the last one.
"""

import json
import os
import shutil
import time

from paths import TRASH_DIR_NAME, UNDO_LOG_NAME, relative_path
from records import error_text, failure, is_cancelled, report_progress, success


# ---- planning moves -----------------------------------------------------------------------------

def trash_target(root, path):
    return os.path.join(root, TRASH_DIR_NAME, relative_path(root, path))


def plan_trash(root, files):
    """Moves that send files (FileInfo) to the trash folder inside root, keeping their relative paths."""
    moves = []
    for info in files:
        moves.append({"source": info["path"], "target": trash_target(root, info["path"])})
    return moves


def plan_empty_dir_removal(empty_dirs):
    """Empty folders are removed directly (nothing to lose); returned as Moves with an empty target."""
    moves = []
    for folder in empty_dirs:
        moves.append({"source": folder, "target": ""})
    return moves


def select_empty_dirs(all_empty, chosen, root):
    """The chosen empty folders plus the empty folders inside them, deepest first, so all can be removed."""
    result = []
    for folder in all_empty:
        if folder in chosen:
            result.append(folder)
            continue
        parent = os.path.dirname(folder)
        while len(parent) > len(root):
            if parent in chosen:
                result.append(folder)
                break
            above = os.path.dirname(parent)
            if above == parent:
                break
            parent = above
    return result


# ---- applying moves and undo --------------------------------------------------------------------

def undo_log_path(root):
    return os.path.join(root, UNDO_LOG_NAME)


def read_undo_log(root):
    path = undo_log_path(root)
    if not os.path.isfile(path):
        return []
    try:
        handle = open(path, "r", encoding="utf-8")
        data = json.load(handle)
        handle.close()
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return data


def write_undo_log(root, batches):
    try:
        handle = open(undo_log_path(root), "w", encoding="utf-8")
        json.dump(batches, handle, indent=1)
        handle.close()
    except OSError as e:
        return failure(error_text(e))
    return success(None)


def apply_moves(root, moves, cancel_flag, progress):
    """Carry out a list of Move; record what was done so undo_last can reverse it.

    -> Result({"done": int, "errors": [str], "moved": [Move]})
    """
    done = []
    errors = []
    made = {}  # folders already created
    for move in moves:
        if is_cancelled(cancel_flag):
            break
        source = move["source"]
        target = move["target"]
        try:
            if target == "":
                os.rmdir(source)
            else:
                parent = os.path.dirname(target)
                if parent not in made:
                    os.makedirs(parent, exist_ok=True)
                    made[parent] = True
                if os.path.exists(target):
                    errors.append("already exists: " + target)
                    continue
                shutil.move(source, target)
            done.append(move)
        except OSError as e:
            errors.append(source + ": " + error_text(e))
        count = len(done) + len(errors)
        if count % 100 == 0:
            report_progress(progress, "Moving", count, len(moves), "items")
    if len(done) > 0:
        batches = read_undo_log(root)
        batches.append({"time": time.time(), "moves": done})
        written = write_undo_log(root, batches)
        if not written["ok"]:
            errors.append("undo log: " + written["error"])
    return success({"done": len(done), "errors": errors, "moved": done})


def undo_last(root):
    """Reverse the most recent applied batch -> Result({"done": int, "errors": [str], "moved": []})."""
    batches = read_undo_log(root)
    if len(batches) == 0:
        return failure("nothing to undo")
    batch = batches.pop()
    moves = batch["moves"]
    errors = []
    count = 0
    index = len(moves) - 1
    while index >= 0:
        move = moves[index]
        index = index - 1
        try:
            if move["target"] == "":
                os.makedirs(move["source"], exist_ok=True)
            else:
                os.makedirs(os.path.dirname(move["source"]), exist_ok=True)
                shutil.move(move["target"], move["source"])
            count = count + 1
        except OSError as e:
            errors.append(move["target"] + ": " + error_text(e))
    write_undo_log(root, batches)
    return success({"done": count, "errors": errors, "moved": []})

# ==== stamp v1 | author=kjFriday | hmac-sha256=5e591f635adf42e74dfe1e047fd960351f635e09eb093c0882444652fd22434d ====
