# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: drive_and_network_storage_manager/storage_manager.py
# About: Generic Company Storage Manager: organize and clean local drives, and handle network...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Generic Company Storage Manager: organize and clean local drives, and handle network shares.

Self-contained: one file, Python 3 standard library only.

Written to be easy to port to another language:
  * Plain functions and plain records (dicts with fixed keys, listed below).
  * Explicit loops; no decorators, generators, comprehension chains or dynamic attributes.
  * The CORE section never touches the GUI. Port it first, then rewrite the GUI in any toolkit.
  * Core functions report failure with a Result record instead of raising across layers.

Records
  Result     {"ok": bool, "error": str, "value": any}
  FileInfo   {"path": str, "size": int, "modified": float}
  Walk       {"files": [FileInfo], "empty_dirs": [str], "errors": [str], "dir_count": int}
  ScanReport {"root": str, "file_count": int, "dir_count": int, "total_bytes": int,
              "drive_free": int, "drive_total": int, "by_type": {name: {"files": int, "bytes": int}},
              "largest": [FileInfo], "stale": [FileInfo], "empty_dirs": [str], "errors": [str],
              "files": [FileInfo]}
  Move       {"source": str, "target": str}             target "" removes an empty folder
  Copy       {"source": str, "target": str, "size": int}
  Share      {"name": str, "unc": str, "letter": str}
  ShareState {"reachable": bool, "total": int, "used": int, "free": int, "error": str}

Progress
  Long functions take progress(text, done, total, unit), or None. unit is "files", "bytes" or
  "items"; total 0 means not known yet. It is called from the worker thread.

Speed
  * Folders are read once with os.scandir, which returns sizes and times with the listing
    (on Windows without opening each file). Empty folders are found in the same pass.
  * Duplicates are narrowed step by step (size, then both ends of large files, then a full
    SHA-256) and files are read on HASH_WORKERS threads at once.
  * A backup lists source and target once and compares them in memory.

Usage
  python storage_manager.py              open the window
  python storage_manager.py --selftest   run the built-in checks and exit
  python storage_manager.py --version
  python storage_manager.py --smoke FILE open the window, write a JSON report to FILE, close
  python storage_manager.py --folder PATH [--view KEY]
                                         analyze PATH straight away (KEY: a sidebar entry, e.g. duplicates)
"""

import concurrent.futures
import hashlib
import heapq
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

__version__ = "0.2.0"
APP_NAME = "Generic Company Storage Manager"
APP_ID = "GenericCompany.Storage"
ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "app.ico")
ICON_CREDIT = ("Icon: drive_network.png from the Silk icon set by Mark James (famfamfam.com/lab/icons/silk), "
               "CC BY 2.5 (creativecommons.org/licenses/by/2.5). Changed: enlarged by whole pixels.")

TRASH_DIR_NAME = "_storage_manager_trash"
UNDO_LOG_NAME = "_storage_manager_undo.json"
CHUNK_SIZE = 1024 * 1024      # bytes read at a time when hashing a whole file
SAMPLE_SIZE = 64 * 1024       # bytes read from each end of a large file before hashing all of it
HASH_WORKERS = 8              # files read at once; hides disk, antivirus and network latency
PROGRESS_EVERY = 500          # files between progress reports
LARGEST_COUNT = 100           # files listed under "Largest files"
MAX_ROWS = 2000               # rows a list shows; actions still apply to every row
SECONDS_PER_DAY = 86400

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
OTHER_FOLDER = "Other"


# =================================================================================================
# CORE: no GUI below this line until the GUI section.
# =================================================================================================

def make_result(ok, value, error):
    return {"ok": ok, "value": value, "error": error}


def success(value):
    return make_result(True, value, "")


def failure(error):
    return make_result(False, None, error)


def is_cancelled(cancel_flag):
    """cancel_flag is a list holding one bool, so a worker can be stopped from another thread."""
    if cancel_flag is None:
        return False
    return cancel_flag[0]


def report_progress(progress, text, done, total, unit):
    if progress is not None:
        progress(text, done, total, unit)


def error_text(error):
    """The OS message for an OSError, without the path Python appends (callers add the path)."""
    if error.strerror:
        return error.strerror
    return str(error)


def is_own_folder(name):
    return name == TRASH_DIR_NAME


def relative_path(root, path):
    """path below root, without a leading separator."""
    if not path.startswith(root):
        return os.path.relpath(path, root)
    rest = path[len(root):]
    while rest.startswith(os.sep) or rest.startswith("/"):
        rest = rest[1:]
    return rest


# ---- walking ------------------------------------------------------------------------------------

def is_link_entry(entry):
    """Symbolic links and Windows junctions are not followed (they can loop or leave the drive)."""
    if entry.is_symlink():
        return True
    if hasattr(entry, "is_junction") and entry.is_junction():
        return True
    return False


def walk_tree(root, cancel_flag, progress):
    """Read every folder under root once -> Result(Walk).

    Our trash folder and undo log are skipped. A folder is empty when it holds no files, links
    or unreadable entries, and every folder inside it is empty too.
    """
    files = []
    errors = []
    dir_paths = [root]      # every folder seen; index 0 is root
    dir_parent = [-1]       # index of each folder's parent
    has_content = [False]   # folder holds something other than folders
    pending = [0]
    while len(pending) > 0:
        if is_cancelled(cancel_flag):
            return failure("cancelled")
        index = pending.pop()
        folder = dir_paths[index]
        try:
            iterator = os.scandir(folder)
        except OSError as e:
            errors.append(folder + ": " + error_text(e))
            has_content[index] = True
            continue
        try:
            for entry in iterator:
                try:
                    if is_link_entry(entry):
                        has_content[index] = True
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if is_own_folder(entry.name):
                            has_content[index] = True
                            continue
                        dir_paths.append(entry.path)
                        dir_parent.append(index)
                        has_content.append(False)
                        pending.append(len(dir_paths) - 1)
                        continue
                    has_content[index] = True
                    if entry.name == UNDO_LOG_NAME:
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError as e:
                    errors.append(entry.path + ": " + error_text(e))
                    has_content[index] = True
                    continue
                files.append({"path": entry.path, "size": info.st_size, "modified": info.st_mtime})
                if len(files) % PROGRESS_EVERY == 0:
                    report_progress(progress, "Reading folders", len(files), 0, "files")
        except OSError as e:
            errors.append(folder + ": " + error_text(e))
            has_content[index] = True
        finally:
            iterator.close()
    # Children always come after their parent, so walking backwards settles each folder
    # before its parent, and the list comes out deepest first (the order they can be removed in).
    nonempty = list(has_content)
    empty_dirs = []
    index = len(dir_paths) - 1
    while index > 0:
        if nonempty[index]:
            nonempty[dir_parent[index]] = True
        else:
            empty_dirs.append(dir_paths[index])
        index = index - 1
    return success({"files": files, "empty_dirs": empty_dirs, "errors": errors, "dir_count": len(dir_paths)})


def find_empty_dirs(root):
    """Folders under root (not root itself) that contain nothing, deepest first."""
    walked = walk_tree(root, None, None)
    if not walked["ok"]:
        return []
    return walked["value"]["empty_dirs"]


def file_size(info):
    return info["size"]


def file_path(info):
    return info["path"]


def sort_by_size_desc(files):
    result = list(files)
    result.sort(key=file_size, reverse=True)
    return result


def total_size(files):
    total = 0
    for info in files:
        total = total + info["size"]
    return total


def largest_files(files, count):
    """The count biggest files, biggest first (a partial sort: port as a top-N / priority queue)."""
    return heapq.nlargest(count, files, key=file_size)


def stale_files(files, days, now):
    """Files not changed for `days` days, biggest first."""
    cutoff = now - days * SECONDS_PER_DAY
    stale = []
    for info in files:
        if info["modified"] < cutoff:
            stale.append(info)
    stale.sort(key=file_size, reverse=True)
    return stale


def summarize_types(files):
    """File count and bytes per type folder (Images, Video, ... Other)."""
    by_type = {}
    for info in files:
        kind = type_folder_for(info["path"])
        if kind not in by_type:
            by_type[kind] = {"files": 0, "bytes": 0}
        by_type[kind]["files"] = by_type[kind]["files"] + 1
        by_type[kind]["bytes"] = by_type[kind]["bytes"] + info["size"]
    return by_type


def drive_usage(path):
    """(free, total) bytes of the drive holding path, or (0, 0) when unknown."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return (0, 0)
    return (usage.free, usage.total)


# ---- scan ---------------------------------------------------------------------------------------

def build_report(root, files, empty_dirs, errors, dir_count, largest_count, stale_days, now):
    return {
        "root": root,
        "file_count": len(files),
        "dir_count": dir_count,
        "total_bytes": total_size(files),
        "drive_free": 0,
        "drive_total": 0,
        "by_type": summarize_types(files),
        "largest": largest_files(files, largest_count),
        "stale": stale_files(files, stale_days, now),
        "empty_dirs": empty_dirs,
        "errors": errors,
        "files": files,
    }


def scan(root, largest_count, stale_days, now, cancel_flag, progress):
    """Summarize a folder in one pass -> Result(ScanReport)."""
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    walked = walk_tree(root, cancel_flag, progress)
    if not walked["ok"]:
        return walked
    found = walked["value"]
    report = build_report(root, found["files"], found["empty_dirs"], found["errors"], found["dir_count"],
                          largest_count, stale_days, now)
    usage = drive_usage(root)
    report["drive_free"] = usage[0]
    report["drive_total"] = usage[1]
    return success(report)


