# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/records.py
# About: Result records: how the codec's functions report success or failure without raising.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Result records: how the codec's functions report success or failure without raising.

Result {"ok": bool, "error": str, "value": any}. A failure has the value None and a short error
phrase with no final period.
"""


def make_result(ok, value, error):
    return {"ok": ok, "value": value, "error": error}


def ok_result(value):
    return make_result(True, value, "")


def fail(error):
    return make_result(False, None, error)

# ==== stamp v1 | author=kjFriday | hmac-sha256=924bc0a8fe6ad2b7944b2b2533281f6d748f9e25eb5b4f39168466b9d0788d98 ====
