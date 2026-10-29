# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/registry.py
# About: QR Palette registry: the SQLite database of QR codes, their colors, their links and where...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette registry: the SQLite database of QR codes, their colors, their links and where they are.

It is relational: colors and links are tables of their own, and each QR code row points at one of
each, so one link can have codes in many colors and one color can be on many codes. The database
belongs to this program alone (it is not the Generic Company hub's shared database). It is created
here in one transaction, and every open checks its application id and schema version, so any other
SQLite file is refused. A connection is opened for one piece of work, in the thread doing it, and
closed again. ECP and MCP open it read-only. It holds data only: every setting is in settings.json.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Row      {"id", "link", "hex", "name", "family", "cube_index", "path", "path_key", "format",
            "ec_level", "version", "origin", "created"}          one line of the qr_lookup view
  Entry    {"link", "color", "path", "format", "ec_level", "version", "origin"}   a code to save
  Filters  {"color": "#rrggbb", "near": bool, "family": str, "link": str, "link_exact": str,
            "path": str}                     "" means "any"; every filter given must match (AND)
  Voat     {"color": "#rrggbb", "voat": 1 | -1}                  what a ranker reads, oldest first
"""

import os
import pathlib
import re
import sqlite3
import time

import swatch

APPLICATION_ID = 0x51525041  # "QRPA" in the SQLite header: marks a QR Palette registry
SCHEMA_VERSION = 1
BUSY_SECONDS = 5.0
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
FORMATS = ("png", "svg")
ORIGINS = ("made", "registered")
EC_LEVELS = ("L", "M", "Q", "H")
STATEMENT_SECONDS = 2.0  # a read-only visit may take this long before it is stopped (settings.json)
HEAP_LIMIT = 64 * 1024 * 1024

# The read rail's allow-list: the only tables, columns and functions a read-only connection may use.
READ_COLUMNS = {
    "colors": ("id", "hex", "name", "family", "cube_index"),
    "links": ("id", "url"),
    "qr_codes": ("id", "link_id", "color_id", "path", "path_key", "format", "ec_level", "version", "origin",
                 "created"),
    "votes": ("color_id", "voat", "voted"),
}
READ_FUNCTIONS = ("count",)
# sqlite3_limit values for the read rail (the sqlite.org high-security column, ECP spec 7.4)
READ_LIMITS = (("SQLITE_LIMIT_LENGTH", 1000000), ("SQLITE_LIMIT_SQL_LENGTH", 10000), ("SQLITE_LIMIT_COLUMN", 100),
               ("SQLITE_LIMIT_EXPR_DEPTH", 10), ("SQLITE_LIMIT_COMPOUND_SELECT", 3),
               ("SQLITE_LIMIT_VDBE_OP", 25000), ("SQLITE_LIMIT_FUNCTION_ARG", 8), ("SQLITE_LIMIT_ATTACHED", 0),
               ("SQLITE_LIMIT_LIKE_PATTERN_LENGTH", 50), ("SQLITE_LIMIT_VARIABLE_NUMBER", 10),
               ("SQLITE_LIMIT_TRIGGER_DEPTH", 10))
LOOKUP = ("SELECT q.id AS id, l.url AS link, c.hex AS hex, c.name AS name, c.family AS family, "
          "c.cube_index AS cube_index, q.path AS path, q.path_key AS path_key, q.format AS format, "
          "q.ec_level AS ec_level, q.version AS version, q.origin AS origin, q.created AS created "
          "FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id")

SCHEMA = (
    """CREATE TABLE colors (
        id INTEGER PRIMARY KEY,
        hex TEXT NOT NULL UNIQUE,
        r INTEGER NOT NULL, g INTEGER NOT NULL, b INTEGER NOT NULL,
        cube_index INTEGER UNIQUE,
        name TEXT NOT NULL,
        family TEXT NOT NULL)""",
    """CREATE TABLE links (
        id INTEGER PRIMARY KEY,
        url TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE qr_codes (
        id INTEGER PRIMARY KEY,
        link_id INTEGER NOT NULL REFERENCES links(id),
        color_id INTEGER NOT NULL REFERENCES colors(id),
        path TEXT NOT NULL,
        path_key TEXT NOT NULL UNIQUE,
        format TEXT NOT NULL CHECK (format IN ('png', 'svg')),
        ec_level TEXT NOT NULL CHECK (ec_level IN ('L', 'M', 'Q', 'H')),
        version INTEGER NOT NULL CHECK (version BETWEEN 1 AND 40),
        origin TEXT NOT NULL CHECK (origin IN ('made', 'registered')),
        created TEXT NOT NULL)""",
    "CREATE INDEX qr_codes_by_color ON qr_codes(color_id)",
    "CREATE INDEX qr_codes_by_link ON qr_codes(link_id)",
    """CREATE TABLE votes (
        color_id INTEGER PRIMARY KEY REFERENCES colors(id),
        voat INTEGER NOT NULL CHECK (voat IN (-1, 1)),
        voted TEXT NOT NULL)""",
    """CREATE VIEW qr_lookup AS
        SELECT q.id AS id, l.url AS link, c.hex AS hex, c.name AS name, c.family AS family,
               c.cube_index AS cube_index, q.path AS path, q.path_key AS path_key, q.format AS format,
               q.ec_level AS ec_level, q.version AS version, q.origin AS origin, q.created AS created
        FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id""",
)
ROW_KEYS = ("id", "link", "hex", "name", "family", "cube_index", "path", "path_key", "format", "ec_level",
            "version", "origin", "created")


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def utc_text(seconds):
    """Seconds since 1970 as UTC ISO-8601, e.g. "2026-10-29T18:04:05Z"."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def now_text():
    return utc_text(time.time())


# --- Paths -----------------------------------------------------------------------------------------

def display_path(path):
    """A path the way it is shown and stored: absolute, with the system's separators."""
    return os.path.normpath(os.path.abspath(path))


def path_key(path):
    """What makes two paths the same file: the real path, in the system's case rules."""
    return os.path.normcase(os.path.realpath(path))


def text_key(path):
    """path_key worked out from the text alone, without touching the disk (for queries)."""
    return os.path.normcase(os.path.normpath(path))


def is_local_drive_path(path):
    """True for a path on this computer's own disks: a drive letter whose drive is not a network
    drive. Network paths (\\\\server\\share, mapped network drives) and device paths are False."""
    if os.name != "nt":
        return path.startswith("/")
    if len(path) < 3 or not path[0].isalpha() or path[1] != ":" or path[2] not in "\\/":
        return False
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(path[0] + ":\\")
    except (AttributeError, OSError):
        return False
    return kind in (2, 3, 6)  # removable, fixed, RAM disk


def file_state(path, local_only):
    """True or False for whether the file is there. None when `local_only` and it is not on a local
    drive, so a query never makes this computer reach out to a network share."""
    if local_only and not is_local_drive_path(path):
        return None
    return os.path.isfile(path)


# --- Opening ---------------------------------------------------------------------------------------

def close(connection):
    try:
        connection.close()
    except sqlite3.Error:
        pass


def rollback(connection):
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def connect(path, read_only):
    """Open the registry -> Result connection. Read-write creates a new registry in a missing or
    empty file; read-only never creates anything and sets query_only. Any file that is not a QR
    Palette registry of this schema version is refused. Close it with close() when done."""
    connection = None
    try:
        if read_only:
            if not os.path.isfile(path):
                return fail("no registry yet at " + path)
            uri = pathlib.Path(path).resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=BUSY_SECONDS, isolation_level=None)
            connection.execute("PRAGMA query_only=ON")
        else:
            folder = os.path.dirname(os.path.abspath(path))
            if not os.path.isdir(folder):
                os.makedirs(folder)
            connection = sqlite3.connect(path, timeout=BUSY_SECONDS, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=" + str(int(BUSY_SECONDS * 1000)))
        connection.execute("PRAGMA foreign_keys=ON")
        application = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        if not read_only and application == 0 and version == 0 and tables == 0:
            created = create_schema(connection)
            if not created["ok"]:
                close(connection)
                return created
            application = APPLICATION_ID
            version = SCHEMA_VERSION
        if application != APPLICATION_ID:
            close(connection)
            return fail(path + " is not a QR Palette registry")
        if version != SCHEMA_VERSION:
            close(connection)
            return fail(path + " is a QR Palette registry of another version (" + str(version) + ")")
        if read_only:
            hardened = harden_read_rail(connection)
            if not hardened["ok"]:
                close(connection)
                return hardened
        elif connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            connection.execute("PRAGMA journal_mode=DELETE")  # registries made before 0.1.0 used WAL
    except (sqlite3.Error, OSError) as error:
        if connection is not None:
            close(connection)
        return fail("cannot open " + path + ": " + str(error))
    return ok_result(connection)


def harden_read_rail(connection):
    """The read-only rail of the ECP research spec, section 7.3, as far as Python's sqlite3 reaches:
    query_only and trusted_schema off for every connection; DEFENSIVE, no triggers, no views and no
    double-quoted strings where the module can set them (Python 3.12+); a quick_check that must
    pass; a 64 MiB heap ceiling; sqlite3_limit values (Python 3.11+); an allow-list authorizer that
    denies everything else; and a progress handler that stops the visit once STATEMENT_SECONDS have
    passed since it opened (a call reads all it needs in one short visit). The pragmas run before
    the authorizer, which would deny them."""
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    if hasattr(connection, "setconfig"):
        for name, enable in (("SQLITE_DBCONFIG_DEFENSIVE", True), ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False),
                             ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False), ("SQLITE_DBCONFIG_ENABLE_VIEW", False),
                             ("SQLITE_DBCONFIG_DQS_DML", False), ("SQLITE_DBCONFIG_DQS_DDL", False)):
            if hasattr(sqlite3, name):
                connection.setconfig(getattr(sqlite3, name), enable)
    check = connection.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        return fail("the registry is damaged (quick_check: " + str(check) + "); it is not served")
    connection.execute("PRAGMA hard_heap_limit=" + str(HEAP_LIMIT))
    if hasattr(connection, "setlimit"):
        for name, value in READ_LIMITS:
            if hasattr(sqlite3, name):
                connection.setlimit(getattr(sqlite3, name), value)
    connection.set_authorizer(read_rail_authorizer)
    deadline = time.monotonic() + STATEMENT_SECONDS

    def too_long():
        return 1 if time.monotonic() > deadline else 0

    connection.set_progress_handler(too_long, 1000)
    return ok_result(True)


