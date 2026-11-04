# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: shares.py
# About: Storage Manager core: check, map and disconnect network shares.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: check, map and disconnect network shares.

Mapping uses Windows `net use` and the reachability check `ping`; map_command, unmap_command and
ping_command build those commands and run_command runs them without a shell. Credentials are never
passed or stored.
"""

import os
import shutil
import subprocess

from records import error_text, failure, success


def unc_host(unc):
    """\\\\host\\share\\path -> host (or "" if it is not a UNC path)."""
    cleaned = unc.replace("/", "\\")
    if not cleaned.startswith("\\\\"):
        return ""
    parts = cleaned[2:].split("\\")
    return parts[0]


def valid_letter(letter):
    if len(letter) == 2 and letter[1] == ":" and letter[0].upper() >= "D" and letter[0].upper() <= "Z":
        return True
    return letter == ""


def share_path(share):
    """The path to read: the drive letter when one is set, else the UNC path."""
    if share["letter"] != "":
        return share["letter"] + "\\"
    return share["unc"]


def run_command(arguments, timeout):
    """Run an OS command -> Result(stdout text). No shell, so arguments are passed as-is."""
    try:
        completed = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return failure(str(e))
    if completed.returncode != 0:
        message = completed.stderr.strip()
        if message == "":
            message = completed.stdout.strip()
        return failure(message)
    return success(completed.stdout)


def map_command(share):
    """The command that maps a share (Windows `net use`). Credentials are never passed or stored."""
    if share["letter"] == "":
        return ["net", "use", share["unc"]]
    return ["net", "use", share["letter"], share["unc"], "/persistent:no"]


def unmap_command(share):
    target = share["letter"]
    if target == "":
        target = share["unc"]
    return ["net", "use", target, "/delete", "/y"]


def map_share(share):
    if os.name != "nt":
        return failure("mapping uses `net use` and is Windows only; mount the share with your OS tools")
    if not valid_letter(share["letter"]):
        return failure("drive letter must look like Z: (D to Z)")
    return run_command(map_command(share), 60)


def unmap_share(share):
    if os.name != "nt":
        return failure("unmapping is Windows only")
    return run_command(unmap_command(share), 30)


def ping_command(host):
    if os.name == "nt":
        return ["ping", "-n", "1", "-w", "1500", host]
    return ["ping", "-c", "1", "-W", "2", host]


def check_share(share):
    """Reachability and space -> ShareState (always returned, error filled in on failure)."""
    state = {"reachable": False, "total": 0, "used": 0, "free": 0, "error": ""}
    host = unc_host(share["unc"])
    if host == "":
        state["error"] = "not a \\\\host\\share path"
        return state
    pinged = run_command(ping_command(host), 10)
    path = share_path(share)
    if not os.path.isdir(path):
        if pinged["ok"]:
            state["error"] = "host answers but the share is not readable (map it or check rights)"
        else:
            state["error"] = "host does not answer"
        return state
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        state["error"] = error_text(e)
        return state
    state["reachable"] = True
    state["total"] = usage.total
    state["used"] = usage.used
    state["free"] = usage.free
    return state

# ==== stamp v1 | author=kjFriday | hmac-sha256=ff202a04fef7978b3b6db893a708de7e04465f63db86412bb8ff14460d291092 ====
