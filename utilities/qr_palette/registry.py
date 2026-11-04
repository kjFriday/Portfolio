# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: registry.py
# About: QR Palette registry: the SQLite database of QR codes, their colors, their links and where...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette registry: the SQLite database of QR codes, their colors, links and files.

It is relational: colors and links are tables of their own, and each QR code row points at one of
each, so one link can have codes in many colors and one color can be on many codes. A short link
(shortlinks.py) is a link whose text is a short address; its row in short_links says where that
address sends people, and it stays when its last picture is forgotten, because printed codes still
use it. The database belongs to this program alone (it is not the Generic Company hub's shared
database). It is created here in one transaction, and every open checks its application id and
schema version, so any other SQLite file is refused. A connection is opened for one piece of work,
in the thread doing it, and closed again. ECP and MCP open it read-only. It holds data only: every
setting is in settings.json.

Schema versions: 2 added short_links; 3 added short_link_changes (where a short link used to go),
scheduled_changes (where it will go, from a day), scans (counts per short link and day, never who
scanned), qr_codes.payload_hash (for a code whose stored text is masked) and qr_codes.has_logo (the
registry keeps no logo, so such a code cannot be drawn again whole). A writable open keeps a
copy of an older registry beside it (NAME-vN.db) and moves it to the current version in one
transaction; a read-only open reads older versions as they are, since it may not write. Version 3
only adds to version 2: other programs that read the older tables and columns read them the same.

Who uses it: the window (gui/) and the core modules behind it open it read-write for one piece of
work, mostly through common.with_registry; ecp.py, sheets.py, registry_export.py and the redirect
export and publishing in short_link_ops.py open it read-only. It calls swatch for the 216 cube colors, their names
and their families.

Main flow
  1. connect() opens a file. A writable open of an empty file runs create_schema(); every open then
     checks the header marks (application_id, user_version) and refuses any other file.
  2. A writable open of an older registry keeps a copy of it (keep_older_copy) and runs upgrade_schema().
  3. A read-only open goes through harden_read_rail(), the "read rail": the connection may only read
     the allowed columns, for a short time, so a query a local model planned cannot do anything else.
  4. Each writer (save_qr, retarget, undo_last_change, schedule_change, apply_due, import_scans, vote,
     import_votes, forget_qr) is one BEGIN IMMEDIATE transaction, rolled back on any error.
  5. Readers (all_rows, short_links, scan_totals, ...) return plain dicts; find_rows() filters Rows in
     Python, not in SQL.
  6. close() forgets the connection's schema version and closes it.

SQLite in brief
  * application_id and user_version are two 32-bit numbers in the file's 100-byte header that SQLite
    keeps but never reads itself; PRAGMA sets and reads them. Here they say "QR Palette registry,
    version N".
  * BEGIN IMMEDIATE takes the write lock when the transaction starts, so a second writer waits
    (busy_timeout) before it has done anything, instead of failing halfway.
  * An authorizer is a callback SQLite asks, while it compiles a statement, about each column read and
    each function called; DENY makes the statement fail.

Start reading at connect().

Records
  Result     {"ok": bool, "error": str, "value": any}
  Row        {"id", "link", "hex", "name", "family", "cube_index", "path", "path_key", "format",
              "ec_level", "version", "origin", "created", "short_code", "target", "payload_hash",
              "has_logo"} one QR code; short_code and target are "" unless its link is a short link;
              payload_hash is None unless link is masked (the code holds a secret the registry must not
              keep); has_logo is 1 for a code drawn with a logo, 0 otherwise
  Entry      {"link", "color", "path", "format", "ec_level", "version", "origin",
              "short": {"code", "target"} or absent, "payload_hash": str or absent,
              "has_logo": 1 or absent}                                               a code to save
  ShortLink  {"code", "url", "target", "hex", "created", "updated", "pictures"}
  Change     {"id", "old_target", "new_target", "changed"}                  a short link's history
  Scheduled  {"id", "code", "target", "from_day": "YYYY-MM-DD", "created"}  a change still to come
  ScanCount  {"total": int, "recent": int}                   a short link's scans, recent = last 30 days
  Filters    {"color": "#rrggbb", "near": bool, "family": str, "link": str, "link_exact": str,
              "path": str, "section": str, "short": bool}  "" means "any"; every filter given must match
  Voat       {"color": "#rrggbb", "voat": 1 | -1}                 what a ranker reads, oldest first
