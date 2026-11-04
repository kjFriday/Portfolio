# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: common.py
# About: What the core modules share: the Result record, with_registry and safe spreadsheet cells.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""What the core modules share: the Result record, with_registry and safe spreadsheet cells.

Spreadsheet cells here are cells that always stay text.

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
    """A successful Result holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result: `error` is a short lowercase phrase the window or a caller can show as is."""
    return {"ok": False, "error": error, "value": None}


def with_registry(db_path, work):
    """Open the registry read-write, run work(connection), close it -> work's Result.

    `db_path` is the registry file (made with its folder if it is not there yet). A failure to open
    comes back as registry.connect's own failed Result and work never runs. The connection is closed
    even when work raises; the exception itself is not caught. Each call opens its own connection,
    so the window's job thread and its main thread never share one."""
    opened = registry.connect(db_path, False)
    if not opened["ok"]:
        return opened
    try:
        return work(opened["value"])
    finally:
        registry.close(opened["value"])


def safe_cell(value):
    """A spreadsheet cell that is never read as a formula: text that starts with = + - @, a tab or a
    carriage return gets a leading apostrophe.

    This is the usual guard against CSV formula injection: Excel and its kin start a formula at any
    of those first characters (a tab or carriage return can hide one), and the apostrophe makes
    them show the cell as text. None becomes an empty cell; other values go through str()."""
    text = ""
    if value is not None:
        text = str(value)
    if text != "" and text[0] in "=+-@\t\r":
        return "'" + text
    return text

# ==== stamp v1 | author=kjFriday | hmac-sha256=18e5ba58a59a4f457b54e09e84a1dc025334529f0edc1d42cc78c731c1768bae ====
