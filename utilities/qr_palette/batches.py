# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: batches.py
# About: Batch make: a whole print run of codes from a list (a CSV file), with a report beside the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Batch make: a print run of codes from a CSV list, with a report beside the pictures.

A print run is a whole list of codes made in one go. The window's Make from a list dialog
(gui/dialogs.py) and selftest.py call it; it calls making.make_qr for every code, and
short_link_ops.short_request when the codes print short links.

read_batch_csv reads the list: UTF-8 (with or without a byte-order mark) or a spreadsheet's Windows-1252,
separated by commas, semicolons or tabs, and marks each row that cannot be made. make_batch makes the rest
one at a time through making.make_qr, never over a file that is already there, and write_batch_report
writes made-<time>.csv beside the pictures with what happened to every row. A Wi-Fi password never reaches
the report.

Records
  BatchRow {"row": its row in the file, "link", "color", "label", "file", "problem": "" when it can be made}
  BatchReport {"made": int, "skipped": int, "report": path of its CSV, "stopped": bool, "rows": one dict per
            row, the columns of BATCH_COLUMNS}

Main flow:
  1. read_batch_csv reads and checks the list, row by row.
  2. The window counts the rows that are ready and shows the first problem.
  3. make_batch makes each ready row (batch_path picks a new file name for it) and notes every
     row's fate.
  4. write_batch_report writes that as made-<time>.csv.
"""

import csv
import io
import os
import time

import payloads
import swatch
import textsafe
from common import fail, ok_result, safe_cell
from making import make_qr, slug, suggested_name
from short_link_ops import short_request

MAX_BATCH_BYTES = 20 * 1024 * 1024  # a list of codes bigger than this is refused
MAX_BATCH_ROWS = 10000  # rows of codes in one list (the header and blank rows do not count)
# the report's columns, in order: status is "made" or "skipped", reason says why a row was skipped,
# note says what was changed (a color that was too light), short_id is the short link's ID
BATCH_COLUMNS = ("row", "status", "reason", "link", "color", "label", "path", "short_id", "note")
# names Windows keeps for devices: a file named NUL or COM1.png, in any case and with any
# extension, opens the device instead of a file
WINDOWS_DEVICES = ("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                   "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9")


def read_batch_csv(path):
    """A print run from a CSV file with a header row -> Result [BatchRow]. The headers link and color
    are needed, label and file are optional, in any order and either case. The file may be UTF-8 (with
    or without a byte-order mark) or a spreadsheet's Windows-1252, separated by commas, semicolons or
    tabs. Every row comes back in order, those that cannot be made with their "problem" filled in.

    The whole list fails (and no rows come back) when the file cannot be read, is over
    MAX_BATCH_BYTES or MAX_BATCH_ROWS, is not CSV, has no link and color headers, or holds no rows.

    Steps:
      1. Read the bytes; decode as UTF-8 (utf-8-sig drops a byte-order mark), else as Windows-1252.
      2. Pick the separator from the first line: ";" or a tab when it holds one and no comma.
      3. The first non-blank row is the header: names trimmed and lowercased; link and color must
         be among them. Columns with other names are ignored.
      4. Each later non-blank row: its cells cleaned of control characters and trimmed, its line
         number in the file kept, its color normalized to #rrggbb, and its problem noted.
    """
    try:
        if os.path.getsize(path) > MAX_BATCH_BYTES:
            return fail(os.path.basename(path) + " is too big for a list of codes")
        handle = open(path, "rb")
        try:
            data = handle.read()
        finally:
            handle.close()
    except OSError as error:
        return fail("cannot read " + path + ": " + str(error))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel saves "CSV" in the system's code page; cp1252 still fails on its five unused bytes
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            return fail(os.path.basename(path) + " is not UTF-8 or Windows-1252 text")
    first = text.split("\n", 1)[0]
    separator = ","
    for candidate in (";", "\t"):
        if candidate in first and "," not in first:
            separator = candidate
    rows = []
    try:
        # newline="" leaves line ends to the csv module, so a quoted cell may hold one
        lines = csv.reader(io.StringIO(text, newline=""), delimiter=separator)
        headers = None
        for cells in lines:
            if headers is None:
                if len(cells) == 0 or "".join(cells).strip() == "":
                    continue
                headers = []
                for cell in cells:
                    headers.append(cell.strip().lower())
                if "link" not in headers or "color" not in headers:
                    return fail("the first row must name the columns: link, color, and optionally label and file")
                continue
            if "".join(cells).strip() == "":
                continue
            if len(rows) >= MAX_BATCH_ROWS:
                return fail("a list may hold at most " + str(MAX_BATCH_ROWS) + " codes")
            found = {"link": "", "color": "", "label": "", "file": ""}
            for index in range(min(len(headers), len(cells))):
                if headers[index] in found:
                    found[headers[index]] = textsafe.clean(cells[index], None).strip()
            found["row"] = lines.line_num  # the line the row ends on: a spreadsheet's row number
            found["problem"] = ""
            given = found["color"]
            found["color"] = swatch.normalize_hex(given)
            if found["link"] == "":
                found["problem"] = "no link"
            elif given == "":
                found["problem"] = "no color"
            elif found["color"] == "":
                found["problem"] = textsafe.clean(given, 40) + " is not a #rrggbb color"
            rows.append(found)
    except csv.Error as error:
        return fail("cannot read " + os.path.basename(path) + " as CSV: " + str(error))
    if len(rows) == 0:
        return fail(os.path.basename(path) + " holds no rows of codes")
    return ok_result(rows)


def batch_file_problem(name):
    """"" when a list's file column is a plain file name for this computer, else what is wrong: it
    may not lead outside the chosen folder or be a name Windows keeps for itself.

    Refused: "." and "..", anything with a folder part or either slash, a device name (the part
    before the first dot, in any case: "nul.png", "Com1"), a name that is empty before its first
    dot, a name ending in a dot or a space (Windows drops them, so the file would get another
    name), and the characters < > : " | ? * that Windows does not allow in names."""
    if name in (".", "..") or name != os.path.basename(name) or "/" in name or "\\" in name:
        return "the file column must be a file name, not a path"
    stem = name.split(".", 1)[0].strip().upper()
    if stem == "" or stem in WINDOWS_DEVICES or name.endswith((".", " ")):
        return "the file column's name cannot be used on Windows"
    for character in name:
        if character in '<>:"|?*':
            return "the file column's name cannot be used on Windows"
    return ""