"""

import datetime
import os
import pathlib
import re
import sqlite3
import time
import urllib.parse

import swatch

# "QRPA" in the SQLite header marks a QR Palette registry. Keep it in every schema, including a move to the
# ECP spec's DDL (which sets only user_version): other programs, such as Data Bridge, find the registry by it
# and by SCHEMA_VERSION, and refuse a file without it.
# 0x51525041 is the four ASCII bytes "QRPA".
APPLICATION_ID = 0x51525041
SCHEMA_VERSION = 3  # those programs check it too: raise it only together with them
READABLE_VERSIONS = (1, 2, 3)  # what a read-only connection accepts (it cannot move a registry to SCHEMA_VERSION)
# id() is unique only while the object lives (Python reuses it later), so close() drops the entry.
OPEN_VERSIONS = {}  # id(connection) -> the schema version that connection opened, until close()
BUSY_SECONDS = 5.0  # how long a connection waits for another's lock before SQLite gives up
# How many Rows find_rows returns (clamp_limit); app_settings sets both from settings.json's queries.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
RECENT_DAYS = 30  # "recent" scans: this many days, today included
DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")  # the shape of a day; is_day also checks the calendar
# What SCHEMA's CHECK constraints allow; check_entry tests them first, for a clearer error.
FORMATS = ("png", "svg")
ORIGINS = ("made", "registered")
EC_LEVELS = ("L", "M", "Q", "H")
STATEMENT_SECONDS = 2.0  # a read-only visit may take this long before it is stopped (settings.json)
# 64 MiB for PRAGMA hard_heap_limit. SQLite keeps one such limit for the whole process, so once a
# read-only connection sets it, every connection in the program lives under it.
HEAP_LIMIT = 64 * 1024 * 1024

# The read rail's allow-list: the only tables, columns and functions a read-only connection may use.
READ_COLUMNS = {
    "colors": ("id", "hex", "name", "family", "cube_index"),
    "links": ("id", "url"),
    "qr_codes": ("id", "link_id", "color_id", "path", "path_key", "format", "ec_level", "version", "origin",
                 "created", "payload_hash", "has_logo"),
    "votes": ("color_id", "voat", "voted"),
    "short_links": ("id", "code", "link_id", "color_id", "target", "created", "updated"),
    "short_link_changes": ("id", "code", "old_target", "new_target", "changed"),
    "scheduled_changes": ("id", "code", "target", "from_day", "created", "applied"),
    "scans": ("code", "day", "source", "count"),
}
READ_FUNCTIONS = ("count",)  # no sum(): scan_totals adds up in Python
# sqlite3_limit values for the read rail (the sqlite.org high-security column, ECP spec 7.4)
READ_LIMITS = (("SQLITE_LIMIT_LENGTH", 1000000), ("SQLITE_LIMIT_SQL_LENGTH", 10000), ("SQLITE_LIMIT_COLUMN", 100),
               ("SQLITE_LIMIT_EXPR_DEPTH", 10), ("SQLITE_LIMIT_COMPOUND_SELECT", 3),
               ("SQLITE_LIMIT_VDBE_OP", 25000), ("SQLITE_LIMIT_FUNCTION_ARG", 8), ("SQLITE_LIMIT_ATTACHED", 0),
               ("SQLITE_LIMIT_LIKE_PATTERN_LENGTH", 50), ("SQLITE_LIMIT_VARIABLE_NUMBER", 10),
               ("SQLITE_LIMIT_TRIGGER_DEPTH", 10))
# Each caps one thing a statement may hold or do: string and SQL length, columns, expression depth,
# UNION parts, compiled program size, function arguments, ?-variables. ATTACHED 0 forbids ATTACH.
# The SELECT behind every Row, one form per schema version: an older registry lacks columns, so
# LOOKUP_V2 and LOOKUP_V1 put fixed values in their place. Rows are read through these joins rather
# than the qr_lookup view, because the read rail turns views off.
LOOKUP_COLUMNS = ("SELECT q.id AS id, l.url AS link, c.hex AS hex, c.name AS name, c.family AS family, "
                  "c.cube_index AS cube_index, q.path AS path, q.path_key AS path_key, q.format AS format, "
                  "q.ec_level AS ec_level, q.version AS version, q.origin AS origin, q.created AS created")
LOOKUP = (LOOKUP_COLUMNS + ", s.code AS short_code, s.target AS target, q.payload_hash AS payload_hash, "
          "q.has_logo AS has_logo "
          "FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id "
          "LEFT JOIN short_links s ON s.link_id = l.id")
LOOKUP_V2 = (LOOKUP_COLUMNS + ", s.code AS short_code, s.target AS target, NULL AS payload_hash, 0 AS has_logo "
             "FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id "
             "LEFT JOIN short_links s ON s.link_id = l.id")
LOOKUP_V1 = (LOOKUP_COLUMNS + ", NULL AS short_code, NULL AS target, NULL AS payload_hash, 0 AS has_logo "
             "FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id")
# The SELECT behind every ShortLink; the subquery counts the pictures that print it.
SHORT_LINKS = ("SELECT s.code, l.url, s.target, c.hex, s.created, s.updated, "
               "(SELECT count(*) FROM qr_codes q WHERE q.link_id = s.link_id) "
               "FROM short_links s JOIN links l ON l.id = s.link_id JOIN colors c ON c.id = s.color_id")

# Version 1: colors (the 216 cube colors, and any other color a code or vote uses), links, QR codes
# and votes. path_key is UNIQUE, so one file is one record; the CHECKs repeat FORMATS, EC_LEVELS, ORIGINS.
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
)
# Version 2: short links (and the view shows them). Run on a new registry, and on a version 1 one.
TO_VERSION_2 = (
    """CREATE TABLE short_links (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        link_id INTEGER NOT NULL UNIQUE REFERENCES links(id),
        color_id INTEGER NOT NULL REFERENCES colors(id),
        target TEXT NOT NULL,
        created TEXT NOT NULL,
        updated TEXT NOT NULL)""",
    "CREATE INDEX short_links_by_target ON short_links(target)",
    "DROP VIEW IF EXISTS qr_lookup",
    """CREATE VIEW qr_lookup AS
        SELECT q.id AS id, l.url AS link, c.hex AS hex, c.name AS name, c.family AS family,
               c.cube_index AS cube_index, q.path AS path, q.path_key AS path_key, q.format AS format,
               q.ec_level AS ec_level, q.version AS version, q.origin AS origin, q.created AS created,
               s.code AS short_code, s.target AS target
        FROM qr_codes q JOIN links l ON l.id = q.link_id JOIN colors c ON c.id = q.color_id
        LEFT JOIN short_links s ON s.link_id = l.id""",
)
# Version 3: history, schedules, scans and masked payloads. Nothing older is renamed or dropped.
# The qr_lookup view keeps its version 2 columns. scans holds one count per short link, day and source.
TO_VERSION_3 = (
    "ALTER TABLE qr_codes ADD COLUMN payload_hash TEXT",
    "ALTER TABLE qr_codes ADD COLUMN has_logo INTEGER NOT NULL DEFAULT 0",
    """CREATE TABLE short_link_changes (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL REFERENCES short_links(code),
        old_target TEXT NOT NULL,
        new_target TEXT NOT NULL,
        changed TEXT NOT NULL)""",
    "CREATE INDEX short_link_changes_by_code ON short_link_changes(code)",
    """CREATE TABLE scheduled_changes (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL REFERENCES short_links(code),
        target TEXT NOT NULL,
        from_day TEXT NOT NULL,
        created TEXT NOT NULL,
        applied TEXT)""",
    "CREATE INDEX scheduled_changes_by_day ON scheduled_changes(from_day)",
    """CREATE TABLE scans (
        code TEXT NOT NULL REFERENCES short_links(code),
        day TEXT NOT NULL,
        source TEXT NOT NULL,
        count INTEGER NOT NULL CHECK (count >= 0),
        PRIMARY KEY (code, day, source))""",
)
# The Row record's keys, as lookup()'s SELECT names them.
ROW_KEYS = ("id", "link", "hex", "name", "family", "cube_index", "path", "path_key", "format", "ec_level",
            "version", "origin", "created", "short_code", "target", "payload_hash", "has_logo")


def ok_result(value):
    """A successful Result holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the short error phrase `error` and the value None."""
    return {"ok": False, "error": error, "value": None}


def utc_text(seconds):
    """Seconds since 1970 as UTC ISO-8601, e.g. "2026-10-29T18:04:05Z"."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def now_text():
    """Now as UTC ISO-8601 text (utc_text). Every stored time has this one form, so text order is time
    order."""
    return utc_text(time.time())


