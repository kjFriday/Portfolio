# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: finding.py
# About: Finding codes again: the Find tab's lookup by QR code or by color, and the codes the Read...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Finding codes again: the Find tab's lookup by code or color, and the Read tab's matches.

The Find tab looks codes up by QR code (the text a code holds, or its picture's path) or by color;
the Read tab, after decoding a picture, lists the registered codes that hold the same text.

Callers: gui/find_tab.py (search, shown_from_record, destination, reveal_command_line and
matches_for_text), gui/read_tab.py (matches_for_text), gui/window.py (search) and selftest.py.

search turns the Find tab's choice into an ECP query plan (ecp.find_plan) and matches the registry's rows
against it in Python (registry.find_rows), as ECP does, with no model involved. The Ask row goes through
ECP itself and gets ECP Records back, which shown_from_record turns into the same result rows.
reveal_command_line is the command that shows a result's file in Explorer.

Records
  Shown    {"id", "link", "hex", "name", "family", "path", "exists", "ec_level", "version", "short_code",
            "target", "scans": registry's ScanCount or None, "has_logo": bool}        a result row
"""

import ecp
import localkey
import payloads
import registry
import textsafe
from common import fail, ok_result, with_registry


def shown_from_row(row, exists, totals=None):
    """A registry Row as a result row. `totals` is registry.scan_totals's answer, when it was read.

    `exists` is registry.file_state's answer for the row's picture (True or False here; an ECP
    Record may also carry None, for a file it did not look at). "scans" stays None for a code
    without a short link, and when no totals were read; a short link never scanned counts zero."""
    count = None
    if totals is not None and row["short_code"] != "":
        count = totals.get(row["short_code"], {"total": 0, "recent": 0})
    return {"id": row["id"], "link": row["link"], "hex": row["hex"], "name": row["name"], "family": row["family"],
            "path": row["path"], "exists": exists, "ec_level": row["ec_level"], "version": row["version"],
            "short_code": row["short_code"], "target": row["target"], "scans": count, "has_logo": bool(row["has_logo"])}


def shown_from_record(record):
    """An ECP Record as a result row. Records carry no EC level or version, so the preview is drawn at
    M, as small as the link allows. A short link's ID is the last part of the address it prints.

    Used for the Find tab's Ask row, whose answers come from ecp.query. Scans are not part of a
    Record, and neither is a logo, so those read as unknown and none."""
    code = ""
    if record["target_url"] != "":  # only a code with a short link has a destination of its own
        code = record["payload_url"].rstrip("/").split("/")[-1]
    return {"id": record["id"], "link": record["payload_url"], "hex": record["hex"], "name": record["color_name"],
            "family": record["color_family"], "path": record["file_path"], "exists": record["exists"],
            "ec_level": "M", "version": 1, "short_code": code, "target": record["target_url"], "scans": None,
            "has_logo": False}


def destination(shown):
    """Where a result's code sends people: its short link's destination, or the link it holds.

    `shown` is a Shown row; its "target" is "" for a code that holds its destination itself."""
    return shown["target"] or shown["link"]


def search(db_path, by, value, near, limit, today=""):
    """The window's own lookup by QR code or by color (no model needed) -> Result [Shown], with each
    short link's scans up to `today` ("" for today).

    `by` is "qr_code" or "color" (any other value is read as color, by ecp.find_plan); `near` asks
    for colors close to a #rrggbb rather than that color alone; `limit` is clamped by the registry.
    `today` lets the tests pin the day the recent scans count back from.

    Steps:
      1. Clean the typed text (no control or direction characters) and refuse it when empty.
      2. ecp.find_plan turns the choice into a QueryPlan, or says why the color is not one.
      3. One read-write visit reads every row and the scan totals (with_registry).
      4. registry.find_rows keeps the rows that pass the plan's filters, newest first, at most
         the plan's limit, and each becomes a Shown with whether its picture is still there.
    """
    text = textsafe.clean(value, None).strip()
    if text == "":
        return fail("type what to look for")
    found_plan = ecp.find_plan(by, text, near, limit)
    if not found_plan["ok"]:
        return found_plan

    # every row and the scan totals, read in one visit
    def read(connection):
        return ok_result({"rows": registry.all_rows(connection),
                          "totals": registry.scan_totals(connection, today or registry.today_text())})

    found = with_registry(db_path, read)
    if not found["ok"]:
        return found
    shown = []
    for row in registry.find_rows(found["value"]["rows"], ecp.plan_filters(found_plan["value"]),
                                  found_plan["value"]["limit"]):
        shown.append(shown_from_row(row, registry.file_state(row["path"], False), found["value"]["totals"]))
    return ok_result(shown)


def matches_for_text(db_path, text, path):
    """Records holding exactly this text, or registered at this file -> Result [Shown]. A masked record
    is found by the keyed hash of the real text, when this registry's key is here.

    `text` is what the Read tab decoded from a picture; `path` is that picture's file ("" for none,
    such as a code read from the clipboard). A masked record is one whose real text is never stored,
    such as a Wi-Fi code with its password (payloads.stored_form says which): the registry keeps an
    HMAC-SHA-256 tag of the text instead, keyed by the secret in localkey's key file beside the
    registry. Without that file such a record cannot be matched by its text.

    Steps:
      1. Read every row in one visit.
      2. When a path is given, take its path_key (real path, the system's case rules).
      3. When the text would be masked and the key is here, compute its "payload" tag.
      4. Keep each row whose link is the text, whose payload_hash is the tag, or whose path_key is
         the picture's, with whether its picture is still there.
    """
    # every row, read in one visit
    def read(connection):
        return ok_result(registry.all_rows(connection))

    rows = with_registry(db_path, read)
    if not rows["ok"]:
        return rows
    key = ""
    if path != "":
        key = registry.path_key(path)
    tag = ""
    if payloads.stored_form(text)[1]:
        secret = localkey.read_key(localkey.key_path(db_path))
        if secret is not None:
            tag = localkey.tag(secret, "payload", text)
    shown = []
    for row in rows["value"]:
        same = row["link"] == text or (tag != "" and row["payload_hash"] == tag)
        if same or (key != "" and row["path_key"] == key):
            shown.append(shown_from_row(row, registry.file_state(row["path"], False)))
    return ok_result(shown)


def reveal_command_line(path):
    """Explorer's command line that shows a file selected (paths quoted: Explorer splits at "," and "=").

    Only builds the text; the Find tab runs it. Explorer's /select, switch opens the folder that
    holds the file with the file highlighted."""
    return 'explorer /select,"' + path + '"'

# ==== stamp v1 | author=kjFriday | hmac-sha256=b347d786755522993b2d5f43bbfc78c39ee9ad48d7c7a26a19f5542beb6ab4c9 ====
