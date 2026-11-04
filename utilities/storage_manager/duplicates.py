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
    handle (no second open) -> Result(Hashed)."""
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
    """Hash files on HASH_WORKERS threads -> Result(dict path -> Hashed). Unreadable files are left out.

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


def copy_frees(info):
    """Bytes moving this one copy away (and emptying the trash) would free: its space on disk, or nothing
    when the file has other names (hard links), which keep its data."""
    if info["link"] is not None and info["link"] != "":
        return 0
    return info["disk"]


def group_savings(group, keep):
    """Bytes moving every copy but the kept one would free."""
    keeper = keeper_index(group, keep)
    total = 0
    index = 0
    while index < len(group):
        if index != keeper:
            total = total + copy_frees(group[index])
        index = index + 1
    return total


def default_savings(group):
    return group_savings(group, {})


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


def link_job(info, cancel_flag):
    if is_cancelled(cancel_flag):
        return failure("cancelled")
    try:
        return success(file_identity(os.stat(info["path"], follow_symlinks=False)))
    except OSError as e:
        return failure(error_text(e))


def read_links(files, cancel_flag):
    """The link (see FileInfo) of each file, read with os.stat on HASH_WORKERS threads
    -> Result(dict path -> link). Files that cannot be read are left out."""
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
    are added to linked, as those copies."""
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
    """
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
            if size <= 2 * SAMPLE_SIZE:
                small.append(info)
            else:
                large.append(info)

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
            for info in one_name_each(by_sample[key], links, linked):
                candidates.append(info)

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
    """{"copies": extra copies, "bytes": space moving them away would free}."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=790f0e0130081f9d16cef265a50135e3dafe761e209f7286a16e8c5af65283c2 ====