def read_rail_authorizer(action, first, second, database, inner):
    """Allow plain SELECTs that read the allowed columns of the four tables and call the allowed
    functions; deny everything else (DENY, never IGNORE, so a mistake is an error, not a silent
    NULL)."""
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if first in READ_COLUMNS and (second in READ_COLUMNS[first] or second in ("", None)):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        if isinstance(second, str) and second.lower() in READ_FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def create_schema(connection):
    """Tables, the 216 cube colors and the header marks, all in one transaction. The journal stays
    SQLite's default rollback journal: a read-only connection can then always read the file."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            connection.execute(statement)
        colors = swatch.palette()
        for index in range(len(colors)):
            insert_color(connection, colors[index])
        connection.execute("PRAGMA application_id=" + str(APPLICATION_ID))
        connection.execute("PRAGMA user_version=" + str(SCHEMA_VERSION))
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot create the registry: " + str(error))
    return ok_result(True)


def insert_color(connection, color):
    values = swatch.channels(color)
    index = swatch.cube_index(color)
    if index < 0:
        index = None
    cursor = connection.execute(
        "INSERT INTO colors (hex, r, g, b, cube_index, name, family) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (color, values[0], values[1], values[2], index, swatch.color_name(color), swatch.family(color)))
    return cursor.lastrowid


# --- Writing (the window only) ---------------------------------------------------------------------

def color_id(connection, color):
    row = connection.execute("SELECT id FROM colors WHERE hex = ?", (color,)).fetchone()
    if row is not None:
        return row[0]
    return insert_color(connection, color)


def link_id(connection, url):
    row = connection.execute("SELECT id FROM links WHERE url = ?", (url,)).fetchone()
    if row is not None:
        return row[0]
    return connection.execute("INSERT INTO links (url) VALUES (?)", (url,)).lastrowid


def check_entry(entry):
    """"" when an Entry can be saved, else what is wrong with it."""
    if swatch.normalize_hex(entry["color"]) != entry["color"]:
        return "the color must be #rrggbb"
    if entry["format"] not in FORMATS:
        return "only PNG and SVG files can be registered"
    if entry["ec_level"] not in EC_LEVELS:
        return "unknown error-correction level"
    if not isinstance(entry["version"], int) or entry["version"] < 1 or entry["version"] > 40:
        return "the QR version must be 1 to 40"
    if entry["origin"] not in ORIGINS:
        return "unknown origin"
    if entry["path"] == "" or not os.path.isabs(entry["path"]):
        return "the path must be absolute"
    return ""


def save_qr(connection, entry):
    """Add a QR code, or replace the one already registered at the same file -> Result id."""
    problem = check_entry(entry)
    if problem != "":
        return fail(problem)
    key = path_key(entry["path"])
    try:
        connection.execute("BEGIN IMMEDIATE")
        color = color_id(connection, entry["color"])
        link = link_id(connection, entry["link"])
        connection.execute(
            "INSERT INTO qr_codes (link_id, color_id, path, path_key, format, ec_level, version, origin, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path_key) DO UPDATE SET link_id = excluded.link_id, color_id = excluded.color_id, "
            "path = excluded.path, format = excluded.format, ec_level = excluded.ec_level, "
            "version = excluded.version, origin = excluded.origin, created = excluded.created",
            (link, color, display_path(entry["path"]), key, entry["format"], entry["ec_level"], entry["version"],
             entry["origin"], now_text()))
        number = connection.execute("SELECT id FROM qr_codes WHERE path_key = ?", (key,)).fetchone()[0]
        drop_unused_links(connection)
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot save the record: " + str(error))
    return ok_result(number)


def drop_unused_links(connection):
    connection.execute("DELETE FROM links WHERE id NOT IN (SELECT link_id FROM qr_codes)")


def forget_qr(connection, number):
    """Remove a record (never the file) -> Result True when there was one."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute("DELETE FROM qr_codes WHERE id = ?", (number,))
        removed = cursor.rowcount > 0
        drop_unused_links(connection)
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot forget the record: " + str(error))
    return ok_result(removed)