def today_text():
    """Today on this computer's calendar, "YYYY-MM-DD" (for the window; tests pass their own day)."""
    return time.strftime("%Y-%m-%d")


def is_day(text):
    """True for a real calendar day written YYYY-MM-DD."""
    if not isinstance(text, str) or DAY_RE.match(text) is None:
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def days_before(day, count):
    """The day `count` days before a "YYYY-MM-DD" day."""
    return (datetime.date.fromisoformat(day) - datetime.timedelta(days=count)).isoformat()


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
    # GetDriveTypeW answers 4 for a network drive, 5 for a CD-ROM and 0 or 1 when it cannot tell
    return kind in (2, 3, 6)  # removable, fixed, RAM disk


def file_state(path, local_only):
    """True or False for whether the file is there. None when `local_only` and it is not on a local
    drive, so a query never makes this computer reach out to a network share."""
    if local_only and not is_local_drive_path(path):
        return None
    return os.path.isfile(path)


# --- Opening ---------------------------------------------------------------------------------------

def close(connection):
    """Close a connection from connect() and forget its schema version; a close that fails is ignored.
    Every connection connect() returned must end here, or OPEN_VERSIONS keeps a stale id()."""
    OPEN_VERSIONS.pop(id(connection), None)
    try:
        connection.close()
    except sqlite3.Error:
        pass


def schema_of(connection):
    """The schema version a connection opened (read-only connections may be at an older one)."""
    return OPEN_VERSIONS.get(id(connection), SCHEMA_VERSION)


