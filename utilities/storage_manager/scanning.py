# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: scanning.py
# About: Storage Manager core: read a folder tree once (walk_tree) and sum it up in a ScanReport.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: read a folder tree once (walk_tree) and sum it up in a ScanReport.

The walk lists every folder with os.scandir, which gives sizes, times and (on Windows) file attributes
without opening each file, and finds empty folders in the same pass. The space each file takes on disk
comes from the listing where it says (see disk_from_listing); the few files it does not settle are
asked about afterwards on HASH_WORKERS threads. The report functions turn a walk into the totals,
lists and type summary the window shows, and update them after files were moved, without a new walk.

Who calls it: gui.py runs scan for Analyze and remove_from_report / count_links_once after changes;
duplicates.py reuses walk_tree, run_on_workers and HASH_WORKERS; space_map.py uses sort_by_disk_desc;
selftest.py checks most of it. It calls paths.py (names, trash folders, hard links), organize.py
(type folders), records.py (Result, cancel, progress) and windows_calls.py (the two Windows calls).

Main flow of scan:
  1. walk_tree lists every folder once, depth first, and builds a FileInfo per file.
  2. Files whose space the listing cannot settle are asked about on worker threads (read_disk_sizes).
  3. Extra names of hard-linked files are set to take 0 bytes (macOS, Linux).
  4. Empty folders are settled bottom-up from the folder list.
  5. build_report sums the Walk into a ScanReport; scan adds the drive's free and total space.