def remove_from_report(report, gone, largest_count, stale_days, now):
    """The report without the paths in gone (dict path -> True), e.g. after moving them to the trash."""
    files = []
    for info in report["files"]:
        if info["path"] not in gone:
            files.append(info)
    empty_dirs = []
    for folder in report["empty_dirs"]:
        if folder not in gone:
            empty_dirs.append(folder)
    dir_count = report["dir_count"] - (len(report["empty_dirs"]) - len(empty_dirs))
    updated = build_report(report["root"], files, empty_dirs, report["errors"], dir_count,
                           largest_count, stale_days, now)
    updated["drive_free"] = report["drive_free"]
    updated["drive_total"] = report["drive_total"]
    return updated


# ---- duplicates ---------------------------------------------------------------------------------

def hash_file(path, size):
    """SHA-256 hex of a whole file -> Result(str).

    A small file is read in one go with a buffer of its own size: allocating a large buffer for
    each small file costs more than reading it. The loop still finishes a file that has grown.
    """
    digest = hashlib.sha256()
    block_size = CHUNK_SIZE
    if size < CHUNK_SIZE:
        block_size = size + 1
    try:
        handle = open(path, "rb", buffering=0)
    except OSError as e:
        return failure(error_text(e))
    try:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    except OSError as e:
        return failure(error_text(e))
    finally:
        handle.close()
    return success(digest.hexdigest())


def hash_sample(path, size):
    """SHA-256 hex of the first and last SAMPLE_SIZE bytes of a file -> Result(str)."""
    digest = hashlib.sha256()
    try:
        handle = open(path, "rb")
    except OSError as e:
        return failure(error_text(e))
    try:
        digest.update(handle.read(SAMPLE_SIZE))
        handle.seek(size - SAMPLE_SIZE)
        digest.update(handle.read(SAMPLE_SIZE))
    except OSError as e:
        return failure(error_text(e))
    finally:
        handle.close()
    return success(digest.hexdigest())


def hash_job(info, mode, cancel_flag):
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    if mode == "sample":
        return hash_sample(info["path"], info["size"])
    return hash_file(info["path"], info["size"])


def bytes_to_read(info, mode):
    if mode == "sample":
        return 2 * SAMPLE_SIZE
    return info["size"]


def hash_many(files, mode, cancel_flag, progress, text):
    """Hash files on HASH_WORKERS threads -> Result(dict path -> hex). Unreadable files are left out.

    mode is "sample" (both ends) or "full". Port with any thread pool or parallel-for.
    """
    total = 0
    for info in files:
        total = total + bytes_to_read(info, mode)
    digests = {}
    done = 0
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=HASH_WORKERS)
    try:
        jobs = []
        for info in files:
            jobs.append(pool.submit(hash_job, info, mode, cancel_flag))
        index = 0
        while index < len(jobs):
            hashed = jobs[index].result()
            if hashed["ok"]:
                digests[files[index]["path"]] = hashed["value"]
            done = done + bytes_to_read(files[index], mode)
            if index % 50 == 0 or index == len(jobs) - 1:
                report_progress(progress, text, done, total, "bytes")
            index = index + 1
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    return success(digests)


def group_savings(group):
    return group[0]["size"] * (len(group) - 1)


def first_path(group):
    return group[0]["path"]


def find_duplicates(root, cancel_flag, progress):
    """Walk root, then find_duplicates_in its files."""
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    walked = walk_tree(root, cancel_flag, progress)
    if not walked["ok"]:
        return walked
    return find_duplicates_in(walked["value"]["files"], cancel_flag, progress)


def find_duplicates_in(files, cancel_flag, progress):
    """Groups of identical files (2+ each, empty files ignored), biggest savings first.

    Each step only looks at files that may still be equal:
      1. same size (nothing read),
      2. large files: same first and last SAMPLE_SIZE bytes,
      3. same SHA-256 of the whole file.
    -> Result(list of list of FileInfo)
    """
    by_size = {}
    for info in files:
        if info["size"] == 0:
            continue
        if info["size"] not in by_size:
            by_size[info["size"]] = []
        by_size[info["size"]].append(info)
    small = []
    large = []
    for size in by_size:
        group = by_size[size]
        if len(group) < 2:
            continue
        for info in group:
            if size <= 2 * SAMPLE_SIZE:
                small.append(info)
            else:
                large.append(info)

    sampled = hash_many(large, "sample", cancel_flag, progress, "Comparing file ends")
    if not sampled["ok"]:
        return sampled
    by_sample = {}
    for info in large:
        if info["path"] not in sampled["value"]:
            continue
        key = str(info["size"]) + ":" + sampled["value"][info["path"]]
        if key not in by_sample:
            by_sample[key] = []
        by_sample[key].append(info)
    candidates = list(small)
    for key in by_sample:
        if len(by_sample[key]) > 1:
            for info in by_sample[key]:
                candidates.append(info)

    hashed = hash_many(candidates, "full", cancel_flag, progress, "Comparing files")
    if not hashed["ok"]:
        return hashed
    by_digest = {}
    for info in candidates:
        if info["path"] not in hashed["value"]:
            continue
        key = str(info["size"]) + ":" + hashed["value"][info["path"]]
        if key not in by_digest:
            by_digest[key] = []
        by_digest[key].append(info)
    groups = []
    for key in by_digest:
        group = by_digest[key]
        if len(group) > 1:
            group.sort(key=file_path)
            groups.append(group)
    groups.sort(key=first_path)
    groups.sort(key=group_savings, reverse=True)
    return success(groups)


def duplicate_savings(groups):
    """{"copies": extra copies, "bytes": space they take}."""
    copies = 0
    total = 0
    for group in groups:
        copies = copies + len(group) - 1
        total = total + group_savings(group)
    return {"copies": copies, "bytes": total}


def keeper_index(group, keep):
    """Index of the copy to keep: the first one listed in keep (dict path -> True), else the first."""
    index = 0
    while index < len(group):
        if group[index]["path"] in keep:
            return index
        index = index + 1
    return 0


def plan_duplicate_removal(root, groups, keep):
    """Keep one copy per group and send the rest to the trash -> list of Move."""
    moves = []
    for group in groups:
        keeper = keeper_index(group, keep)
        index = 0
        while index < len(group):
            if index != keeper:
                moves.append({"source": group[index]["path"], "target": trash_target(root, group[index]["path"])})
            index = index + 1
    return moves


def remove_from_groups(groups, gone):
    """Duplicate groups without the paths in gone; groups left with one file are dropped."""
    result = []
    for group in groups:
        kept = []
        for info in group:
            if info["path"] not in gone:
                kept.append(info)
        if len(kept) > 1:
            result.append(kept)
    return result


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


# ---- organize -----------------------------------------------------------------------------------

def type_folder_for(path):
    extension = os.path.splitext(path)[1].lower()
    if extension in TYPE_FOLDERS:
        return TYPE_FOLDERS[extension]
    return OTHER_FOLDER


def date_folder_for(modified):
    return time.strftime("%Y-%m", time.localtime(modified))


def entry_name(item):
    return item["name"]


