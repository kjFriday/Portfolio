# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: windows_calls.py
# About: Storage Manager: the two Windows calls the walk makes, through ctypes.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager: the two Windows calls the walk makes, through ctypes.

allocated_size asks what a compressed or sparse file takes on disk (GetCompressedFileSizeW) and
is_network_path tells whether a folder is on a network share (GetDriveTypeW). Elsewhere they answer
"not available" and False. They are the only calls of the core that need ctypes, so they are kept
here, apart from the core modules: a port replaces this file with its own platform's calls.
"""

import ctypes
import os

from records import failure, success

DRIVE_REMOTE = 4              # GetDriveTypeW: a mapped network drive


# Windows calls: the only OS-specific pieces of the walk. Loaded on first use; None elsewhere.
WINDOWS_API = {}


def windows_api():
    """kernel32 functions the core calls -> dict of ctypes functions, or None when not on Windows."""
    if os.name != "nt":
        return None
    if len(WINDOWS_API) == 0:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # our own copy: argtypes stay ours
        compressed = kernel32.GetCompressedFileSizeW
        compressed.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        compressed.restype = ctypes.c_ulong
        drive_type = kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        WINDOWS_API["drive_type"] = drive_type
        WINDOWS_API["compressed_size"] = compressed
    return WINDOWS_API


def long_path(path):
    """path in the \\\\?\\ form Windows calls take past 260 characters."""
    if len(path) < 260 or path.startswith("\\\\?\\"):
        return path
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full


def is_network_path(path):
    """True for a folder on a network share: a \\\\host\\share path or a mapped drive (Windows only;
    elsewhere the listing already says what a file takes, so it does not matter)."""
    api = windows_api()
    if api is None:
        return False
    full = os.path.abspath(path)
    if full.upper().startswith("\\\\?\\UNC\\"):
        return True
    if full.startswith("\\\\?\\"):
        full = full[4:]
    if full.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(full)[0]
    if drive == "":
        return False
    return api["drive_type"](drive + "\\") == DRIVE_REMOTE


def allocated_size(path):
    """Bytes a compressed or sparse file takes on disk -> Result(int). Windows only
    (GetCompressedFileSizeW); it reads the file's attributes, not its data."""
    api = windows_api()
    if api is None:
        return failure("not available")
    high = ctypes.c_ulong(0)
    low = api["compressed_size"](long_path(path), ctypes.byref(high))
    if low == 0xFFFFFFFF:
        code = ctypes.get_last_error()
        if code != 0:
            return failure("Windows error " + str(code))
    return success(high.value * 4294967296 + low)

# ==== stamp v1 | author=kjFriday | hmac-sha256=a08d1d0030f93b58100f31c963b5732d5a1e2f85ce7ab35aa1bffbed903eb6bf ====
