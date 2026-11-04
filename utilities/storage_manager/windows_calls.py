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

Who calls it: scanning.walk_tree (is_network_path once per walk, allocated_size per compressed or
sparse file on worker threads). Both functions are safe to call from several threads at once: the
kernel32 table is filled once, and ctypes keeps a last-error value per thread.
"""

import ctypes
import os

from records import failure, success

DRIVE_REMOTE = 4              # GetDriveTypeW: a mapped network drive


# Windows calls: the only OS-specific pieces of the walk. Loaded on first use; None elsewhere.
# Keys "drive_type" and "compressed_size" hold the configured ctypes functions.
WINDOWS_API = {}


def windows_api():
    """kernel32 functions the core calls -> dict of ctypes functions, or None when not on Windows.

    Setting argtypes and restype makes ctypes pass a Python str as a UTF-16 wide string (the W in
    the names) and read the result as an unsigned 32-bit DWORD / UINT rather than a signed int.
    """
    if os.name != "nt":
        return None
    # two threads may both see it empty and fill it: harmless, they store equal functions
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
    """path in the \\\\?\\ form Windows calls take past 260 characters.

    260 is MAX_PATH, the classic Windows path limit; the \\\\?\\ prefix lifts it to about 32,767
    characters but turns off path parsing, so the path is made absolute first. A UNC path becomes
    \\\\?\\UNC\\host\\share\\... Shorter paths and paths already in this form are returned as is.
    """
    if len(path) < 260 or path.startswith("\\\\?\\"):
        return path
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full


def is_network_path(path):
    """True for a folder on a network share: a \\\\host\\share path or a mapped drive (Windows only;
    elsewhere the listing already says what a file takes, so it does not matter).

    Steps:
      1. A \\\\?\\UNC\\ or \\\\host\\ path is on a share.
      2. Otherwise take its drive ("D:") and ask GetDriveTypeW, which needs the drive's root ("D:\\").
    """
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
    (GetCompressedFileSizeW); it reads the file's attributes, not its data.

    The call returns the size as two 32-bit halves: the low DWORD as its result, the high one through
    the pointer. 0xFFFFFFFF (INVALID_FILE_SIZE) is a failure only when the last error is not 0, since a
    size can end in those bits too. Any other failure comes back as "Windows error N".
    """
    api = windows_api()
    if api is None:
        return failure("not available")
    high = ctypes.c_ulong(0)
    low = api["compressed_size"](long_path(path), ctypes.byref(high))
    # Known limitation: the last error is not reset to 0 before the call, so a file whose low half
    # is exactly 0xFFFFFFFF can read as a failure when an earlier call on this thread left an error
    # (the caller then counts the file at its size)
    if low == 0xFFFFFFFF:
        code = ctypes.get_last_error()
        if code != 0:
            return failure("Windows error " + str(code))
    # 4294967296 is 2 ** 32: the high half shifted above the low one
    return success(high.value * 4294967296 + low)

# ==== stamp v1 | author=kjFriday | hmac-sha256=a08d1d0030f93b58100f31c963b5732d5a1e2f85ce7ab35aa1bffbed903eb6bf ====
