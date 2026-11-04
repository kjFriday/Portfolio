# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: selftest.py
# About: Storage Manager self-test: exercises the core on a throwaway folder.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager self-test: exercises the core on a throwaway folder.

Run it with `python storage_manager.py --selftest`. It works in a temp folder named
storage_manager_test_..., prints "ok" or "FAIL" for each check, grouped by area, and returns 0 when
every check passed, else 1. Besides the core it checks option_value, the command-line helper in
storage_manager.py, which imports this module only when --selftest is given.

Main flow of selftest:
  1. Build a small tree (two equal text files, an old "photo", a song, an unknown type, nested and
     side-by-side empty folders) with known sizes and times.
  2. Run each area's checks in turn: scan, duplicates (and undo), large duplicates, space on disk,
     empty folders, organize, names and paths, sync, space map, shares/settings/desktop.
  3. Remove the temp folder, also after an exception, and print the count of failed checks.

Some checks need what the drive allows (hard links, NTFS compression, the offline attribute); where
it refuses, the check prints "skip" and the reason instead of failing. The space-map checks use
fake_file records rather than real files, so the byte counts and angles are exact.
Start reading at selftest; check_space_on_disk holds the space-on-disk checks.
"""

import ctypes
import math
import os
import shutil
import tempfile
import time

from backup import apply_copies, plan_sync
from desktop import add_recent, command_line, normalize_folder, reveal_command
from duplicates import (SAMPLE_SIZE, copy_frees, duplicate_savings, find_duplicates, find_duplicates_in,
                        group_savings, hash_many, keeper_index, plan_duplicate_removal, remove_from_groups)
from formatting import disk_note, human_count, human_date, human_size, join_words, plural
from moves import apply_moves, plan_empty_dir_removal, select_empty_dirs, trash_target, undo_last
from organize import date_folder_for, plan_organize, unique_target
from paths import TRASH_DIR_NAME, file_identity, in_trash_folder, is_inside, relative_path, trash_folder_of
from scanning import (ASK_OS, FILE_ATTRIBUTE_COMPRESSED, FILE_ATTRIBUTE_OFFLINE,
                      FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, FILE_ATTRIBUTE_RECALL_ON_OPEN,
                      FILE_ATTRIBUTE_SPARSE_FILE, SECONDS_PER_DAY, build_report, count_links_once,
                      disk_from_listing, disk_summary, find_empty_dirs, remove_from_report, scan)
from settings import default_settings, load_settings, save_settings
from shares import map_command, run_command, unc_host, valid_letter
from space_map import (MAP_MIN_DEGREES, MAP_MIN_PIXELS, TRASH_COLOUR, arc_color, build_folder_tree, file_folder,
                       find_node, layout_sunburst, map_entries, map_item_count, mark_wasted, ring_min_angles,
                       ring_points, shift_kept_copy)
from storage_manager import option_value


def write_file(path, text, modified):
    """Write text to path as UTF-8, creating its folders, and set its access and modified times to
    modified (seconds since the epoch), so the old-file checks have known ages."""
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()
    os.utime(path, (modified, modified))


def write_bytes(path, data):
    """Write the bytes data to path, creating its folders; the times are left as written."""
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle = open(path, "wb")
    handle.write(data)
    handle.close()


def check(condition, message, failures):
    """Print "ok" or "FAIL" with message; a failed message is appended to failures (a list)."""
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def fake_file(path, size, modified):
    """A FileInfo for checks that need no real file: one name, as much on disk as its size."""
    return {"path": path, "size": size, "disk": size, "modified": modified, "link": ""}


def set_offline(path):
    """Mark a file offline, as a file whose data is elsewhere (Windows) -> True when it worked.

    SetFileAttributesW replaces all of a file's attributes, so ARCHIVE (which a new file has) is set
    again with OFFLINE. Some file systems refuse OFFLINE; the caller then skips its check.
    """
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong]
    return kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_OFFLINE | 0x20) != 0  # 0x20: archive


def check_space_on_disk(work, now, failures):
    """Space on disk, hard links and cloud-only files, with real files where this drive allows them.

    work is the temp folder, now the current time, failures the shared list of failed checks. First
    the pure functions on made-up values, then real hard links (any OS that has them), then on
    Windows an NTFS-compressed file and an offline one.
    """
    # 16 blocks of 512 bytes are 8192; 8 blocks (4096) are more than 1000 bytes, so the size wins
    check(disk_from_listing(1000, FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_SPARSE_FILE, -1, True) == 0
          and disk_from_listing(1000, FILE_ATTRIBUTE_RECALL_ON_OPEN, -1, True) == 0
          and disk_from_listing(1000, FILE_ATTRIBUTE_OFFLINE, -1, False) == 0,
          "cloud-only placeholders and offline files take no space", failures)
    check(disk_from_listing(1000, FILE_ATTRIBUTE_COMPRESSED, -1, True) == ASK_OS
          and disk_from_listing(1000, FILE_ATTRIBUTE_SPARSE_FILE, -1, True) == ASK_OS
          and disk_from_listing(1000, FILE_ATTRIBUTE_COMPRESSED, -1, False) == 1000
          and disk_from_listing(1000, 0x20, -1, True) == 1000,
          "compressed and sparse files are asked about, but not on a network share", failures)
    check(disk_from_listing(100000, 0, 16, False) == 8192 and disk_from_listing(1000, 0, 8, False) == 1000
          and disk_from_listing(5000, 0, 0, False) == 0, "allocated blocks, where the listing has them", failures)
    # os.stat_result fields in order: mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime;
    # identity is "dev:ino", given only when nlink is above 1
    check(file_identity(os.stat_result((0, 7, 3, 2, 0, 0, 10, 0, 0, 0))) == "3:7"
          and file_identity(os.stat_result((0, 7, 3, 1, 0, 0, 10, 0, 0, 0))) == ""
          and file_identity(os.stat_result((0, 0, 0, 0, 0, 0, 10, 0, 0, 0))) is None, "which names are one file", failures)
    top = os.path.join(work, "sizes")
    linked = {"path": os.path.join(top, "a.bin"), "size": 100, "disk": 100, "modified": now, "link": "1:5"}
    plain = fake_file(os.path.join(top, "b.bin"), 100, now)
    packed = {"path": os.path.join(top, "c.bin"), "size": 100, "disk": 40, "modified": now, "link": ""}
    check(copy_frees(linked) == 0 and copy_frees(plain) == 100 and keeper_index([plain, linked], {}) == 1
          and group_savings([plain, linked], {}) == 100 and group_savings([plain, linked], {plain["path"]: True}) == 0,
          "a copy with other names is kept: moving it would free nothing", failures)
    check(keeper_index([plain, packed], {}) == 1 and duplicate_savings([[plain, packed]], {})["bytes"] == 100
          and keeper_index([plain, fake_file(plain["path"] + "2", 100, now)], {}) == 0,
          "the copy that frees least is kept, else the first", failures)
    pair_tree = build_folder_tree(top, [plain, linked], [])
    mark_wasted(pair_tree, top, [[plain, linked]], {plain["path"]: True})
    unmarked = pair_tree["wasted"] == 0 and len(pair_tree["wasted_paths"]) == 0
    mark_wasted(pair_tree, top, [[plain, linked]], {})
    check(unmarked and pair_tree["wasted"] == 100 and pair_tree["wasted_paths"] == {plain["path"]: 100},
          "the map marks only copies whose removal frees space", failures)
    # sizes 100 + 100 + 50 + 30 = 280; on disk 100 + 40 + 0 + 0 = 140: 60 saved by compression,
    # 50 with no data here, 30 a second name of a linked file
    mixed = [plain, packed, {"path": os.path.join(top, "cloud.bin"), "size": 50, "disk": 0, "modified": now, "link": ""},
             {"path": os.path.join(top, "a2.bin"), "size": 30, "disk": 0, "modified": now, "link": "1:5"}]
    summary = disk_summary(mixed)
    mixed_report = build_report(top, mixed, [], [], [], 1, 10, 365, now)
    note = disk_note(mixed_report, True)
    check(summary["file_bytes"] == 280 and summary["compressed"] == 60 and summary["no_data"] == 50 and summary["links"] == 30
          and mixed_report["total_bytes"] == 140 and note.find("no data on this disk") > 0 and note.find("hard-linked") > 0
          and disk_note(mixed_report, False).endswith("comparison is done.")
          and disk_note(build_report(top, [plain], [], [], [], 1, 10, 365, now), True).find("is what the files add up to") > 0,
          "what on disk leaves out", failures)
    check(join_words(["a"]) == "a" and join_words(["a", "b", "c"]) == "a, b and c", "lists in words", failures)

    # Real hard links: a large and a small file with a second name and a real copy each, and one with
    # a second name only. The second names sort after the first ones.
    space = os.path.join(work, "links")
    # film is big enough to take the large-file path (both ends sampled), note_text the small one
    film = os.urandom(3 * SAMPLE_SIZE)
    note_text = b"tiny but shared " * 10
    solo = os.urandom(1000)
    write_bytes(os.path.join(space, "film.bin"), film)
    write_bytes(os.path.join(space, "copy", "film.bin"), film)
    write_bytes(os.path.join(space, "note.txt"), note_text)
    write_bytes(os.path.join(space, "copy", "note.txt"), note_text)
    write_bytes(os.path.join(space, "solo.bin"), solo)
    try:
        os.link(os.path.join(space, "film.bin"), os.path.join(space, "film_link.bin"))
        os.link(os.path.join(space, "note.txt"), os.path.join(space, "note_link.txt"))
        os.link(os.path.join(space, "solo.bin"), os.path.join(space, "solo_link.bin"))
        has_links = True
    except (OSError, AttributeError, NotImplementedError) as e:
        print("  skip hard links: " + str(e))
        has_links = False
    if has_links:
        scanned = scan(space, 10, 365, now, None, None)["value"]
        found = find_duplicates_in(scanned["files"], None, None)["value"]
        separate = True
        for group in found["groups"]:
            files_seen = {}
            for info in group:
                stat = os.stat(info["path"])
                files_seen[str(stat.st_dev) + ":" + str(stat.st_ino)] = True
                separate = separate and info["path"].find("_link") < 0
            separate = separate and len(files_seen) == len(group) == 2
        check(len(found["groups"]) == 2 and separate, "hard links are never offered as duplicate copies", failures)
        counted = scanned
        if len(found["linked"]) > 0:
            counted = count_links_once(scanned, found["linked"], 10, 365, now)
        once = 2 * len(film) + 2 * len(note_text) + len(solo)
        check(counted["file_count"] == 8 and counted["total_bytes"] == once
              and counted["saved"]["links"] == len(film) + len(note_text) + len(solo),
              "a hard-linked file is counted once", failures)
        savings = duplicate_savings(found["groups"], {})
        moves = plan_duplicate_removal(space, found["groups"], {})
        check(savings["bytes"] == len(film) + len(note_text) and len(moves) == 2
              and moves[0]["source"].find(os.sep + "copy" + os.sep) > 0
              and moves[1]["source"].find(os.sep + "copy" + os.sep) > 0,
              "the copy without other names goes, freeing its space", failures)

    if os.name != "nt":
        return
    # Windows: an NTFS-compressed file and an offline one (the attribute cloud files carry too).
    real = os.path.join(work, "real")
    packed_path = os.path.join(real, "packed.txt")
    # 18 bytes * 60000 of repeated text compresses well; `compact /c` turns on NTFS compression for
    # the file and /q keeps its report short. FAT and exFAT drives refuse, so the check is skipped.
    write_bytes(packed_path, b"compressible text " * 60000)
    compacted = run_command(["compact", "/c", "/q", packed_path], 60)
    if compacted["ok"]:
        listed = scan(real, 10, 365, now, None, None)["value"]["files"]
        check(len(listed) == 1 and 0 < listed[0]["disk"] < listed[0]["size"] == 18 * 60000,
              "a compressed file counts the space it takes", failures)
    else:
        print("  skip compressed file: " + compacted["error"])
    offline_path = os.path.join(real, "offline.txt")
    # two equal 5000-byte files: if the offline one were read and compared they would form a group
    write_bytes(offline_path, b"elsewhere " * 500)
    write_bytes(os.path.join(real, "here.txt"), b"elsewhere " * 500)
    if set_offline(offline_path):
        listed = scan(real, 10, 365, now, None, None)["value"]
        offline_disk = -1
        for info in listed["files"]:
            if info["path"] == offline_path:
                offline_disk = info["disk"]
        compared = find_duplicates_in(listed["files"], None, None)["value"]
        check(offline_disk == 0 and len(compared["groups"]) == 0 and listed["saved"]["no_data"] == 5000,
              "an offline file takes no space and is not read to compare it", failures)
    else:
        print("  skip offline file: Windows did not set the attribute")


def selftest():
    """Run every check in a throwaway temp folder -> 0 when all passed, else 1 (the exit code).

    Prints one line per check, grouped under the area's name. Areas run in order on the same tree,
    and later ones rely on what earlier ones left (undo puts each change back first). The temp folder
    is removed at the end, whatever happened.
    """
    failures = []
    now = time.time()
    # 800 days is well past the 365-day limit the scans below use, so photo.jpg is the one old file
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

        # the six files add up to 12 + 12 + 17 + 5 + 1 + 1 = 48 bytes; empty1, empty1\empty2 and
        # mixed\hollow are the empty folders (mixed holds keep.txt)
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
        check(report["value"]["total_bytes"] == 48 and report["value"]["file_bytes"] == 48
              and report["value"]["trash_bytes"] == 0, "space on disk of plain files is their size", failures)
        smaller = remove_from_report(report["value"], {os.path.join(root, "song.mp3"): ""}, 10, 365, now)
        check(smaller["file_count"] == 5 and "Audio" not in smaller["by_type"] and len(smaller["trash"]) == 0,
              "remove_from_report drops a file", failures)
        song_trash = trash_target(root, os.path.join(root, "song.mp3"))
        trashed = remove_from_report(report["value"], {os.path.join(root, "song.mp3"): song_trash}, 10, 365, now)
        check(trashed["file_count"] == 5 and len(trashed["trash"]) == 1 and trashed["trash"][0]["path"] == song_trash
              and trashed["trash_bytes"] == 5 and trashed["total_bytes"] == 43, "a file moved to the trash still counts there",
              failures)

        # a.txt and sub\b.txt are the one pair; once b.txt is in the trash, sub is empty too (4 empty)
        print("duplicates")
        dupes = find_duplicates(root, None, None)
        check(dupes["ok"] and len(dupes["value"]["groups"]) == 1 and len(dupes["value"]["linked"]) == 0,
              "one duplicate group", failures)
        moves = plan_duplicate_removal(root, dupes["value"]["groups"], {})
        check(len(moves) == 1 and moves[0]["source"].endswith("b.txt"), "first copy is kept by default", failures)
        chosen = plan_duplicate_removal(root, dupes["value"]["groups"], {os.path.join(root, "sub", "b.txt"): True})
        check(chosen[0]["source"].endswith("a.txt"), "chosen copy is kept", failures)
        applied = apply_moves(root, moves, None, None)
        check(applied["value"]["done"] == 1 and len(applied["value"]["moved"]) == 1, "duplicate moved to trash", failures)
        check(os.path.isfile(os.path.join(root, TRASH_DIR_NAME, "sub", "b.txt")), "trash keeps relative path", failures)
        after = scan(root, 10, 365, now, None, None)["value"]
        check(after["file_count"] == 5 and len(after["trash"]) == 1 and after["trash_bytes"] == 12
              and after["dir_count"] == report["value"]["dir_count"] and len(after["empty_dirs"]) == 4,
              "the trash is counted apart, not offered again", failures)
        trash_tree = build_folder_tree(root, after["files"], after["trash"])
        trash_node = trash_tree["children"][TRASH_DIR_NAME]
        check(trash_tree["bytes"] == after["total_bytes"] + 12 and trash_tree["trash"] == 12 and trash_node["kind"] == "trash"
              and trash_node["bytes"] == 12 and len(trash_node["children"]) == 0 and len(trash_node["file_list"]) == 0,
              "the trash folder is one slice of the map", failures)
        check(find_duplicates(root, None, None)["value"]["groups"] == [], "trashed copies are not compared again", failures)
        undone = undo_last(root)
        check(undone["ok"] and os.path.isfile(os.path.join(root, "sub", "b.txt")), "undo restores duplicate", failures)
        restored = scan(root, 10, 365, now, None, None)["value"]
        check(len(restored["trash"]) == 0 and len(restored["empty_dirs"]) == 3,
              "an emptied trash folder is not listed as empty", failures)
        check(len(remove_from_groups(dupes["value"]["groups"], {moves[0]["source"]: True})) == 0, "group of one is dropped",
              failures)
        check(in_trash_folder(song_trash) and not in_trash_folder(os.path.join(root, "song.mp3"))
              and trash_folder_of(root, os.path.join(root, "a", TRASH_DIR_NAME, "b", "c.txt"))
              == os.path.join(root, "a", TRASH_DIR_NAME), "which trash folder a path is in", failures)

        # files of 3 * SAMPLE_SIZE bytes: end.bin differs only in its last byte (caught by the end
        # sample), middle.bin only in its middle byte, which neither sample reads (caught by the full hash)
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
        check(big_dupes["ok"] and len(big_dupes["value"]["groups"]) == 1 and len(big_dupes["value"]["groups"][0]) == 2,
              "only true copies match (ends and middle checked)", failures)
        check(hash_many([], "full", None, None, "")["ok"], "nothing to hash is fine", failures)

        print("space on disk")
        check_space_on_disk(work, now, failures)

        print("empty folders")
        all_empty = find_empty_dirs(root)
        picked = select_empty_dirs(all_empty, {os.path.join(root, "empty1"): True}, root)
        check(len(picked) == 2 and picked[0].endswith("empty2"), "choosing a folder takes its empty insides first", failures)
        apply_moves(root, plan_empty_dir_removal(picked), None, None)
        check(not os.path.exists(os.path.join(root, "empty1")), "empty folders removed", failures)
        undo_last(root)
        check(os.path.isdir(os.path.join(root, "empty1", "empty2")), "undo recreates empty folders", failures)

        # the top level holds a.txt, photo.jpg, song.mp3 and notes.unknownext: 4 moves by type
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

        # all six files are new to the empty backup; then song.mp3 changes (size and a later time)
        # and new.txt appears, so exactly those two are copied again
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

        # 1000 bytes in all, so a slice's angle is bytes * 0.36 degrees: big (900) 324, a.bin (600)
        # 216. no_merge draws every slice, flat merges below MAP_MIN_DEGREES, wide below 50 degrees.
        print("space map")
        top = os.path.join(work, "m")
        map_files = [fake_file(os.path.join(top, "big", "a.bin"), 600, now),
                     fake_file(os.path.join(top, "big", "deep", "b.bin"), 210, now),
                     fake_file(os.path.join(top, "big", "c.bin"), 90, now),
                     fake_file(os.path.join(top, "small", "c.bin"), 90, now),
                     fake_file(os.path.join(top, "loose.bin"), 10, now)]
        # The tree is built from the files smallest first, so the checks below also prove both sorts.
        smallest_first = []
        index = len(map_files) - 1
        while index >= 0:
            smallest_first.append(map_files[index])
            index = index - 1
        tree = build_folder_tree(top, smallest_first, [])
        no_merge = ring_min_angles(6, 0.0, 0.0, 0, 0.0)
        flat = ring_min_angles(6, 0.0, 0.0, 0, MAP_MIN_DEGREES)
        wide = ring_min_angles(6, 0.0, 0.0, 0, 50.0)
        check(tree["bytes"] == 1000 and tree["files"] == 5 and len(tree["file_list"]) == 1
              and tree["file_list"][0]["size"] == 10, "tree totals", failures)
        big_node = tree["children"]["big"]
        check(big_node["bytes"] == 900 and len(big_node["file_list"]) == 2 and big_node["file_list"][0]["size"] == 600
              and big_node["file_list"][1]["size"] == 90, "folder totals, files biggest first", failures)
        check(len(tree["folder_list"]) == 2 and tree["folder_list"][0]["name"] == "big" and tree["item_files"] == 5,
              "subfolders biggest first", failures)
        # ring 1 starts at radius 40: 4 pixels there are 4 / 40 = 0.1 radians
        angles = ring_min_angles(3, 40.0, 20.0, 4, MAP_MIN_DEGREES)
        check(abs(angles[0] - math.degrees(0.1)) < 1e-9 and angles[0] > angles[1] > angles[2] > MAP_MIN_DEGREES
              and ring_min_angles(2, 1000.0, 10.0, 4, MAP_MIN_DEGREES) == [MAP_MIN_DEGREES, MAP_MIN_DEGREES],
              "inner rings need wider slices", failures)
        drive = build_folder_tree("D:" + os.sep, [fake_file("D:" + os.sep + "x.bin", 5, now),
                                                  fake_file(os.path.join("D:" + os.sep, "a", "y.bin"), 7, now)], [])
        check(len(drive["file_list"]) == 1 and drive["file_list"][0]["size"] == 5 and drive["children"]["a"]["bytes"] == 7
              and drive["bytes"] == 12, "tree of a drive root", failures)
        empty_tree = build_folder_tree(top, [fake_file(os.path.join(top, "e.txt"), 0, now),
                                             fake_file(os.path.join(top, "f.txt"), 4, now)], [])
        empty_arcs = layout_sunburst(empty_tree, 6, flat)
        check(empty_tree["files"] == 2 and len(empty_tree["file_list"]) == 1 and len(empty_arcs) == 1
              and empty_arcs[0]["kind"] == "file" and abs(empty_arcs[0]["extent"] - 360.0) < 1e-9,
              "empty files are counted but get no slice", failures)
        arcs = layout_sunburst(tree, 6, no_merge)
        ring_total = 0.0
        big_arc = None
        for arc in arcs:
            if arc["depth"] == 1:
                ring_total = ring_total + arc["extent"]
            if arc["path"] == os.path.join(top, "big") and arc["kind"] == "folder":
                big_arc = arc
        check(abs(ring_total - 360.0) < 1e-9, "first ring is a full circle", failures)
        check(big_arc is not None and abs(big_arc["extent"] - 324.0) < 1e-9 and big_arc["start"] == 0.0,
              "biggest slice first, sized by bytes", failures)
        inside = 0.0
        for arc in arcs:
            if arc["depth"] == 2 and arc["branch"] == big_arc["branch"]:
                inside = inside + arc["extent"]
        check(abs(inside - big_arc["extent"]) < 1e-9, "a folder's slices fill its angle", failures)
        follow = True
        expected = big_arc["start"]
        for arc in arcs:
            if arc["depth"] == 2 and arc["branch"] == big_arc["branch"]:
                follow = follow and abs(arc["start"] - expected) < 1e-9
                expected = arc["start"] + arc["extent"]
        three_top = os.path.join(work, "three")
        three = layout_sunburst(build_folder_tree(three_top, [
            fake_file(os.path.join(three_top, "c.mkv"), 100, now),
            fake_file(os.path.join(three_top, "a.mkv"), 600, now),
            fake_file(os.path.join(three_top, "b.mkv"), 300, now)], []), 6, no_merge)
        check(follow and abs(expected - big_arc["start"] - big_arc["extent"]) < 1e-9 and len(three) == 3
              and three[0]["start"] == 0.0 and abs(three[1]["start"] - 216.0) < 1e-9
              and abs(three[2]["start"] - 324.0) < 1e-9, "slices follow one another without overlapping", failures)
        file_arcs = {}
        for arc in arcs:
            if arc["kind"] == "file":
                file_arcs[arc["path"]] = arc
        a_arc = file_arcs.get(map_files[0]["path"])
        loose_arc = file_arcs.get(map_files[4]["path"])
        check(len(file_arcs) == 5 and a_arc is not None and a_arc["depth"] == 2 and abs(a_arc["extent"] - 216.0) < 1e-9
              and a_arc["name"] == "a.bin" and a_arc["modified"] == now and loose_arc is not None
              and loose_arc["depth"] == 1, "files get slices of their own", failures)
        check(len(map_entries(big_node, 1)) == 1 and map_entries(big_node, 1)[0]["kind"] == "file"
              and map_entries(big_node, 9)[1]["kind"] == "folder" and map_item_count(big_node) == 3,
              "slices merge folders and files biggest first, up to a limit", failures)
        many_top = os.path.join(work, "many")
        many = [fake_file(os.path.join(many_top, "big.bin"), 10000, now)]
        index = 0
        while index < 1000:
            many.append(fake_file(os.path.join(many_top, "t" + str(index) + ".bin"), 1, now))
            index = index + 1
        many_tree = build_folder_tree(many_top, many, [])
        # big.bin is an extra copy of a file kept elsewhere, and so are two tiny files: the drawn slice
        # and the merged one both hold duplicate bytes, and each must keep only its own.
        kept_big = fake_file(os.path.join(work, "keep", "big.bin"), 10000, now)
        mark_wasted(many_tree, many_top, [[kept_big, many[0]], [many[1], many[2]], [many[3], many[4]]], {})
        many_arcs = layout_sunburst(many_tree, 6, flat)
        check(len(many_arcs) == 2 and many_arcs[1]["kind"] == "rest" and many_arcs[1]["bytes"] == 1000
              and many_arcs[1]["files"] == 1000 and many_arcs[1]["name"] == "1,000 smaller items"
              and abs(many_arcs[0]["extent"] + many_arcs[1]["extent"] - 360.0) < 1e-9,
              "a thousand tiny files become one slice", failures)
        check(many_tree["wasted"] == 10002 and many_arcs[0]["wasted"] == 10000 and many_arcs[1]["wasted"] == 2,
              "the merged slice keeps its duplicate copies", failures)
        pair_arcs = layout_sunburst(build_folder_tree(many_top, [many[0], many[1]], []), 6, flat)
        check(len(pair_arcs) == 2 and pair_arcs[1]["kind"] == "file" and pair_arcs[1]["extent"] < MAP_MIN_DEGREES,
              "a lone narrow slice is drawn as itself", failures)
        # 500 slices of exactly the narrowest angle and 200 of half: only the look-ahead limit decides
        # how many are drawn, so a smaller limit would hide drawable slices in "smaller items".
        edge_top = os.path.join(work, "edge")
        edge = []
        index = 0
        while index < 700:
            size = 1
            if index < 500:
                size = 2
            edge.append(fake_file(os.path.join(edge_top, "f" + str(index) + ".bin"), size, now))
            index = index + 1
        edge_arcs = layout_sunburst(build_folder_tree(edge_top, edge, []), 6, flat)
        edge_total = 0.0
        for arc in edge_arcs:
            edge_total = edge_total + arc["extent"]
        check(len(edge_arcs) == 501 and edge_arcs[500]["kind"] == "rest" and edge_arcs[500]["bytes"] == 200
              and edge_arcs[500]["name"] == "200 smaller items" and abs(edge_total - 360.0) < 1e-6,
              "every slice wide enough is drawn", failures)
        holes_top = os.path.join(work, "holes")
        holes = layout_sunburst(build_folder_tree(holes_top, [
            fake_file(os.path.join(holes_top, "big.bin"), 1000, now),
            fake_file(os.path.join(holes_top, "a.bin"), 1, now),
            fake_file(os.path.join(holes_top, "b.bin"), 1, now),
            fake_file(os.path.join(holes_top, "empty.txt"), 0, now),
            fake_file(os.path.join(holes_top, "pkg", "__init__.py"), 0, now)], []), 6, flat)
        check(len(holes) == 2 and holes[1]["kind"] == "rest" and holes[1]["files"] == 2
              and holes[1]["name"] == "2 smaller items", "the merged slice counts only its own files", failures)
        # Every folder's ring of slices must tile exactly its angle, also for a folder that does not start
        # at 12 o'clock and whose ring ends in a merged slice (x\B here).
        x_top = os.path.join(work, "x")
        x_files = [fake_file(os.path.join(x_top, "A", "big.bin"), 600, now),
                   fake_file(os.path.join(x_top, "B", "big.bin"), 390, now)]
        index = 0
        while index < 10:
            x_files.append(fake_file(os.path.join(x_top, "B", "t" + str(index) + ".bin"), 1, now))
            index = index + 1
        tiled = True
        for layout in (arcs, layout_sunburst(build_folder_tree(x_top, x_files, []), 6, flat)):
            for parent_arc in layout:
                if parent_arc["kind"] != "folder":
                    continue
                parent_end = parent_arc["start"] + parent_arc["extent"]
                expected = parent_arc["start"]
                inside_count = 0
                for arc in layout:
                    if (arc["depth"] == parent_arc["depth"] + 1 and arc["start"] >= parent_arc["start"] - 1e-9
                            and arc["start"] < parent_end - 1e-9):
                        tiled = tiled and abs(arc["start"] - expected) < 1e-9 and arc["extent"] > 0
                        expected = arc["start"] + arc["extent"]
                        inside_count = inside_count + 1
                tiled = tiled and inside_count > 0 and abs(expected - parent_end) < 1e-9
        check(tiled, "each folder's slices tile its angle exactly", failures)
        # Each ring uses its own narrowest angle: ring 1 keeps all three slices, ring 2 merges what is
        # under 100 degrees.
        per_ring = layout_sunburst(tree, 6, [10.0, 100.0, 0.0, 0.0, 0.0, 0.0])
        ring_one = 0
        ring_two_rests = []
        for arc in per_ring:
            if arc["depth"] == 1:
                ring_one = ring_one + 1
            if arc["depth"] == 2 and arc["kind"] == "rest":
                ring_two_rests.append(arc)
        chain_top = os.path.join(work, "chain")
        chain_arcs = layout_sunburst(build_folder_tree(chain_top, [
            fake_file(os.path.join(chain_top, "a", "b", "c", "d", "e", "f", "x.bin"), 5, now)], []),
            6, ring_min_angles(6, 30.0, 20.0, MAP_MIN_PIXELS, MAP_MIN_DEGREES))
        check(ring_one == 3 and len(ring_two_rests) == 1 and ring_two_rests[0]["bytes"] == 300
              and len(chain_arcs) == 6 and chain_arcs[5]["depth"] == 6, "each ring has its own narrowest angle", failures)
        merged = layout_sunburst(tree, 6, wide)
        rests = []
        for arc in merged:
            if arc["kind"] == "rest":
                rests.append(arc)
        check(len(rests) == 1 and rests[0]["bytes"] == 100 and abs(rests[0]["extent"] - 36.0) < 1e-9
              and abs(rests[0]["start"] - 324.0) < 1e-9 and rests[0]["name"] == "2 smaller items",
              "narrow slices merge into one", failures)
        shallow = layout_sunburst(tree, 1, no_merge)
        deepest = 0
        for arc in shallow:
            if arc["depth"] > deepest:
                deepest = arc["depth"]
        check(deepest == 1, "rings stop at max depth", failures)
        pair = [[map_files[3], map_files[2]]]
        mark_wasted(tree, top, pair, {})
        check(tree["wasted"] == 90 and big_node["wasted"] == 90 and map_files[2]["path"] in big_node["wasted_paths"]
              and tree["children"]["small"]["wasted"] == 0, "wasted bytes land on the extra copy's folders", failures)
        copy_arc = None
        for arc in layout_sunburst(tree, 6, no_merge):
            if arc["path"] == map_files[2]["path"]:
                copy_arc = arc
        check(copy_arc is not None and copy_arc["wasted"] == 90, "the extra copy's own slice is marked", failures)
        mark_wasted(tree, top, pair, {map_files[2]["path"]: True})
        check(tree["children"]["small"]["wasted"] == 90 and big_node["wasted"] == 0 and len(big_node["wasted_paths"]) == 0,
              "wasted bytes follow the kept copy", failures)
        mark_wasted(tree, top, pair, {})
        shift_kept_copy(tree, top, map_files[3], map_files[2])
        check(tree["children"]["small"]["wasted"] == 90 and big_node["wasted"] == 0 and tree["wasted"] == 90
              and len(big_node["wasted_paths"]) == 0 and map_files[3]["path"] in tree["children"]["small"]["wasted_paths"],
              "changing the kept copy moves its marks", failures)
        # Siblings whose names start like the analyzed folder's (m.bin, msmall) are outside it, even where
        # the rest of the name matches a real subfolder.
        outside = fake_file(os.path.join(work, "msmall", "c.bin"), 90, now)
        beside = fake_file(top + ".bin", 90, now)
        far = fake_file("Z:" + os.sep + "c.bin", 90, now)
        mark_wasted(tree, top, [[map_files[0], outside, beside, far]], {map_files[0]["path"]: True})
        check(tree["wasted"] == 0, "copies outside the folder are left out", failures)
        check(find_node(tree, top, os.path.join(top, "big", "deep"))["name"] == "deep"
              and find_node(tree, top, top) is tree and find_node(tree, top, os.path.join(top, "gone")) is None
              and find_node(tree, top, top + "small") is None and find_node(tree, top, "Z:" + os.sep + "x") is None,
              "find a folder in the tree", failures)
        data = "D:" + os.sep + "data"
        check(is_inside(data, data + os.sep + "s") and not is_inside(data, data + "s") and is_inside(data, data + os.sep)
              and is_inside("D:" + os.sep, "D:" + os.sep + "x") and not is_inside(data, "E:" + os.sep + "x"),
              "inside a folder", failures)
        check(file_folder("D:" + os.sep, "D:" + os.sep + "x.bin") == "D:" + os.sep
              and file_folder(data, os.path.join(data, "s", "x.bin")) == os.path.join(data, "s"),
              "a file's folder", failures)
        # a quarter ring in 30-degree steps: 4 points per edge, 16 numbers; the outer edge starts
        # straight up (100, 80) and ends at 3 o'clock (120, 100)
        points = ring_points(100.0, 100.0, 10.0, 20.0, 0.0, 90.0, 30.0)
        check(len(points) == 16 and abs(points[0] - 100.0) < 1e-9 and abs(points[1] - 80.0) < 1e-9
              and abs(points[6] - 120.0) < 1e-9 and abs(points[7] - 100.0) < 1e-9,
              "ring slice starts at 12 o'clock and runs clockwise", failures)
        # "#rrggbb": a grey has equal channels; red's channel is above green's once copies are marked
        grey = arc_color({"depth": 1, "bytes": 10, "wasted": 0, "kind": "folder", "branch": 0}, "duplicates", 6)
        red = arc_color({"depth": 1, "bytes": 10, "wasted": 10, "kind": "folder", "branch": 0}, "duplicates", 6)
        check(grey[1:3] == grey[3:5] == grey[5:7] and red[1:3] > red[3:5], "duplicate colours go from grey to red", failures)
        folder_colour = arc_color({"depth": 2, "bytes": 10, "wasted": 0, "kind": "folder", "branch": 1}, "folders", 6)
        file_colour = arc_color({"depth": 2, "bytes": 10, "wasted": 0, "kind": "file", "branch": 1}, "folders", 6)
        check(folder_colour != file_colour, "files look different from folders", failures)
        bin_top = os.path.join(work, "t")
        bin_tree = build_folder_tree(bin_top, [fake_file(os.path.join(bin_top, "a.bin"), 600, now)],
                                     [fake_file(os.path.join(bin_top, TRASH_DIR_NAME, "x", "old.bin"), 300, now),
                                      fake_file(os.path.join(bin_top, "sub", TRASH_DIR_NAME, "y.bin"), 100, now)])
        bin_arcs = layout_sunburst(bin_tree, 6, no_merge)
        trash_arcs = []
        for arc in bin_arcs:
            if arc["kind"] == "trash":
                trash_arcs.append(arc)
        check(bin_tree["bytes"] == 1000 and bin_tree["trash"] == 400 and bin_tree["children"]["sub"]["trash"] == 100
              and len(bin_arcs) == 4 and len(trash_arcs) == 2 and trash_arcs[0]["bytes"] == 300
              and trash_arcs[0]["depth"] == 1 and trash_arcs[1]["depth"] == 2 and trash_arcs[0]["trash"] == 300
              and arc_color(trash_arcs[0], "folders", 6) == TRASH_COLOUR
              and arc_color(trash_arcs[0], "duplicates", 6) == TRASH_COLOUR, "trash folders are slices of their own",
              failures)
        # Explorer splits its arguments at commas and "=", so such paths must be quoted; a drive root
        # is given as "D:\." since a quoted "D:\" would end in an escaped quote
        check(command_line(["explorer", "/select,", "D:\\Q1,Q2\\a.xlsx"]) == 'explorer /select,"D:\\Q1,Q2\\a.xlsx"'
              and command_line(["explorer", "/select,", "D:\\Music\\E=mc2.mp3"]) == 'explorer /select,"D:\\Music\\E=mc2.mp3"'
              and command_line(["explorer", "D:\\x=y"]) == 'explorer "D:\\x=y"'
              and command_line(["explorer", "D:\\"]) == 'explorer "D:\\."'
              and command_line(["notepad", "a b.txt"]) == 'notepad "a b.txt"',
              "paths for Explorer are quoted", failures)
        # 10 ** 20 seconds is past any date the system can show; a normal date is "YYYY-MM-DD"
        check(human_date(10.0 ** 20) == "unknown" and len(human_date(now)) == 10, "dates the system cannot show", failures)

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

# ==== stamp v1 | author=kjFriday | hmac-sha256=24f1036ac70540b0373428d5b93f08b58e57498f5d11b3058bece20116e5f397 ====
