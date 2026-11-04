# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: duplicates.py
# About: Storage Manager core: find identical files step by step, and choose the copy to keep.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: find identical files step by step, and choose the copy to keep.

Files are narrowed by size, then (large files) by both ends, then by a full SHA-256, read on
HASH_WORKERS threads; two names of one file (hard links) are never offered as copies. The kept copy of
a group is the one whose removal would free the least, unless the user chose another.

What it is for: after a scan, gui.py runs find_duplicates_in on the same file list on a worker job,
shows the groups in the Duplicates view, and turns the user's choice into Moves with
plan_duplicate_removal (applied by moves.apply_moves, so Undo works). space_map.py uses
keeper_index and copy_frees to colour the bytes extra copies waste. bench/run_ours.py times
find_duplicates on a seeded dataset. It calls walk_tree and run_on_workers (scanning.py),
file_identity (paths.py) and trash_target (moves.py).

Why the steps: a SHA-256 of every file would read every byte on the disk. Files of different sizes
cannot be equal, so grouping by size costs nothing; large files of one size usually differ near the
start or end (headers, trailers), so hashing 64 KB from each end rules most of them out cheaply; only
files still alike are read whole. SHA-256 (FIPS 180-4) makes two different files with the same
digest practically impossible, so equal digests are taken as equal content without a byte compare.

Hard links: one file can have several names. They share their data, so moving one name to the trash
frees nothing and they are not copies of each other. A FileInfo's link ("volume:file id", see
records.py) tells which names are one file; a Windows listing leaves it None, so it is read here,
only for files that matched.

Start reading at find_duplicates_in.
"""

import concurrent.futures
import hashlib
import os

from moves import trash_target
from paths import file_identity
from records import error_text, failure, is_cancelled, report_progress, success
from scanning import HASH_WORKERS, file_path, run_on_workers, walk_tree

CHUNK_SIZE = 1024 * 1024      # bytes read at a time when hashing a whole file
SAMPLE_SIZE = 64 * 1024       # bytes read from each end of a large file before hashing all of it


def hash_file(path, size):
    """SHA-256 of a whole file -> Result(Hashed), its link not read (None).

    A small file is read in one go with a buffer of its own size: allocating a large buffer for
    each small file costs more than reading it. The loop still finishes a file that has grown.

    size: the size from the listing; it only picks the block size. The file is opened unbuffered
    (buffering=0) because blocks are already large, so Python's own buffer would only add a copy. A
    small file takes one read of size + 1 bytes, then one empty read that marks the end. Fails with
    the OS message when the file cannot be opened or read (locked, gone, no access).
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
    return success({"digest": digest.hexdigest(), "link": None})


def hash_sample(path, size):
    """SHA-256 of the first and last SAMPLE_SIZE bytes of a file, and its link read from the open
    handle (no second open) -> Result(Hashed).

    Only called for files larger than 2 * SAMPLE_SIZE, so the two ends never overlap. size is the
    listing's size: the last block is read from size - SAMPLE_SIZE. The digest does not include the
    size, so callers key it with the size. os.fstat on an open handle fills in the file id and link
    count even on Windows, where the folder listing left them out.
    """
    digest = hashlib.sha256()
    try:
        handle = open(path, "rb")
    except OSError as e:
        return failure(error_text(e))
    try:
        link = file_identity(os.fstat(handle.fileno()))
        digest.update(handle.read(SAMPLE_SIZE))
        handle.seek(size - SAMPLE_SIZE)
        digest.update(handle.read(SAMPLE_SIZE))
    except OSError as e:
        return failure(error_text(e))
    finally:
        handle.close()
    return success({"digest": digest.hexdigest(), "link": link})


def hash_job(info, mode, cancel_flag):
    """One pool job for hash_many: hash FileInfo info by mode ("sample" or "full") -> Result(Hashed).

    Runs on a pool thread. Checks cancel_flag first, so jobs queued after a cancel return at once
    with failure("cancelled") instead of reading.
    """
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    if mode == "sample":
        return hash_sample(info["path"], info["size"])
    return hash_file(info["path"], info["size"])


def bytes_to_read(info, mode):
    """Bytes hashing info in mode reads, for progress: both ends for "sample", the whole size else."""
    if mode == "sample":
        return 2 * SAMPLE_SIZE
    return info["size"]


