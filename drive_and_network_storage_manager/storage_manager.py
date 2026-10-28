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
  ScanReport {"root": str, "file_count": int, "total_bytes": int, "largest": [FileInfo],
              "stale": [FileInfo], "empty_dirs": [str], "errors": [str]}
  Move       {"source": str, "target": str}
  Share      {"name": str, "unc": str, "letter": str}
  ShareState {"reachable": bool, "total": int, "used": int, "free": int, "error": str}

Usage
  python storage_manager.py              open the window
  python storage_manager.py --selftest   run the built-in checks and exit
  python storage_manager.py --version
  python storage_manager.py --smoke FILE open the window, write a JSON report to FILE, close
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

__version__ = "0.1.0"
APP_NAME = "Generic Company Storage Manager"
APP_ID = "GenericCompany.Storage"
ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon", "app.ico")
ICON_CREDIT = ("Icon: drive_network.png from the Silk icon set by Mark James (famfamfam.com/lab/icons/silk), "
               "CC BY 2.5 (creativecommons.org/licenses/by/2.5). Changed: enlarged by whole pixels.")

TRASH_DIR_NAME = "_storage_manager_trash"
UNDO_LOG_NAME = "_storage_manager_undo.json"
CHUNK_SIZE = 1024 * 1024
SECONDS_PER_DAY = 86400

# Extension (lower case, with dot) -> folder name used by organize_by_type.
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


def is_own_folder(name):
    return name == TRASH_DIR_NAME


# ---- walking ------------------------------------------------------------------------------------

def list_files(root, cancel_flag):
    """Every file under root (skipping our trash folder) -> (list of FileInfo, list of error strings)."""
    files = []
    errors = []
    pending = [root]
    while len(pending) > 0:
        if is_cancelled(cancel_flag):
            break
        folder = pending.pop()
        try:
            names = os.listdir(folder)
        except OSError as e:
            errors.append(folder + ": " + str(e))
            continue
        for name in names:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            if os.path.isdir(path):
                if not is_own_folder(name):
                    pending.append(path)
                continue
            if name == UNDO_LOG_NAME:
                continue
            try:
                info = os.stat(path)
            except OSError as e:
                errors.append(path + ": " + str(e))
                continue
            files.append({"path": path, "size": info.st_size, "modified": info.st_mtime})
    return files, errors


def find_empty_dirs(root):
    """Folders under root (not root itself) that contain nothing, deepest first."""
    empty = []
    walk = []
    for folder, subdirs, names in os.walk(root, topdown=False):
        walk.append((folder, subdirs, names))
    empty_set = {}
    for entry in walk:
        folder = entry[0]
        subdirs = entry[1]
        names = entry[2]
        if folder == root or is_own_folder(os.path.basename(folder)):
            continue
        if len(names) > 0:
            continue
        all_children_empty = True
        for sub in subdirs:
            if os.path.join(folder, sub) not in empty_set:
                all_children_empty = False
                break
        if all_children_empty:
            empty_set[folder] = True
            empty.append(folder)
    return empty


def sort_by_size_desc(files):
    result = list(files)
    result.sort(key=file_size, reverse=True)
    return result


def file_size(info):
    return info["size"]


# ---- scan ---------------------------------------------------------------------------------------

def scan(root, largest_count, stale_days, now, cancel_flag):
    """Summarize a folder -> Result(ScanReport)."""
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    files, errors = list_files(root, cancel_flag)
    total = 0
    stale = []
    cutoff = now - stale_days * SECONDS_PER_DAY
    for info in files:
        total = total + info["size"]
        if info["modified"] < cutoff:
            stale.append(info)
    by_size = sort_by_size_desc(files)
    report = {
        "root": root,
        "file_count": len(files),
        "total_bytes": total,
        "largest": by_size[:largest_count],
        "stale": sort_by_size_desc(stale),
        "empty_dirs": find_empty_dirs(root),
        "errors": errors,
    }
    return success(report)


# ---- duplicates ---------------------------------------------------------------------------------