def rollback(connection):
    """Roll back the open transaction, ignoring the error SQLite raises when none is open."""
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def connect(path, read_only):
    """Open the registry -> Result connection. Read-write creates a new registry in a missing or
    empty file, and moves an older one to SCHEMA_VERSION; read-only never creates or changes
    anything, sets query_only, and also reads the versions in READABLE_VERSIONS. Any file that is
    not a QR Palette registry of such a version is refused. Close it with close() when done.

    Steps:
    1. Open the file. Read-only goes through a "file:...?mode=ro" URI, so SQLite never creates or
       writes it; read-write first makes its folder. isolation_level=None: this module writes BEGIN and
       COMMIT itself, so Python's sqlite3 starts no transaction behind its back.
    2. Set busy_timeout, and foreign_keys (SQLite enforces REFERENCES only when a connection asks).
    3. Read the header marks. A writable open of a new file (no marks, no tables) creates the schema.
    4. Refuse a file without APPLICATION_ID, or of a version this kind of open cannot use.
    5. Read-only: harden the connection (the read rail). Read-write: leave WAL if an old registry
       used it, and move an older registry to SCHEMA_VERSION after keeping a copy of it.
    6. Remember the version the connection opened, for schema_of().
    """
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
        if version not in READABLE_VERSIONS or (not read_only and version > SCHEMA_VERSION):
            close(connection)
            return fail(path + " is a QR Palette registry of another version (" + str(version) + ")")
        if read_only:
            hardened = harden_read_rail(connection)
            if not hardened["ok"]:
                close(connection)
                return hardened
        else:
            if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
                connection.execute("PRAGMA journal_mode=DELETE")  # registries made before 0.1.0 used WAL
            if version < SCHEMA_VERSION:
                kept = keep_older_copy(path, version)
                if not kept["ok"]:
                    close(connection)
                    return kept
                upgraded = upgrade_schema(connection)
                if not upgraded["ok"]:
                    close(connection)
                    return upgraded
                version = SCHEMA_VERSION
        OPEN_VERSIONS[id(connection)] = version
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
    the authorizer, which would deny them.

    The deadline counts from the open and covers every statement on the connection, so a read-only
    connection serves one short visit. SQLite calls the progress handler every 1000 virtual-machine
    instructions; when it answers 1, the running statement fails with "interrupted"."""
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    # setconfig and these constants exist from Python 3.12; an older Python skips them. DEFENSIVE
    # refuses writes that could corrupt the file even through SQL; DQS off makes "x" a name, never text.
    if hasattr(connection, "setconfig"):
        for name, enable in (("SQLITE_DBCONFIG_DEFENSIVE", True), ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False),
                             ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False), ("SQLITE_DBCONFIG_ENABLE_VIEW", False),
                             ("SQLITE_DBCONFIG_DQS_DML", False), ("SQLITE_DBCONFIG_DQS_DDL", False)):
            if hasattr(sqlite3, name):
                connection.setconfig(getattr(sqlite3, name), enable)
    # quick_check: integrity_check without the slow comparison of indexes against their tables
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
        """Progress handler: 1 (stop the statement) once the deadline has passed, else 0."""
        return 1 if time.monotonic() > deadline else 0

    connection.set_progress_handler(too_long, 1000)
    return ok_result(True)


def read_rail_authorizer(action, first, second, database, inner):
    """Allow plain SELECTs that read the allowed columns of the tables in READ_COLUMNS and call the
    allowed functions; deny everything else (DENY, never IGNORE, so a mistake is an error, not a
    silent NULL). SQLite calls it while compiling each statement: for SQLITE_READ `first` is the table
    and `second` the column; for SQLITE_FUNCTION `second` is the function's name."""
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # an empty column name: a table is read with no column taken from it, as in count(*)
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
    SQLite's default rollback journal: a read-only connection can then always read the file (WAL
    would need it to write a -shm file beside the registry). Runs only on a file connect() found
    empty."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA + TO_VERSION_2 + TO_VERSION_3:
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


def keep_older_copy(path, version):
    """Before a registry moves up: a checked copy of it beside it, NAME-vN.db, since this version's
    programs are the last that can open it as it was. One copy per version; it is never replaced."""
    stem, extension = os.path.splitext(path)
    target = stem + "-v" + str(version) + extension
    if os.path.exists(target):
        return ok_result(target)
    kept = backup(path, target)
    if not kept["ok"]:
        return fail("the registry was not updated, because a copy of it could not be kept first: " + kept["error"])
    return kept


