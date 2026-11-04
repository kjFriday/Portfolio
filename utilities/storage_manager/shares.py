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

A Share is {"name", "unc", "letter"} (records.py): unc is a \\\\host\\share path and letter a drive
letter such as "Z:" or "" for none. Windows signs in to the share with the user's own logon or with
credentials Windows already stores; when it cannot, `net use` fails and its message is shown.

Who calls it: gui.py's Network shares view (check, map, disconnect, add-share dialog) and
selftest.py, which also uses run_command for `compact`. Only records.py is imported.
"""

import os
import shutil
import subprocess

from records import error_text, failure, success


def unc_host(unc):
    """\\\\host\\share\\path -> host (or "" if it is not a UNC path).

    A UNC (Universal Naming Convention) path starts with two backslashes and the host name; forward
    slashes are accepted too.
    """
    cleaned = unc.replace("/", "\\")
    if not cleaned.startswith("\\\\"):
        return ""
    parts = cleaned[2:].split("\\")
    return parts[0]


def valid_letter(letter):
    """True for a drive letter a share may take: "" (none), or "D:" to "Z:" in either case.

    A to C are refused: A and B are the old floppy letters and C is the system drive.
    """
    if len(letter) == 2 and letter[1] == ":" and letter[0].upper() >= "D" and letter[0].upper() <= "Z":
        return True
    return letter == ""


def share_path(share):
    """The path to read: the drive letter when one is set, else the UNC path.

    The letter gets a backslash ("Z:\\"): a bare "Z:" means the current folder on that drive.
    """
    if share["letter"] != "":
        return share["letter"] + "\\"
    return share["unc"]


def run_command(arguments, timeout):
    """Run an OS command -> Result(stdout text). No shell, so arguments are passed as-is.

    arguments is the argv list; timeout is in seconds. Blocks until the command ends, so callers run
    it on a job thread. A command that cannot start or runs too long fails with Python's message;
    a non-zero exit fails with its stderr, or its stdout when stderr is empty.
    """
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
    """The command that maps a share (Windows `net use`). Credentials are never passed or stored.

    Without a letter, `net use \\\\host\\share` only connects to the share (signs in) so its UNC
    path can be read. With one, /persistent:no keeps Windows from mapping it again at the next logon.
    """
    if share["letter"] == "":
        return ["net", "use", share["unc"]]
    return ["net", "use", share["letter"], share["unc"], "/persistent:no"]


def unmap_command(share):
    """The command that disconnects a share: its drive letter, or its UNC path when it has none.

    /y answers yes up front when Windows asks whether to close files still open on it, so the
    command never waits for input.
    """
    target = share["letter"]
    if target == "":
        target = share["unc"]
    return ["net", "use", target, "/delete", "/y"]


def map_share(share):
    """Map (or connect to) a share with `net use` -> Result(command output).

    Fails at once off Windows or for a drive letter valid_letter refuses; waits up to 60 seconds,
    since a first connection can be slow.
    """
    if os.name != "nt":
        return failure("mapping uses `net use` and is Windows only; mount the share with your OS tools")
    if not valid_letter(share["letter"]):
        return failure("drive letter must look like Z: (D to Z)")
    return run_command(map_command(share), 60)


def unmap_share(share):
    """Disconnect a share with `net use ... /delete` -> Result(command output); Windows only, up to
    30 seconds."""
    if os.name != "nt":
        return failure("unmapping is Windows only")
    return run_command(unmap_command(share), 30)


def ping_command(host):
    """The command that pings host once.

    Windows: -n 1 sends one echo request and -w 1500 waits 1500 milliseconds for the reply.
    Elsewhere: -c 1 sends one and -W 2 sets the wait. Known limitation: -W is seconds on Linux but
    milliseconds on macOS, where 2 ms is usually too short and the host reads as not answering.
    """
    if os.name == "nt":
        return ["ping", "-n", "1", "-w", "1500", host]
    return ["ping", "-c", "1", "-W", "2", host]


def check_share(share):
    """Reachability and space -> ShareState (always returned, error filled in on failure).

    Steps:
      1. Take the host from the UNC path; a share without one fails at once.
      2. Ping the host (up to 10 seconds). The answer only picks the error message below.
      3. If the share's path (its letter, else its UNC path) is not a readable folder, report whether
         the host answered.
      4. Otherwise read the total, used and free bytes of the share's disk.

    Blocks on the network, so gui.py calls it on a job thread, one share after another.
    Known limitation: the host is pinged before the path is tried, so even a readable share waits
    for the ping, and a host that drops pings waits its full timeout.
    """
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