def vote(connection, color, voat):
    """Good (1) or Bad (-1) for a color, one vote per color; the same vote again takes it back
    -> Result the color's vote now (1, -1 or 0)."""
    if voat not in (1, -1) or swatch.normalize_hex(color) != color:
        return fail("a vote is 1 or -1 for a #rrggbb color")
    try:
        connection.execute("BEGIN IMMEDIATE")
        number = color_id(connection, color)
        row = connection.execute("SELECT voat FROM votes WHERE color_id = ?", (number,)).fetchone()
        if row is not None and row[0] == voat:
            connection.execute("DELETE FROM votes WHERE color_id = ?", (number,))
            now = 0
        else:
            connection.execute("INSERT INTO votes (color_id, voat, voted) VALUES (?, ?, ?) "
                               "ON CONFLICT(color_id) DO UPDATE SET voat = excluded.voat, voted = excluded.voted",
                               (number, voat, now_text()))
            now = voat
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot save the vote: " + str(error))
    return ok_result(now)


def import_votes(connection, votes):
    """Votes from Color Voats ({color: {"voat": 1 | -1, "when": seconds}}) -> Result how many changed.
    For each color the newer vote wins, so importing the same file twice changes nothing."""
    changed = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for color in sorted(votes):
            entry = votes[color]
            hex_value = swatch.normalize_hex(color)
            if hex_value == "" or not isinstance(entry, dict) or entry.get("voat") not in (1, -1):
                continue
            when = entry.get("when")
            if isinstance(when, bool) or not isinstance(when, (int, float)) or when < 0 or when > 32503680000:
                continue
            voted = utc_text(when)
            number = color_id(connection, hex_value)
            row = connection.execute("SELECT voat, voted FROM votes WHERE color_id = ?", (number,)).fetchone()
            if row is not None and (row[1] > voted or (row[1] == voted and row[0] == entry["voat"])):
                continue
            connection.execute("INSERT INTO votes (color_id, voat, voted) VALUES (?, ?, ?) "
                               "ON CONFLICT(color_id) DO UPDATE SET voat = excluded.voat, voted = excluded.voted",
                               (number, entry["voat"], voted))
            changed = changed + 1
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot import the votes: " + str(error))
    return ok_result(changed)


