# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/gf.py
# About: GF(256): the field Reed-Solomon codewords live in, with the polynomial 0x11D.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""GF(256): the field Reed-Solomon codewords live in, with the polynomial 0x11D.

The field is built on x^8 + x^4 + x^3 + x^2 + 1 (0x11D) with alpha = 2, as ISO/IEC 18004 uses. The log
and antilog tables are built when the module is imported; GF_EXP is doubled to 512 entries so gf_mul
needs no modulo.
"""


GF_EXP = [0] * 512
GF_LOG = [0] * 256


def build_gf_tables():
    value = 1
    index = 0
    while index < 255:
        GF_EXP[index] = value
        GF_LOG[value] = index
        value = value << 1
        if value & 0x100:
            value = value ^ 0x11D
        index = index + 1
    while index < 512:
        GF_EXP[index] = GF_EXP[index - 255]
        index = index + 1


build_gf_tables()


def gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def gf_div(a, b):
    """a / b; b must not be 0."""
    if a == 0:
        return 0
    return GF_EXP[(GF_LOG[a] + 255 - GF_LOG[b]) % 255]


def alpha_power(n):
    return GF_EXP[n % 255]


def poly_eval_low(coefficients, x):
    """Value of a polynomial whose coefficients[i] belongs to x**i."""
    result = 0
    index = len(coefficients) - 1
    while index >= 0:
        result = gf_mul(result, x) ^ coefficients[index]
        index = index - 1
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=4875824dbfe4bb46dcbde75e5637770e8b1ca21d958d958174103992d31db23f ====