def batch_path(row, color, kind, folder, taken):
    """Where a row's picture goes -> (path, problem). From its file column, else its label (if any)
    and suggested_name; a name that is in the folder or already used by this run gets -2, -3, ...,
    because make_qr replaces a file that is already there.

    `row` is a BatchRow; `color` is the color the code is made in (it may differ from the row's);
    `kind` is "png" or "svg", added to a file name that has neither ending; `taken` is the set of
    this run's names, casefolded (Windows names ignore case), and gains the name chosen. The
    problem is "" when the path can be used."""
    name = row["file"]
    if name != "":
        problem = batch_file_problem(name)
        if problem != "":
            return "", problem
        if not name.lower().endswith((".png", ".svg")):
            name = name + "." + kind
    else:
        name = suggested_name(row["link"], color, kind)
        if row["label"] != "":
            name = slug(row["label"]) + "-" + name
    stem, extension = os.path.splitext(name)
    candidate = name
    number = 1
    while os.path.exists(os.path.join(folder, candidate)) or candidate.casefold() in taken:
        number = number + 1
        candidate = stem + "-" + str(number) + extension
    taken.add(candidate.casefold())
    return os.path.join(folder, candidate), ""


def make_batch(db_path, rows, folder, kind, level, scale, section, snap=False, watch=None, when=""):
    """Make a code for every BatchRow, with a report beside the pictures -> Result BatchReport. `kind`
    is "png" or "svg" (a row's file column may say otherwise). `section` is the short-link section
    to print ("" for none); the same destination in the same color shares its short link, as ever. A
    color too light to scan is skipped with the reason, or with `snap` replaced by the nearest that
    scans. A row the same as an earlier one is skipped. `watch(done, total)`, called before each row,
    may return True to stop: the rest are reported as not made. `when` names the report (the time).

    `db_path` is the registry every code is registered in; `level` is the error correction level
    (L, M, Q or H) and `scale` the pixels per module, as in the Make tab. `watch` runs on the job's
    thread, so it only sets and reads plain values. Fails only when the folder cannot be made or the
    report cannot be written; a row that fails is reported, and the run goes on.

    Steps, for each row in order:
      1. Start its report line as skipped, with the link in its stored form.
      2. Ask watch whether to stop; once stopped, every later row says so.
      3. Skip a row with a problem from read_batch_csv, or the same as an earlier row.
      4. A color too light to scan on white: skip it, or with snap use the nearest that scans and
         note it.
      5. Pick its path (batch_path); a bad file column skips it.
      6. Make it with make_qr, with a new short link in `section` when one is asked for, and note
         its path and short link ID.
    Then write the report.
    """
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        return fail("cannot use the folder " + folder + ": " + str(error))
    report = []
    seen = {}
    taken = set()
    made_count = 0
    stopped = False
    for index in range(len(rows)):
        row = rows[index]
        line = {"row": row["row"], "status": "skipped", "reason": row["problem"], "link": row["link"],
                "color": row["color"], "label": row["label"], "path": "", "short_id": "", "note": ""}
        line["link"] = payloads.stored_form(row["link"])[0]  # a report never holds a Wi-Fi password
        report.append(line)
        if not stopped and watch is not None and watch(index, len(rows)):
            stopped = True
        if stopped:
            line["reason"] = "stopped before this row"
            continue
        if line["reason"] != "":
            continue
        same = (row["link"], row["color"], row["label"], row["file"])
        if same in seen:
            line["reason"] = "the same as row " + str(seen[same])
            continue
        seen[same] = row["row"]
        color = row["color"]
        if not swatch.usable(color):
            if not snap:
                line["reason"] = color + " is too light to scan on white"
                continue
            color = swatch.nearest_usable(color)
            line["note"] = "color " + row["color"] + " was too light to scan: used " + color
            line["color"] = color
        path, problem = batch_path(row, color, kind, folder, taken)
        if problem != "":
            line["reason"] = problem
            continue
        short = None
        if section != "":
            short = short_request("", section)  # no ID kept ready: make_qr picks one, or reuses a shared one
        made = make_qr(db_path, row["link"], color, level, path, scale, short)
        if not made["ok"]:
            line["reason"] = made["error"]
            continue
        line["status"] = "made"
        line["path"] = made["value"]["path"]
        line["short_id"] = made["value"]["short_code"]
        made_count = made_count + 1
    written = write_batch_report(folder, report, when or time.strftime("%Y%m%d-%H%M%S"))
    if not written["ok"]:
        return written
    return ok_result({"made": made_count, "skipped": len(report) - made_count, "report": written["value"],
                      "rows": report, "stopped": stopped})