# --- Reading ---------------------------------------------------------------------------------------

def row_record(row):
    record = {}
    for key in ROW_KEYS:
        record[key] = row[key]
    return record


def all_rows(connection):
    """Every QR code, newest first, as Row records (the cursor is finished before returning)."""
    rows = []
    for row in connection.execute(LOOKUP + " ORDER BY q.id DESC").fetchall():
        rows.append(row_record(row))
    return rows


def row_by_id(connection, number):
    row = connection.execute(LOOKUP + " WHERE q.id = ?", (number,)).fetchone()
    if row is None:
        return None
    return row_record(row)


def vote_log(connection):
    """The votes, oldest first, as Voat records (what the rankers read)."""
    log = []
    for row in connection.execute("SELECT c.hex, v.voat FROM votes v JOIN colors c ON c.id = v.color_id "
                                  "ORDER BY v.voted, c.hex").fetchall():
        log.append({"color": row[0], "voat": row[1]})
    return log


def vote_map(connection):
    votes = {}
    for row in connection.execute("SELECT c.hex, v.voat FROM votes v JOIN colors c ON c.id = v.color_id").fetchall():
        votes[row[0]] = row[1]
    return votes


def colors_in_use(connection):
    """The colors that have QR codes, most used first: [{"hex", "name", "family", "uses"}]."""
    used = []
    for row in connection.execute("SELECT c.hex, c.name, c.family, count(*) FROM qr_codes q "
                                  "JOIN colors c ON c.id = q.color_id GROUP BY c.id "
                                  "ORDER BY count(*) DESC, c.hex").fetchall():
        used.append({"hex": row[0], "name": row[1], "family": row[2], "uses": row[3]})
    return used