def hash_file(path):
    """SHA-256 hex of a file -> Result(str)."""
    digest = hashlib.sha256()
    try:
        handle = open(path, "rb")
    except OSError as e:
        return failure(str(e))
    try:
        while True:
            block = handle.read(CHUNK_SIZE)
            if len(block) == 0:
                break
            digest.update(block)
    except OSError as e:
        handle.close()
        return failure(str(e))
    handle.close()
    return success(digest.hexdigest())


def find_duplicates(root, cancel_flag):
    """Groups of identical files (2+ each, empty files ignored) -> Result(list of list of FileInfo).

    Files are grouped by size first, and only same-size files are hashed.
    """
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    files, _ = list_files(root, cancel_flag)
    by_size = {}
    for info in files:
        if info["size"] == 0:
            continue
        key = info["size"]
        if key not in by_size:
            by_size[key] = []
        by_size[key].append(info)
    groups = []
    for size in sorted(by_size.keys(), reverse=True):
        candidates = by_size[size]
        if len(candidates) < 2:
            continue
        by_hash = {}
        for info in candidates:
            if is_cancelled(cancel_flag):
                return failure("cancelled")
            hashed = hash_file(info["path"])
            if not hashed["ok"]:
                continue
            if hashed["value"] not in by_hash:
                by_hash[hashed["value"]] = []
            by_hash[hashed["value"]].append(info)
        for digest in sorted(by_hash.keys()):
            group = by_hash[digest]
            if len(group) > 1:
                group.sort(key=file_path)
                groups.append(group)
    return success(groups)


def file_path(info):
    return info["path"]


def plan_duplicate_removal(root, groups):
    """Keep the first file of each group, send the rest to the trash -> list of Move."""
    moves = []
    for group in groups:
        index = 1
        while index < len(group):
            moves.append({"source": group[index]["path"], "target": trash_target(root, group[index]["path"])})
            index = index + 1
    return moves


def trash_target(root, path):
    relative = os.path.relpath(path, root)
    return os.path.join(root, TRASH_DIR_NAME, relative)


def plan_empty_dir_removal(empty_dirs):
    """Empty folders are removed directly (nothing to lose); returned as Moves with an empty target."""
    moves = []
    for folder in empty_dirs:
        moves.append({"source": folder, "target": ""})
    return moves


# ---- organize -----------------------------------------------------------------------------------

def type_folder_for(path):
    extension = os.path.splitext(path)[1].lower()
    if extension in TYPE_FOLDERS:
        return TYPE_FOLDERS[extension]
    return OTHER_FOLDER


def date_folder_for(modified):
    return time.strftime("%Y-%m", time.localtime(modified))


def plan_organize(root, mode, cancel_flag):
    """Moves that sort the files directly inside root into subfolders.

    mode is "type" or "date". Only top-level files move, so running it twice does nothing new.
    -> Result(list of Move)
    """
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    if mode != "type" and mode != "date":
        return failure("unknown mode: " + mode)
    moves = []
    taken = {}
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        return failure(str(e))
    for name in names:
        if is_cancelled(cancel_flag):
            return failure("cancelled")
        source = os.path.join(root, name)
        if not os.path.isfile(source) or name == UNDO_LOG_NAME:
            continue
        if mode == "type":
            folder = type_folder_for(source)
        else:
            folder = date_folder_for(os.path.getmtime(source))
        target = unique_target(os.path.join(root, folder, name), taken)
        taken[target.lower()] = True
        moves.append({"source": source, "target": target})
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
        return failure(str(e))
    return success(None)


def apply_moves(root, moves, cancel_flag):
    """Carry out a list of Move; record what was done so undo_last can reverse it.

    -> Result({"done": int, "errors": [str]})
    """
    done = []
    errors = []
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
                if not os.path.isdir(parent):
                    os.makedirs(parent)
                if os.path.exists(target):
                    errors.append("already exists: " + target)
                    continue
                shutil.move(source, target)
            done.append(move)
        except OSError as e:
            errors.append(source + ": " + str(e))
    if len(done) > 0:
        batches = read_undo_log(root)
        batches.append({"time": time.time(), "moves": done})
        written = write_undo_log(root, batches)
        if not written["ok"]:
            errors.append("undo log: " + written["error"])
    return success({"done": len(done), "errors": errors})