def write_batch_report(folder, report, when):
    """The batch's report as a CSV beside its pictures, never over an earlier one -> Result path.

    The name is made-WHEN.csv, then made-WHEN-2.csv and so on. The file is UTF-8 with a byte-order
    mark, which Excel needs to read it as UTF-8, and every cell goes through safe_cell so no cell
    is read as a formula. It is written to PATH.part and renamed into place, so a half-written
    report is never left under the real name."""
    path = os.path.join(folder, "made-" + when + ".csv")
    number = 1
    while os.path.exists(path):
        number = number + 1
        path = os.path.join(folder, "made-" + when + "-" + str(number) + ".csv")
    temporary = path + ".part"
    try:
        handle = open(temporary, "w", encoding="utf-8-sig", newline="")
        try:
            writer = csv.writer(handle)
            writer.writerow(BATCH_COLUMNS)
            for line in report:
                cells = []
                for key in BATCH_COLUMNS:
                    cells.append(safe_cell(line[key]))
                writer.writerow(cells)
        finally:
            handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot write the report " + path + ": " + str(error))
    return ok_result(path)

# ==== stamp v1 | author=kjFriday | hmac-sha256=a97af04483d7bbb0f88e96c4a20c658a30949c1dd05efe4c603954f38c19a2da ====