Records: it builds Walk and ScanReport records and fills FileInfo (all described in records.py).
Start reading at walk_tree.
"""

import concurrent.futures
import heapq
import os
import shutil

from organize import type_folder_for
from paths import UNDO_LOG_NAME, extra_names, file_identity, is_own_folder
from records import error_text, failure, is_cancelled, report_progress, success
from windows_calls import allocated_size, is_network_path

HASH_WORKERS = 8              # files read at once; hides disk, antivirus and network latency
PROGRESS_EVERY = 500          # files between progress reports

# Windows file attributes that change the space a file takes (the listing has them for free).
# The values are the FILE_ATTRIBUTE_* constants of the Windows SDK (winnt.h); os.stat reports them in
# st_file_attributes on Windows only.
FILE_ATTRIBUTE_SPARSE_FILE = 0x200
FILE_ATTRIBUTE_COMPRESSED = 0x800
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# The data is elsewhere: cloud-only placeholders (OneDrive Files On-Demand and the like), offline files.
NOT_HERE_ATTRIBUTES = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
# The file may take less space than its size.
SMALLER_ATTRIBUTES = FILE_ATTRIBUTE_SPARSE_FILE | FILE_ATTRIBUTE_COMPRESSED
SPACE_ATTRIBUTES = NOT_HERE_ATTRIBUTES | SMALLER_ATTRIBUTES
ASK_OS = -1                   # disk_from_listing: only a call per file can tell

# File times are seconds since the epoch, so "older than N days" compares against now - N * this.
SECONDS_PER_DAY = 86400


# ---- walking ------------------------------------------------------------------------------------

def is_link_entry(entry):
    """Symbolic links and Windows junctions are not followed (they can loop or leave the drive).

    entry is an os.DirEntry -> True for a link of either kind. DirEntry.is_junction exists from
    Python 3.12 on; older versions skip that test.
    """
    if entry.is_symlink():
        return True
    if hasattr(entry, "is_junction") and entry.is_junction():
        return True
    return False


def disk_from_listing(size, attributes, blocks, can_ask):
    """Bytes a file takes on disk, from what its folder listing says -> int, or ASK_OS when only a
    call per file can tell.

    attributes are its Windows file attributes (0 elsewhere): a cloud-only or offline file has no data
    here and takes 0; a compressed or sparse one may take less than its size (ASK_OS when can_ask, else
    its size). blocks are the 512-byte blocks it has (macOS, Linux), or -1 where the listing does not
    say (Windows). Never more than the file's size: the unused end of its last cluster is left out.

    can_ask is True only on a local Windows drive: on a network share each call would be a round
    trip to the server, so such files count at their size there.
    """
    if (attributes & NOT_HERE_ATTRIBUTES) != 0:
        return 0
    # st_blocks counts 512-byte units on both macOS and Linux, whatever the file system's block size
    if blocks >= 0:
        if blocks * 512 < size:
            return blocks * 512
        return size
    if (attributes & SMALLER_ATTRIBUTES) != 0 and can_ask:
        return ASK_OS
    return size


def run_on_workers(job, items, cancel_flag):
    """job(item, cancel_flag) for every item on HASH_WORKERS threads -> list of Result, in item order.
    Port with any thread pool or parallel-for.

    job runs on pool threads and must return a Result rather than raise: an exception it raises comes
    back out of this function. cancel_flag is passed through so each job can stop early; jobs not yet
    started when this returns or raises are dropped (cancel_futures, Python 3.9+).
    """
    results = []
    # results are collected in submit order, not finish order, so results[i] belongs to items[i]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=HASH_WORKERS)
    try:
        jobs = []
        for item in items:
            jobs.append(pool.submit(job, item, cancel_flag))
        for running in jobs:
            results.append(running.result())
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return results


def disk_job(record, cancel_flag):
    """One worker's job for read_disk_sizes: the space the OS says record (a FileInfo) takes ->
    Result(int), or a "cancelled" failure once cancel_flag is set. Runs on a pool thread."""
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    return allocated_size(record["path"])


def read_disk_sizes(records, cancel_flag):
    """Ask the OS what each record (FileInfo) takes on disk and store it as its disk; a file the OS says
    nothing about counts at its size.

    Changes the records in place. An answer at or above the size is ignored too, so disk never grows
    past size (the unused end of the last cluster is left out, as in disk_from_listing). After a
    cancel the remaining records simply keep their size; the caller checks the flag.
    """
    results = run_on_workers(disk_job, records, cancel_flag)
    index = 0
    while index < len(records):
        record = records[index]
        record["disk"] = record["size"]
        if results[index]["ok"] and results[index]["value"] < record["size"]:
            record["disk"] = results[index]["value"]
        index = index + 1


def walk_tree(root, cancel_flag, progress):
    """Read every folder under root once -> Result(Walk).

    Files in our trash folders (any folder named TRASH_DIR_NAME) are listed apart, in trash: they still
    take space, but are not offered for cleaning again. The undo log is skipped. A folder is empty when
    it holds no files, links or unreadable entries, and every folder inside it is empty too.

    Each file's space on disk comes from the listing (see disk_from_listing). Compressed and sparse files
    on a local Windows drive are asked about once the folders are read, on HASH_WORKERS threads. Where
    the listing tells which names are one file (macOS, Linux), a hard-linked file's space is counted
    under one name; on Windows find_duplicates_in finds them.

    cancel_flag (or None) is checked once per folder and after the disk-size calls; a cancel gives
    failure("cancelled"). progress (or None) hears "Reading folders" every PROGRESS_EVERY files.
    Folders and entries that cannot be read go to errors as "path: message" and do not stop the walk.

    Steps:
      1. Keep a stack of folders still to read (pending), as indexes into flat lists that hold each
         folder's path, its parent's index, whether it holds anything but folders, and whether it is
         in the trash. An explicit stack instead of recursion: deep trees cannot overflow the stack.
      2. Pop a folder and list it with os.scandir. Links are content and are not followed; folders
         are pushed; files become FileInfo records in files, or in trash inside a trash folder.
      3. Set each record's disk from the listing; queue for the OS the ones it cannot settle, and
         note the ones the listing says have several names.
      4. When every folder is read, ask the OS about the queued records (read_disk_sizes) and set
         every hard link's extra names to 0 bytes (extra_names).
      5. Walk the folder list backwards to settle which folders are empty (see below).
    """
    files = []
    trash = []
    errors = []
    to_ask = []             # records whose space on disk the OS is asked for after the walk
    linked = []             # records of files the listing says have more than one name
    windows = os.name == "nt"
    can_ask = windows and not is_network_path(root)
    listed = 0
    dir_paths = [root]      # every folder seen; index 0 is root
    dir_parent = [-1]       # index of each folder's parent
    has_content = [False]   # folder holds something other than folders
    in_trash = [False]      # folder is one of our trash folders or inside one
    dir_count = 1           # folders outside the trash
    pending = [0]
    # ---- read every folder ----
    while len(pending) > 0:
        if is_cancelled(cancel_flag):
            return failure("cancelled")
        # pop() takes the newest folder, so the walk goes depth first and the stack stays short
        index = pending.pop()
        folder = dir_paths[index]
        found = files
        if in_trash[index]:
            found = trash
        try:
            iterator = os.scandir(folder)
        except OSError as e:
            # an unreadable folder counts as holding something: it is never offered as empty
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
                        trashed = in_trash[index] or is_own_folder(entry.name)
                        if trashed:
                            # a trash folder is still read (its files take space) but makes its
                            # parent non-empty, and is not counted among the folders
                            has_content[index] = True
                        else:
                            dir_count = dir_count + 1
                        dir_paths.append(entry.path)
                        dir_parent.append(index)
                        has_content.append(False)
                        in_trash.append(trashed)
                        pending.append(len(dir_paths) - 1)
                        continue
                    has_content[index] = True
                    if entry.name == UNDO_LOG_NAME:
                        continue
                    # on Windows this stat comes from the listing itself (no file is opened); it
                    # has size, times and attributes, but no inode or link count (see file_identity)
                    info = entry.stat(follow_symlinks=False)
                except OSError as e:
                    errors.append(entry.path + ": " + error_text(e))
                    has_content[index] = True
                    continue
                size = info.st_size
                record = {"path": entry.path, "size": size, "disk": size, "modified": info.st_mtime, "link": None}
                if windows:
                    attributes = info.st_file_attributes
                    # most files have none of these bits: their space is their size, no call needed
                    if (attributes & SPACE_ATTRIBUTES) != 0:
                        record["disk"] = disk_from_listing(size, attributes, -1, can_ask)
                        if record["disk"] == ASK_OS:
                            to_ask.append(record)
                else:
                    record["disk"] = disk_from_listing(size, 0, info.st_blocks, False)
                    record["link"] = file_identity(info)
                    if record["link"] is not None and record["link"] != "":
                        linked.append(record)
                found.append(record)
                listed = listed + 1
                if listed % PROGRESS_EVERY == 0:
                    report_progress(progress, "Reading folders", listed, 0, "files")
        except OSError as e:
            errors.append(folder + ": " + error_text(e))
            has_content[index] = True
        finally:
            # release the listing's OS handle now, also after an error, not at garbage collection
            iterator.close()
    # ---- space the listing could not settle ----
    if len(to_ask) > 0:
        report_progress(progress, "Reading the space compressed files take", 0, len(to_ask), "files")
        read_disk_sizes(to_ask, cancel_flag)
        if is_cancelled(cancel_flag):
            return failure("cancelled")
    extra = extra_names(linked)
    for record in linked:
        if record["path"] in extra:
            record["disk"] = 0
    # ---- empty folders ----
    # Children always come after their parent, so walking backwards settles each folder
    # before its parent, and the list comes out deepest first (the order they can be removed in).
    # Nothing in the trash is listed: the trash folder itself counts as content of its parent.
    nonempty = list(has_content)
    empty_dirs = []
    index = len(dir_paths) - 1
    while index > 0:
        if not in_trash[index]:
            if nonempty[index]:
                nonempty[dir_parent[index]] = True
            else:
                empty_dirs.append(dir_paths[index])
        index = index - 1
    return success({"files": files, "trash": trash, "empty_dirs": empty_dirs, "errors": errors,
                    "dir_count": dir_count, "links_checked": not windows})


def find_empty_dirs(root):
    """Folders under root (not root itself) that contain nothing, deepest first.

    A full walk_tree without cancel or progress; a failed walk gives an empty list.
    """
    walked = walk_tree(root, None, None)
    if not walked["ok"]:
        return []
    return walked["value"]["empty_dirs"]


# ---- the scan report ----------------------------------------------------------------------------

def file_size(info):
    """Sort key: a FileInfo's size in bytes (the GUI's Size column)."""
    return info["size"]


def file_disk(info):
    """Sort key: the bytes a FileInfo takes on disk (biggest-first lists and the GUI's On disk column)."""
    return info["disk"]


def file_path(info):
    """Sort key: a FileInfo's path (duplicates.py orders groups by it)."""
    return info["path"]


def sort_by_disk_desc(files):
    """A new list of the FileInfo records, the most space on disk first; files itself is not changed.

    Python's sort is stable, so files with equal space keep their order.
    """
    result = list(files)
    result.sort(key=file_disk, reverse=True)
    return result


def total_disk(files):
    """Space the files take on disk."""
    total = 0
    for info in files:
        total = total + info["disk"]
    return total


def disk_summary(files):
    """Space on disk and how it differs from the files' sizes, in one pass -> {"disk_bytes": space on
    disk, "file_bytes": sizes added up, "compressed": bytes compressed and sparse files save, "no_data":
    sizes of files with no data on this disk (cloud-only, or sparse or compressed down to nothing),
    "links": sizes of second names of hard-linked files, counted once}.

    A file that takes less than its size is sorted by why: some space left (compressed or sparse),
    none left and a known link (an extra name, set to 0 by the walk or count_links_once), or none
    left otherwise (data elsewhere).
    """
    disk_bytes = 0
    file_bytes = 0
    compressed = 0
    no_data = 0
    links = 0
    for info in files:
        size = info["size"]
        disk = info["disk"]
        disk_bytes = disk_bytes + disk
        file_bytes = file_bytes + size
        if disk >= size:
            continue
        if disk > 0:
            compressed = compressed + size - disk
        elif info["link"] is not None and info["link"] != "":
            links = links + size
        else:
            no_data = no_data + size
    return {"disk_bytes": disk_bytes, "file_bytes": file_bytes, "compressed": compressed, "no_data": no_data,
            "links": links}


def largest_files(files, count):
    """The count files that take the most space, biggest first (a partial sort: port as a top-N /
    priority queue)."""
    return heapq.nlargest(count, files, key=file_disk)


def stale_files(files, days, now):
    """Files not changed for `days` days, biggest first.

    now is the current time in seconds since the epoch (time.time()); a file counts as stale when its
    modified time is before now minus days whole days.
    """
    cutoff = now - days * SECONDS_PER_DAY
    stale = []
    for info in files:
        if info["modified"] < cutoff:
            stale.append(info)
    stale.sort(key=file_disk, reverse=True)
    return stale


def summarize_types(files):
    """File count and bytes on disk per type folder (Images, Video, ... Other) -> {name: {"files",
    "bytes"}}. The type comes from the file's extension through organize.type_folder_for; types with
    no files are absent."""
    by_type = {}
    for info in files:
        kind = type_folder_for(info["path"])
        if kind not in by_type:
            by_type[kind] = {"files": 0, "bytes": 0}
        by_type[kind]["files"] = by_type[kind]["files"] + 1
        by_type[kind]["bytes"] = by_type[kind]["bytes"] + info["disk"]
    return by_type


def drive_usage(path):
    """(free, total) bytes of the drive holding path, or (0, 0) when unknown."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return (0, 0)
    return (usage.free, usage.total)


def build_report(root, files, trash, empty_dirs, errors, dir_count, largest_count, stale_days, now):
    """A ScanReport from the lists a Walk gives -> dict (see records.py).

    largest_count caps the largest list; stale_days and now (seconds since the epoch) pick the old
    files. Pure: it reads no disk. links_checked and the drive's space are left False and 0 here;
    scan and rebuild_report fill them in.
    """
    summary = disk_summary(files)
    return {
        "root": root,
        "file_count": len(files),
        "dir_count": dir_count,
        "total_bytes": summary["disk_bytes"],
        "file_bytes": summary["file_bytes"],
        "saved": {"compressed": summary["compressed"], "no_data": summary["no_data"], "links": summary["links"]},
        "trash": trash,
        "trash_bytes": total_disk(trash),
        "links_checked": False,
        "drive_free": 0,
        "drive_total": 0,
        "by_type": summarize_types(files),
        "largest": largest_files(files, largest_count),
        "stale": stale_files(files, stale_days, now),
        "empty_dirs": empty_dirs,
        "errors": errors,
        "files": files,
    }


def rebuild_report(report, files, trash, empty_dirs, dir_count, largest_count, stale_days, now):
    """A new report of the same folder from changed lists; what was read about the drive is kept."""
    updated = build_report(report["root"], files, trash, empty_dirs, report["errors"], dir_count,
                           largest_count, stale_days, now)
    updated["drive_free"] = report["drive_free"]
    updated["drive_total"] = report["drive_total"]
    updated["links_checked"] = report["links_checked"]
    return updated


def scan(root, largest_count, stale_days, now, cancel_flag, progress):
    """Summarize a folder in one pass -> Result(ScanReport).

    Fails with "not a folder: ..." when root is not a folder, and with walk_tree's error ("cancelled")
    otherwise. largest_count, stale_days and now are as in build_report; cancel_flag and progress as in
    walk_tree. Runs on a GUI job thread; it only reads the disk.
    """
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    walked = walk_tree(root, cancel_flag, progress)
    if not walked["ok"]:
        return walked
    found = walked["value"]
    report = build_report(root, found["files"], found["trash"], found["empty_dirs"], found["errors"],
                          found["dir_count"], largest_count, stale_days, now)
    report["links_checked"] = found["links_checked"]
    usage = drive_usage(root)
    report["drive_free"] = usage[0]
    report["drive_total"] = usage[1]
    return success(report)


def remove_from_report(report, gone, largest_count, stale_days, now):
    """The report without the paths in gone (dict path -> where it went: its path in a trash folder, or
    "" when it was removed or moved elsewhere). Files moved to a trash folder are counted there: they
    still take the same space.

    Empty folders named in gone are dropped from empty_dirs and from dir_count. The old report is not
    changed. A folder that became empty because its files left is not added to empty_dirs; it shows
    up at the next scan.
    """
    files = []
    trash = list(report["trash"])
    for info in report["files"]:
        if info["path"] not in gone:
            files.append(info)
        elif gone[info["path"]] != "":
            trash.append({"path": gone[info["path"]], "size": info["size"], "disk": info["disk"],
                          "modified": info["modified"], "link": info["link"]})
    empty_dirs = []
    for folder in report["empty_dirs"]:
        if folder not in gone:
            empty_dirs.append(folder)
    dir_count = report["dir_count"] - (len(report["empty_dirs"]) - len(empty_dirs))
    return rebuild_report(report, files, trash, empty_dirs, dir_count, largest_count, stale_days, now)


def count_links_once(report, linked, largest_count, stale_days, now):
    """The report with the hard links found while comparing (Duplicates linked) in place of the records
    of those names: each such file is counted once, under its first name.

    linked is Duplicates["linked"]: FileInfo records with their link read and disk 0 for every name
    but the first. The result has links_checked True (formatting.disk_note then drops its remark on
    hard links). Only Windows listings leave links unknown, so elsewhere linked is empty and walk_tree
    has already counted each file once.
    """
    replace = {}
    for info in linked:
        replace[info["path"]] = info
    files = []
    for info in report["files"]:
        if info["path"] in replace:
            files.append(replace[info["path"]])
        else:
            files.append(info)
    updated = rebuild_report(report, files, report["trash"], report["empty_dirs"], report["dir_count"],
                             largest_count, stale_days, now)
    updated["links_checked"] = True
    return updated

# ==== stamp v1 | author=kjFriday | hmac-sha256=dce802adad607a2d1cad27cd5eb148caa06bdb69dea30a61d99ac8e5faacc4a8 ====