def upgrade_schema(connection):
    """Move an older registry to SCHEMA_VERSION, step by step, all in one transaction. Each step
    reads user_version again, so a version 1 file goes to 2 and then to 3."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("PRAGMA user_version").fetchone()[0] == 1:
            for statement in TO_VERSION_2:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=2")
        if connection.execute("PRAGMA user_version").fetchone()[0] == 2:
            for statement in TO_VERSION_3:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=3")
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot update the registry to version " + str(SCHEMA_VERSION) + ": " + str(error))
    return ok_result(True)


def insert_color(connection, color):
    """Add a #rrggbb color with its channels, cube index (NULL when it is not one of the 216), name and
    family -> its id. Runs inside the caller's transaction."""
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
    """The id of a #rrggbb color, adding it first when it is not there yet (a color outside the cube,
    from a registered picture or an imported vote). Runs inside the caller's transaction."""
    row = connection.execute("SELECT id FROM colors WHERE hex = ?", (color,)).fetchone()
    if row is not None:
        return row[0]
    return insert_color(connection, color)


def link_id(connection, url):
    """The id of a link's text, adding it first when it is new. Runs inside the caller's transaction."""
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
    short = entry.get("short")
    if short is not None:
        if not isinstance(short.get("code"), str) or not short["code"].isdigit() or not short["code"].isascii():
            return "a short link's ID is digits"
        if not isinstance(short.get("target"), str) or short["target"] == "":
            return "a short link needs a destination"
    return ""


def save_qr(connection, entry):
    """Add a QR code, or replace the one already registered at the same file -> Result id. An Entry
    with "short" also records its short link (or keeps the one already recorded for that ID).

    Steps:
    1. check_entry, then one BEGIN IMMEDIATE transaction.
    2. Find or add the color and the link.
    3. With "short": add the short link, or refuse when its ID already belongs to another link.
    4. Insert the code, or update the row with the same path_key (an "upsert": INSERT ... ON CONFLICT
       DO UPDATE), so a file drawn again keeps its record id.
    5. Drop links no record uses any more, then commit.
    """
    problem = check_entry(entry)
    if problem != "":
        return fail(problem)
    key = path_key(entry["path"])
    try:
        connection.execute("BEGIN IMMEDIATE")
        color = color_id(connection, entry["color"])
        link = link_id(connection, entry["link"])
        short = entry.get("short")
        if short is not None:
            row = connection.execute("SELECT link_id FROM short_links WHERE code = ?", (short["code"],)).fetchone()
            if row is None:
                now = now_text()
                connection.execute("INSERT INTO short_links (code, link_id, color_id, target, created, updated) "
                                   "VALUES (?, ?, ?, ?, ?, ?)", (short["code"], link, color, short["target"], now, now))
            elif row[0] != link:
                rollback(connection)
                return fail("the short link ID " + short["code"] + " is already used for another address")
        connection.execute(
            "INSERT INTO qr_codes (link_id, color_id, path, path_key, format, ec_level, version, origin, created, "
            "payload_hash, has_logo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path_key) DO UPDATE SET link_id = excluded.link_id, color_id = excluded.color_id, "
            "path = excluded.path, format = excluded.format, ec_level = excluded.ec_level, "
            "version = excluded.version, origin = excluded.origin, created = excluded.created, "
            "payload_hash = excluded.payload_hash, has_logo = excluded.has_logo",
            (link, color, display_path(entry["path"]), key, entry["format"], entry["ec_level"], entry["version"],
             entry["origin"], now_text(), entry.get("payload_hash"), entry.get("has_logo", 0)))
        number = connection.execute("SELECT id FROM qr_codes WHERE path_key = ?", (key,)).fetchone()[0]
        drop_unused_links(connection)
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot save the record: " + str(error))
    return ok_result(number)


def drop_unused_links(connection):
    """Links no picture uses any more, except short links: printed codes still send people there."""
    connection.execute("DELETE FROM links WHERE id NOT IN (SELECT link_id FROM qr_codes) "
                       "AND id NOT IN (SELECT link_id FROM short_links)")


def short_link_for(connection, target, color, base):
    """The short link made on `base` for this destination in this color -> ShortLink, or None."""
    for found in short_links(connection):
        if found["target"] == target and found["hex"] == color and found["url"].startswith(base):
            return found
    return None


def code_taken(connection, code):
    """True when a short link with this ID is recorded."""
    return connection.execute("SELECT count(*) FROM short_links WHERE code = ?", (code,)).fetchone()[0] > 0


def change_target(connection, code, target):
    """Inside a transaction: send a short link to `target` and write it in its history -> True when
    there is such a short link. Going where it already goes changes nothing."""
    row = connection.execute("SELECT target FROM short_links WHERE code = ?", (code,)).fetchone()
    if row is None:
        return False
    if row[0] != target:
        now = now_text()
        connection.execute("UPDATE short_links SET target = ?, updated = ? WHERE code = ?", (target, now, code))
        connection.execute("INSERT INTO short_link_changes (code, old_target, new_target, changed) VALUES (?, ?, ?, ?)",
                           (code, row[0], target, now))
    return True