def counts(connection):
    records = connection.execute("SELECT count(*) FROM qr_codes").fetchone()[0]
    links = connection.execute("SELECT count(*) FROM links").fetchone()[0]
    used = connection.execute("SELECT count(DISTINCT color_id) FROM qr_codes").fetchone()[0]
    return {"records": records, "links": links, "colors_used": used}


# --- Finding (plain Python over the rows: no LIKE wildcards, full Unicode case folding) -------------

def empty_filters():
    return {"color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": ""}


def clamp_limit(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_LIMIT
    if value < 1:
        return 1
    if value > MAX_LIMIT:
        return MAX_LIMIT
    return value


def has_filter(filters):
    return (filters["color"] != "" or filters["family"] != "" or filters["link"] != "" or
            filters["link_exact"] != "" or filters["path"] != "")


def loose_words(text):
    """Text as its words: case-folded letters and digits, every run of anything else one space."""
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def text_contains(haystack, needle):
    """True when `needle` is in `haystack` as typed (case-folded), or when each of its words is,
    ignoring punctuation: "store hours" finds ".../store-hours", "shop sale" finds "shop.example.com/sale"."""
    if needle.casefold() in haystack.casefold():
        return True
    wanted = loose_words(needle).split(" ")
    if wanted == [""]:
        return False
    words = loose_words(haystack)
    for word in wanted:
        if word not in words:
            return False
    return True


def row_matches(row, filters):
    if filters["color"] != "":
        if filters["near"]:
            if not swatch.is_near(row["hex"], filters["color"]):
                return False
        elif row["hex"] != filters["color"]:
            return False
    if filters["family"] != "" and row["family"] != filters["family"]:
        return False
    if filters["link_exact"] != "" and row["link"] != filters["link_exact"]:
        return False
    if filters["link"] != "" and not text_contains(row["link"], filters["link"]):
        return False
    if filters["path"] != "":
        wanted = text_key(filters["path"]).casefold()
        if wanted not in row["path_key"].casefold() and not text_contains(row["path"], filters["path"]):
            return False
    return True


def find_rows(rows, filters, limit):
    """The rows that match every filter given, in the order given (newest first), at most `limit`.
    With no filter at all, the newest rows."""
    found = []
    wanted = clamp_limit(limit)
    for row in rows:
        if len(found) >= wanted:
            break
        if row_matches(row, filters):
            found.append(row)
    return found

# ==== stamp v1 | author=kjFriday | hmac-sha256=4f9b59edf385a047ff334fb46ebb01ac93198fdd3b2a1c6ce98b97bd6b91da3a ====
