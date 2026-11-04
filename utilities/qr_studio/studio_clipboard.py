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
"""

import os
import subprocess

from qr_codec import fail, ok_result


def run_powershell(script, timeout):
    """-> Result stdout. Windows only."""
    if os.name != "nt":
        return fail("the clipboard needs Windows")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                              text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        return fail(str(error))
    if done.returncode != 0:
        return fail(done.stderr.strip() or "PowerShell failed")
    return ok_result(done.stdout)


def quote_for_powershell(text):
    return "'" + text.replace("'", "''") + "'"


def clipboard_image_to_png(path):
    """Save the picture on the clipboard as a PNG -> Result path."""
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$i = [Windows.Forms.Clipboard]::GetImage(); if ($i -eq $null) { exit 3 }; "
              "$i.Save(" + quote_for_powershell(path) + ", [Drawing.Imaging.ImageFormat]::Png)")
    done = run_powershell(script, 20)
    if not done["ok"]:
        if os.name == "nt" and not os.path.isfile(path):
            return fail("there is no picture on the clipboard")
        return done
    return ok_result(path)


def png_to_clipboard(path):
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "[Windows.Forms.Clipboard]::SetImage([Drawing.Image]::FromFile(" + quote_for_powershell(path) + "))")
    return run_powershell(script, 20)

# ==== stamp v1 | author=kjFriday | hmac-sha256=64efd1398a350a7052f17d976da7b94ca7605e4227d76f423ca3e9597769ffd0 ====
