# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: space_map.py
# About: Storage Manager core: the space map's folder tree, sunburst layout and colours.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: the space map's folder tree, sunburst layout and colours.

build_folder_tree sums a walk up per folder (a Node tree), mark_wasted marks the duplicate copies in
it, layout_sunburst turns one of its folders into rings of Arcs, and ring_points and arc_color turn an
Arc into a polygon and a fill colour. The window only draws what these return.

A sunburst is a pie chart of a folder tree in rings: the centre is the folder shown, ring 1 holds its
subfolders and files, each sized by the bytes it takes, and every folder's slice is split again in
the next ring out by what it holds. Slices too narrow to see are merged into one "smaller items"
slice per folder, so a drive with millions of files still draws in a few thousand polygons.

Who calls it: gui.py builds the tree on a job thread after a scan ("Drawing the map"), marks the
duplicate copies once the comparison is done, and lays out and draws the folder the user opened;
selftest.py checks the sums, the angles and the colours. It calls duplicates.py (which copy is kept
and what removing one frees), paths.py, formatting.plural and scanning.sort_by_disk_desc.

Records: Node and Arc (records.py). Start reading at build_folder_tree, then layout_sunburst.
"""

import colorsys
import math
import os

from duplicates import copy_frees, keeper_index
from formatting import plural
from paths import is_inside, path_parts, relative_path, trash_folder_of
from scanning import sort_by_disk_desc

MAP_DEPTH = 6                 # rings the space map shows around its centre folder
MAP_MIN_DEGREES = 0.6         # narrower slices are merged into one "smaller items" slice
MAP_MIN_PIXELS = 4            # ... and so are slices narrower than this at the inner edge of their ring
TRASH_COLOUR = "#8c8c8c"      # a trash folder's slice on the map, in both colour modes

# Hues in degrees on the colour wheel (0 red, 120 green, 240 blue), used in turn by the ring-1 slices;
# arc_color divides them by 360 for colorsys.
MAP_HUES = [210, 135, 35, 275, 180, 55, 245, 95]   # one per top-level slice; no red, which marks duplicates


# ---- folder tree --------------------------------------------------------------------------------

def new_node(name, path):
    """An empty folder Node (see records.py) named name at path, with all totals 0."""
    return {"name": name, "path": path, "kind": "folder", "bytes": 0, "files": 0, "trash": 0, "wasted": 0,
            "children": {}, "file_list": [], "folder_list": [], "item_files": 0, "wasted_paths": {}}


def file_folder(root, path):
    """The folder a file below root is directly in, spelled the way build_folder_tree names it.

    A string cut at the last separator ("\\" or "/"), not os.path.dirname: it is called once per file
    and needs no normalising, as the paths come from the same walk as root.
    """
    cut = path.rfind(os.sep)
    if path.rfind("/") > cut:
        cut = path.rfind("/")
    folder = root
    if cut >= 0:
        folder = path[0:cut]
    if len(folder) < len(root):  # a file right in a drive root: "D:\x" gives "D:"
        folder = root
    return folder


def folder_nodes(tree):
    """Every Node of the tree, each folder before the folders inside it.

    A breadth-first walk: the list grows while it is read, so reading it backwards visits every
    folder before its parent (mark_wasted relies on that).
    """
    nodes = [tree]
    index = 0
    while index < len(nodes):
        node = nodes[index]
        for name in node["children"]:
            nodes.append(node["children"][name])
        index = index + 1
    return nodes


def build_folder_tree(root, files, trash):
    """Folder tree of root with the bytes on disk and file count of everything below each folder -> Node.

    Each Node lists its slices once, biggest first, so drawing never sorts: file_list holds the files
    directly in it that take space (files taking none are counted but not listed) and folder_list the
    subfolders that take space. item_files counts the files those slices hold. The trash files (a
    Walk's trash) are added up per trash folder, each a Node of kind "trash" with no slices inside.

    files and trash are FileInfo lists; their disk (not size) is what is summed. Pure: reads no disk.

    Steps:
      1. Sum each folder's own files (bytes, count, the files that take space) in a dict keyed by the
         folder's path; trash files are summed per trash folder instead.
      2. Place each folder in the tree once, adding its sums to every Node on the way down from the
         top, and creating the Nodes it needs.
      3. Give each folder its file_list, biggest first.
      4. For every Node, list the subfolders that take space (folder_list, biggest first) and count
         the files those slices hold (item_files).
    """
    name = os.path.basename(root.rstrip("\\/"))
    # a drive root ("D:\") has no base name: show the root as it is spelled
    if name == "":
        name = root
    tree = new_node(name, root)
    # Totals per folder first (a cut at the last separator is cheap), then each folder is placed in
    # the tree once: there are far fewer folders than files.
    own = {}
    for info in files:
        folder = file_folder(root, info["path"])
        if folder not in own:
            own[folder] = {"bytes": 0, "files": 0, "list": [], "trash": False}
        own[folder]["bytes"] = own[folder]["bytes"] + info["disk"]
        own[folder]["files"] = own[folder]["files"] + 1
        if info["disk"] > 0:
            own[folder]["list"].append(info)
    for info in trash:
        folder = trash_folder_of(root, info["path"])
        if folder not in own:
            own[folder] = {"bytes": 0, "files": 0, "list": [], "trash": True}
        own[folder]["bytes"] = own[folder]["bytes"] + info["disk"]
        own[folder]["files"] = own[folder]["files"] + 1
    # the top Node gets every folder's sums, and each Node below it those of the folders inside it
    for folder in own:
        total = own[folder]
        trash_bytes = 0
        if total["trash"]:
            trash_bytes = total["bytes"]
        node = tree
        node["bytes"] = node["bytes"] + total["bytes"]
        node["files"] = node["files"] + total["files"]
        node["trash"] = node["trash"] + trash_bytes
        for part in path_parts(relative_path(root, folder)):
            if part not in node["children"]:
                node["children"][part] = new_node(part, os.path.join(node["path"], part))
            node = node["children"][part]
            node["bytes"] = node["bytes"] + total["bytes"]
            node["files"] = node["files"] + total["files"]
            node["trash"] = node["trash"] + trash_bytes
        if total["trash"]:
            node["kind"] = "trash"
        for info in sort_by_disk_desc(total["list"]):
            node["file_list"].append(info)
    for node in folder_nodes(tree):
        item_files = len(node["file_list"])
        for name in node["children"]:
            child = node["children"][name]
            if child["bytes"] > 0:
                node["folder_list"].append(child)
                item_files = item_files + child["files"]
        # sorted once here, so map_entries can merge the two lists without sorting
        node["folder_list"].sort(key=entry_bytes, reverse=True)
        node["item_files"] = item_files
    return tree


def folder_chain(tree, root, parts):
    """Nodes from the tree's top down through the folders named in parts, or None if one is missing.

    parts are folder names below the top (path_parts of a relative path). root is not used; it is
    kept so the call reads like find_node's.
    """
    chain = [tree]
    node = tree
    for part in parts:
        if part not in node["children"]:
            return None
        node = node["children"][part]
        chain.append(node)
    return chain


def find_node(tree, root, folder):
    """The Node for folder (root or a folder below it), or None when it is not in the tree.

    A folder outside root (a sibling with a longer name, another drive) and a folder with no files
    anywhere below it (so build_folder_tree made no Node for it) both give None. The GUI uses it to find the
    folder the map is centred on.
    """
    if not is_inside(root, folder):
        return None
    chain = folder_chain(tree, root, path_parts(relative_path(root, folder)))
    if chain is None:
        return None
    return chain[len(chain) - 1]


def mark_wasted(tree, root, groups, keep):
    """Set each Node's wasted bytes (what the duplicate copies below it that are not the kept one would
    free) and its wasted_paths (those copies directly in it; a copy that frees nothing, such as a hard
    link, is not marked). Copies outside the tree are left out.

    Each copy is added to the folder it is in, then every folder's total is added to its parent's,
    deepest first: one pass over the copies and one over the folders, however deep they are.

    groups are Duplicates groups (lists of FileInfo); keep maps a path to True for copies the user
    chose to keep (keeper_index picks the kept copy of each group from it). Changes the Nodes in place.
    """
    nodes = folder_nodes(tree)
    by_path = {}
    for node in nodes:
        node["wasted"] = 0
        node["wasted_paths"] = {}
        by_path[node["path"]] = node
    # Paths come from the same walk as the tree, spelled the same way, so a plain prefix test is enough
    # (and much cheaper than is_inside for tens of thousands of copies).
    prefix = root
    if not root.endswith(os.sep) and not root.endswith("/"):
        prefix = root + os.sep
    for group in groups:
        keeper = keeper_index(group, keep)
        index = 0
        while index < len(group):
            info = group[index]
            frees = copy_frees(info)
            if index != keeper and frees > 0 and info["path"].startswith(prefix):
                folder = file_folder(root, info["path"])
                if folder in by_path:
                    by_path[folder]["wasted"] = by_path[folder]["wasted"] + frees
                    by_path[folder]["wasted_paths"][info["path"]] = frees
            index = index + 1
    # nodes lists each folder before its subfolders, so backwards every child's total is final
    # before it is added to its parent
    index = len(nodes) - 1
    while index >= 0:
        node = nodes[index]
        for name in node["children"]:
            node["wasted"] = node["wasted"] + node["children"][name]["wasted"]
        index = index - 1


def change_wasted(tree, root, info, amount):
    """Add amount (negative to take away) to the wasted bytes of every folder holding info, and mark
    (amount > 0) or unmark (amount < 0) info as an extra copy in its own folder. Copies outside the
    tree are left out.

    The chain runs from the top Node to the file's own folder, so the change reaches every folder
    that holds the file and nothing else.
    """
    if amount == 0 or not is_inside(root, info["path"]):
        return
    parts = path_parts(relative_path(root, info["path"]))
    chain = folder_chain(tree, root, parts[0:len(parts) - 1])
    if chain is None:
        return
    for node in chain:
        node["wasted"] = node["wasted"] + amount
    last = chain[len(chain) - 1]
    if amount > 0:
        last["wasted_paths"][info["path"]] = amount
    elif info["path"] in last["wasted_paths"]:
        del last["wasted_paths"][info["path"]]


def shift_kept_copy(tree, root, kept_before, kept_now):
    """Update mark_wasted's marks when a group's kept copy changes: the old one becomes an extra copy and
    the new one stops being one. Costs the depth of two folders, not a pass over every copy.

    Called by the GUI when the user picks another copy to keep in the Duplicates view. Copies that
    free nothing (hard links) change nothing, as copy_frees gives 0 for them.
    """
    if kept_before["path"] == kept_now["path"]:
        return
    change_wasted(tree, root, kept_before, copy_frees(kept_before))
    change_wasted(tree, root, kept_now, 0 - copy_frees(kept_now))


# ---- sunburst layout ----------------------------------------------------------------------------

def entry_bytes(entry):
    """Sort key: the bytes on disk of a Node or a map entry."""
    return entry["bytes"]


def map_item_count(node):
    """How many slices a folder has: subfolders and files that take space."""
    return len(node["folder_list"]) + len(node["file_list"])


def map_entries(node, limit):
    """A folder's slices, biggest first, at most limit of them: its subfolders (and trash folders) and
    the files directly in it, as {"kind", "node", "name", "path", "bytes", "size", "files", "wasted",
    "trash", "modified"} (see Arc).

    folder_list and file_list are already sorted, so this merges two sorted lists and stops at limit:
    a folder with a hundred thousand files or subfolders costs no more than one with a few.

    On equal bytes the folder comes first. A file's wasted is its entry in node's wasted_paths (0 when
    it is not an extra duplicate copy); a folder's is its Node's total.
    """
    folders = node["folder_list"]
    files = node["file_list"]
    entries = []
    next_folder = 0
    next_file = 0
    while len(entries) < limit and (next_folder < len(folders) or next_file < len(files)):
        take_folder = next_file >= len(files)
        if next_folder < len(folders) and next_file < len(files):
            take_folder = folders[next_folder]["bytes"] >= files[next_file]["disk"]
        if take_folder:
            child = folders[next_folder]
            entries.append({"kind": child["kind"], "node": child, "name": child["name"], "path": child["path"],
                            "bytes": child["bytes"], "size": 0, "files": child["files"], "wasted": child["wasted"],
                            "trash": child["trash"], "modified": 0.0})
            next_folder = next_folder + 1
        else:
            info = files[next_file]
            wasted = 0
            if info["path"] in node["wasted_paths"]:
                wasted = node["wasted_paths"][info["path"]]
            entries.append({"kind": "file", "node": None, "name": os.path.basename(info["path"]),
                            "path": info["path"], "bytes": info["disk"], "size": info["size"], "files": 1,
                            "wasted": wasted, "trash": 0, "modified": info["modified"]})
            next_file = next_file + 1
    return entries


def ring_min_angles(max_depth, hole, ring, min_pixels, min_degrees):
    """The narrowest slice each ring may draw, in degrees: [ring 1, ring 2, ...].

    A slice must be min_pixels wide at the inner edge of its ring (inner rings are short, so they
    need wider angles), and never narrower than min_degrees.

    hole is the radius of the empty centre and ring the width of each ring, both in pixels, so ring
    d starts at radius hole + (d - 1) * ring. An arc of angle a (radians) at radius r is a * r long,
    so min_pixels needs a = min_pixels / r radians there. A radius or min_pixels of 0 leaves only
    min_degrees.
    """
    angles = []
    depth = 1
    while depth <= max_depth:
        angle = min_degrees
        inner = hole + (depth - 1) * ring
        if inner > 0 and min_pixels > 0:
            needed = math.degrees(min_pixels / inner)
            if needed > angle:
                angle = needed
        angles.append(angle)
        depth = depth + 1
    return angles


def layout_sunburst(node, max_depth, min_angles):
    """Rings around node -> list of Arc, inner rings first.

    Angles are degrees clockwise from 12 o'clock. Each folder's slices (subfolders and files) share
    its angle by bytes; slices narrower than min_angles[depth - 1] (see ring_min_angles) are merged
    into one "rest" arc. Rings stop at max_depth; a trash folder is one slice, never opened.

    node is the folder at the centre (a Node, which is not drawn itself); min_angles has max_depth
    values. An empty folder gives no arcs.

    Steps:
      1. Queue the centre: the full circle at depth 1. Folders are handled in queue order, so arcs
         come out ring by ring.
      2. For each queued folder, take its biggest slices (map_entries), only as many as could be wide
         enough, and give each its share of the folder's angle, one after another clockwise.
      3. At the first slice narrower than the ring's minimum, stop: the rest are smaller still.
         The folder's very last slice is the exception: alone it is drawn as itself.
      4. Queue each drawn subfolder for the next ring, inside its own angle, while depth allows.
      5. If some slices were not drawn, add one "rest" arc for them that fills the angle up to the
         folder's end, its bytes and counts being the folder's totals less what was drawn.

    branch is the index of the ring-1 slice an arc lies under; arc_color picks the hue from it.
    """
    arcs = []
    if node["bytes"] <= 0:
        return arcs
    pending = [{"node": node, "start": 0.0, "extent": 360.0, "depth": 1, "branch": -1}]
    while len(pending) > 0:
        item = pending.pop(0)
        parent = item["node"]
        count = map_item_count(parent)
        narrowest = min_angles[item["depth"] - 1]
        # At most extent / narrowest slices can be wide enough to draw, so only that many (and two
        # spare, as int() rounds down and floating point can fall just short) are looked at; the
        # rest is summed from the folder's totals below.
        limit = count
        if narrowest > 0:
            limit = int(item["extent"] / narrowest) + 2
            if limit > count:
                limit = count
        entries = map_entries(parent, limit)
        angle = item["start"]
        drawn = {"count": 0, "bytes": 0, "files": 0, "wasted": 0, "trash": 0}
        index = 0
        while index < len(entries):
            entry = entries[index]
            extent = item["extent"] * entry["bytes"] / parent["bytes"]
            # Biggest first, so once one slice is too narrow every later one is too: merge the tail
            # (a lone narrow slice is drawn as itself).
            if extent < narrowest and index < count - 1:
                break
            # ring-1 slices start a branch; everything further out inherits it (and its hue)
            branch = item["branch"]
            if item["depth"] == 1:
                branch = index
            arcs.append({"path": entry["path"], "name": entry["name"], "kind": entry["kind"],
                         "depth": item["depth"], "start": angle, "extent": extent, "bytes": entry["bytes"],
                         "size": entry["size"], "files": entry["files"], "wasted": entry["wasted"],
                         "trash": entry["trash"], "branch": branch, "modified": entry["modified"]})
            if entry["kind"] == "folder" and item["depth"] < max_depth:
                pending.append({"node": entry["node"], "start": angle, "extent": extent,
                                "depth": item["depth"] + 1, "branch": branch})
            drawn["count"] = drawn["count"] + 1
            drawn["bytes"] = drawn["bytes"] + entry["bytes"]
            drawn["files"] = drawn["files"] + entry["files"]
            drawn["wasted"] = drawn["wasted"] + entry["wasted"]
            drawn["trash"] = drawn["trash"] + entry["trash"]
            angle = angle + extent
            index = index + 1
        # the rest arc ends exactly at the folder's end angle, so rounding never leaves a gap
        if drawn["count"] < count:
            branch = item["branch"]
            if item["depth"] == 1:
                branch = index
            arcs.append({"path": parent["path"], "name": plural(count - drawn["count"], "smaller item"),
                         "kind": "rest", "depth": item["depth"], "start": angle,
                         "extent": item["start"] + item["extent"] - angle, "bytes": parent["bytes"] - drawn["bytes"],
                         "size": 0, "files": parent["item_files"] - drawn["files"],
                         "wasted": parent["wasted"] - drawn["wasted"], "trash": parent["trash"] - drawn["trash"],
                         "branch": branch, "modified": 0.0})
    return arcs


# ---- shapes and colours -------------------------------------------------------------------------

def ring_points(cx, cy, inner, outer, start, extent, step):
    """Polygon [x0, y0, x1, y1, ...] for a ring slice: along the outer edge, then back along the inner one.

    Angles are degrees clockwise from 12 o'clock; step is the largest angle between two points.

    cx, cy is the centre and inner, outer the two radii, in canvas pixels. Canvas y grows downward,
    so a point at angle a is (cx + r sin a, cy - r cos a): a = 0 is straight up and growing a turns
    clockwise. A curved edge is drawn as straight pieces at most step degrees apart, at least one.
    """
    count = int(math.ceil(extent / step))
    if count < 1:
        count = 1
    points = []
    index = 0
    while index <= count:
        angle = math.radians(start + extent * index / count)
        points.append(cx + outer * math.sin(angle))
        points.append(cy - outer * math.cos(angle))
        index = index + 1
    index = count
    while index >= 0:
        angle = math.radians(start + extent * index / count)
        points.append(cx + inner * math.sin(angle))
        points.append(cy - inner * math.cos(angle))
        index = index - 1
    return points


def hls_hex(hue, lightness, saturation):
    """A colour given as hue, lightness and saturation (each 0 to 1) -> "#rrggbb" for Tk.

    HLS describes a colour by its hue on the colour wheel, how light it is (0 black, 0.5 full colour,
    1 white) and how strong (0 grey). The + 0.5 rounds each channel to the nearest of 0 to 255.
    """
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#%02x%02x%02x" % (int(red * 255 + 0.5), int(green * 255 + 0.5), int(blue * 255 + 0.5))


def arc_color(arc, mode, max_depth):
    """Fill colour of an Arc. mode "folders": one hue per top-level slice, lighter further out.
    mode "duplicates": grey, turning red as the share of duplicate copies in the slice grows.
    A trash folder is a darker grey in both.

    outward runs from 0 at ring 1 to 1 at ring max_depth. In "duplicates" mode the redness reaches
    its full strength once half of the slice's bytes are extra copies. In "folders" mode folders are
    the strongest colour, files paler and "rest" slices plain grey, all getting lighter outward.
    """
    if arc["kind"] == "trash":
        return TRASH_COLOUR
    outward = 0.0
    if max_depth > 1:
        outward = (arc["depth"] - 1) / float(max_depth - 1)
    if mode == "duplicates":
        share = 0.0
        if arc["bytes"] > 0:
            share = arc["wasted"] / float(arc["bytes"])
        # full red at a 50% share: lightness 0.86 (pale grey) down to 0.50, saturation 0 up to 0.75
        strength = share / 0.5
        if strength > 1.0:
            strength = 1.0
        return hls_hex(0.0, 0.86 - 0.36 * strength, 0.75 * strength)
    hue = MAP_HUES[arc["branch"] % len(MAP_HUES)] / 360.0
    if arc["kind"] == "rest":
        return hls_hex(hue, 0.80 + 0.08 * outward, 0.0)
    if arc["kind"] == "file":
        return hls_hex(hue, 0.74 + 0.08 * outward, 0.18)
    return hls_hex(hue, 0.50 + 0.25 * outward, 0.55)

# ==== stamp v1 | author=kjFriday | hmac-sha256=6a201a456ce6ae16679c3c3a134b536bb9b5023341bcae3bd2503dafc5b5882c ====
