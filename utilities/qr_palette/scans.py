# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: scans.py
# About: QR Palette scan counts: how often each short link was opened, from reports or logs.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette scan counts: how often each short link was opened, from reports or logs.

The counts are read from an analytics export or from a web server's access log.

Only counts are taken: a short link's ID, a day and a number. Addresses, user agents and everything
else in a log are never kept, not even in memory past the line being read. Two kinds of file:
  * An analytics CSV: a date column (YYYY-MM-DD or YYYYMMDD), a column holding the utm_content tag the
    redirect pages add (ID-color, such as 73491205-3366cc) and a count column. Comment lines (#) and
    other columns are ignored. Its source is "analytics", so a newer export of the same days corrects them.
  * A server access log (Common or Combined Log Format, or gzipped): GET requests for /ID/ or /ID with a
    2xx or 3xx status, counted per day as the log dates them. Its source names the time of the file's
    first request, so a log that grew, or was rotated, imports over itself rather than adding to it.

An ID must pass its check digit here; the registry then keeps only those that are its own.

Called by short_link_ops.import_scan_file, which hands the counts to registry.import_scans. It calls
shortlinks.is_valid_code for the check digit.

Flow (read_file)
  1. Read the first line that is neither empty nor a comment. When it parses as an access-log line,
     the file is a log, read line by line (gzipped or not) by read_log().
  2. Otherwise read it whole (at most MAX_CSV_BYTES), as UTF-8 or else Latin-1, and parse it with
     read_analytics().

A Common Log Format line holds: host, identity, user, [day/Mon/year:hh:mm:ss zone], "METHOD target
protocol", status and size; the Combined format adds the referrer and the user agent after them. Only
the date, method, target and status are read. The zone is ignored: a request counts on the day the log
wrote, in the server's own time.

Start reading at read_file().

Records
  Result    {"ok": bool, "error": str, "value": any}
  ScanFile  {"counts": {(code, day): int}, "source": str, "read": lines or rows read, "ignored": int of
             those that held no usable count, "kind": "analytics" | "log"}
"""

import csv
import datetime
import gzip
import io
import os
import re
import urllib.parse

import shortlinks

MAX_CSV_BYTES = 50 * 1024 * 1024  # a report is read whole into memory; a log is read a line at a time
# Groups: 1 day, 2 month name, 3 year, 4 time, 5 method, 6 target, 7 status. The size and anything
# after it (referrer, user agent) are never matched.
LOG_LINE = re.compile(r'^\S+ \S+ .*?\[(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}:\d{2}:\d{2}) [^\]]*\] "(\S+) (\S+)[^"]*" (\d{3}) ')
# The log's English month names, matched lower-cased.
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}
# Header names (lower-cased) for the three columns of a report, each tried in order: the first found
# wins. They cover the names analytics tools give the date, the utm_content tag and a count.
DATE_HEADERS = ("date", "day")
TAG_HEADERS = ("utm_content", "content", "session manual ad content", "manual ad content", "session ad content",
               "ad content", "campaign content", "id", "code")
COUNT_HEADERS = ("count", "scans", "sessions", "clicks", "views", "page views", "pageviews", "visits", "users",
                 "total users", "active users", "events", "event count", "hits")


def ok_result(value):
    """A successful Result holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the short error phrase `error` and the value None."""
    return {"ok": False, "error": error, "value": None}


def code_in_tag(text):
    """The short-link ID in a tag: "73491205-3366cc" or "73491205" -> the ID; "" when it holds none."""
    code = text.strip().split("-")[0]
    if shortlinks.is_valid_code(code):
        return code
    return ""


def day_of(text):
    """A date as YYYY-MM-DD or YYYYMMDD -> "YYYY-MM-DD"; "" when it is not a real day."""
    value = text.strip()
    if re.match(r"^[0-9]{8}$", value):
        value = value[:4] + "-" + value[4:6] + "-" + value[6:8]
    if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", value):
        return ""
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return ""
    return value


def count_of(text):
    """A count as a report writes it ("1,234" and "12" are fine) -> int, or -1 when it is not one."""
    value = text.strip().replace(",", "").replace(" ", "")
    if value == "" or not value.isdigit() or not value.isascii():
        return -1
    return int(value)


def column_of(headers, names):
    """The first of `names` found among the lower-cased headers -> its index, or -1."""
    for name in names:
        if name in headers:
            return headers.index(name)
    return -1


def read_analytics(text):
    """An analytics CSV's text -> Result ScanFile. Rows of one day and ID add up, because a report may
    split them by another column.

    Steps:
    1. Drop comment lines, and pick the separator from the first line: ";" or a tab when it has no
       comma (spreadsheets write ";" where the comma is the decimal mark).
    2. The first non-empty row is the header: find the date, tag and count columns, or fail.
    3. Every later row gives a day, an ID and a count; a row lacking any of them is counted as ignored.
    4. Add each count to its (ID, day).
    """
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            lines.append(line)
    first = ""
    for line in lines:
        if line.strip() != "":
            first = line
            break
    separator = ","
    for candidate in (";", "\t"):
        if candidate in first and "," not in first:
            separator = candidate
    counts = {}
    read = 0
    ignored = 0
    date_column = tag_column = count_column = -1
    headers = None
    try:
        for cells in csv.reader(io.StringIO("\n".join(lines)), delimiter=separator):
            if "".join(cells).strip() == "":
                continue
            if headers is None:
                headers = []
                for cell in cells:
                    headers.append(cell.strip().lower())
                date_column = column_of(headers, DATE_HEADERS)
                tag_column = column_of(headers, TAG_HEADERS)
                count_column = column_of(headers, COUNT_HEADERS)
                if date_column < 0 or tag_column < 0 or count_column < 0:
                    return fail("the first row must name a date column, a utm_content column and a count column")
                continue
            read = read + 1
            if max(date_column, tag_column, count_column) >= len(cells):
                ignored = ignored + 1
                continue
            day = day_of(cells[date_column])
            code = code_in_tag(cells[tag_column])
            count = count_of(cells[count_column])
            if day == "" or code == "" or count < 0:
                ignored = ignored + 1
                continue
            counts[(code, day)] = counts.get((code, day), 0) + count
    except csv.Error as error:
        return fail("cannot read it as CSV: " + str(error))
    if headers is None:
        return fail("it holds no rows of scans")
    return ok_result({"counts": counts, "source": "analytics", "read": read, "ignored": ignored, "kind": "analytics"})


def code_in_path(target):
    """The short-link ID a request asked for: "/73491205/", "/73491205" or "/go/73491205/?x=1" -> the
    ID; "" when the last part of the path is not one."""
    path = urllib.parse.urlsplit(target).path
    parts = []
    for part in path.split("/"):
        if part != "":
            parts.append(part)
    if len(parts) > 0 and parts[len(parts) - 1].lower() == "index.html":
        parts = parts[:len(parts) - 1]
    if len(parts) == 0 or not shortlinks.is_valid_code(parts[len(parts) - 1]):
        return ""
    return parts[len(parts) - 1]


def parsed_line(line):
    """One access-log line -> (day, time, method, target, status), or None when it is not one."""
    match = LOG_LINE.match(line)
    if match is None or match.group(2).lower() not in MONTHS:
        return None
    try:
        day = datetime.date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))).isoformat()
    except ValueError:
        return None
    return day, match.group(4), match.group(5), match.group(6), int(match.group(7))


def read_log(lines):
    """An access log's lines, as an iterable of text -> ScanFile. Each line is dropped as soon as its
    date, request and status are read."""
    counts = {}
    read = 0
    ignored = 0
    source = ""
    for line in lines:
        if line.strip() == "":
            continue
        read = read + 1
        parts = parsed_line(line)
        if parts is None:
            ignored = ignored + 1
            continue
        # the first request's time names the source, so the same log imported again replaces its own counts
        if source == "":
            source = "server log from " + parts[0] + "T" + parts[1]
        code = code_in_path(parts[3])
        # 2xx or 3xx: the redirect page was served (a 304 Not Modified counts too)
        if parts[2] != "GET" or not 200 <= parts[4] < 400 or code == "":
            ignored = ignored + 1
            continue
        counts[(code, parts[0])] = counts.get((code, parts[0]), 0) + 1
    return {"counts": counts, "source": source or "server log", "read": read, "ignored": ignored, "kind": "log"}


def text_lines(handle):
    """Lines of a binary file as text: a log's bytes may be anything, and only ASCII parts are read."""
    for raw in handle:
        yield raw.decode("latin-1")  # Latin-1 maps every byte to a character, so it never fails


def first_line(handle):
    """The first line of a file that is neither empty nor a comment, as text; "" when there is none."""
    for raw in handle:
        line = raw.decode("latin-1").strip()
        if line != "" and not line.startswith("#"):
            return line
    return ""


def read_file(path):
    """A scan file of either kind, told apart by its first line -> Result ScanFile.

    Steps:
    1. Open it (gzip.open for .gz) and test its first line against LOG_LINE.
    2. A log: open it again and stream its lines through read_log().
    3. A report: refuse it above MAX_CSV_BYTES, read it whole, decode it and pass it to read_analytics().
    """
    name = os.path.basename(path)
    opener = open
    if path.lower().endswith(".gz"):
        opener = gzip.open
    try:
        handle = opener(path, "rb")
        try:
            is_log = parsed_line(first_line(handle)) is not None
        finally:
            handle.close()
        if is_log:
            handle = opener(path, "rb")
            try:
                return ok_result(read_log(text_lines(handle)))
            finally:
                handle.close()
        # a .gz file's size on disk is its compressed size: the read below, one byte past the cap,
        # catches a big one instead
        if opener is open and os.path.getsize(path) > MAX_CSV_BYTES:
            return fail(name + " is too big for a report, and is not a server log")
        handle = opener(path, "rb")
        try:
            data = handle.read(MAX_CSV_BYTES + 1)
        finally:
            handle.close()
    # a damaged gzip raises BadGzipFile (an OSError) or, when cut short, EOFError
    except (OSError, EOFError, ValueError) as error:
        return fail("cannot read " + name + ": " + str(error))
    if len(data) > MAX_CSV_BYTES:
        return fail(name + " is too big for a report, and is not a server log")
    try:
        text = data.decode("utf-8-sig")  # utf-8-sig drops a byte-order mark if there is one
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    read = read_analytics(text)
    if not read["ok"]:
        return fail(name + ": " + read["error"])
    return read

# ==== stamp v1 | author=kjFriday | hmac-sha256=df0cd153f6224d57eacf0cdb17c71f01c055b238632dcb4a46cafb484e93e9fc ====
