# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_clipboard.py
# About: QR Studio's clipboard: pictures to and from the Windows clipboard, through PowerShell.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's clipboard: pictures to and from the Windows clipboard, through PowerShell.

Windows only. Python's standard library cannot reach a picture on the clipboard, so each call runs a short
PowerShell script that uses System.Windows.Forms.Clipboard. run_powershell starts it with -STA (the Forms
clipboard needs a single-threaded apartment) and CREATE_NO_WINDOW (so pythonw shows no console window), and
reports the outcome as a Result record. A path goes into a script between single quotes, with any single
quote in it doubled (quote_for_powershell). The window uses clipboard_image_to_png for Paste picture and
png_to_clipboard for Copy picture.

Who calls what: studio_gui.StudioWindow (paste_picture, copy_picture) calls the two public functions;
they build a script, hand it to run_powershell, and turn its Result into one about the file. Nothing
else in the program touches the clipboard, so a port replaces only this module.

Flow of one call:
  1. Build a one-line PowerShell script that loads System.Windows.Forms and System.Drawing.
  2. Put the file path in it as a single-quoted PowerShell literal (quote_for_powershell).
  3. Run powershell.exe hidden, in a single-threaded apartment, with a time limit (run_powershell).
  4. Map the exit code and stderr to a Result record.
"""

import os
import subprocess

from qr_codec import fail, ok_result


def run_powershell(script, timeout):
    """Run one PowerShell `script` and wait for it -> Result stdout. Windows only.

    `timeout` is in seconds; past it the process is killed and the Result fails with the timeout
    message. Side effect: starts powershell.exe as a child process (no profile, no console window).
    Fails without starting anything on other systems, when powershell cannot start, or when the
    script exits non-zero (the error is its stderr, or "PowerShell failed" when stderr is empty).
    """
    if os.name != "nt":
        return fail("the clipboard needs Windows")
    try:
        # -NoProfile: a user's profile script could print or fail and is slow to load.
        # getattr: CREATE_NO_WINDOW (0x08000000) exists only in the Windows build of subprocess.
        done = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                              text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        return fail(str(error))
    if done.returncode != 0:
        return fail(done.stderr.strip() or "PowerShell failed")
    return ok_result(done.stdout)


def quote_for_powershell(text):
    """Return `text` as a single-quoted PowerShell string literal.

    Inside single quotes PowerShell expands nothing ($ and backticks stay literal); the only special
    character is the single quote itself, written twice. So any file path is safe to splice in.
    """
    return "'" + text.replace("'", "''") + "'"


def clipboard_image_to_png(path):
    """Save the picture on the clipboard as a PNG -> Result path.

    Side effect: writes the PNG file at `path` (the window passes a fixed name in the temp folder and
    removes any old copy first, so the file check below sees only this run's output). Fails with "there is no
    picture on the clipboard" when the script fails and left no file, which is what exit 3 (GetImage
    returned nothing) leads to; other failures, and every failure off Windows, pass through as they are.
    """
    # GetImage returns $null when the clipboard holds no bitmap; exit 3 makes that a non-zero exit
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$i = [Windows.Forms.Clipboard]::GetImage(); if ($i -eq $null) { exit 3 }; "
              "$i.Save(" + quote_for_powershell(path) + ", [Drawing.Imaging.ImageFormat]::Png)")
    done = run_powershell(script, 20)  # 20 seconds: a cold PowerShell start loading Forms can take several
    if not done["ok"]:
        if os.name == "nt" and not os.path.isfile(path):
            return fail("there is no picture on the clipboard")
        return done
    return ok_result(path)


def png_to_clipboard(path):
    """Put the picture in the PNG file at `path` on the clipboard -> Result stdout (empty on success).

    Side effect: replaces whatever is on the Windows clipboard. The file must exist until the script
    ends; the window leaves its copy in the temp folder and overwrites it on the next Copy picture.
    """
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "[Windows.Forms.Clipboard]::SetImage([Drawing.Image]::FromFile(" + quote_for_powershell(path) + "))")
    return run_powershell(script, 20)

# ==== stamp v1 | author=kjFriday | hmac-sha256=64efd1398a350a7052f17d976da7b94ca7605e4227d76f423ca3e9597769ffd0 ====
