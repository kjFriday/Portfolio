# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: audit.py
# About: The audit log: one JSON line per ECP call, each holding the SHA-256 of the line before.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The audit log: one JSON line per ECP call, each holding the SHA-256 of the line before.

QR Palette's audit log is a hash chain. Every record has "prev_sha256", the SHA-256 of the exact
bytes of the line before it (64 zeros, GENESIS, for the first line), and "audit_id", its line number
counted from 1. Change one byte of line 5 and line 6's prev_sha256 no longer matches; delete line 5
and line 6 no longer follows line 4, and the audit_ids skip. The chain needs no key: it does not stop
someone who rewrites every line after the change, it only makes a quiet edit impossible.

Who calls it: ecp.write_audit appends a line for every MCP tool call and every ECP call from the
window's Ask row (listing, choosing and asking a model); the window's Audit log dialog
(gui/dialogs.py) reads, verifies and fingerprints the log; the tests pin the chain's behavior.

The chain makes any edit or deletion visible: verify() recomputes it from the first line. A line
records what was asked and how it was answered (hashes of the prompt, the planner's rules and the plan
schema; the model and its digest; the plan as run; counts and timings), never the prompt itself and
never stored data. Nothing in it is sent back to a client except its audit_id. Writers take a lock
file for the moment of appending, so the window and an MCP server can share one log.

