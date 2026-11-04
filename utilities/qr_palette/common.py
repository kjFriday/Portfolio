# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: common.py
# About: What the core modules share: the Result record, with_registry, and spreadsheet cells that...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""What the core modules share: the Result record, with_registry, and spreadsheet cells that stay text.

Every operation of the core answers with a Result instead of raising. The operations that write the
registry, and most that read it, go through with_registry: it opens the registry read-write, runs the work
and closes it again, so no connection outlives a call (the exports read it on the read-only rail instead).
safe_cell keeps a CSV cell from being read as a formula; the registry's export and a batch's report both
write their cells through it.

Records
  Result   {"ok": bool, "error": str, "value": any}   a failure has the value None and a short error phrase
"""

import registry


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def with_registry(db_path, work):
    """Open the registry read-write, run work(connection), close it -> work's Result."""
    opened = registry.connect(db_path, False)
    if not opened["ok"]:
        return opened
    try:
        return work(opened["value"])
    finally:
        registry.close(opened["value"])


def safe_cell(value):
    """A spreadsheet cell that is never read as a formula: text that starts with = + - @, a tab or a
    carriage return gets a leading apostrophe."""
    text = ""
    if value is not None:
        text = str(value)
    if text != "" and text[0] in "=+-@\t\r":
        return "'" + text
    return text

# ==== stamp v1 | author=kjFriday | hmac-sha256=ecabf082e6ccde5c99dad96a19fc3d1cc109b624e532be76dcbe722d42dd4660 ====
