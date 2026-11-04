# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: desktop.py
# About: Storage Manager core: drives, the system file manager, starting programs, typed folders.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: drives, the system file manager, starting programs, typed folders.

The commands that show a file or open a folder differ per OS (Explorer, Finder, xdg-open). A file is
only ever shown in its folder, never opened.
"""

import os
import subprocess
import sys

from records import error_text, failure, success

# Folder name endings macOS shows as a single file (a package): opening one would launch an app or a
# document, so such folders are shown selected in Finder instead.
MAC_PACKAGES = {
    ".app": True, ".bundle": True, ".framework": True, ".plugin": True, ".kext": True, ".appex": True,
    ".xpc": True, ".prefpane": True, ".qlgenerator": True, ".mdimporter": True, ".saver": True,
    ".photoslibrary": True, ".photolibrary": True, ".musiclibrary": True, ".tvlibrary": True,
    ".imovielibrary": True, ".fcpbundle": True, ".logicx": True, ".band": True, ".pages": True,
    ".numbers": True, ".key": True, ".rtfd": True, ".xcodeproj": True, ".xcworkspace": True,
    ".xcarchive": True, ".playground": True, ".sparsebundle": True, ".pkg": True, ".mpkg": True,
    ".scptd": True, ".dsym": True,
}


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
        if os.path.splitext(folder.rstrip("/"))[1].lower() in MAC_PACKAGES:
            # A package such as Xcode.app or Photos Library.photoslibrary: "open" would launch it.
            return ["open", "-R", folder]
        return ["open", folder]
    return ["xdg-open", folder]


def command_line(arguments):
    """The Windows command line for arguments. Explorer splits its own arguments at "," and "=", so
    every path for it is quoted, with "/select," joined to the path after it."""
    if len(arguments) == 0 or arguments[0] != "explorer":
        return subprocess.list2cmdline(arguments)
    line = "explorer"
    index = 1
    while index < len(arguments):
        part = arguments[index]
        switch = ""
        if part.endswith(",") and index + 1 < len(arguments):
            switch = part
            index = index + 1
            part = arguments[index]
        if part.endswith("\\"):
            part = part + "."  # D:\ becomes "D:\." : a backslash right before the closing quote would escape it
        part = '"' + part + '"'
        if switch != "":
            line = line + " " + switch + part
        else:
            line = line + " " + part
        index = index + 1
    return line


def launch(arguments):
    """Start a program without waiting for it -> Result(None)."""
    try:
        if os.name == "nt":
            subprocess.Popen(command_line(arguments))
        else:
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=a6f0fce5051964b02aa789f3fec22b2b779eeddc63a174a15767ac0590428b19 ====