A chain alone cannot show lines cut off its end. So every append also writes an anchor beside the log
(LOG.anchor: the last line's audit_id and SHA-256), and verify() checks the log still reaches it. For
more assurance, keep the fingerprint somewhere else as well (the window copies it) and check it with
check_fingerprint(): whoever can rewrite the folder can rewrite the anchor too.

Records
  Result       {"ok": bool, "error": str, "value": any}
  Fingerprint  {"audit_id": int, "line_sha256": str}         the last line of a log, or a kept copy

Main flow of append:
  1. Make the log's folder if it is not there.
  2. Take the lock file (take_lock), waiting up to LOCK_SECONDS.
  3. Read the last line, and number the new record one past its audit_id.
  4. Write the record as one ASCII JSON line with the previous line's SHA-256, flush and fsync it.
  5. Write the anchor beside the log, then let the lock go.

Start reading at append, then chain.
"""

import hashlib
import json
import os
import time

# LOCK_SECONDS: how long a writer waits for another writer's lock before it gives up (the tests
# shorten it). GENESIS: the prev_sha256 of the first line, which has no line before it.
LOCK_SECONDS = 2.0
GENESIS = "0" * 64


def ok_result(value):
    """A successful Result holding `value` (this module keeps its own copy, so it imports nothing
    of the program's)."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with a short error phrase."""
    return {"ok": False, "error": error, "value": None}


def sha256_text(text):
    """The SHA-256 of `text`'s UTF-8 bytes, as 64 lowercase hex digits."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now():
    """The time now in UTC as ISO 8601 to the second, such as "2026-11-03T14:05:09Z"."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def last_line(path):
    """The last non-empty line of the file, or "" (reads only the end of a long file).

    Steps:
      1. "" when there is no file.
      2. Read the last 64 KiB; while that holds no whole line (no newline besides the trailing
         ones) and the file has more, start 64 KiB earlier and read to the end again.
      3. Split what was read at newlines and decode the last line as UTF-8.
    """
    if not os.path.isfile(path):
        return ""
    handle = open(path, "rb")
    try:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        step = 65536
        start = max(0, size - step)
        handle.seek(start)
        tail = handle.read()
        while start > 0 and tail.rstrip(b"\n").count(b"\n") == 0:
            start = max(0, start - step)
            handle.seek(start)
            tail = handle.read()
    finally:
        handle.close()
    lines = tail.rstrip(b"\n").split(b"\n")
    return lines[len(lines) - 1].decode("utf-8")


def take_lock(path):
    """Take the log's lock file (LOG.lock) -> Result the lock's path, which the caller removes.

    The lock is a file made with O_CREAT | O_EXCL, which the operating system makes atomic: of two
    writers, exactly one creates it and the other gets FileExistsError. A waiting writer tries again
    every 10 ms. After LOCK_SECONDS it gives up ("busy"), unless the lock file is more than 30
    seconds old: no append takes that long, so its writer must have died, and the lock is removed
    and taken again. Works across processes (the window and an MCP server), not only threads."""
    lock = path + ".lock"
    deadline = time.monotonic() + LOCK_SECONDS
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            return ok_result(lock)
        except FileExistsError:
            if time.monotonic() > deadline:
                try:
                    if time.time() - os.path.getmtime(lock) > 30:
                        os.remove(lock)  # left behind by a process that died while appending
                        continue
                except OSError:
                    pass
                return fail("the audit log is busy")
            time.sleep(0.01)
        except OSError as error:
            return fail("cannot lock the audit log: " + str(error))


def append(path, fields):
    """Add one record -> Result audit_id. `fields` is a flat object of the call's facts.

    The record is {"audit_id", "ts", then `fields` in their order, then "prev_sha256"}. A field
    named prev_sha256 in `fields` is overwritten by the chain's own; one named audit_id or ts would
    replace the chain's (the callers never pass them). The line is
    ASCII JSON (ensure_ascii escapes everything else, U+2028 and newlines included), so one record
    is always exactly one line. A damaged last line is never built on: nothing is added, so the
    damage stays visible instead of being chained over. Side effects: may create the folder, the
    log, its lock and its anchor."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except OSError as error:
        return fail("cannot make the audit folder: " + str(error))
    locked = take_lock(path)
    if not locked["ok"]:
        return locked
    try:
        previous = last_line(path)
        number = 1
        if previous != "":
            try:
                number = int(json.loads(previous)["audit_id"]) + 1
            except (ValueError, KeyError, TypeError):
                return fail("the audit log's last line is damaged; nothing was added")
        record = {"audit_id": number, "ts": utc_now()}
        for key in fields:
            record[key] = fields[key]
        record["prev_sha256"] = GENESIS
        if previous != "":
            record["prev_sha256"] = sha256_text(previous)
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        handle = open(path, "ab")
        try:
            handle.write(line.encode("ascii") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())  # on disk before the anchor names it
        finally:
            handle.close()
        write_anchor(path, number, line)
    except OSError as error:
        return fail("cannot write the audit log: " + str(error))
    finally:
        try:
            os.remove(locked["value"])
        except OSError:
            pass
    return ok_result(number)


def anchor_path(path):
    """The anchor file of a log: the log's path with ".anchor" added."""
    return path + ".anchor"


def write_anchor(path, number, line):
    """The anchor beside the log: the last line's audit_id and SHA-256 (written into place, so it is
    never half written). It may fall behind if writing it fails; that only weakens the check.

    "Written into place": the anchor goes to ANCHOR.part first and os.replace renames it over the
    old one, a single step on the same drive, so a reader sees the old anchor or the new one. Any
    OSError is swallowed."""
    try:
        temporary = anchor_path(path) + ".part"
        handle = open(temporary, "w", encoding="ascii", newline="\n")
        try:
            handle.write(json.dumps({"audit_id": number, "line_sha256": sha256_text(line)}) + "\n")
        finally:
            handle.close()
        os.replace(temporary, anchor_path(path))
    except OSError:
        pass


def read_anchor(path):
    """The anchor's Fingerprint, or None when there is none (or it cannot be read).

    An anchor that is not an object with an integer audit_id (a bool is refused, since JSON true
    would pass Python's int check) and a string line_sha256 also reads as None."""
    try:
        handle = open(anchor_path(path), "r", encoding="ascii")
        try:
            found = json.loads(handle.read())
        finally:
            handle.close()
    except (OSError, ValueError):
        return None
    if (not isinstance(found, dict) or isinstance(found.get("audit_id"), bool) or
            not isinstance(found.get("audit_id"), int) or not isinstance(found.get("line_sha256"), str)):
        return None
    return {"audit_id": found["audit_id"], "line_sha256": found["line_sha256"]}


def chain(path, kept):
    """Walk the chain, checking it and, when given, a kept Fingerprint -> Result number of records.

    `kept` is None to check the chain alone. A failure names the first line that is wrong.

    Steps:
      1. No log: fine when nothing was kept, else the whole log is gone.
      2. For each non-empty line, counted from 1: it must be a JSON object, its prev_sha256 must be
         the SHA-256 of the line before (GENESIS for the first), and its audit_id its own number.
      3. On the kept line's number, note that line's SHA-256.
      4. With a Fingerprint: the log must reach its line (else lines were cut off the end), and that
         line must hash to what was kept. Lines added after it are fine.
    """
    if not os.path.isfile(path):
        if kept is not None:
            return fail("there is no log, but a fingerprint says " + str(kept["audit_id"]) + " lines were written")
        return ok_result(0)
    previous = ""
    count = 0
    seen = None
    # every line is written as ASCII; a byte that is not becomes U+FFFD and breaks the next hash
    handle = open(path, "r", encoding="ascii", errors="replace")
    try:
        for line in handle:
            line = line.rstrip("\n")
            if line == "":
                continue
            count = count + 1
            try:
                record = json.loads(line)
            except ValueError:
                return fail("line " + str(count) + " is not JSON")
            expected = GENESIS
            if previous != "":
                expected = sha256_text(previous)
            if not isinstance(record, dict) or record.get("prev_sha256") != expected:
                return fail("line " + str(count) + " does not follow the line before it")
            if record.get("audit_id") != count:
                return fail("line " + str(count) + " has audit_id " + str(record.get("audit_id")))
            if kept is not None and count == kept["audit_id"]:
                seen = sha256_text(line)
            previous = line
    finally:
        handle.close()
    if kept is not None:
        if count < kept["audit_id"]:
            return fail("the log ends at line " + str(count) + ", but " + str(kept["audit_id"]) + " lines were "
                        "written: lines were cut off the end")
        if seen != kept["line_sha256"]:
            return fail("line " + str(kept["audit_id"]) + " is not the line that was written")
    return ok_result(count)


def verify(path):
    """Check the whole chain, and that it still reaches its anchor -> Result number of records, or a
    failure naming the first bad line (or the cut-off end)."""
    return chain(path, read_anchor(path))


def fingerprint(path):
    """The log's last line as a Fingerprint, to keep somewhere else -> Result.

    Fails when the log is empty or missing, or its last line is not a record with an audit_id. The
    chain itself is not checked here; verify does that."""
    line = last_line(path)
    if line == "":
        return fail("the audit log is empty")
    try:
        number = json.loads(line)["audit_id"]
    except (ValueError, KeyError, TypeError):
        return fail("the audit log's last line is damaged")
    return ok_result({"audit_id": number, "line_sha256": sha256_text(line)})


def fingerprint_text(found):
    """A Fingerprint as one short line to copy: "45:3f2a…" (audit_id, then the SHA-256)."""
    return str(found["audit_id"]) + ":" + found["line_sha256"]


def check_fingerprint(path, text):
    """Check the log against a fingerprint kept elsewhere ("45:3f2a…", as fingerprint_text writes it)
    -> Result number of records.

    The text must be digits, one colon and 64 characters; the hash is compared in lowercase, so a
    fingerprint typed in capitals still matches."""
    parts = text.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) != 64:
        return fail("a fingerprint is the line number, a colon and 64 hex digits")
    return chain(path, {"audit_id": int(parts[0]), "line_sha256": parts[1].lower()})


def read_records(path, limit):
    """The last `limit` records of the log, oldest first, for reading (a damaged line becomes
    {"audit_id": "?", "damaged": its text})."""
    # Known limitation: the whole log is read into memory to take its last lines; a very long log
    # makes the Audit log dialog slow to open.
    found = []
    if not os.path.isfile(path):
        return found
    handle = open(path, "r", encoding="ascii", errors="replace")
    try:
        lines = handle.read().splitlines()
    finally:
        handle.close()
    for line in lines[max(0, len(lines) - limit):]:
        if line == "":
            continue
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if not isinstance(record, dict):
            record = {"audit_id": "?", "damaged": line[:200]}  # the first 200 characters, to look at
        found.append(record)
    return found

# ==== stamp v1 | author=kjFriday | hmac-sha256=71b214f257689fd15205158333698e2a150f075f62a75aba8cb540388c9dfc56 ====
