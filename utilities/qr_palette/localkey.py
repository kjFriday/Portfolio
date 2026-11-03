# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: localkey.py
# About: QR Palette's local key: a secret in a file of its own beside the registry, never in...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette's local key: a secret in a file of its own beside the registry, never in settings.json or
the registry itself.

Two things use it, each under a purpose of its own, so one can never stand in for the other:
  * "payload": the keyed hash stored for a code whose text is masked (a Wi-Fi password is not kept). It
    finds the record again when the code is scanned, and without the key the registry file or a backup
    of it cannot be used to guess the password.
  * "id": the two tag digits in a short-link ID, which tell your printed codes from others.

Back the key up with the registry if you need those to keep working on another computer. Losing it
makes old tags unverifiable and masked codes unfindable by scanning; it never makes anything invalid.

Records
  Result  {"ok": bool, "error": str, "value": any}
"""

import hashlib
import hmac
import os
import secrets

KEY_NAME = "qr_palette.key"
KEY_BYTES = 32


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def key_path(db_path):
    """The key file of a registry: beside it, so a scratch registry never touches your own key."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), KEY_NAME)


def read_key(path):
    """The key in a key file -> bytes, or None when there is no such file or it holds no key."""
    try:
        handle = open(path, "r", encoding="ascii")
        try:
            text = handle.read().strip()
        finally:
            handle.close()
        key = bytes.fromhex(text)
    except (OSError, ValueError):
        return None
    if len(key) != KEY_BYTES:
        return None
    return key


def key_for(db_path):
    """The key of a registry, made on first need -> Result bytes. A file there that holds no key is
    never overwritten. Two programs making it at once end up with the same one."""
    path = key_path(db_path)
    key = read_key(path)
    if key is not None:
        return ok_result(key)
    if os.path.exists(path):
        return fail(path + " does not hold a key; move it away and a new key will be made")
    key = secrets.token_bytes(KEY_BYTES)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(handle, (key.hex() + "\n").encode("ascii"))
        finally:
            os.close(handle)
    except FileExistsError:
        key = read_key(path)
        if key is None:
            return fail(path + " does not hold a key; move it away and a new key will be made")
    except OSError as error:
        return fail("cannot make the key " + path + ": " + str(error))
    return ok_result(key)


def tag(key, purpose, text):
    """HMAC-SHA-256 of `text` under the key, kept apart by `purpose` -> 64 hex digits."""
    message = purpose.encode("utf-8") + b"\x00" + text.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a30334d36e209afe755eddce32ceb33995e995e0e67a2106213accf6090ba8c8 ====