def retarget(connection, code, target):
    """Send a short link somewhere else -> Result True when there was one. Printed codes keep working:
    export the redirect pages again to publish the change. Where it used to go stays in its history."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        changed = change_target(connection, code, target)
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot change the destination: " + str(error))
    return ok_result(changed)


def link_changes(connection, code):
    """Where a short link has gone, newest first -> [Change]. A version 2 registry kept no history."""
    found = []
    if schema_of(connection) < 3:
        return found
    for row in connection.execute("SELECT id, old_target, new_target, changed FROM short_link_changes "
                                  "WHERE code = ? ORDER BY id DESC", (code,)).fetchall():
        found.append({"id": row[0], "old_target": row[1], "new_target": row[2], "changed": row[3]})
    return found


def undo_last_change(connection, code):
    """Send a short link back where it went before its latest change -> Result the target it goes to
    now. The undoing is a change too: nothing is ever taken out of the history."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT old_target FROM short_link_changes WHERE code = ? ORDER BY id DESC LIMIT 1",
                                 (code,)).fetchone()
        if row is None:
            rollback(connection)
            return fail("this short link has not been changed yet")
        change_target(connection, code, row[0])
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot undo the change: " + str(error))
    return ok_result(row[0])


def schedule_change(connection, code, target, from_day):
    """Send a short link to `target` from `from_day` on -> Result the schedule's id. It takes effect in
    exports from that day, and in the registry when due changes are applied."""
    if not is_day(from_day):
        return fail("a day is written YYYY-MM-DD, such as 2026-12-01")
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not code_taken(connection, code):
            rollback(connection)
            return fail("there is no short link " + code)
        cursor = connection.execute("INSERT INTO scheduled_changes (code, target, from_day, created) VALUES (?, ?, ?, ?)",
                                    (code, target, from_day, now_text()))
        number = cursor.lastrowid
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot schedule the change: " + str(error))
    return ok_result(number)


def cancel_scheduled(connection, number):
    """Take back a change that has not happened yet -> Result True when there was one."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute("DELETE FROM scheduled_changes WHERE id = ? AND applied IS NULL", (number,))
        removed = cursor.rowcount > 0
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot cancel the change: " + str(error))
    return ok_result(removed)


def scheduled(connection, code):
    """The changes still to come: of one short link, or of all ("") -> [Scheduled], soonest first."""
    found = []
    if schema_of(connection) < 3:
        return found
    for row in connection.execute("SELECT id, code, target, from_day, created FROM scheduled_changes "
                                  "WHERE applied IS NULL AND (? = '' OR code = ?) ORDER BY from_day, id",
                                  (code, code)).fetchall():
        found.append({"id": row[0], "code": row[1], "target": row[2], "from_day": row[3], "created": row[4]})
    return found


def due_changes(connection, today):
    """The scheduled changes whose day has come -> [Scheduled], soonest first."""
    found = []
    for change in scheduled(connection, ""):
        if change["from_day"] <= today:
            found.append(change)
    return found


def apply_due(connection, today):
    """Make every scheduled change whose day has come, in order, each written in the history -> Result
    how many were applied."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        due = due_changes(connection, today)
        for change in due:
            change_target(connection, change["code"], change["target"])
            connection.execute("UPDATE scheduled_changes SET applied = ? WHERE id = ?", (now_text(), change["id"]))
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot apply the scheduled changes: " + str(error))
    return ok_result(len(due))


def import_scans(connection, counts, source):
    """Scan counts {(code, day): count} from one source -> Result {"days": rows written, "unknown":
    [codes that are not short links here]}. A day's count from a source is replaced by a new one, so
    importing the same file again changes nothing, and a report that grew simply corrects its days."""
    written = 0
    unknown = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for key in sorted(counts):
            if not code_taken(connection, key[0]):
                if key[0] not in unknown:
                    unknown.append(key[0])
                continue
            connection.execute("INSERT INTO scans (code, day, source, count) VALUES (?, ?, ?, ?) "
                               "ON CONFLICT(code, day, source) DO UPDATE SET count = excluded.count",
                               (key[0], key[1], source, counts[key]))
            written = written + 1
        connection.execute("COMMIT")
    except sqlite3.Error as error:
        rollback(connection)
        return fail("cannot save the scans: " + str(error))
    return ok_result({"days": written, "unknown": unknown})


def scan_totals(connection, today):
    """Scans per short link -> {code: ScanCount}. Added up here: the read rail allows no sum()."""
    totals = {}
    if schema_of(connection) < 3:
        return totals
    recent_from = days_before(today, RECENT_DAYS - 1)  # 29 days back plus today: 30 days
    # YYYY-MM-DD text sorts in date order, so days compare as strings
    for row in connection.execute("SELECT code, day, count FROM scans").fetchall():
        if row[0] not in totals:
            totals[row[0]] = {"total": 0, "recent": 0}
        totals[row[0]]["total"] = totals[row[0]]["total"] + row[2]
        if recent_from <= row[1] <= today:
            totals[row[0]]["recent"] = totals[row[0]]["recent"] + row[2]
    return totals