def hash_many(files, mode, cancel_flag, progress, text):
    """Hash files on HASH_WORKERS threads -> Result(dict path -> Hashed). Unreadable files are left out.

    mode is "sample" (both ends) or "full". Port with any thread pool or parallel-for.

    Reading on several threads at once hides the wait for each file (disk seek, antivirus scan, a
    network round trip). progress hears text in bytes every 50 files and after the last; it runs on
    the calling thread, not the pool. A cancel gives failure("cancelled") once the pool has stopped.

    Steps:
      1. Add up the bytes to read, for the progress total.
      2. Submit every file to the pool.
      3. Collect the results in submit order (not finish order), so files[index] matches jobs[index];
         failed files are simply left out of the dict.
      4. Shut the pool down, dropping jobs not yet started, and check for a cancel.
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


def copy_frees(info):
    """Bytes moving this one copy away (and emptying the trash) would free: its space on disk, or nothing
    when the file has other names (hard links), which keep its data.

    info: a copy from a duplicate group, whose link is "" (one name) or "volume:file id" (several).
    disk is space on disk, so a compressed copy frees less than its size.
    """
    if info["link"] is not None and info["link"] != "":
        return 0
    return info["disk"]


def group_savings(group, keep):
    """Bytes moving every copy but the kept one would free.

    group: copies of one file; keep: dict path -> True of copies the user chose to keep (see
    keeper_index).
    """
    keeper = keeper_index(group, keep)
    total = 0
    index = 0
    while index < len(group):
        if index != keeper:
            total = total + copy_frees(group[index])
        index = index + 1
    return total


def default_savings(group):
    """Sort key: bytes the group frees with the default kept copy (no user choice)."""
    return group_savings(group, {})


def first_path(group):
    """Sort key: the path of a group's first copy (copies are sorted by path, so its smallest)."""
    return group[0]["path"]


def find_duplicates(root, cancel_flag, progress):
    """Walk root, then find_duplicates_in its files -> Result(Duplicates).

    Fails when root is not a folder or the walk is cancelled. The GUI does not use it (it reuses the
    scan's file list); the self-test and bench/run_ours.py do.
    """
    if not os.path.isdir(root):
        return failure("not a folder: " + root)
    walked = walk_tree(root, cancel_flag, progress)
    if not walked["ok"]:
        return walked
    return find_duplicates_in(walked["value"]["files"], cancel_flag, progress)


def link_job(info, cancel_flag):
    """One pool job for read_links: the link of FileInfo info from a full os.stat -> Result(link).

    A full stat (not the listing's cached one) is what fills in the file id and link count on
    Windows. follow_symlinks=False: a symbolic link is described itself, not its target. The value
    can still be None when the file system gives no file id.
    """
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    try:
        return success(file_identity(os.stat(info["path"], follow_symlinks=False)))
    except OSError as e:
        return failure(error_text(e))


def read_links(files, cancel_flag):
    """The link (see FileInfo) of each file, read with os.stat on HASH_WORKERS threads
    -> Result(dict path -> link). Files that cannot be read are left out.

    Files whose stat gives no link (None) are left out too. A cancel gives failure("cancelled").
    """
    results = run_on_workers(link_job, files, cancel_flag)
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    links = {}
    index = 0
    while index < len(files):
        if results[index]["ok"] and results[index]["value"] is not None:
            links[files[index]["path"]] = results[index]["value"]
        index = index + 1
    return success(links)


def one_name_each(group, links, linked):
    """The files of group (FileInfo) with one name each, sorted by path, as copies that carry their link
    (from links, else their own; "" when not known). The first name of a file keeps its space; its other
    names are left out and take none. Names found to be hard links only now (their own link was None)
    are added to linked, as those copies.

    group is not changed: each kept name becomes a new record. The copies keep the link they were
    given, so a second call on them (find_duplicates_in calls this after sampling and again after
    hashing) adds nothing to linked twice. A name that is not a hard link ("") is always kept.

    Steps:
      1. Sort the names by path, so the first name of a file is the same every time.
      2. For each name, take its link from links if read while comparing, else its own; None
         becomes "" so a name of unknown kind is treated as a file of its own.
      3. Keep the first name of each link; later names get disk 0 and are not kept.
      4. Record each name found to be a hard link only now in linked, kept or not, so the caller
         can correct the scan's totals (scanning.count_links_once).
    """
    ordered = list(group)
    ordered.sort(key=file_path)
    seen = {}
    kept = []
    for info in ordered:
        link = info["link"]
        if info["path"] in links:
            link = links[info["path"]]
        if link is None:
            link = ""
        record = {"path": info["path"], "size": info["size"], "disk": info["disk"], "modified": info["modified"],
                  "link": link}
        first = link == "" or link not in seen
        if first:
            kept.append(record)
        else:
            record["disk"] = 0
        if link != "":
            seen[link] = True
            if info["link"] is None:
                linked.append(record)
    return kept