def plan_organize(root, mode, cancel_flag):
    """Moves that sort the files directly inside root into subfolders.

    mode is "type" or "date". Only top-level files move, so running it twice does nothing new.
    -> Result(list of Move)
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
        taken[target.lower()] = True
        moves.append({"source": item["path"], "target": target})
    return success(moves)


def unique_target(target, taken):
    """target, or target with " (2)", " (3)"... when the name is already used."""
    if not os.path.exists(target) and target.lower() not in taken:
        return target
    stem, extension = os.path.splitext(target)
    number = 2
    while True:
        candidate = stem + " (" + str(number) + ")" + extension
        if not os.path.exists(candidate) and candidate.lower() not in taken:
            return candidate
        number = number + 1


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


# ---- backup sync --------------------------------------------------------------------------------

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


# ---- network shares -----------------------------------------------------------------------------

def unc_host(unc):
    """\\\\host\\share\\path -> host (or "" if it is not a UNC path)."""
    cleaned = unc.replace("/", "\\")
    if not cleaned.startswith("\\\\"):
        return ""
    parts = cleaned[2:].split("\\")
    return parts[0]


def valid_letter(letter):
    if len(letter) == 2 and letter[1] == ":" and letter[0].upper() >= "D" and letter[0].upper() <= "Z":
        return True
    return letter == ""


def share_path(share):
    """The path to read: the drive letter when one is set, else the UNC path."""
    if share["letter"] != "":
        return share["letter"] + "\\"
    return share["unc"]


def run_command(arguments, timeout):
    """Run an OS command -> Result(stdout text). No shell, so arguments are passed as-is."""
    try:
        completed = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return failure(str(e))
    if completed.returncode != 0:
        message = completed.stderr.strip()
        if message == "":
            message = completed.stdout.strip()
        return failure(message)
    return success(completed.stdout)


def map_command(share):
    """The command that maps a share (Windows `net use`). Credentials are never passed or stored."""
    if share["letter"] == "":
        return ["net", "use", share["unc"]]
    return ["net", "use", share["letter"], share["unc"], "/persistent:no"]


def unmap_command(share):
    target = share["letter"]
    if target == "":
        target = share["unc"]
    return ["net", "use", target, "/delete", "/y"]


def map_share(share):
    if os.name != "nt":
        return failure("mapping uses `net use` and is Windows only; mount the share with your OS tools")
    if not valid_letter(share["letter"]):
        return failure("drive letter must look like Z: (D to Z)")
    return run_command(map_command(share), 60)


def unmap_share(share):
    if os.name != "nt":
        return failure("unmapping is Windows only")
    return run_command(unmap_command(share), 30)


def ping_command(host):
    if os.name == "nt":
        return ["ping", "-n", "1", "-w", "1500", host]
    return ["ping", "-c", "1", "-W", "2", host]


def check_share(share):
    """Reachability and space -> ShareState (always returned, error filled in on failure)."""
    state = {"reachable": False, "total": 0, "used": 0, "free": 0, "error": ""}
    host = unc_host(share["unc"])
    if host == "":
        state["error"] = "not a \\\\host\\share path"
        return state
    pinged = run_command(ping_command(host), 10)
    path = share_path(share)
    if not os.path.isdir(path):
        if pinged["ok"]:
            state["error"] = "host answers but the share is not readable (map it or check rights)"
        else:
            state["error"] = "host does not answer"
        return state
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        state["error"] = error_text(e)
        return state
    state["reachable"] = True
    state["total"] = usage.total
    state["used"] = usage.used
    state["free"] = usage.free
    return state


# ---- the desktop --------------------------------------------------------------------------------

def list_drives():
    """Drive roots on this machine (C:\\, D:\\ ... on Windows, / elsewhere)."""
    if os.name != "nt":
        return ["/"]
    if hasattr(os, "listdrives"):
        try:
            return os.listdrives()
        except OSError:
            return []
    found = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        if os.path.exists(letter + ":\\"):
            found.append(letter + ":\\")
    return found


def reveal_command(path):
    """The command that shows a file selected in the system file manager."""
    if os.name == "nt":
        return ["explorer", "/select,", path]
    if sys.platform == "darwin":
        return ["open", "-R", path]
    return ["xdg-open", os.path.dirname(path)]


def open_folder_command(folder):
    if os.name == "nt":
        return ["explorer", folder]
    if sys.platform == "darwin":
        return ["open", folder]
    return ["xdg-open", folder]


def launch(arguments):
    """Start a program without waiting for it -> Result(None)."""
    try:
        subprocess.Popen(arguments)
    except OSError as e:
        return failure(error_text(e))
    return success(None)


def normalize_folder(text):
    """What the user typed -> a folder path ("D:" becomes "D:\\", surrounding quotes and spaces go)."""
    folder = text.strip()
    if len(folder) >= 2 and folder[0] == '"' and folder[len(folder) - 1] == '"':
        folder = folder[1:len(folder) - 1]
    if len(folder) == 2 and folder[1] == ":":
        folder = folder + os.sep
    return folder


def add_recent(recent, folder, limit):
    """recent with folder moved to the front, at most limit entries."""
    result = [folder]
    for item in recent:
        if os.path.normcase(item) != os.path.normcase(folder) and len(result) < limit:
            result.append(item)
    return result


# ---- settings -----------------------------------------------------------------------------------

def settings_path():
    base = os.environ.get("LOCALAPPDATA", "")
    if base == "":
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Generic Company Inc", APP_ID, "settings.json")


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


# ---- formatting ---------------------------------------------------------------------------------

def human_size(count):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(count)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value = value / 1024
        index = index + 1
    if index == 0:
        return str(count) + " B"
    return "%.1f %s" % (value, units[index])


def human_count(count):
    """1234567 -> "1,234,567"."""
    return format(count, ",")


def human_date(seconds):
    return time.strftime("%Y-%m-%d", time.localtime(seconds))


def plural(count, word):
    """plural(1, "file") -> "1 file", plural(3, "copy") -> "3 copies"."""
    if count == 1:
        return "1 " + word
    if len(word) > 1 and word[len(word) - 1] == "y" and word[len(word) - 2] not in "aeiou":
        return human_count(count) + " " + word[:len(word) - 1] + "ies"
    return human_count(count) + " " + word + "s"


# =================================================================================================
# SELF-TEST: exercises the core on a throwaway folder. `python storage_manager.py --selftest`
# =================================================================================================

def write_file(path, text, modified):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()
    os.utime(path, (modified, modified))


def write_bytes(path, data):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle = open(path, "wb")
    handle.write(data)
    handle.close()


def check(condition, message, failures):
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    failures = []
    now = time.time()
    old = now - 800 * SECONDS_PER_DAY
    work = tempfile.mkdtemp(prefix="storage_manager_test_")
    try:
        root = os.path.join(work, "drive")
        write_file(os.path.join(root, "a.txt"), "same content", now)
        write_file(os.path.join(root, "sub", "b.txt"), "same content", now)
        write_file(os.path.join(root, "photo.jpg"), "not really a jpeg", old)
        write_file(os.path.join(root, "song.mp3"), "la la", now)
        write_file(os.path.join(root, "notes.unknownext"), "?", now)
        os.makedirs(os.path.join(root, "empty1", "empty2"))
        os.makedirs(os.path.join(root, "mixed", "hollow"))
        write_file(os.path.join(root, "mixed", "keep.txt"), "x", now)

        print("scan")
        report = scan(root, 10, 365, now, None, None)
        check(report["ok"], "scan succeeds", failures)
        check(report["value"]["file_count"] == 6, "counts 6 files", failures)
        check(len(report["value"]["stale"]) == 1, "finds 1 stale file", failures)
        check(len(report["value"]["empty_dirs"]) == 3, "finds 3 empty folders (nested and beside a file)", failures)
        check(report["value"]["empty_dirs"].index(os.path.join(root, "empty1", "empty2"))
              < report["value"]["empty_dirs"].index(os.path.join(root, "empty1")), "empty folders deepest first", failures)
        check(report["value"]["by_type"]["Images"]["files"] == 1, "type summary counts images", failures)
        check(report["value"]["largest"][0]["path"].endswith("photo.jpg"), "largest file first", failures)
        check(scan(os.path.join(work, "missing"), 10, 365, now, None, None)["ok"] == False, "missing folder fails", failures)
        cancelled = scan(root, 10, 365, now, [True], None)
        check(not cancelled["ok"] and cancelled["error"] == "cancelled", "scan can be cancelled", failures)
        smaller = remove_from_report(report["value"], {os.path.join(root, "song.mp3"): True}, 10, 365, now)
        check(smaller["file_count"] == 5 and "Audio" not in smaller["by_type"], "remove_from_report drops a file", failures)

        print("duplicates")
        dupes = find_duplicates(root, None, None)
        check(dupes["ok"] and len(dupes["value"]) == 1, "one duplicate group", failures)
        moves = plan_duplicate_removal(root, dupes["value"], {})
        check(len(moves) == 1 and moves[0]["source"].endswith("b.txt"), "first copy is kept by default", failures)
        chosen = plan_duplicate_removal(root, dupes["value"], {os.path.join(root, "sub", "b.txt"): True})
        check(chosen[0]["source"].endswith("a.txt"), "chosen copy is kept", failures)
        applied = apply_moves(root, moves, None, None)
        check(applied["value"]["done"] == 1 and len(applied["value"]["moved"]) == 1, "duplicate moved to trash", failures)
        check(os.path.isfile(os.path.join(root, TRASH_DIR_NAME, "sub", "b.txt")), "trash keeps relative path", failures)
        check(scan(root, 10, 365, now, None, None)["value"]["file_count"] == 5, "trash folder is not scanned", failures)
        undone = undo_last(root)
        check(undone["ok"] and os.path.isfile(os.path.join(root, "sub", "b.txt")), "undo restores duplicate", failures)
        check(len(remove_from_groups(dupes["value"], {moves[0]["source"]: True})) == 0, "group of one is dropped", failures)

        print("large duplicates")
        big = os.path.join(work, "big")
        body = bytes(range(256)) * (3 * SAMPLE_SIZE // 256)
        changed_end = body[:len(body) - 1] + b"!"
        middle = bytearray(body)
        middle[len(middle) // 2] = (middle[len(middle) // 2] + 1) % 256
        write_bytes(os.path.join(big, "same1.bin"), body)
        write_bytes(os.path.join(big, "same2.bin"), body)
        write_bytes(os.path.join(big, "end.bin"), changed_end)
        write_bytes(os.path.join(big, "middle.bin"), bytes(middle))
        big_dupes = find_duplicates(big, None, None)
        check(big_dupes["ok"] and len(big_dupes["value"]) == 1 and len(big_dupes["value"][0]) == 2,
              "only true copies match (ends and middle checked)", failures)
        check(hash_many([], "full", None, None, "")["ok"], "nothing to hash is fine", failures)

        print("empty folders")
        all_empty = find_empty_dirs(root)
        picked = select_empty_dirs(all_empty, {os.path.join(root, "empty1"): True}, root)
        check(len(picked) == 2 and picked[0].endswith("empty2"), "choosing a folder takes its empty insides first", failures)
        apply_moves(root, plan_empty_dir_removal(picked), None, None)
        check(not os.path.exists(os.path.join(root, "empty1")), "empty folders removed", failures)
        undo_last(root)
        check(os.path.isdir(os.path.join(root, "empty1", "empty2")), "undo recreates empty folders", failures)

        print("organize")
        planned = plan_organize(root, "type", None)
        check(planned["ok"] and len(planned["value"]) == 4, "4 top-level files planned", failures)
        apply_moves(root, planned["value"], None, None)
        check(os.path.isfile(os.path.join(root, "Images", "photo.jpg")), "jpg goes to Images", failures)
        check(os.path.isfile(os.path.join(root, "Other", "notes.unknownext")), "unknown goes to Other", failures)
        again = plan_organize(root, "type", None)
        check(len(again["value"]) == 0, "second run plans nothing", failures)
        undo_last(root)
        check(os.path.isfile(os.path.join(root, "photo.jpg")), "undo puts files back", failures)
        by_date = plan_organize(root, "date", None)
        photo_target = ""
        for move in by_date["value"]:
            if move["source"].endswith("photo.jpg"):
                photo_target = move["target"]
        check(photo_target.find(date_folder_for(old)) >= 0, "date mode uses year-month", failures)

        print("names and paths")
        first = unique_target(os.path.join(root, "a.txt"), {})
        check(first.endswith("a (2).txt"), "clash gets (2)", failures)
        check(relative_path(root, os.path.join(root, "sub", "b.txt")) == os.path.join("sub", "b.txt"), "relative path", failures)
        check(relative_path("D:" + os.sep, "D:" + os.sep + "x") == "x", "relative path from a drive root", failures)
        check(normalize_folder(' "D:" ') == "D:" + os.sep, "typed drive becomes its root", failures)
        check(add_recent(["a", "b", "c"], "b", 2) == ["b", "a"], "recent folders", failures)

        print("sync")
        target = os.path.join(work, "backup")
        copies = plan_sync(root, target, None, None)
        check(copies["ok"] and len(copies["value"]) == 6, "6 files to copy", failures)
        check(copies["value"][0]["size"] > 0, "copies carry their size", failures)
        apply_copies(copies["value"], None, None)
        check(len(plan_sync(root, target, None, None)["value"]) == 0, "nothing to copy after sync", failures)
        write_file(os.path.join(root, "song.mp3"), "la la la, longer now", now + 60)
        write_file(os.path.join(root, "new.txt"), "new", now)
        changed = plan_sync(root, target, None, None)["value"]
        check(len(changed) == 2, "changed and new files found", failures)

        print("shares, settings, desktop")
        check(unc_host("\\\\nas01\\media\\x") == "nas01", "host from UNC", failures)
        check(unc_host("C:\\x") == "", "non-UNC has no host", failures)
        check(valid_letter("Z:") and not valid_letter("C:") and not valid_letter("ZZ"), "drive letter rules", failures)
        check(map_command({"name": "n", "unc": "\\\\h\\s", "letter": "Z:"})[2] == "Z:", "map command", failures)
        check(reveal_command(os.path.join(root, "a.txt"))[0] in ("explorer", "open", "xdg-open"), "reveal command", failures)
        settings_file = os.path.join(work, "settings", "settings.json")
        saved = default_settings()
        saved["shares"].append({"name": "NAS", "unc": "\\\\nas\\share", "letter": "Y:"})
        save_settings(settings_file, saved)
        check(load_settings(settings_file)["shares"][0]["letter"] == "Y:", "settings round trip", failures)
        check(human_size(1536) == "1.5 KB" and human_count(1234567) == "1,234,567", "human size and count", failures)
        check(plural(1, "file") == "1 file" and plural(2000, "file") == "2,000 files", "plural", failures)
        check(plural(3, "extra copy") == "3 extra copies" and plural(2, "day") == "2 days", "plural of -y words", failures)
        check(option_value(["--smoke", "r.json"], "--smoke") == "r.json", "option value", failures)
        check(option_value([], "--smoke") == "" and option_value(["--smoke"], "--smoke") is None, "option absent / missing", failures)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1


# =================================================================================================
# GUI: tkinter. Everything here only calls the CORE functions above.
# =================================================================================================

def windows_identity():
    """Own taskbar button (not Python's) and crisp text on scaled displays. Windows only."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def set_icon(window):
    """The pixel icon on the window and its dialogs -> True when it was set."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


# Sidebar: (key, label, section). Sections group the entries; "" is top level.
VIEWS = [
    ("overview", "Overview", ""),
    ("largest", "Largest files", "Clean up"),
    ("old", "Old files", "Clean up"),
    ("duplicates", "Duplicates", "Clean up"),
    ("empty", "Empty folders", "Clean up"),
    ("errors", "Unreadable", "Clean up"),
    ("organize", "Organize", "Tools"),
    ("network", "Network shares", "Tools"),
    ("activity", "Activity", "Tools"),
]


def run_gui(smoke_path, start_folder, start_view):
    import queue
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox

    path_to_settings = settings_path()
    settings = load_settings(path_to_settings)
    state = {
        "busy": False,
        "cancel": [False],
        "root": "",          # folder the results below belong to
        "report": None,      # ScanReport of the last analysis
        "groups": None,      # duplicate groups; None until compared
        "dup_note": "",      # shown instead of duplicate counts while comparing or after a cancel
        "keep": {},          # path -> True: copies the user chose to keep
        "org_moves": [],
        "org_root": "",
        "old_days": settings["stale_days"],
        "view": "overview",
    }
    buttons = []        # (button, predicate): enabled when idle and predicate() is true
    views = {}
    primary = {}        # view key -> action for the Delete key

    windows_identity()
    window = tk.Tk()
    window.title("Generic Company Inc. \u2014 Storage Manager " + __version__)
    if settings["geometry"] != "":
        window.geometry(settings["geometry"])
    else:
        window.geometry("1120x700")
    window.minsize(880, 540)
    icon_set = set_icon(window)

    base_font = tkfont.nametofont("TkDefaultFont")
    line_height = base_font.metrics("linespace")
    size = base_font.cget("size")
    title_font = base_font.copy()
    if size < 0:
        title_font.configure(size=size - 5, weight="bold")
    else:
        title_font.configure(size=size + 5, weight="bold")
    strong_font = base_font.copy()
    strong_font.configure(weight="bold")
    style = ttk.Style(window)
    style.configure("Treeview", rowheight=line_height + 8)
    style.configure("Side.Treeview", rowheight=line_height + 14)
    style.configure("Title.TLabel", font=title_font)
    style.configure("Strong.TLabel", font=strong_font)
    style.configure("Muted.TLabel", foreground="#6b6b6b")
    style.configure("Primary.TButton", font=strong_font)

    # --- top bar: what to look at ----------------------------------------------------------------
    top = ttk.Frame(window, padding=(10, 10, 10, 6))
    top.pack(fill="x")
    ttk.Label(top, text="Folder or drive").pack(side="left")
    folder_var = tk.StringVar(value=settings["last_folder"])
    folder_box = ttk.Combobox(top, textvariable=folder_var)
    folder_box.pack(side="left", fill="x", expand=True, padx=8)
    browse_button = ttk.Button(top, text="Browse\u2026", command=lambda: browse())
    browse_button.pack(side="left")
    analyze_button = ttk.Button(top, text="Analyze", style="Primary.TButton", command=lambda: analyze())
    analyze_button.pack(side="left", padx=6)
    undo_button = ttk.Button(top, text="Undo last change", command=lambda: undo())
    undo_button.pack(side="left")

    # --- bottom bar: what is happening -----------------------------------------------------------
    bottom = ttk.Frame(window, padding=(10, 4, 10, 8))
    bottom.pack(side="bottom", fill="x")
    status_var = tk.StringVar(value="Pick a folder or drive and press Analyze (or Enter).")
    # Right-hand widgets are packed first so a long status line is cut, not the buttons.
    ttk.Button(bottom, text="About", command=lambda: about()).pack(side="right", padx=(6, 0))
    cancel_button = ttk.Button(bottom, text="Cancel", state="disabled", command=lambda: cancel())
    cancel_button.pack(side="right")
    progress = ttk.Progressbar(bottom, length=220, mode="determinate", maximum=100)
    progress.pack(side="right", padx=8)
    ttk.Label(bottom, textvariable=status_var, width=1).pack(side="left", fill="x", expand=True)

    # --- body: sidebar and the selected view ---------------------------------------------------
    body = ttk.PanedWindow(window, orient="horizontal")
    body.pack(fill="both", expand=True, padx=10)
    side = ttk.Frame(body)
    main = ttk.Frame(body, padding=(14, 0, 0, 0))
    body.add(side, weight=0)
    body.add(main, weight=1)
    main.rowconfigure(0, weight=1)
    main.columnconfigure(0, weight=1)

    sidebar = ttk.Treeview(side, columns=("info",), show="tree", selectmode="browse", style="Side.Treeview")
    sidebar.column("#0", width=170, stretch=True)
    sidebar.column("info", width=150, anchor="e", stretch=False)
    sidebar.pack(fill="both", expand=True)
    sidebar.tag_configure("section", font=strong_font)
    for entry in VIEWS:
        parent = ""
        if entry[2] != "":
            parent = "section-" + entry[2].lower().replace(" ", "-")
            if not sidebar.exists(parent):
                sidebar.insert("", "end", iid=parent, text=entry[2], open=True, tags=("section",))
        sidebar.insert(parent, "end", iid=entry[0], text=entry[1], values=("",))

    # --- small helpers ---------------------------------------------------------------------------
    log_text = None  # set when the Activity view is built

    def log(message):
        if log_text is None:
            return
        log_text.configure(state="normal")
        log_text.insert("end", time.strftime("%H:%M:%S") + "  " + message + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")

    def wrapping(label):
        """Let a label wrap to whatever width it is given instead of being cut off."""
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(event.width - 4, 100)))
        return label

    def rel(path):
        if state["root"] == "":
            return path
        return relative_path(state["root"], path)

    def ask(question):
        return messagebox.askyesno(APP_NAME, question, parent=window)

    def refresh_buttons():
        busy = state["busy"]
        for pair in buttons:
            enabled = False
            if not busy:
                try:
                    enabled = pair[1]()
                except Exception:
                    enabled = False
            if enabled:
                pair[0].configure(state="normal")
            else:
                pair[0].configure(state="disabled")
        idle = "disabled" if busy else "normal"
        analyze_button.configure(state=idle)
        browse_button.configure(state=idle)
        if not busy and state["root"] != "" and os.path.isfile(undo_log_path(state["root"])):
            undo_button.configure(state="normal")
        else:
            undo_button.configure(state="disabled")
        cancel_button.configure(state="normal" if busy else "disabled")

    def show_progress(item):
        text = item[0]
        done = item[1]
        total = item[2]
        unit = item[3]
        if total > 0:
            if str(progress.cget("mode")) != "determinate":
                progress.stop()
                progress.configure(mode="determinate")
            progress.configure(value=100.0 * done / total)
            if unit == "bytes":
                amount = human_size(done) + " of " + human_size(total)
            else:
                amount = human_count(done) + " of " + human_count(total)
            status_var.set(text + "\u2026 " + amount)
        else:
            if str(progress.cget("mode")) != "indeterminate":
                progress.configure(mode="indeterminate")
                progress.start(15)
            status_var.set(text + "\u2026 " + human_count(done) + " " + unit)

    def run_job(label, work, finish, on_message, on_fail):
        """Run work(post) on a worker thread. post(kind, value) sends messages back; the window polls
        for them, so Tk is only touched from its own thread. finish(result) runs on success."""
        if state["busy"]:
            return
        state["busy"] = True
        state["cancel"][0] = False
        messages = queue.Queue()
        holder = {"result": None, "done": False}

        def post(kind, value):
            messages.put((kind, value))

        def worker():
            try:
                result = work(post)
            except Exception as e:  # keep the window alive whatever happens in a job
                result = failure("unexpected error: " + str(e))
            holder["result"] = result
            holder["done"] = True

        def poll():
            finished = holder["done"]
            latest = None
            while True:
                try:
                    item = messages.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "progress":
                    latest = item[1]
                elif on_message is not None:
                    on_message(item[0], item[1])
            if not finished:
                if latest is not None:
                    show_progress(latest)
                window.after(100, poll)
                return
            state["busy"] = False
            progress.stop()
            progress.configure(mode="determinate", value=0)
            result = holder["result"]
            if result["ok"]:
                status_var.set(label + " \u2014 done")
                finish(result)
            else:
                status_var.set(label + " \u2014 " + result["error"])
                log("  " + result["error"])
                if on_fail is not None:
                    on_fail(result)
            refresh_buttons()

        status_var.set(label + "\u2026")
        log(label)
        progress.configure(mode="indeterminate")
        progress.start(15)
        refresh_buttons()
        threading.Thread(target=worker, daemon=True).start()
        window.after(100, poll)

    def progress_sender(post):
        def send(text, done, total, unit):
            post("progress", (text, done, total, unit))
        return send

    def cancel():
        state["cancel"][0] = True
        status_var.set("Cancelling\u2026")
        log("cancel requested")

    def report_apply(result, verb):
        info = result["value"]
        log("  " + verb + " " + plural(info["done"], "item"))
        for error in info["errors"]:
            log("  error: " + error)
        message = verb + " " + plural(info["done"], "item")
        if len(info["errors"]) > 0:
            message = message + ", " + plural(len(info["errors"]), "error") + " (see Activity)"
        status_var.set(message)

    # --- views ---------------------------------------------------------------------------------
    def make_view(key, title):
        frame = ttk.Frame(main)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
        subtitle = tk.StringVar(value="")
        wrapping(ttk.Label(frame, textvariable=subtitle, style="Muted.TLabel")).pack(fill="x", pady=(2, 8))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 8))
        view = {"frame": frame, "subtitle": subtitle, "actions": actions}
        views[key] = view
        return view

    def add_button(view, text, command, predicate, primary_style):
        style_name = "Primary.TButton" if primary_style else "TButton"
        button = ttk.Button(view["actions"], text=text, command=command, style=style_name)
        button.pack(side="left", padx=(0, 6))
        buttons.append((button, predicate))
        return button

    def make_table(parent, columns, values, sort_keys):
        """columns: list of (key, heading, width, anchor, stretch). values(row) -> tuple for a row."""
        holder = ttk.Frame(parent)
        keys = []
        for column in columns:
            keys.append(column[0])
        tree = ttk.Treeview(holder, columns=keys, show="headings", selectmode="extended")
        table = {"tree": tree, "frame": holder, "rows": [], "values": values, "sort_keys": sort_keys,
                 "sorted_by": "", "descending": False, "note": tk.StringVar(value="")}
        for column in columns:
            tree.heading(column[0], text=column[1], anchor=column[3], command=lambda key=column[0]: sort_table(table, key))
            tree.column(column[0], width=column[2], anchor=column[3], stretch=column[4])
        bar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        wrapping(ttk.Label(holder, textvariable=table["note"], style="Muted.TLabel")).pack(side="bottom", fill="x", pady=(4, 0))
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda event: refresh_buttons())
        return table

    def fill_table(table, rows):
        tree = table["tree"]
        tree.delete(*tree.get_children())
        table["rows"] = rows
        shown = len(rows)
        if shown > MAX_ROWS:
            shown = MAX_ROWS
        index = 0
        while index < shown:
            tree.insert("", "end", iid=str(index), values=table["values"](rows[index]))
            index = index + 1
        if len(rows) > shown:
            table["note"].set("Showing the first " + human_count(shown) + " of " + human_count(len(rows))
                              + ". With nothing selected, actions apply to all of them.")
        else:
            table["note"].set("")

    def sort_table(table, key):
        if key not in table["sort_keys"]:
            return
        if table["sorted_by"] == key:
            table["descending"] = not table["descending"]
        else:
            table["descending"] = key == "size" or key == "modified" or key == "files"
        table["sorted_by"] = key
        rows = list(table["rows"])
        rows.sort(key=table["sort_keys"][key], reverse=table["descending"])
        fill_table(table, rows)

    def picked_rows(table):
        """Selected rows, or every row when nothing is selected."""
        chosen = table["tree"].selection()
        if len(chosen) == 0:
            return list(table["rows"])
        rows = []
        for iid in chosen:
            rows.append(table["rows"][int(iid)])
        return rows

    def has_rows(table):
        return len(table["rows"]) > 0

    def has_selection(table):
        return len(table["tree"].selection()) > 0

    def path_key(row):
        return row["path"].lower()

    def text_key(row):
        return row.lower()

    def file_values(row):
        return (rel(row["path"]), human_size(row["size"]), human_date(row["modified"]))

    file_columns = [("path", "File", 340, "w", True), ("size", "Size", 100, "e", False),
                    ("modified", "Changed", 110, "e", False)]
    file_sorts = {"path": path_key, "size": file_size, "modified": lambda row: row["modified"]}

    def reveal_first(table):
        rows = picked_rows(table)
        if len(rows) > 0:
            target = rows[0]
            if isinstance(target, dict):
                target = target["path"]
            launch(reveal_command(target))

    # Overview
    ov = make_view("overview", "Overview")
    ov_files = tk.StringVar(value="No folder analyzed yet.")
    ov_drive = tk.StringVar(value="Choose a folder or drive above and press Analyze. Nothing is changed without asking.")
    ov_reclaim = tk.StringVar(value="")
    ttk.Label(ov["frame"], textvariable=ov_files, style="Strong.TLabel").pack(anchor="w")
    ttk.Label(ov["frame"], textvariable=ov_drive).pack(anchor="w", pady=(2, 0))
    ttk.Label(ov["frame"], textvariable=ov_reclaim).pack(anchor="w", pady=(2, 10))
    ov["actions"].pack_forget()
    ov["actions"].pack(fill="x", pady=(0, 8))
    ttk.Label(ov["frame"], text="What takes space, by type", style="Strong.TLabel").pack(anchor="w", pady=(4, 4))
    type_table = make_table(
        ov["frame"],
        [("type", "Type", 200, "w", True), ("files", "Files", 110, "e", False),
         ("size", "Size", 110, "e", False), ("share", "Share", 90, "e", False)],
        lambda row: (row["type"], human_count(row["files"]), human_size(row["bytes"]), row["share"]),
        {"type": lambda row: row["type"].lower(), "files": lambda row: row["files"], "size": lambda row: row["bytes"]})
    type_table["frame"].pack(fill="both", expand=True)

    def trash_folder():
        if state["root"] == "":
            return ""
        return os.path.join(state["root"], TRASH_DIR_NAME)

    add_button(ov, "Open trash folder", lambda: launch(open_folder_command(trash_folder())),
               lambda: trash_folder() != "" and os.path.isdir(trash_folder()), False)

    # Largest files
    lg = make_view("largest", "Largest files")
    lg_table = make_table(lg["frame"], file_columns, file_values, file_sorts)
    add_button(lg, "Move to trash", lambda: trash_rows(lg_table), lambda: has_rows(lg_table), True)
    add_button(lg, "Show in folder", lambda: reveal_first(lg_table), lambda: has_selection(lg_table), False)
    lg_table["frame"].pack(fill="both", expand=True)
    primary["largest"] = lambda: trash_rows(lg_table)

    # Old files
    od = make_view("old", "Old files")
    old_table = make_table(od["frame"], file_columns, file_values, file_sorts)
    add_button(od, "Move to trash", lambda: trash_rows(old_table), lambda: has_rows(old_table), True)
    add_button(od, "Show in folder", lambda: reveal_first(old_table), lambda: has_selection(old_table), False)
    ttk.Label(od["actions"], text="Not changed for").pack(side="left", padx=(12, 4))
    days_var = tk.IntVar(value=state["old_days"])
    days_box = ttk.Spinbox(od["actions"], from_=1, to=20000, increment=30, textvariable=days_var, width=7,
                           command=lambda: change_days())
    days_box.pack(side="left")
    ttk.Label(od["actions"], text="days").pack(side="left", padx=(4, 0))
    days_box.bind("<Return>", lambda event: change_days())
    days_box.bind("<FocusOut>", lambda event: change_days())
    old_table["frame"].pack(fill="both", expand=True)
    primary["old"] = lambda: trash_rows(old_table)

    def change_days():
        try:
            days = int(days_var.get())
        except (ValueError, tk.TclError):
            days_var.set(state["old_days"])
            return
        if days < 1 or days == state["old_days"]:
            return
        state["old_days"] = days
        settings["stale_days"] = days
        save_settings(path_to_settings, settings)
        if state["report"] is not None:
            state["report"]["stale"] = stale_files(state["report"]["files"], days, time.time())
            refresh_all()

    # Duplicates
    dp = make_view("duplicates", "Duplicates")
    dup_holder = ttk.Frame(dp["frame"])
    dup_tree = ttk.Treeview(dup_holder, columns=("size", "modified", "action"), show="tree headings",
                            selectmode="extended")
    dup_tree.heading("#0", text="File", anchor="w")
    dup_tree.column("#0", width=340, stretch=True)
    dup_tree.heading("size", text="Size", anchor="e")
    dup_tree.column("size", width=100, anchor="e", stretch=False)
    dup_tree.heading("modified", text="Changed", anchor="e")
    dup_tree.column("modified", width=110, anchor="e", stretch=False)
    dup_tree.heading("action", text="")
    dup_tree.column("action", width=90, anchor="w", stretch=False)
    dup_tree.tag_configure("group", font=strong_font)
    dup_tree.tag_configure("keep", foreground="#2e7d32")
    dup_tree.tag_configure("trash", foreground="#a33a1a")
    dup_bar = ttk.Scrollbar(dup_holder, orient="vertical", command=dup_tree.yview)
    dup_tree.configure(yscrollcommand=dup_bar.set)
    dup_note = tk.StringVar(value="")
    wrapping(ttk.Label(dup_holder, textvariable=dup_note, style="Muted.TLabel")).pack(side="bottom", fill="x", pady=(4, 0))
    dup_tree.pack(side="left", fill="both", expand=True)
    dup_bar.pack(side="left", fill="y")
    dup_tree.bind("<<TreeviewSelect>>", lambda event: refresh_buttons())

    def has_groups():
        return state["groups"] is not None and len(state["groups"]) > 0

    def selected_group_numbers():
        numbers = {}
        for iid in dup_tree.selection():
            numbers[int(iid.split(":")[0][1:])] = True
        return numbers

    def selected_copies():
        """(group number, index) of each selected file row."""
        pairs = []
        for iid in dup_tree.selection():
            if ":" in iid:
                parts = iid.split(":")
                pairs.append((int(parts[0][1:]), int(parts[1])))
        return pairs

    def keep_selected():
        groups = state["groups"]
        for pair in selected_copies():
            group = groups[pair[0]]
            for info in group:
                if info["path"] in state["keep"]:
                    del state["keep"][info["path"]]
            state["keep"][group[pair[1]]["path"]] = True
        refresh_duplicates()

    def trash_duplicates():
        groups = state["groups"]
        numbers = selected_group_numbers()
        chosen = []
        index = 0
        while index < len(groups):
            if len(numbers) == 0 or index in numbers:
                chosen.append(groups[index])
            index = index + 1
        moves = plan_duplicate_removal(state["root"], chosen, state["keep"])
        savings = duplicate_savings(chosen)
        scope = "selected groups" if len(numbers) > 0 else "all groups"
        if not ask("Move " + plural(len(moves), "extra copy") + " (" + human_size(savings["bytes"]) + ") from "
                   + scope + " to the trash folder?\n\nOne copy of each file stays. Undo is available."):
            return
        apply_and_forget("Moving duplicates to the trash", moves, "Moved")

    add_button(dp, "Move extra copies to trash", lambda: trash_duplicates(), has_groups, True)
    add_button(dp, "Keep selected copy", lambda: keep_selected(), lambda: len(selected_copies()) > 0, False)
    add_button(dp, "Show in folder", lambda: reveal_copy(), lambda: len(selected_copies()) > 0, False)
    dup_holder.pack(fill="both", expand=True)
    primary["duplicates"] = lambda: trash_duplicates()

    def reveal_copy():
        pairs = selected_copies()
        if len(pairs) > 0:
            launch(reveal_command(state["groups"][pairs[0][0]][pairs[0][1]]["path"]))

    # Empty folders
    em = make_view("empty", "Empty folders")
    empty_table = make_table(em["frame"], [("path", "Folder", 700, "w", True)], lambda row: (rel(row),),
                             {"path": text_key})
    add_button(em, "Remove", lambda: remove_empty(), lambda: has_rows(empty_table), True)
    add_button(em, "Show in folder", lambda: reveal_first(empty_table), lambda: has_selection(empty_table), False)
    empty_table["frame"].pack(fill="both", expand=True)
    primary["empty"] = lambda: remove_empty()

    def remove_empty():
        chosen = {}
        for folder in picked_rows(empty_table):
            chosen[folder] = True
        folders = select_empty_dirs(state["report"]["empty_dirs"], chosen, state["root"])
        if not ask("Remove " + plural(len(folders), "empty folder") + "?\n\nThey hold no files. Undo is available."):
            return
        apply_and_forget("Removing empty folders", plan_empty_dir_removal(folders), "Removed")

    # Unreadable
    er = make_view("errors", "Unreadable")
    error_table = make_table(er["frame"], [("path", "Path and problem", 700, "w", True)], lambda row: (row,),
                             {"path": text_key})
    error_table["frame"].pack(fill="both", expand=True)

    # Organize
    og = make_view("organize", "Organize")
    org_mode = tk.StringVar(value="type")
    org_table = make_table(og["frame"], [("from", "File", 360, "w", True), ("to", "Moves to", 360, "w", True)],
                           lambda row: (os.path.basename(row["source"]), relative_path(state["org_root"], row["target"])),
                           {"from": lambda row: row["source"].lower(), "to": lambda row: row["target"].lower()})
    add_button(og, "Preview", lambda: preview_organize(), lambda: True, False)
    add_button(og, "Apply", lambda: apply_organize(), lambda: len(state["org_moves"]) > 0, True)
    ttk.Radiobutton(og["actions"], text="By type", variable=org_mode, value="type",
                    command=lambda: clear_organize()).pack(side="left", padx=(12, 4))
    ttk.Radiobutton(og["actions"], text="By year-month", variable=org_mode, value="date",
                    command=lambda: clear_organize()).pack(side="left")
    org_table["frame"].pack(fill="both", expand=True)

    def clear_organize():
        state["org_moves"] = []
        fill_table(org_table, [])
        og["subtitle"].set("Sorts the files directly inside the folder into subfolders. Folders are left alone.")
        refresh_buttons()

    def preview_organize():
        folder = current_folder()
        if folder == "":
            return
        mode = org_mode.get()

        def finish(result):
            state["org_moves"] = result["value"]
            state["org_root"] = folder
            fill_table(org_table, result["value"])
            targets = {}
            for move in result["value"]:
                targets[os.path.dirname(move["target"])] = True
            og["subtitle"].set(plural(len(result["value"]), "file") + " would move into "
                               + plural(len(targets), "folder") + " in " + folder)

        run_job("Planning", lambda post: plan_organize(folder, mode, state["cancel"]), finish, None, None)

    def apply_organize():
        moves = state["org_moves"]
        root = state["org_root"]
        if not ask("Move " + plural(len(moves), "file") + " into subfolders of " + root + "?\n\nUndo is available."):
            return

        def finish(result):
            report_apply(result, "Moved")
            clear_organize()
            if state["report"] is not None and os.path.normcase(state["root"]) == os.path.normcase(root):
                window.after(10, analyze)

        run_job("Organizing", lambda post: apply_moves(root, moves, state["cancel"], progress_sender(post)),
                finish, None, None)

    # Network shares
    nw = make_view("network", "Network shares")
    nw["subtitle"].set("Saved shares. Passwords are never stored; Windows asks for them when mapping if needed.")
    net_rows = []
    net_table = make_table(
        nw["frame"],
        [("name", "Name", 140, "w", False), ("unc", "Share", 240, "w", True), ("letter", "Letter", 60, "center", False),
         ("status", "Status", 260, "w", True), ("free", "Free", 90, "e", False), ("total", "Total", 90, "e", False)],
        lambda row: (row["share"]["name"], row["share"]["unc"], row["share"]["letter"] or "\u2014",
                     row["status"], row["free"], row["total"]),
        {})
    add_button(nw, "Add share\u2026", lambda: add_share_dialog(), lambda: True, True)
    add_button(nw, "Check all", lambda: check_shares(), lambda: len(net_rows) > 0, False)
    add_button(nw, "Analyze", lambda: analyze_share(), lambda: has_selection(net_table), False)
    add_button(nw, "Map", lambda: map_selected(), lambda: has_selection(net_table), False)
    add_button(nw, "Disconnect", lambda: unmap_selected(), lambda: has_selection(net_table), False)
    add_button(nw, "Back up a folder here\u2026", lambda: backup_to_share(), lambda: has_selection(net_table), False)
    add_button(nw, "Remove", lambda: remove_share(), lambda: has_selection(net_table), False)
    net_table["frame"].pack(fill="both", expand=True)

    def rebuild_shares():
        old_rows = {}
        for row in net_rows:
            old_rows[row["share"]["unc"].lower()] = row
        del net_rows[:]
        for share in settings["shares"]:
            key = share["unc"].lower()
            if key in old_rows:
                old_rows[key]["share"] = share
                net_rows.append(old_rows[key])
            else:
                net_rows.append({"share": share, "status": "not checked", "free": "", "total": ""})
        fill_table(net_table, list(net_rows))
        refresh_buttons()

    def selected_share():
        chosen = net_table["tree"].selection()
        if len(chosen) == 0:
            return None
        return net_table["rows"][int(chosen[0])]["share"]

    def add_share_dialog():
        dialog = tk.Toplevel(window)
        dialog.title("Add network share")
        dialog.transient(window)
        dialog.resizable(False, False)
        form = ttk.Frame(dialog, padding=14)
        form.pack(fill="both", expand=True)
        unc_var = tk.StringVar()
        name_var = tk.StringVar()
        letter_var = tk.StringVar()
        problem = tk.StringVar(value="")
        ttk.Label(form, text="Share path").grid(row=0, column=0, sticky="w", pady=3)
        unc_entry = ttk.Entry(form, textvariable=unc_var, width=36)
        unc_entry.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(form, text="e.g. \\\\nas01\\media", style="Muted.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Name").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=name_var, width=36).grid(row=2, column=1, sticky="we", pady=3)
        ttk.Label(form, text="Drive letter").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=letter_var, width=6).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(form, textvariable=problem, foreground="#a33a1a").grid(row=4, column=0, columnspan=2, sticky="w")
        row = ttk.Frame(form)
        row.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def save():
            unc = unc_var.get().strip()
            letter = letter_var.get().strip().upper()
            if len(letter) == 1:
                letter = letter + ":"
            if unc_host(unc) == "":
                problem.set("The share path must look like \\\\host\\share.")
                return
            if not valid_letter(letter):
                problem.set("The drive letter must be D: to Z:, or empty.")
                return
            name = name_var.get().strip()
            if name == "":
                name = unc_host(unc)
            settings["shares"].append({"name": name, "unc": unc, "letter": letter})
            save_settings(path_to_settings, settings)
            log("added share " + name + " (" + unc + ")")
            dialog.destroy()
            rebuild_shares()

        ttk.Button(row, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(row, text="Add", style="Primary.TButton", command=save).pack(side="right", padx=6)
        dialog.bind("<Return>", lambda event: save())
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        unc_entry.focus_set()
        dialog.grab_set()

    def check_shares():
        rows = list(net_rows)

        def work(post):
            results = []
            for row in rows:
                if is_cancelled(state["cancel"]):
                    break
                results.append((row, check_share(row["share"])))
            return success(results)

        def finish(result):
            for pair in result["value"]:
                row = pair[0]
                found = pair[1]
                if found["reachable"]:
                    row["status"] = "online"
                    row["free"] = human_size(found["free"])
                    row["total"] = human_size(found["total"])
                else:
                    row["status"] = found["error"]
                    row["free"] = ""
                    row["total"] = ""
                log("  " + row["share"]["name"] + ": " + row["status"])
            fill_table(net_table, list(net_rows))

        run_job("Checking shares", work, finish, None, None)

    def analyze_share():
        share = selected_share()
        if share is not None:
            folder_var.set(share_path(share))
            analyze()

    def map_selected():
        share = selected_share()
        if share is None:
            return
        run_job("Mapping " + share["unc"], lambda post: map_share(share), lambda result: check_shares_later(), None, None)

    def unmap_selected():
        share = selected_share()
        if share is None or not ask("Disconnect " + share_path(share) + "?"):
            return
        run_job("Disconnecting " + share["unc"], lambda post: unmap_share(share), lambda result: check_shares_later(),
                None, None)

    def check_shares_later():
        window.after(10, check_shares)

    def remove_share():
        share = selected_share()
        if share is None:
            return
        settings["shares"].remove(share)
        save_settings(path_to_settings, settings)
        log("removed share " + share["name"] + " from the list")
        rebuild_shares()

    def backup_to_share():
        share = selected_share()
        if share is None:
            return
        start = settings["last_folder"] if settings["last_folder"] != "" else None
        folder = filedialog.askdirectory(parent=window, initialdir=start, title="Folder to back up to " + share["name"])
        if not folder:
            return
        folder = os.path.normpath(folder)
        target = os.path.join(share_path(share), os.path.basename(folder))

        def finish(result):
            copies = result["value"]
            total = 0
            for copy in copies:
                total = total + copy["size"]
            if len(copies) == 0:
                status_var.set(target + " is already up to date")
                log("  up to date")
                return
            if not ask("Copy " + plural(len(copies), "new or changed file") + " (" + human_size(total) + ") to "
                       + target + "?\n\nNothing in the target is deleted."):
                return
            run_job("Backing up to " + target,
                    lambda post: apply_copies(copies, state["cancel"], progress_sender(post)),
                    lambda copy_result: report_apply(copy_result, "Copied"), None, None)

        run_job("Comparing " + folder + " with " + target,
                lambda post: plan_sync(folder, target, state["cancel"], progress_sender(post)), finish, None, None)

    # Activity
    ac = make_view("activity", "Activity")
    ac["subtitle"].set("Everything done in this session.")
    log_holder = ttk.Frame(ac["frame"])
    log_text = tk.Text(log_holder, wrap="none", height=10, state="disabled", relief="flat", padx=6, pady=6)
    log_bar = ttk.Scrollbar(log_holder, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_bar.set)
    log_text.pack(side="left", fill="both", expand=True)
    log_bar.pack(side="left", fill="y")

    def clear_log():
        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")

    add_button(ac, "Clear", clear_log, lambda: True, False)
    log_holder.pack(fill="both", expand=True)

    # --- refreshing the views from state ---------------------------------------------------------
    def set_side(key, text):
        sidebar.set(key, "info", text)

    def refresh_all():
        report = state["report"]
        if report is None:
            for entry in VIEWS:
                set_side(entry[0], "")
            refresh_buttons()
            return
        stale_total = total_size(report["stale"])
        set_side("overview", human_size(report["total_bytes"]))
        set_side("largest", human_size(report["largest"][0]["size"]) if len(report["largest"]) > 0 else "")
        set_side("old", human_count(len(report["stale"])) + " \u00b7 " + human_size(stale_total))
        set_side("empty", human_count(len(report["empty_dirs"])))
        set_side("errors", human_count(len(report["errors"])))
        if state["groups"] is None:
            set_side("duplicates", state["dup_note"])
        else:
            savings = duplicate_savings(state["groups"])
            set_side("duplicates", human_count(savings["copies"]) + " \u00b7 " + human_size(savings["bytes"]))

        # Overview
        ov_files.set(plural(report["file_count"], "file") + " \u00b7 " + human_size(report["total_bytes"])
                     + " in " + plural(report["dir_count"], "folder"))
        if report["drive_total"] > 0:
            ov_drive.set("Drive: " + human_size(report["drive_free"]) + " free of " + human_size(report["drive_total"]))
        else:
            ov_drive.set("")
        parts = []
        if state["groups"] is not None:
            savings = duplicate_savings(state["groups"])
            if savings["copies"] > 0:
                parts.append(human_size(savings["bytes"]) + " in " + plural(savings["copies"], "duplicate copy"))
        if len(report["stale"]) > 0:
            parts.append(human_size(stale_total) + " in " + plural(len(report["stale"]), "old file"))
        if len(report["empty_dirs"]) > 0:
            parts.append(plural(len(report["empty_dirs"]), "empty folder"))
        if len(parts) > 0:
            ov_reclaim.set("Worth a look: " + "  \u00b7  ".join(parts))
        else:
            ov_reclaim.set("Nothing obvious to clean up.")
        type_rows = []
        for name in report["by_type"]:
            entry = report["by_type"][name]
            share = 0.0
            if report["total_bytes"] > 0:
                share = 100.0 * entry["bytes"] / report["total_bytes"]
            type_rows.append({"type": name, "files": entry["files"], "bytes": entry["bytes"], "share": "%.1f %%" % share})
        type_rows.sort(key=lambda row: row["bytes"], reverse=True)
        fill_table(type_table, type_rows)
        ov["subtitle"].set(report["root"])

        # Lists
        fill_table(lg_table, list(report["largest"]))
        lg["subtitle"].set("The " + plural(len(report["largest"]), "biggest file") + ". Select some, or act on all.")
        fill_table(old_table, list(report["stale"]))
        od["subtitle"].set(plural(len(report["stale"]), "file") + " (" + human_size(stale_total)
                           + ") not changed for " + plural(state["old_days"], "day") + ".")
        empty_rows = list(report["empty_dirs"])
        empty_rows.sort(key=text_key)
        fill_table(empty_table, empty_rows)
        em["subtitle"].set(plural(len(report["empty_dirs"]), "folder") + " with nothing in them, including nested ones.")
        fill_table(error_table, list(report["errors"]))
        er["subtitle"].set(plural(len(report["errors"]), "path") + " could not be read (no rights, in use, or gone).")
        refresh_duplicates()
        refresh_buttons()

    def refresh_duplicates():
        dup_tree.delete(*dup_tree.get_children())
        groups = state["groups"]
        if groups is None:
            dp["subtitle"].set(state["dup_note"] if state["dup_note"] != "" else "Analyze a folder to compare its files.")
            dup_note.set("")
            refresh_buttons()
            return
        savings = duplicate_savings(groups)
        dp["subtitle"].set(plural(len(groups), "file") + " stored more than once; " + human_size(savings["bytes"])
                           + " in extra copies. Green is kept, red goes to the trash.")
        rows = 0
        number = 0
        while number < len(groups) and rows < MAX_ROWS:
            group = groups[number]
            keeper = keeper_index(group, state["keep"])
            parent = "g" + str(number)
            dup_tree.insert("", "end", iid=parent, open=True, tags=("group",),
                            text=os.path.basename(group[0]["path"]) + "  \u00b7  " + plural(len(group), "copy")
                            + "  \u00b7  " + human_size(group_savings(group)) + " in extra copies",
                            values=(human_size(group[0]["size"]), "", ""))
            index = 0
            while index < len(group):
                info = group[index]
                tag = "keep" if index == keeper else "trash"
                dup_tree.insert(parent, "end", iid=parent + ":" + str(index), text=rel(info["path"]), tags=(tag,),
                                values=(human_size(info["size"]), human_date(info["modified"]),
                                        "keep" if index == keeper else "to trash"))
                index = index + 1
            rows = rows + len(group) + 1
            number = number + 1
        if number < len(groups):
            dup_note.set("Showing the " + human_count(number) + " groups that save the most, of " + human_count(len(groups))
                         + ". With nothing selected, actions apply to all of them.")
        else:
            dup_note.set("Select rows to act on some groups only. \u201cKeep selected copy\u201d changes which one stays.")
        refresh_buttons()

    def show_view(key):
        state["view"] = key
        views[key]["frame"].tkraise()
        if tuple(sidebar.selection()) != (key,):
            sidebar.selection_set(key)

    def on_sidebar(event):
        chosen = sidebar.selection()
        if len(chosen) == 0:
            return
        key = chosen[0]
        if key not in views:
            children = sidebar.get_children(key)
            if len(children) > 0:
                sidebar.selection_set(children[0])
            return
        if key != state["view"]:
            show_view(key)

    sidebar.bind("<<TreeviewSelect>>", on_sidebar)

    # --- the main actions --------------------------------------------------------------------------
    def folder_choices():
        choices = []
        seen = {}
        candidates = list(settings["recent"])
        for drive in list_drives():
            candidates.append(drive)
        for share in settings["shares"]:
            candidates.append(share_path(share))
        for item in candidates:
            key = os.path.normcase(item)
            if key not in seen:
                seen[key] = True
                choices.append(item)
        return choices

    folder_box.configure(postcommand=lambda: folder_box.configure(values=folder_choices()))

    def browse():
        start = folder_var.get().strip()
        chosen = filedialog.askdirectory(parent=window, initialdir=start if start != "" else None)
        if chosen:
            folder_var.set(os.path.normpath(chosen))
            analyze()

    def current_folder():
        folder = normalize_folder(folder_var.get())
        if folder == "" or not os.path.isdir(folder):
            status_var.set("Choose an existing folder or drive first.")
            folder_box.focus_set()
            return ""
        folder_var.set(folder)
        settings["last_folder"] = folder
        settings["recent"] = add_recent(settings["recent"], folder, 10)
        save_settings(path_to_settings, settings)
        return folder

    def analyze():
        if state["busy"]:
            return
        root = current_folder()
        if root == "":
            return
        days = state["old_days"]
        cancel_flag = state["cancel"]

        def work(post):
            send = progress_sender(post)
            scanned = scan(root, LARGEST_COUNT, days, time.time(), cancel_flag, send)
            if not scanned["ok"]:
                return scanned
            post("scan", scanned["value"])
            return find_duplicates_in(scanned["value"]["files"], cancel_flag, send)

        def on_message(kind, value):
            if kind == "scan":
                state["root"] = root
                state["report"] = value
                state["groups"] = None
                state["keep"] = {}
                state["dup_note"] = "comparing\u2026"
                refresh_all()
                log("  " + plural(value["file_count"], "file") + ", " + human_size(value["total_bytes"]))
                if state["view"] in ("network", "organize", "activity"):
                    show_view("overview")

        def finish(result):
            state["groups"] = result["value"]
            state["dup_note"] = ""
            refresh_all()
            savings = duplicate_savings(result["value"])
            log("  " + plural(savings["copies"], "duplicate copy") + ", " + human_size(savings["bytes"]))
            status_var.set("Analyzed " + root + " \u2014 " + plural(state["report"]["file_count"], "file") + ", "
                           + human_size(savings["bytes"]) + " in duplicate copies")

        def on_fail(result):
            if state["report"] is not None and state["root"] == root:
                state["dup_note"] = "not compared (" + result["error"] + ")"
                refresh_all()

        run_job("Analyzing " + root, work, finish, on_message, on_fail)

    def apply_and_forget(label, moves, verb):
        """Apply moves, then drop the moved paths from the results instead of analyzing again."""
        root = state["root"]

        def finish(result):
            report_apply(result, verb)
            gone = {}
            for move in result["value"]["moved"]:
                gone[move["source"]] = True
            state["report"] = remove_from_report(state["report"], gone, LARGEST_COUNT, state["old_days"], time.time())
            if state["groups"] is not None:
                state["groups"] = remove_from_groups(state["groups"], gone)
            refresh_all()

        run_job(label, lambda post: apply_moves(root, moves, state["cancel"], progress_sender(post)), finish, None, None)

    def trash_rows(table):
        rows = picked_rows(table)
        if len(rows) == 0:
            return
        scope = "selected " if has_selection(table) else ""
        if not ask("Move " + plural(len(rows), scope + "file") + " (" + human_size(total_size(rows))
                   + ") to the trash folder in " + state["root"] + "?\n\nUndo is available."):
            return
        apply_and_forget("Moving files to the trash", plan_trash(state["root"], rows), "Moved")

    def undo():
        root = state["root"]
        if state["busy"] or root == "" or not os.path.isfile(undo_log_path(root)):
            return
        if not ask("Undo the last change made in " + root + "?"):
            return

        def finish(result):
            report_apply(result, "Restored")
            window.after(10, analyze)

        run_job("Undoing the last change", lambda post: undo_last(root), finish, None, None)

    def about():
        messagebox.showinfo("About", APP_NAME + " " + __version__ + "\n\nGeneric Company Inc. is fictional.\n"
                            "License: AGPL-3.0.\n\n" + ICON_CREDIT, parent=window)

    def on_delete(event):
        if isinstance(event.widget, (ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Entry, tk.Text)):
            return
        if state["busy"] or state["report"] is None:
            return
        if state["view"] in primary:
            primary[state["view"]]()

    def double_click(table):
        table["tree"].bind("<Double-1>", lambda event: reveal_first(table))

    for table in (lg_table, old_table, empty_table):
        double_click(table)
    dup_tree.bind("<Double-1>", lambda event: reveal_copy())

    def close():
        state["cancel"][0] = True
        settings["geometry"] = window.geometry()
        save_settings(path_to_settings, settings)
        window.destroy()

    folder_box.bind("<Return>", lambda event: analyze())
    window.bind("<F5>", lambda event: analyze())
    window.bind("<Control-z>", lambda event: undo())
    window.bind("<Delete>", on_delete)
    window.protocol("WM_DELETE_WINDOW", close)

    rebuild_shares()
    clear_organize()
    show_view("overview")
    refresh_all()
    log(APP_NAME + " " + __version__ + " started")
    folder_box.focus_set()

    if start_view in views:
        show_view(start_view)
    if start_folder != "":
        folder_var.set(start_folder)
        window.after(100, analyze)

    if smoke_path != "":
        def write_smoke_report():
            if state["busy"]:
                window.after(200, write_smoke_report)
                return
            report = {"app_id": APP_ID, "version": __version__, "title": window.title(), "icon_set": icon_set,
                      "views": [], "shares": len(settings["shares"]), "folder": state["root"],
                      "view": state["view"], "status": status_var.get(), "sidebar": {}}
            for entry in VIEWS:
                report["views"].append(entry[1])
                report["sidebar"][entry[0]] = sidebar.set(entry[0], "info")
            handle = open(smoke_path, "w", encoding="utf-8")
            json.dump(report, handle, indent=2)
            handle.close()
            window.destroy()

        window.after(800, write_smoke_report)

    window.mainloop()
    return 0


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing."""
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        return selftest()
    smoke_path = option_value(arguments, "--smoke")
    start_folder = option_value(arguments, "--folder")
    start_view = option_value(arguments, "--view")
    if smoke_path is None or start_folder is None or start_view is None:
        print("--smoke, --folder and --view each need a value")
        return 2
    return run_gui(smoke_path, start_folder, start_view)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=4b9f63f495d910d72e7a2881c26304f122a166bcb7aa5b4c2a998a79b879f6f8 ====
