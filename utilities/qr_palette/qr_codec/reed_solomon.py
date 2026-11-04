# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/reed_solomon.py
# About: Reed-Solomon: error-correction codewords for the encoder, and corrections for the decoder.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Reed-Solomon: error-correction codewords for the encoder, and corrections for the decoder.

A block is a list of codewords, highest power first. The generator's roots are alpha**0 ..
alpha**(degree-1). rs_correct finds the errors with Berlekamp-Massey, a Chien search and Forney's
formula, then checks the syndromes again, so a wrong correction is refused rather than returned.

The idea (ISO/IEC 18004 section 7.5): treat a block of n codewords as a polynomial over GF(256)
(gf.py), the first codeword the coefficient of x^(n-1). The encoder appends the remainder of
data * x^degree divided by the generator, which makes the whole block a multiple of the generator, so
it is zero at each of the generator's roots. A reader evaluates the block at those roots (the
syndromes): all zero means no error; otherwise the syndromes carry enough to find and fix up to
degree // 2 wrong codewords.

Callers: blocks.py (rs_remainder, when encoding), decode.py (rs_correct, per block) and the tests,
through the package's re-exports.

Start reading at rs_remainder, then rs_correct.
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
    """The ec_count syndromes of a block: the block, read as a polynomial, evaluated at alpha**0 ..
    alpha**(ec_count-1).

    Each value is computed by Horner's rule (multiply the running value by x, add the next codeword),
    highest power first. A block that left the encoder intact gives all zeros, because those points
    are the generator's roots.
    """
    syndromes = []
    for i in range(ec_count):
        value = 0
        x = alpha_power(i)
        for byte in block:
            value = gf_mul(value, x) ^ byte
        syndromes.append(value)
    return syndromes


def all_zero(values):
    """True when every item of values is 0 (and for an empty list)."""
    for value in values:
        if value != 0:
            return False
    return True


def rs_correct(block, ec_count):
    """Fix up to ec_count // 2 wrong codewords -> Result {"block": [int], "errors": int}.

    block is the whole block, data then error-correction codewords; ec_count is how many of the latter
    it has. "errors" counts the codewords changed. Fails with "too many errors" when the damage is
    beyond repair or the repair does not check out. The input list is not changed.

    Steps:
    1. Syndromes: all zero means nothing to fix.
    2. Berlekamp-Massey builds the shortest error-locator polynomial whose roots mark the wrong
       positions, one syndrome at a time; more than ec_count // 2 errors cannot be located.
    3. Chien search tries every position: a root at alpha**-e means the codeword at power e (counted
       from the block's end) is wrong. The roots found must match the locator's degree.
    4. Forney's formula gives each error's value from the error evaluator (syndromes times locator,
       cut to ec_count terms) and the locator's formal derivative (in GF(2^8) only the odd terms
       survive differentiation). XOR the value into the codeword.
    5. Recompute the syndromes; anything but zeros means the block was beyond repair.
    """
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=a51a52693f94ac1af915142824cb11a389e3f0f28f89fde5d0d18454b877810e ====