def find_duplicates_in(files, cancel_flag, progress):
    """Groups of identical files (2+ each, empty files ignored), biggest savings first, and never two
    names of one file: a hard link is a second name of the same data, not a copy.

    Each step only looks at files that may still be equal:
      1. same size (nothing read). Files with no data on this disk are left out: a cloud-only file
         would be downloaded to read it, and moving it frees nothing here;
      2. large files: same first and last SAMPLE_SIZE bytes. The handle opened for that tells which
         names are one file, so only one of them is read whole;
      3. same SHA-256 of the whole file. Where it is not known yet which of a group's names are one
         file (a Windows listing does not say), those names are looked up: only files that matched.
    -> Result(Duplicates)

    files: FileInfo records from a walk (the scan's list in the GUI). Each group's copies are sorted
    by path and carry their link. Groups are ordered by the bytes they free with the default kept
    copy, biggest first; ties by first path (two sorts: the second is stable, so it keeps the first's
    order among equals). A cancel gives failure("cancelled"); files that cannot be read are left out
    without an error. progress hears "Comparing file ends", "Comparing files" (bytes) and "Looking for
    hard links" (files).
    """
    # ---- 1. group by size ----------------------------------------------------------------------
    # disk 0 also drops the extra names of a hard-linked file the listing already settled (macOS,
    # Linux): only the first name of such a file is compared
    by_size = {}
    for info in files:
        if info["size"] == 0 or info["disk"] == 0:
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
            # up to two samples long, sampling would read as much as hashing the whole file
            if size <= 2 * SAMPLE_SIZE:
                small.append(info)
            else:
                large.append(info)

    # ---- 2. large files: compare both ends ------------------------------------------------------
    links = {}   # path -> link, where read while comparing
    linked = []  # names found to be hard links (see Duplicates)
    sampled = hash_many(large, "sample", cancel_flag, progress, "Comparing file ends")
    if not sampled["ok"]:
        return sampled
    by_sample = {}
    for info in large:
        if info["path"] not in sampled["value"]:
            continue
        found = sampled["value"][info["path"]]
        if found["link"] is not None:
            links[info["path"]] = found["link"]
        key = str(info["size"]) + ":" + found["digest"]
        if key not in by_sample:
            by_sample[key] = []
        by_sample[key].append(info)
    candidates = list(small)
    for key in by_sample:
        if len(by_sample[key]) > 1:
            # one name per file: the other names of a hard-linked file are the same data, so
            # reading them whole again would prove nothing
            for info in one_name_each(by_sample[key], links, linked):
                candidates.append(info)

    # ---- 3. same size: compare whole files ------------------------------------------------------
    hashed = hash_many(candidates, "full", cancel_flag, progress, "Comparing files")
    if not hashed["ok"]:
        return hashed
    by_digest = {}
    for info in candidates:
        if info["path"] not in hashed["value"]:
            continue
        key = str(info["size"]) + ":" + hashed["value"][info["path"]]["digest"]
        if key not in by_digest:
            by_digest[key] = []
        by_digest[key].append(info)
    # ---- 4. look up which matching names are one file -------------------------------------------
    # only names in a group of two or more, whose link nothing has told yet (small files on Windows):
    # looking up every same-size file before hashing would cost far more stat calls
    unknown = []
    for key in by_digest:
        if len(by_digest[key]) > 1:
            for info in by_digest[key]:
                if info["link"] is None and info["path"] not in links:
                    unknown.append(info)
    if len(unknown) > 0:
        report_progress(progress, "Looking for hard links", 0, len(unknown), "files")
        looked_up = read_links(unknown, cancel_flag)
        if not looked_up["ok"]:
            return looked_up
        for path in looked_up["value"]:
            links[path] = looked_up["value"][path]
    # ---- 5. groups with at least two distinct files ---------------------------------------------
    # a group whose names all turn out to be one file shrinks to one copy and is dropped
    groups = []
    for key in by_digest:
        if len(by_digest[key]) > 1:
            group = one_name_each(by_digest[key], links, linked)
            if len(group) > 1:
                groups.append(group)
    groups.sort(key=first_path)
    groups.sort(key=default_savings, reverse=True)
    return success({"groups": groups, "linked": linked})


def duplicate_savings(groups, keep):
    """{"copies": extra copies, "bytes": space moving them away would free}.

    groups: duplicate groups; keep: the user's chosen copies (see keeper_index). Every copy but one per
    group counts as extra, even one that frees nothing (a hard link).
    """
    copies = 0
    total = 0
    for group in groups:
        copies = copies + len(group) - 1
        total = total + group_savings(group, keep)
    return {"copies": copies, "bytes": total}


def keeper_index(group, keep):
    """Index of the copy to keep: the first one listed in keep (dict path -> True); else the one whose
    removal would free the least (a hard link frees nothing, a compressed copy little), so removing
    the others frees the most; ties go to the first."""
    index = 0
    while index < len(group):
        if group[index]["path"] in keep:
            return index
        index = index + 1
    best = 0
    index = 1
    while index < len(group):
        if copy_frees(group[index]) < copy_frees(group[best]):
            best = index
        index = index + 1
    return best


def plan_duplicate_removal(root, groups, keep):
    """Keep one copy per group and send the rest to the trash -> list of Move.

    root: the scanned folder; each target is in root's trash folder at the copy's path relative to
    root (moves.trash_target), so Undo can put it back. keep: dict path -> True of chosen copies.
    Nothing is moved here; the caller applies the Moves with moves.apply_moves.
    """
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
    """Duplicate groups without the paths in gone; groups left with one file are dropped.

    gone: dict path -> True of files just moved away. Used after a move, so the view updates without
    comparing the files again. New lists are returned; the old groups are not changed.
    """
    result = []
    for group in groups:
        kept = []
        for info in group:
            if info["path"] not in gone:
                kept.append(info)
        if len(kept) > 1:
            result.append(kept)
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=790f0e0130081f9d16cef265a50135e3dafe761e209f7286a16e8c5af65283c2 ====
