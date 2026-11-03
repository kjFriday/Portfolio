# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: textsafe.py
# About: Input guard for text that arrives from outside: drop invisible control characters, cap...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Input guard for text that arrives from outside: drop invisible control characters, cap the length.

Removed: C0 controls except tab and newline, DEL, the whole C1 block (U+0080-U+009F, which includes
U+009B, a one-character escape-sequence start), the line/paragraph separators U+2028/U+2029, and the
bidirectional embedding, override and isolate controls (U+202A-U+202E, U+2066-U+2069).
Everything else, including ordinary non-ASCII text, passes through unchanged.
"""

LIMIT = 240  # shared default cap, in characters

_INVISIBLE = frozenset([0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)])


def refused(ch):
    c = ord(ch)
    return (c < 0x20 and ch not in "\t\n") or 0x7F <= c <= 0x9F or c in _INVISIBLE


def clean(text, limit=LIMIT):
    """Return text without refused characters, cut to at most `limit` characters (None = no cap)."""
    if text is None:
        return ""
    if limit is not None:
        limit = max(limit, 0)  # a negative slice would count from the end
    return "".join(ch for ch in text if not refused(ch))[:limit]

# ==== stamp v1 | author=kjFriday | hmac-sha256=b7e51f67583d9fca4f32d97a3d49ebdf7f9e19af09fea44969dfc16a1e5bff0f ====