def color_scans(connection):
    """Scans per color, for ranking -> {"#rrggbb": {"scans": int, "links": short links in this color}}."""
    found = {}
    if schema_of(connection) < 3:
        return found
    colors = {}
    for row in connection.execute("SELECT s.code, c.hex FROM short_links s JOIN colors c ON c.id = s.color_id").fetchall():
        colors[row[0]] = row[1]
        if row[1] not in found:
            found[row[1]] = {"scans": 0, "links": 0}
        found[row[1]]["links"] = found[row[1]]["links"] + 1
    for row in connection.execute("SELECT code, count FROM scans").fetchall():
        if row[0] in colors:
            found[colors[row[0]]]["scans"] = found[colors[row[0]]]["scans"] + row[1]
    return found


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
            # 32503680000 seconds is 3000-01-01T00:00:00Z; a vote's time is a number of seconds, never a bool
            if isinstance(when, bool) or not isinstance(when, (int, float)) or when < 0 or when > 32503680000:
                continue
            voted = utc_text(when)
            number = color_id(connection, hex_value)
            row = connection.execute("SELECT voat, voted FROM votes WHERE color_id = ?", (number,)).fetchone()
            # both times are utc_text, so text order is time order; the same vote at the same time is no change
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
    """A sqlite3.Row from lookup()'s SELECT -> Row record. A code with no short link gets "" for
    short_code and target instead of NULL."""
    record = {}
    for key in ROW_KEYS:
        record[key] = row[key]
    for key in ("short_code", "target"):
        if record[key] is None:
            record[key] = ""
    return record


def lookup(connection):
    """The SELECT that reads Rows, for the schema version this connection opened."""
    if schema_of(connection) < 2:
        return LOOKUP_V1
    if schema_of(connection) < 3:
        return LOOKUP_V2
    return LOOKUP


def all_rows(connection):
    """Every QR code, newest first, as Row records (the cursor is finished before returning)."""
    rows = []
    for row in connection.execute(lookup(connection) + " ORDER BY q.id DESC").fetchall():
        rows.append(row_record(row))
    return rows


def row_by_id(connection, number):
    """One QR code by its record id -> Row, or None when there is no such record."""
    row = connection.execute(lookup(connection) + " WHERE q.id = ?", (number,)).fetchone()
    if row is None:
        return None
    return row_record(row)


def vote_entries(connection):
    """Every vote with its time, oldest first: [{"color", "voat", "voted"}] (for exports)."""
    found = []
    for row in connection.execute("SELECT c.hex, v.voat, v.voted FROM votes v JOIN colors c ON c.id = v.color_id "
                                  "ORDER BY v.voted, c.hex").fetchall():
        found.append({"color": row[0], "voat": row[1], "voted": row[2]})
    return found


def backup(path, target):
    """Copy the registry into `target`, a new file -> Result target. SQLite's backup copies it page by
    page, consistently even while the window writes; the copy is checked (marks, version, quick_check)
    before it counts, and written next to its place first.

    Steps:
    1. Refuse when there is no registry, or when `target` exists already.
    2. Open the registry read-only and copy it with SQLite's online backup API into TARGET.part.
    3. Move TARGET.part into place with os.replace, which is one step on the same drive.
    4. Open the copy on the read rail, which checks its marks, its version and quick_check.
    """
    if not os.path.isfile(path):
        return fail("no registry yet at " + path)
    if os.path.exists(target):
        return fail(target + " already exists")
    temporary = target + ".part"
    source = None
    copy = None
    try:
        folder = os.path.dirname(os.path.abspath(target))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        source = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=BUSY_SECONDS)
        copy = sqlite3.connect(temporary)
        source.backup(copy)
        copy.close()
        copy = None
        os.replace(temporary, target)
    except (sqlite3.Error, OSError) as error:
        if copy is not None:
            copy.close()
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot back up the registry: " + str(error))
    finally:
        if source is not None:
            source.close()
    # Known limitation: a copy that fails this check stays at `target`.
    checked = connect(target, True)
    if not checked["ok"]:
        return fail("the backup did not check out: " + checked["error"])
    close(checked["value"])
    return ok_result(target)


def short_links(connection):
    """Every short link, oldest first, as ShortLink records ("pictures" counts the files that print it).
    A version 1 registry has none."""
    found = []
    if schema_of(connection) < 2:
        return found
    for row in connection.execute(SHORT_LINKS + " ORDER BY s.id").fetchall():
        found.append({"code": row[0], "url": row[1], "target": row[2], "hex": row[3], "created": row[4],
                      "updated": row[5], "pictures": row[6]})
    return found


