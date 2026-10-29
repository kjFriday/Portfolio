# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/audit.py
# About: QR Palette audit log: one JSON line per ECP tool call, each holding the SHA-256 of the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette audit log: one JSON line per ECP tool call, each holding the SHA-256 of the line before.

The chain makes any edit or deletion visible: verify() recomputes it from the first line. A line
records what was asked and how it was answered (hashes of the prompt, the planner's rules and the plan
schema; the model and its digest; the plan as run; counts and timings), never the prompt itself and
never stored data. Nothing in it is sent back to a client except its audit_id. Writers take a lock
file for the moment of appending, so the window and an MCP server can share one log.

Records
  Result  {"ok": bool, "error": str, "value": any}
"""

import hashlib
import json
import os
import time

LOCK_SECONDS = 2.0
GENESIS = "0" * 64


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def last_line(path):
    """The last non-empty line of the file, or "" (reads only the end of a long file)."""
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
    """Add one record -> Result audit_id. `fields` is a flat object of the call's facts."""
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
            os.fsync(handle.fileno())
        finally:
            handle.close()
    except OSError as error:
        return fail("cannot write the audit log: " + str(error))
    finally:
        try:
            os.remove(locked["value"])
        except OSError:
            pass
    return ok_result(number)


def verify(path):
    """Check the whole chain -> Result number of records, or a failure naming the first bad line."""
    if not os.path.isfile(path):
        return ok_result(0)
    previous = ""
    count = 0
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
            previous = line
    finally:
        handle.close()
    return ok_result(count)

# ==== stamp v1 | author=kjFriday | hmac-sha256=c0c8f5f02ec08bad3be05dbfc92da761c684e95396c65b32af6a16770a8e1981 ====
