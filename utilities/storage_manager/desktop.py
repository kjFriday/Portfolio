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

What it is for: gui.py fills the folder box from list_drives and add_recent, cleans what the user
typed with normalize_folder, and runs reveal_command or open_folder_command through launch for "Show
in its folder" and "Open folder" (gui_views.py does the same for the map and the trash folder). These
are the OS-specific pieces README.md names for porting. The self-test pins command_line's Explorer
quoting, normalize_folder and add_recent.

Main flow for showing a file:
  1. reveal_command or open_folder_command builds an argument list for this OS.
  2. launch starts it without waiting. On Windows it first turns the list into one command line
     with command_line, because Explorer parses its command line its own way.
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
    """Drive roots on this machine (C:\\, D:\\ ... on Windows, / elsewhere).

    On Python 3.12+ os.listdrives asks Windows (GetLogicalDriveStrings) and returns [] when that
    fails. Older Pythons probe C: to Z: with os.path.exists instead; A: and B: are skipped, as
    probing a floppy letter can be slow.
    """
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
    """The command that shows a file selected in the system file manager -> argument list.

    Windows: explorer /select,<path> (command_line joins the two). macOS: open -R reveals it in
    Finder. Elsewhere xdg-open has no way to select a file, so it opens the file's folder; the file
    itself is never passed, as that would open (run) it.
    """
    if os.name == "nt":
        return ["explorer", "/select,", path]
    if sys.platform == "darwin":
        return ["open", "-R", path]
    return ["xdg-open", os.path.dirname(path)]


def open_folder_command(folder):
    """The command that opens folder in the system file manager -> argument list.

    On macOS a folder that is a package (see MAC_PACKAGES) is shown selected instead of opened, as
    "open" would launch it. A trailing "/" is stripped first so "Xcode.app/" is still recognised.
    """
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
    every path for it is quoted, with "/select," joined to the path after it.

    Any other program gets the usual Microsoft C runtime quoting from subprocess.list2cmdline.
    Explorer does not use those rules: it reads its command line as a list of switches split at ","
    and "=", so an unquoted path such as D:\\Q1,Q2\\a.xlsx would be cut in two. The self-test pins
    these outputs (for example explorer /select,"D:\\Q1,Q2\\a.xlsx").

    Steps:
      1. Start the line with "explorer".
      2. For each argument: when it ends with "," (a switch such as "/select,") and a path follows,
         take the path too and write the switch right before the quoted path, with no space.
      3. Quote every path, adding "." after a trailing backslash (see below).
    """
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
            # C runtime rule: backslashes are literal unless a quote follows them; "\." names the
            # same folder and keeps the closing quote a quote
            part = part + "."  # D:\ becomes "D:\." : a backslash right before the closing quote would escape it
        part = '"' + part + '"'
        if switch != "":
            line = line + " " + switch + part
        else:
            line = line + " " + part
        index = index + 1
    return line


def launch(arguments):
    """Start a program without waiting for it -> Result(None).

    arguments: an argument list from reveal_command or open_folder_command. Windows gets one command
    line built by command_line (Popen passes a string through as is); elsewhere the list is passed
    as argv. The process is not waited for or kept. Fails with the OS message when the program
    cannot be started; what the program does after starting is not checked.
    """
    try:
        if os.name == "nt":
            subprocess.Popen(command_line(arguments))
        else:
            subprocess.Popen(arguments)
    except OSError as e:
        return failure(error_text(e))
    return success(None)


def normalize_folder(text):
    """What the user typed -> a folder path ("D:" becomes "D:\\", surrounding quotes and spaces go).

    Quotes come with a pasted path, for example from Explorer's "Copy as path". A bare "D:" means the current folder on drive D, not
    its root, so it gets a separator. The path is not checked to exist.
    """
    folder = text.strip()
    if len(folder) >= 2 and folder[0] == '"' and folder[len(folder) - 1] == '"':
        folder = folder[1:len(folder) - 1]
    if len(folder) == 2 and folder[1] == ":":
        folder = folder + os.sep
    return folder


def add_recent(recent, folder, limit):
    """recent with folder moved to the front, at most limit entries.

    Any earlier entry for the same folder is dropped, compared with os.path.normcase so "d:\\x" and
    "D:\\X" are one entry on Windows. The list passed in is not changed.
    """
    result = [folder]
    for item in recent:
        if os.path.normcase(item) != os.path.normcase(folder) and len(result) < limit:
            result.append(item)
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=c39470758a68c965a47e4ed137675182a50bf3051fd597e261f3e69972d721d1 ====