def undo_last(root):
    """Reverse the most recent applied batch -> Result({"done": int, "errors": [str]})."""
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
                if not os.path.isdir(move["source"]):
                    os.makedirs(move["source"])
            else:
                parent = os.path.dirname(move["source"])
                if not os.path.isdir(parent):
                    os.makedirs(parent)
                shutil.move(move["target"], move["source"])
            count = count + 1
        except OSError as e:
            errors.append(move["target"] + ": " + str(e))
    write_undo_log(root, batches)
    return success({"done": count, "errors": errors})


# ---- backup sync --------------------------------------------------------------------------------

def plan_sync(source_root, target_root, cancel_flag):
    """One-way copy plan: files that are missing or differ (size or newer time) in target.

    -> Result(list of Move) where each Move is a copy, not a move.
    """
    if not os.path.isdir(source_root):
        return failure("not a folder: " + source_root)
    files, _ = list_files(source_root, cancel_flag)
    copies = []
    for info in files:
        relative = os.path.relpath(info["path"], source_root)
        target = os.path.join(target_root, relative)
        if needs_copy(info, target):
            copies.append({"source": info["path"], "target": target})
    copies.sort(key=move_source)
    return success(copies)


def move_source(move):
    return move["source"]


def needs_copy(info, target):
    try:
        existing = os.stat(target)
    except OSError:
        return True
    if existing.st_size != info["size"]:
        return True
    return info["modified"] > existing.st_mtime + 2  # 2 s slack for FAT/SMB time rounding


def apply_copies(copies, cancel_flag, progress):
    """Copy files (keeping times). progress(done, total) is called after each file, may be None."""
    errors = []
    count = 0
    for copy in copies:
        if is_cancelled(cancel_flag):
            break
        try:
            parent = os.path.dirname(copy["target"])
            if not os.path.isdir(parent):
                os.makedirs(parent)
            shutil.copy2(copy["source"], copy["target"])
            count = count + 1
        except OSError as e:
            errors.append(copy["source"] + ": " + str(e))
        if progress is not None:
            progress(count + len(errors), len(copies))
    return success({"done": count, "errors": errors})


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
        state["error"] = str(e)
        return state
    state["reachable"] = True
    state["total"] = usage.total
    state["used"] = usage.used
    state["free"] = usage.free
    return state


# ---- settings -----------------------------------------------------------------------------------

def settings_path():
    base = os.environ.get("LOCALAPPDATA", "")
    if base == "":
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Generic Company Inc", APP_ID, "settings.json")


def default_settings():
    return {"shares": [], "last_folder": "", "stale_days": 365, "largest_count": 50}


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
        return failure(str(e))
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


