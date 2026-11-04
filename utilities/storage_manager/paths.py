# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: paths.py
# About: Storage Manager core: paths, the names it gives things on disk, which names are one file.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: paths, the names it gives things on disk, which names are one file.

The trash folder and the undo log keep these names on every drive the program has worked on, so the
walk, organize and undo all recognise them. A file with more than one name (a hard link) is told apart
by its link, "volume:file id" (see FileInfo in records.py).

Who uses it: scanning.py (skip and count the trash, find hard links), moves.py (trash targets, undo log),
space_map.py (place paths in the tree), backup.py, duplicates.py, gui.py and gui_views.py (show paths
relative to the analyzed folder). It calls nothing but os.path.

Path rules
  1. Comparisons ignore case through os.path.normcase, since Windows names are case insensitive.
  2. Both separators, "\\" and "/", are accepted in incoming paths.
  3. Our trash folder is recognised anywhere in a path by its exact name (is_own_folder).
"""

import os

# Names of what the program leaves in a folder it worked on: the trash folder that moves.py fills
# (files keep their path relative to the analyzed folder below it) and the JSON undo log of applied
# batches.
TRASH_DIR_NAME = "_storage_manager_trash"
UNDO_LOG_NAME = "_storage_manager_undo.json"


def is_own_folder(name):
    """True when the folder name (one path part, not a path) is our trash folder's name.

    The match is exact and case sensitive: only the name this program creates counts.
    """
    return name == TRASH_DIR_NAME


def is_inside(root, path):
    """True when path is root or below it. Windows case is ignored; a sibling such as D:\\datas is not
    inside D:\\data, and a path on another drive is simply outside."""
    folder = os.path.normcase(root)
    target = os.path.normcase(path)
    if target == folder:
        return True
    if not folder.endswith(os.sep) and not folder.endswith("/"):
        folder = folder + os.sep
    return target.startswith(folder)


def relative_path(root, path):
    """path below root, without a leading separator."""
    # the fast path below keeps the original case; a path that differs from root only in case, or
    # lies outside it, goes through relpath (which may start with "..")
    if not path.startswith(root):
        return os.path.relpath(path, root)
    rest = path[len(root):]
    while rest.startswith(os.sep) or rest.startswith("/"):
        rest = rest[1:]
    return rest


def path_parts(relative):
    """'a\\b/c.txt' -> ['a', 'b', 'c.txt']."""
    parts = []
    for part in relative.replace("/", os.sep).split(os.sep):
        if part != "" and part != ".":
            parts.append(part)
    return parts


def in_trash_folder(path):
    """True when one of the folders in path is one of our trash folders."""
    for part in path_parts(path):
        if is_own_folder(part):
            return True
    return False


def trash_folder_of(root, path):
    """The trash folder below root that path is in: root and its parts up to the first one named
    TRASH_DIR_NAME (root's own trash folder when path has none)."""
    folder = root
    for part in path_parts(relative_path(root, path)):
        folder = os.path.join(folder, part)
        if is_own_folder(part):
            return folder
    return os.path.join(root, TRASH_DIR_NAME)


def file_identity(info):
    """A stat result's link (see FileInfo): "volume:file id" when the file has more than one name, ""
    when it has one, None when the stat does not say (a Windows folder listing)."""
    # on Windows, os.scandir's cached DirEntry.stat() leaves st_ino, st_dev and st_nlink at 0 (a folder
    # listing does not carry them); only a full os.stat on the file fills them in
    if info.st_nlink == 0 or info.st_ino == 0:
        return None
    if info.st_nlink > 1:
        return str(info.st_dev) + ":" + str(info.st_ino)
    return ""


def name_order(info):
    """Sort key: names outside our trash folders first, then by path."""
    if in_trash_folder(info["path"]):
        return "1" + info["path"]
    return "0" + info["path"]


def extra_names(records):
    """For each file seen under several names (records with the same link), every name but the first in
    name_order: the names whose space is already counted under that first one. -> dict path -> True

    Steps:
      1. Group the records by link, skipping records whose link is unknown (None) or single ("").
      2. In each group of two or more, sort by name_order so a name outside the trash is kept first.
      3. Mark every name after the first.
    """
    by_link = {}
    for info in records:
        link = info["link"]
        if link is None or link == "":
            continue
        if link not in by_link:
            by_link[link] = []
        by_link[link].append(info)
    extra = {}
    for link in by_link:
        names = by_link[link]
        if len(names) < 2:
            continue
        names.sort(key=name_order)
        index = 1
        while index < len(names):
            extra[names[index]["path"]] = True
            index = index + 1
    return extra

# ==== stamp v1 | author=kjFriday | hmac-sha256=5a3c0d643f001e6baa9ee5d4f11224814a9c254b78619ce1aec4afd748473bae ====
