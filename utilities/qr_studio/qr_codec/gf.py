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

What GF(256) is: a set of 256 values (one byte each) where addition is XOR and multiplication is
polynomial multiplication of the bits, reduced modulo the field polynomial. Every nonzero value is a
power of alpha (2), so multiplying two values is adding their exponents: a * b = alpha^(log a + log b).
The two tables turn that into lookups: GF_LOG maps a value to its exponent, GF_EXP maps an exponent
back to the value. Subtraction is the same as addition (XOR), so there is no gf_sub.

Callers: reed_solomon.py (generator polynomials, remainders, syndromes, error location) and the
decoder's error correction. Nothing here touches files or global state beyond the two tables.

Defines GF_EXP, GF_LOG, build_gf_tables, gf_mul, gf_div, alpha_power and poly_eval_low.
"""


# GF_EXP[i] is alpha**i; entries 255..511 repeat 0..256 so GF_LOG[a] + GF_LOG[b] (at most 508) indexes
# it directly. GF_LOG[v] is the exponent of v; GF_LOG[0] stays 0 and is never meaningful.
GF_EXP = [0] * 512
GF_LOG = [0] * 256


def build_gf_tables():
    """Fill GF_EXP and GF_LOG in place; run once at import.

    Steps:
    1. Start at alpha**0 = 1 and multiply by alpha (a left shift) 255 times, recording each value and its
       exponent.
    2. When the shift carries into bit 8, XOR with 0x11D to reduce modulo the field polynomial.
    3. Copy the 255-entry cycle into GF_EXP[255:512] so sums of two logs need no modulo.
    """
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
    """Product of two field elements (bytes 0..255) by adding their logs."""
    # zero has no log, so it is handled before the table lookup
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def gf_div(a, b):
    """a / b; b must not be 0."""
    if a == 0:
        return 0
    # + 255 keeps the exponent difference non-negative before the modulo
    return GF_EXP[(GF_LOG[a] + 255 - GF_LOG[b]) % 255]


def alpha_power(n):
    """alpha**n for any integer n; the multiplicative group has order 255, so n wraps mod 255."""
    return GF_EXP[n % 255]


def poly_eval_low(coefficients, x):
    """Value of a polynomial whose coefficients[i] belongs to x**i.

    Uses Horner's rule from the highest power down: result = result * x + c at each step.
    """
    result = 0
    index = len(coefficients) - 1
    while index >= 0:
        result = gf_mul(result, x) ^ coefficients[index]
        index = index - 1
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=5c2db81e7cddd90e8b424b68f67bcade4f677a285a1f877bc42cb189d1c6c62a ====