def history_entries(connection):
    """Everything versions 3 and later keep about short links, for exports -> {"short_link_changes",
    "scheduled_changes", "scans"}, lists of records, empty for an older registry."""
    found = {"short_link_changes": [], "scheduled_changes": [], "scans": []}
    if schema_of(connection) < 3:
        return found
    for row in connection.execute("SELECT code, old_target, new_target, changed FROM short_link_changes "
                                  "ORDER BY id").fetchall():
        found["short_link_changes"].append({"code": row[0], "old_target": row[1], "new_target": row[2], "changed": row[3]})
    for row in connection.execute("SELECT code, target, from_day, created, applied FROM scheduled_changes "
                                  "ORDER BY id").fetchall():
        found["scheduled_changes"].append({"code": row[0], "target": row[1], "from_day": row[2], "created": row[3],
                                           "applied": row[4]})
    for row in connection.execute("SELECT code, day, source, count FROM scans ORDER BY code, day, source").fetchall():
        found["scans"].append({"code": row[0], "day": row[1], "source": row[2], "count": row[3]})
    return found


def short_links_on(connection, day):
    """Every short link as ShortLink, with the destination in force on `day`: the latest scheduled
    change whose day has come, even if it has not been applied yet."""
    found = short_links(connection)
    coming = {}
    for change in due_changes(connection, day):
        coming[change["code"]] = change["target"]
    for link in found:
        if link["code"] in coming:
            link["target"] = coming[link["code"]]
    return found


def vote_log(connection):
    """The votes, oldest first, as Voat records (what the rankers read)."""
    log = []
    for row in connection.execute("SELECT c.hex, v.voat FROM votes v JOIN colors c ON c.id = v.color_id "
                                  "ORDER BY v.voted, c.hex").fetchall():
        log.append({"color": row[0], "voat": row[1]})
    return log


def vote_map(connection):
    """Every color's vote now -> {"#rrggbb": 1 | -1}."""
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
    """How much the registry holds -> {"records": QR codes, "links": links, "colors_used": colors with
    at least one code}."""
    records = connection.execute("SELECT count(*) FROM qr_codes").fetchone()[0]
    links = connection.execute("SELECT count(*) FROM links").fetchone()[0]
    used = connection.execute("SELECT count(DISTINCT color_id) FROM qr_codes").fetchone()[0]
    return {"records": records, "links": links, "colors_used": used}


# --- Finding (plain Python over the rows: no LIKE wildcards, full Unicode case folding) -------------

def empty_filters():
    """No filter at all. "section" ("local" or "nonlocal") matches rows marked with that section (ECP
    marks them from links.json's bases); "short" matches rows that print a short link."""
    return {"color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "", "section": "",
            "short": False}


def clamp_limit(value):
    """A result limit made safe: DEFAULT_LIMIT when it is not a whole number (a bool is not one), else
    held to 1..MAX_LIMIT."""
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_LIMIT
    if value < 1:
        return 1
    if value > MAX_LIMIT:
        return MAX_LIMIT
    return value


def has_filter(filters):
    """True when a Filters record sets any filter ("near" alone is none: it only changes how a color
    matches)."""
    return (filters["color"] != "" or filters["family"] != "" or filters["link"] != "" or
            filters["link_exact"] != "" or filters["path"] != "" or filters["section"] != "" or filters["short"])


def loose_words(text):
    """Text as its words: case-folded letters and digits, every run of anything else one space."""
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def text_contains(haystack, needle):
    """True when `needle` is in `haystack` as typed (case-folded), or when each of its words is,
    ignoring punctuation: "store hours" finds ".../store-hours", "shop sale" finds "shop.example.com/sale".
    A link's percent-escapes are read too, so "blue mug" finds ".../p/blue%20mug"."""
    if contains_once(haystack, needle):
        return True
    decoded = urllib.parse.unquote(haystack)
    return decoded != haystack and contains_once(decoded, needle)


def contains_once(haystack, needle):
    """text_contains for one form of the haystack: the needle as typed, case-folded, or else each of the
    needle's words somewhere in the haystack's words (a substring test, so "sto" finds "store"). A
    needle with no words matches only as typed."""
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
    """True when a Row passes every filter set in `filters` (Filters). "section" is only on Rows that
    ECP marked; a path matches by its path_key or by its words."""
    if filters["color"] != "":
        if filters["near"]:
            if not swatch.is_near(row["hex"], filters["color"]):
                return False
        elif row["hex"] != filters["color"]:
            return False
    if filters["family"] != "" and row["family"] != filters["family"]:
        return False
    # A short link matches by the address it prints and by where it sends people.
    if filters["link_exact"] != "" and filters["link_exact"] not in (row["link"], row["target"]):
        return False
    if filters["link"] != "" and not text_contains(row["link"], filters["link"]) and not (
            row["target"] != "" and text_contains(row["target"], filters["link"])):
        return False
    if filters["path"] != "":
        wanted = text_key(filters["path"]).casefold()
        if wanted not in row["path_key"].casefold() and not text_contains(row["path"], filters["path"]):
            return False
    if filters["short"] and row["short_code"] == "":
        return False
    if filters["section"] != "" and row.get("section", "") != filters["section"]:
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=aa75749cff0b4826d6137039b539a383722d7475f94fd03b8b5ecebcce3c2f0c ====
