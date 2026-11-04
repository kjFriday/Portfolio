# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/records.py
# About: Result records: how the codec's functions report success or failure without raising.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Result records: how the codec's functions report success or failure without raising.

Result {"ok": bool, "error": str, "value": any}. A failure has the value None and a short error
phrase with no final period.

Returning a record instead of raising keeps bad input (a damaged picture, text too long for any
version) an ordinary outcome the caller checks with result["ok"], and lets a message reach the user
as it is. The codec's modules import fail and ok_result from here.
"""


def make_result(ok, value, error):
    """A Result record from its three fields; ok_result and fail are the usual ways to make one."""
    return {"ok": ok, "value": value, "error": error}


def ok_result(value):
    """A successful Result carrying value, with an empty error."""
    return make_result(True, value, "")


def fail(error):
    """A failed Result with the short reason `error` (no final period) and the value None."""
    return make_result(False, None, error)

# ==== stamp v1 | author=kjFriday | hmac-sha256=c8efd6bada5695874ff4ed0b829e458af103c528c628c06eb944f665a640ed05 ====
