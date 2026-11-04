# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: localkey.py
# About: QR Palette's local key: a secret kept in a file of its own beside the registry.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette's local key: a secret kept in a file of its own beside the registry.

The key is never in settings.json or the registry itself, so a copy of the registry alone reveals
nothing it protects.

Two things use it, each under a purpose of its own, so one can never stand in for the other:
  * "payload": the keyed hash stored for a code whose text is masked (a Wi-Fi password is not kept). It
    finds the record again when the code is scanned, and without the key the registry file or a backup
    of it cannot be used to guess the password.
  * "id": the two tag digits in a short-link ID, which tell your printed codes from others.

Back the key up with the registry if you need those to keep working on another computer. Losing it
makes old tags unverifiable and masked codes unfindable by scanning; it never makes anything invalid.

Callers: making.py (masked payload hash when a code is saved), finding.py and selftest.py (the
same hash when a scanned code is looked up), shortlinks.py and short_link_ops.py (tag digits of a
short-link ID), and window.py (a reminder to back the key up). This module calls only the standard
library.

Main flow:
  1. key_path() names the key file beside the registry.
  2. key_for() reads it, or makes a new random key there on first need.
  3. tag() turns (key, purpose, text) into an HMAC-SHA-256 hex digest.

How the tag works: HMAC (RFC 2104) mixes a secret key into a hash, so only someone holding the key
can compute or check the digest. The purpose and the text are joined with a NUL byte before hashing;
a purpose never contains NUL, so the first NUL always marks where it ends, and ("id", "x") and
("payload", "x") never hash the same message.

Records
  Result  {"ok": bool, "error": str, "value": any}
"""

import hashlib
import hmac
import os
import secrets

# KEY_NAME is the key file's name, beside the registry file; KEY_BYTES is the key length (256 bits,
# the output size of SHA-256, as RFC 2104 suggests for an HMAC key).
KEY_NAME = "qr_palette.key"
KEY_BYTES = 32


def ok_result(value):
    """A successful Result carrying `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the message `error` and no value."""
    return {"ok": False, "error": error, "value": None}


def key_path(db_path):
    """The key file of a registry: beside it, so a scratch registry never touches your own key."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), KEY_NAME)


def read_key(path):
    """The key in a key file -> bytes, or None when there is no such file or it holds no key.

    The file holds the key as hex digits on one line; surrounding whitespace is ignored. Text that
    is not hex, or a key of any length but KEY_BYTES, counts as no key. Never raises."""
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
    never overwritten. Two programs making it at once end up with the same one.

    Steps:
      1. Read the key file; a valid key there is the answer.
      2. A file there that is not a key is refused, so a damaged key is never replaced silently
         (replacing it would orphan every tag and masked hash made with the old one).
      3. Otherwise make KEY_BYTES of cryptographic randomness and create the file with O_EXCL,
         which fails if another program created it first; that program's key is then read back.

    Side effects: may create the registry's folder and the key file (mode 0600, owner only where
    the system honors it)."""
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
    """HMAC-SHA-256 of `text` under the key, kept apart by `purpose` -> 64 hex digits.

    `purpose` is "payload" or "id" (see the module doc); the message is purpose, a NUL byte, then
    the text, all UTF-8. The same inputs always give the same digest."""
    message = purpose.encode("utf-8") + b"\x00" + text.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()

# ==== stamp v1 | author=kjFriday | hmac-sha256=1cb6420498e49a4370288b9faead2ced40fa60d68bae3888a2baab92dc123407 ====