def human_date(seconds):
    return time.strftime("%Y-%m-%d", time.localtime(seconds))


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

        print("scan")
        report = scan(root, 10, 365, now, None)
        check(report["ok"], "scan succeeds", failures)
        check(report["value"]["file_count"] == 5, "counts 5 files", failures)
        check(len(report["value"]["stale"]) == 1, "finds 1 stale file", failures)
        check(len(report["value"]["empty_dirs"]) == 2, "finds 2 empty folders (nested)", failures)
        check(scan(os.path.join(work, "missing"), 10, 365, now, None)["ok"] == False, "missing folder fails", failures)

        print("duplicates")
        dupes = find_duplicates(root, None)
        check(dupes["ok"] and len(dupes["value"]) == 1, "one duplicate group", failures)
        moves = plan_duplicate_removal(root, dupes["value"])
        check(len(moves) == 1, "one file planned for trash", failures)
        applied = apply_moves(root, moves, None)
        check(applied["value"]["done"] == 1, "duplicate moved to trash", failures)
        check(os.path.isfile(os.path.join(root, TRASH_DIR_NAME, "sub", "b.txt")), "trash keeps relative path", failures)
        undone = undo_last(root)
        check(undone["ok"] and os.path.isfile(os.path.join(root, "sub", "b.txt")), "undo restores duplicate", failures)

        print("empty folders")
        applied = apply_moves(root, plan_empty_dir_removal(find_empty_dirs(root)), None)
        check(not os.path.exists(os.path.join(root, "empty1")), "empty folders removed", failures)
        undo_last(root)
        check(os.path.isdir(os.path.join(root, "empty1", "empty2")), "undo recreates empty folders", failures)

        print("organize")
        planned = plan_organize(root, "type", None)
        check(planned["ok"] and len(planned["value"]) == 4, "4 top-level files planned", failures)
        apply_moves(root, planned["value"], None)
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

        print("names")
        taken = {}
        first = unique_target(os.path.join(root, "a.txt"), taken)
        check(first.endswith("a (2).txt"), "clash gets (2)", failures)

        print("sync")
        target = os.path.join(work, "backup")
        copies = plan_sync(root, target, None)
        check(copies["ok"] and len(copies["value"]) == 5, "5 files to copy", failures)
        apply_copies(copies["value"], None, None)
        check(len(plan_sync(root, target, None)["value"]) == 0, "nothing to copy after sync", failures)

        print("shares and settings")
        check(unc_host("\\\\nas01\\media\\x") == "nas01", "host from UNC", failures)
        check(unc_host("C:\\x") == "", "non-UNC has no host", failures)
        check(valid_letter("Z:") and not valid_letter("C:") and not valid_letter("ZZ"), "drive letter rules", failures)
        check(map_command({"name": "n", "unc": "\\\\h\\s", "letter": "Z:"})[2] == "Z:", "map command", failures)
        settings_file = os.path.join(work, "settings", "settings.json")
        saved = default_settings()
        saved["shares"].append({"name": "NAS", "unc": "\\\\nas\\share", "letter": "Y:"})
        save_settings(settings_file, saved)
        check(load_settings(settings_file)["shares"][0]["letter"] == "Y:", "settings round trip", failures)
        check(human_size(1536) == "1.5 KB", "human size", failures)
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


