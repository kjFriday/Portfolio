# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: registry_export.py
# About: The registry exported: CSV with one row per code (for spreadsheets), or JSON with...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Registry export: a CSV file with one row per code, or a JSON file with everything.

The CSV is for spreadsheets. The JSON also holds the short links with their history, schedules and
scans, and the votes.

The registry is read on the read-only rail, and the file is written next to its place first and then moved
into it. The JSON names the program and its version, which qr_palette.py holds; qr_palette.py never
imports this module, so the two do not import each other. A Wi-Fi password is never in an export: the
registry only has it masked.

Called by the window's export command (gui/window.py). It calls registry (read-only), app_settings and
shortlinks.section_of for each short link's section, and common.safe_cell for every CSV cell.
Start reading at export_registry().
"""

import csv
import json
import os

import app_settings
import registry
import shortlinks
from common import fail, ok_result, safe_cell
from qr_palette import APP_NAME, __version__

# The CSV's header, in order. Each is a key of the rows export_registry builds; the JSON's codes use the
# same keys.
CSV_COLUMNS = ("id", "color", "color_name", "family", "link", "destination", "short_id", "section", "path", "format",
               "ec_level", "version", "origin", "created", "scans_total", "scans_30_days", "password_masked", "has_logo")


def export_registry(db_path, path, today=""):
    """The registry as CSV (one row per QR code, for spreadsheets) or JSON (codes, short links with
    their history, schedules and scans, and votes), by `path`'s extension -> Result {"path", "codes",
    "short_links"}. Scans up to `today` ("" for today). Read on the read-only rail, and written next to
    its place first. A Wi-Fi password is never here: the registry only has it masked.

    Steps:
    1. Choose CSV or JSON by the extension.
    2. Read everything in one read-only visit, then close the registry.
    3. Build one flat row per code, with its short link's section and scan counts.
    4. Write PATH.part, then move it into place; a failed write removes PATH.part.
    """
    kind = os.path.splitext(path)[1].lower()
    if kind not in (".csv", ".json"):
        return fail("export to a .csv or a .json file")
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        codes = registry.all_rows(opened["value"])
        links = registry.short_links(opened["value"])
        votes = registry.vote_entries(opened["value"])
        kept = registry.history_entries(opened["value"])
        totals = registry.scan_totals(opened["value"], today or registry.today_text())
    except Exception as error:
        return fail("cannot read the registry: " + str(error))
    finally:
        registry.close(opened["value"])
    rows = []
    for row in codes:
        section = ""
        if row["short_code"] != "":
            section = shortlinks.section_of(app_settings.LINKS, row["link"])
        # scans: blank for a code without a short link, 0 for a short link never scanned
        scanned = totals.get(row["short_code"], {"total": "", "recent": ""})
        if row["short_code"] != "" and row["short_code"] not in totals:
            scanned = {"total": 0, "recent": 0}
        rows.append({"id": row["id"], "color": row["hex"], "color_name": row["name"], "family": row["family"],
                     "link": row["link"], "destination": row["target"] or row["link"], "short_id": row["short_code"],
                     "section": section, "path": row["path"], "format": row["format"], "ec_level": row["ec_level"],
                     "version": row["version"], "origin": row["origin"], "created": row["created"],
                     "scans_total": scanned["total"], "scans_30_days": scanned["recent"],
                     "password_masked": "yes" if row["payload_hash"] is not None else "",
                     "has_logo": "yes" if row["has_logo"] else ""})
    temporary = path + ".part"
    try:
        if kind == ".csv":
            # utf-8-sig starts the file with a byte-order mark, which tells Excel it is UTF-8; newline=""
            # lets the csv module write its own line ends
            handle = open(temporary, "w", encoding="utf-8-sig", newline="")
            try:
                writer = csv.writer(handle)
                writer.writerow(CSV_COLUMNS)
                for row in rows:
                    cells = []
                    for key in CSV_COLUMNS:
                        cells.append(safe_cell(row[key]))  # text starting with = + - @ is never a formula
                    writer.writerow(cells)
            finally:
                handle.close()
        else:
            data = {"program": APP_NAME + " " + __version__, "exported": registry.now_text(), "codes": rows,
                    "short_links": links, "short_link_changes": kept["short_link_changes"],
                    "scheduled_changes": kept["scheduled_changes"], "scans": kept["scans"], "votes": votes}
            handle = open(temporary, "w", encoding="utf-8", newline="\n")
            try:
                handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            finally:
                handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot write " + path + ": " + str(error))
    return ok_result({"path": path, "codes": len(rows), "short_links": len(links)})

# ==== stamp v1 | author=kjFriday | hmac-sha256=a412c9f2f3ecb440adee871bd7e50b312432e6367bc5d718f13af765a5dab47d ====
