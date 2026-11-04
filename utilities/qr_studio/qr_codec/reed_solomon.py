# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/reed_solomon.py
# About: Reed-Solomon: error-correction codewords for the encoder, and corrections for the decoder.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Reed-Solomon: error-correction codewords for the encoder, and corrections for the decoder.

A block is a list of codewords, highest power first. The generator's roots are alpha**0 ..
alpha**(degree-1). rs_correct finds the errors with Berlekamp-Massey, a Chien search and Forney's
formula, then checks the syndromes again, so a wrong correction is refused rather than returned.
"""

from .records import fail, ok_result
from .gf import alpha_power, gf_div, gf_mul, poly_eval_low


def rs_generator(degree):
    """Generator polynomial, highest power first, with roots alpha**0 .. alpha**(degree-1)."""
    generator = [1]
    for i in range(degree):
        product = [0] * (len(generator) + 1)
        for j in range(len(generator)):
            product[j] = product[j] ^ generator[j]
            product[j + 1] = product[j + 1] ^ gf_mul(generator[j], alpha_power(i))
        generator = product
    return generator


def rs_remainder(data, degree):
    """The `degree` error-correction codewords for a list of data codewords."""
    generator = rs_generator(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:]
        remainder.append(0)
        for j in range(degree):
            remainder[j] = remainder[j] ^ gf_mul(generator[j + 1], factor)
    return remainder


def rs_syndromes(block, ec_count):
    syndromes = []
    for i in range(ec_count):
        value = 0
        x = alpha_power(i)
        for byte in block:
            value = gf_mul(value, x) ^ byte
        syndromes.append(value)
    return syndromes


def all_zero(values):
    for value in values:
        if value != 0:
            return False
    return True


def rs_correct(block, ec_count):
    """Fix up to ec_count // 2 wrong codewords -> Result {"block": [int], "errors": int}."""
    n = len(block)
    syndromes = rs_syndromes(block, ec_count)
    if all_zero(syndromes):
        return ok_result({"block": list(block), "errors": 0})

    # Berlekamp-Massey: error locator, lowest power first.
    locator = [1]
    previous = [1]
    length = 0
    shift = 1
    last_discrepancy = 1
    for step in range(ec_count):
        discrepancy = syndromes[step]
        for i in range(1, length + 1):
            if i < len(locator):
                discrepancy = discrepancy ^ gf_mul(locator[i], syndromes[step - i])
        if discrepancy == 0:
            shift = shift + 1
            continue
        scale = gf_div(discrepancy, last_discrepancy)
        updated = list(locator)
        while len(updated) < len(previous) + shift:
            updated.append(0)
        for i in range(len(previous)):
            updated[i + shift] = updated[i + shift] ^ gf_mul(scale, previous[i])
        if 2 * length <= step:
            previous = locator
            length = step + 1 - length
            last_discrepancy = discrepancy
            shift = 1
        else:
            shift = shift + 1
        locator = updated
    while len(locator) > 1 and locator[len(locator) - 1] == 0:
        locator.pop()
    if 2 * length > ec_count or len(locator) - 1 != length:
        return fail("too many errors")

    # Chien search: a root at alpha**-e means an error at power e.
    powers = []
    for power in range(n):
        if poly_eval_low(locator, alpha_power(255 - power)) == 0:
            powers.append(power)
    if len(powers) != length:
        return fail("too many errors")

    # Forney: magnitudes from the evaluator and the locator's derivative.
    evaluator = [0] * ec_count
    for i in range(ec_count):
        for j in range(len(locator)):
            if i + j < ec_count:
                evaluator[i + j] = evaluator[i + j] ^ gf_mul(syndromes[i], locator[j])
    derivative = []
    for i in range(1, len(locator)):
        if i % 2 == 1:
            derivative.append(locator[i])
        else:
            derivative.append(0)
    fixed = list(block)
    for power in powers:
        x = alpha_power(power)
        x_inverse = alpha_power(255 - power)
        denominator = poly_eval_low(derivative, x_inverse)
        if denominator == 0:
            return fail("too many errors")
        magnitude = gf_mul(x, gf_div(poly_eval_low(evaluator, x_inverse), denominator))
        fixed[n - 1 - power] = fixed[n - 1 - power] ^ magnitude
    if not all_zero(rs_syndromes(fixed, ec_count)):
        return fail("too many errors")
    return ok_result({"block": fixed, "errors": len(powers)})

# ==== stamp v1 | author=kjFriday | hmac-sha256=819139dffb5eeacd8a5814fbacbd29b3743d074536cc0dba8770aaa7d2437a96 ====