def run_gui(smoke_path):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    path_to_settings = settings_path()
    settings = load_settings(path_to_settings)
    state = {"busy": False, "cancel": [False], "moves": [], "copies": [], "root": "", "sync_target": ""}

    windows_identity()
    window = tk.Tk()
    window.title("Generic Company Inc. \u2014 Storage Manager " + __version__)
    window.geometry("980x640")
    window.minsize(760, 480)
    icon_set = set_icon(window)

    # --- shared: folder bar, status bar, log -----------------------------------------------------
    top = ttk.Frame(window, padding=6)
    top.pack(fill="x")
    ttk.Label(top, text="Folder:").pack(side="left")
    folder_var = tk.StringVar(value=settings["last_folder"])
    ttk.Entry(top, textvariable=folder_var).pack(side="left", fill="x", expand=True, padx=4)

    def browse():
        chosen = filedialog.askdirectory(initialdir=folder_var.get() or None)
        if chosen:
            folder_var.set(os.path.normpath(chosen))

    ttk.Button(top, text="Browse\u2026", command=browse).pack(side="left")

    bottom = ttk.Frame(window, padding=6)
    bottom.pack(side="bottom", fill="x")
    status_var = tk.StringVar(value="Ready")
    ttk.Label(bottom, textvariable=status_var).pack(side="left", fill="x", expand=True)
    progress = ttk.Progressbar(bottom, mode="indeterminate", length=160)
    progress.pack(side="left", padx=6)
    cancel_button = ttk.Button(bottom, text="Cancel", state="disabled")
    cancel_button.pack(side="left")

    def about():
        messagebox.showinfo("About", APP_NAME + " " + __version__ + "\n\nGeneric Company Inc. is fictional.\n"
                            "License: AGPL-3.0.\n\n" + ICON_CREDIT)

    ttk.Button(bottom, text="About", command=about).pack(side="left", padx=(6, 0))

    tabs = ttk.Notebook(window)
    tabs.pack(fill="both", expand=True, padx=6)

    log_text = tk.Text(tabs, wrap="none", height=10)

    def log(message):
        log_text.insert("end", time.strftime("%H:%M:%S") + "  " + message + "\n")
        log_text.see("end")

    def remember_folder():
        settings["last_folder"] = folder_var.get()
        save_settings(path_to_settings, settings)

    def current_folder():
        folder = folder_var.get().strip()
        if folder == "" or not os.path.isdir(folder):
            messagebox.showwarning(APP_NAME, "Choose an existing folder first.")
            return ""
        remember_folder()
        return folder

    def run_job(label, work, finish):
        """Run work() on a worker thread, then finish(result) on the GUI thread."""
        if state["busy"]:
            return
        state["busy"] = True
        state["cancel"][0] = False
        status_var.set(label + "\u2026")
        progress.start(12)
        cancel_button.configure(state="normal")
        log(label)
        holder = [None]

        def worker():
            try:
                holder[0] = work()
            except Exception as e:  # keep the window alive whatever happens in a job
                holder[0] = failure("unexpected error: " + str(e))
            window.after(0, done)

        def done():
            state["busy"] = False
            progress.stop()
            cancel_button.configure(state="disabled")
            result = holder[0]
            if isinstance(result, dict) and "ok" in result and not result["ok"]:
                status_var.set(label + " failed: " + result["error"])
                log("  failed: " + result["error"])
                return
            status_var.set(label + " done")
            finish(result)

        threading.Thread(target=worker, daemon=True).start()

    def cancel():
        state["cancel"][0] = True
        log("cancel requested")

    cancel_button.configure(command=cancel)

    def make_tree(parent, columns, widths):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        index = 0
        while index < len(columns):
            tree.heading(columns[index], text=columns[index])
            tree.column(columns[index], width=widths[index], anchor="w", stretch=(index == 0))
            index = index + 1
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        return frame, tree

    def clear(tree):
        for item in tree.get_children():
            tree.delete(item)

    def report_apply(result, verb):
        info = result["value"]
        log("  " + verb + " " + str(info["done"]) + " item(s)")
        for error in info["errors"]:
            log("  error: " + error)
        status_var.set(verb + " " + str(info["done"]) + " item(s), " + str(len(info["errors"])) + " error(s)")

    # --- Scan tab ---------------------------------------------------------------------------------
    scan_tab = ttk.Frame(tabs, padding=6)
    tabs.add(scan_tab, text="Scan")
    scan_bar = ttk.Frame(scan_tab)
    scan_bar.pack(fill="x")
    ttk.Label(scan_bar, text="Stale after (days):").pack(side="left")
    stale_var = tk.IntVar(value=settings["stale_days"])
    ttk.Spinbox(scan_bar, from_=1, to=10000, textvariable=stale_var, width=6).pack(side="left", padx=4)
    summary_var = tk.StringVar(value="")
    ttk.Label(scan_bar, textvariable=summary_var).pack(side="right")
    scan_view = ttk.Combobox(scan_bar, state="readonly", width=18,
                             values=["Largest files", "Stale files", "Empty folders", "Read errors"])
    scan_view.current(0)
    scan_frame, scan_tree = make_tree(scan_tab, ("Path", "Size", "Modified"), (560, 90, 100))
    last_report = [None]

    def show_scan(_event=None):
        clear(scan_tree)
        report = last_report[0]
        if report is None:
            return
        choice = scan_view.get()
        if choice == "Largest files" or choice == "Stale files":
            rows = report["largest"] if choice == "Largest files" else report["stale"]
            for info in rows:
                scan_tree.insert("", "end", values=(info["path"], human_size(info["size"]), human_date(info["modified"])))
        elif choice == "Empty folders":
            for folder in report["empty_dirs"]:
                scan_tree.insert("", "end", values=(folder, "", ""))
        else:
            for error in report["errors"]:
                scan_tree.insert("", "end", values=(error, "", ""))

    def start_scan():
        folder = current_folder()
        if folder == "":
            return
        days = stale_var.get()
        settings["stale_days"] = days
        save_settings(path_to_settings, settings)

        def work():
            return scan(folder, settings["largest_count"], days, time.time(), state["cancel"])

        def finish(result):
            report = result["value"]
            last_report[0] = report
            summary_var.set(str(report["file_count"]) + " files, " + human_size(report["total_bytes"]) + ", "
                            + str(len(report["empty_dirs"])) + " empty folders")
            log("  " + summary_var.get())
            show_scan()

        run_job("Scanning " + folder, work, finish)

    def remove_empty():
        report = last_report[0]
        if report is None or len(report["empty_dirs"]) == 0:
            messagebox.showinfo(APP_NAME, "Scan first; no empty folders found yet.")
            return
        count = len(report["empty_dirs"])
        if not messagebox.askyesno(APP_NAME, "Remove " + str(count) + " empty folder(s)? (Undo is available.)"):
            return
        root = report["root"]
        run_job("Removing empty folders", lambda: apply_moves(root, plan_empty_dir_removal(report["empty_dirs"]), state["cancel"]),
                lambda result: report_apply(result, "Removed"))

    scan_view.bind("<<ComboboxSelected>>", show_scan)
    ttk.Button(scan_bar, text="Scan", command=start_scan).pack(side="left", padx=4)
    scan_view.pack(side="left", padx=4)
    ttk.Button(scan_bar, text="Remove empty folders", command=remove_empty).pack(side="left", padx=4)
    scan_frame.pack(fill="both", expand=True, pady=6)

    # --- Duplicates tab ---------------------------------------------------------------------------
    dup_tab = ttk.Frame(tabs, padding=6)
    tabs.add(dup_tab, text="Duplicates")
    dup_bar = ttk.Frame(dup_tab)
    dup_bar.pack(fill="x")
    dup_frame, dup_tree = make_tree(dup_tab, ("Path", "Size", "Action"), (600, 90, 110))

    def start_duplicates():
        folder = current_folder()
        if folder == "":
            return

        def finish(result):
            clear(dup_tree)
            groups = result["value"]
            state["moves"] = plan_duplicate_removal(folder, groups)
            state["root"] = folder
            wasted = 0
            number = 1
            for group in groups:
                parent = dup_tree.insert("", "end", values=("Group " + str(number), human_size(group[0]["size"]), ""))
                index = 0
                for info in group:
                    action = "keep" if index == 0 else "to trash"
                    if index > 0:
                        wasted = wasted + info["size"]
                    dup_tree.insert("", "end", values=("    " + info["path"], "", action))
                    index = index + 1
                number = number + 1
            log("  " + str(len(groups)) + " group(s), " + human_size(wasted) + " reclaimable")
            status_var.set(str(len(groups)) + " duplicate group(s), " + human_size(wasted) + " reclaimable")

        run_job("Finding duplicates in " + folder, lambda: find_duplicates(folder, state["cancel"]), finish)

    def trash_duplicates():
        if len(state["moves"]) == 0:
            messagebox.showinfo(APP_NAME, "Find duplicates first.")
            return
        count = len(state["moves"])
        if not messagebox.askyesno(APP_NAME, "Move " + str(count) + " duplicate(s) to " + TRASH_DIR_NAME + "? (Undo is available.)"):
            return
        root = state["root"]
        moves = state["moves"]
        state["moves"] = []
        run_job("Moving duplicates to trash", lambda: apply_moves(root, moves, state["cancel"]),
                lambda result: report_apply(result, "Moved"))

    ttk.Button(dup_bar, text="Find duplicates", command=start_duplicates).pack(side="left")
    ttk.Button(dup_bar, text="Move extras to trash", command=trash_duplicates).pack(side="left", padx=4)
    dup_frame.pack(fill="both", expand=True, pady=6)

    # --- Organize tab -----------------------------------------------------------------------------
    org_tab = ttk.Frame(tabs, padding=6)
    tabs.add(org_tab, text="Organize")
    org_bar = ttk.Frame(org_tab)
    org_bar.pack(fill="x")
    mode_var = tk.StringVar(value="type")
    ttk.Radiobutton(org_bar, text="By type", variable=mode_var, value="type").pack(side="left")
    ttk.Radiobutton(org_bar, text="By year-month", variable=mode_var, value="date").pack(side="left", padx=4)
    org_frame, org_tree = make_tree(org_tab, ("From", "To"), (420, 420))
    org_moves = [[], ""]

    def preview_organize():
        folder = current_folder()
        if folder == "":
            return
        mode = mode_var.get()

        def finish(result):
            clear(org_tree)
            org_moves[0] = result["value"]
            org_moves[1] = folder
            for move in result["value"]:
                org_tree.insert("", "end", values=(os.path.basename(move["source"]), os.path.relpath(move["target"], folder)))
            status_var.set(str(len(result["value"])) + " file(s) would move")

        run_job("Planning organize", lambda: plan_organize(folder, mode, state["cancel"]), finish)

    def apply_organize():
        if len(org_moves[0]) == 0:
            messagebox.showinfo(APP_NAME, "Preview first.")
            return
        if not messagebox.askyesno(APP_NAME, "Move " + str(len(org_moves[0])) + " file(s)? (Undo is available.)"):
            return
        moves = org_moves[0]
        root = org_moves[1]
        org_moves[0] = []
        clear(org_tree)
        run_job("Organizing", lambda: apply_moves(root, moves, state["cancel"]), lambda result: report_apply(result, "Moved"))

    def undo():
        folder = current_folder()
        if folder == "":
            return
        if not messagebox.askyesno(APP_NAME, "Undo the last change made in this folder?"):
            return
        run_job("Undoing last change", lambda: undo_last(folder), lambda result: report_apply(result, "Restored"))

    ttk.Button(org_bar, text="Preview", command=preview_organize).pack(side="left", padx=4)
    ttk.Button(org_bar, text="Apply", command=apply_organize).pack(side="left")
    ttk.Button(org_bar, text="Undo last change", command=undo).pack(side="right")
    org_frame.pack(fill="both", expand=True, pady=6)

    # --- Network tab ------------------------------------------------------------------------------
    net_tab = ttk.Frame(tabs, padding=6)
    tabs.add(net_tab, text="Network")
    form = ttk.Frame(net_tab)
    form.pack(fill="x")
    name_var = tk.StringVar()
    unc_var = tk.StringVar()
    letter_var = tk.StringVar()
    ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
    ttk.Entry(form, textvariable=name_var, width=16).grid(row=0, column=1, padx=4)
    ttk.Label(form, text="\\\\host\\share").grid(row=0, column=2, sticky="w")
    ttk.Entry(form, textvariable=unc_var, width=32).grid(row=0, column=3, padx=4)
    ttk.Label(form, text="Letter").grid(row=0, column=4, sticky="w")
    ttk.Entry(form, textvariable=letter_var, width=4).grid(row=0, column=5, padx=4)
    net_frame, net_tree = make_tree(net_tab, ("Name", "Share", "Letter", "Status", "Free", "Total"),
                                    (140, 260, 60, 280, 90, 90))

    def refresh_shares():
        clear(net_tree)
        index = 0
        for share in settings["shares"]:
            net_tree.insert("", "end", iid=str(index), values=(share["name"], share["unc"], share["letter"], "", "", ""))
            index = index + 1

    def selected_share():
        chosen = net_tree.selection()
        if len(chosen) == 0:
            messagebox.showinfo(APP_NAME, "Select a share first.")
            return None
        return settings["shares"][int(chosen[0])]

    def add_share():
        unc = unc_var.get().strip()
        letter = letter_var.get().strip().upper()
        if len(letter) == 1:
            letter = letter + ":"
        if unc_host(unc) == "":
            messagebox.showwarning(APP_NAME, "Share must look like \\\\host\\share.")
            return
        if not valid_letter(letter):
            messagebox.showwarning(APP_NAME, "Letter must be D: to Z:, or empty.")
            return
        name = name_var.get().strip() or unc_host(unc)
        settings["shares"].append({"name": name, "unc": unc, "letter": letter})
        save_settings(path_to_settings, settings)
        refresh_shares()
        log("added share " + name)

    def remove_share():
        share = selected_share()
        if share is None:
            return
        settings["shares"].remove(share)
        save_settings(path_to_settings, settings)
        refresh_shares()
        log("removed share " + share["name"] + " from the list")

    def check_selected():
        chosen = net_tree.selection()
        if len(chosen) == 0:
            chosen = net_tree.get_children()
        targets = []
        for iid in chosen:
            targets.append((iid, settings["shares"][int(iid)]))

        def work():
            results = []
            for pair in targets:
                if is_cancelled(state["cancel"]):
                    break
                results.append((pair[0], check_share(pair[1])))
            return results

        def finish(results):
            for pair in results:
                share_state = pair[1]
                values = list(net_tree.item(pair[0], "values"))
                if share_state["reachable"]:
                    values[3] = "online"
                    values[4] = human_size(share_state["free"])
                    values[5] = human_size(share_state["total"])
                else:
                    values[3] = share_state["error"]
                    values[4] = ""
                    values[5] = ""
                net_tree.item(pair[0], values=values)
                log("  " + values[0] + ": " + values[3])

        run_job("Checking shares", work, finish)

    def map_selected():
        share = selected_share()
        if share is None:
            return
        run_job("Mapping " + share["unc"], lambda: map_share(share), lambda result: log("  mapped"))

    def unmap_selected():
        share = selected_share()
        if share is None:
            return
        if not messagebox.askyesno(APP_NAME, "Disconnect " + share_path(share) + "?"):
            return
        run_job("Disconnecting " + share["unc"], lambda: unmap_share(share), lambda result: log("  disconnected"))

    def use_as_folder():
        share = selected_share()
        if share is not None:
            folder_var.set(share_path(share))

    def plan_backup():
        folder = current_folder()
        share = selected_share()
        if folder == "" or share is None:
            return
        target = os.path.join(share_path(share), os.path.basename(os.path.normpath(folder)))

        def finish(result):
            state["copies"] = result["value"]
            state["sync_target"] = target
            total = 0
            for copy in result["value"]:
                total = total + os.path.getsize(copy["source"])
            status_var.set(str(len(result["value"])) + " file(s), " + human_size(total) + " to copy to " + target)
            log("  " + status_var.get())
            if len(result["value"]) > 0 and messagebox.askyesno(APP_NAME, status_var.get() + ". Copy now?"):
                copies = state["copies"]
                progress.configure(mode="determinate")

                def update(done_count, total_count):
                    window.after(0, lambda: progress.configure(value=100.0 * done_count / max(total_count, 1)))

                def done_copy(copy_result):
                    progress.configure(mode="indeterminate", value=0)
                    report_apply(copy_result, "Copied")

                run_job("Backing up", lambda: apply_copies(copies, state["cancel"], update), done_copy)

        run_job("Planning backup of " + folder, lambda: plan_sync(folder, target, state["cancel"]), finish)

    buttons = ttk.Frame(net_tab)
    buttons.pack(fill="x", pady=4)
    ttk.Button(form, text="Add", command=add_share).grid(row=0, column=6, padx=4)
    for label, command in (("Check", check_selected), ("Map", map_selected), ("Disconnect", unmap_selected),
                           ("Use as folder", use_as_folder), ("Back up folder to share", plan_backup),
                           ("Remove from list", remove_share)):
        ttk.Button(buttons, text=label, command=command).pack(side="left", padx=2)
    net_frame.pack(fill="both", expand=True)
    ttk.Label(net_tab, text="Passwords are never stored; Windows asks for them when mapping if needed.").pack(anchor="w")
    refresh_shares()

    # --- Log tab ----------------------------------------------------------------------------------
    tabs.add(log_text, text="Log")
    log(APP_NAME + " " + __version__ + " started")

    if smoke_path != "":
        def write_smoke_report():
            report = {"app_id": APP_ID, "version": __version__, "title": window.title(), "icon_set": icon_set,
                      "tabs": [], "shares": len(settings["shares"])}
            for tab_id in tabs.tabs():
                report["tabs"].append(tabs.tab(tab_id, "text"))
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
    if smoke_path is None:
        print("--smoke needs a file")
        return 2
    return run_gui(smoke_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=6d6408580cf4835960694e88033b402665fcaef57ce0447e6cc6c29e2c8d39ae ====
