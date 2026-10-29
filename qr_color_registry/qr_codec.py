# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/qr_codec.py
# About: QR Palette codec: QR Studio's QR encoder and decoder, with colored output.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette codec: QR Studio's QR encoder and decoder, with colored output.

Standard library only (struct and zlib; random for the test helpers). Copied from QR Studio's CORE
section (see PROVENANCE.md) and extended with two-color PNG and SVG output, reading back this codec's
own SVG drawings, the dark color of a picture, PNG transparency (tRNS), and limits on how much a
picture may cost to read.

Written to be easy to port to another language, like QR Studio: plain functions and plain records,
explicit loops, and failures reported as Result records instead of exceptions across layers.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Image    {"width": int, "height": int, "gray": bytearray, "rgb": bytearray or None}
           one gray byte per pixel, rows from the top, 0 = black; "rgb" has three bytes per pixel
           when the picture was in color, else None
  Matrix   {"size": int, "dark": [[bool]] (row, column), "version": int, "level": str, "mask": int}
  Reading  {"text": str, "version": int, "level": str, "mask": int, "corrected": int,
            "corners": [[x, y]] finder centres top-left, top-right, bottom-left in image pixels}
"""

import os
import random
import struct
import zlib

EC_LEVELS = "LMQH"
FORMAT_LEVEL_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}
ALPHANUMERIC = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
MODE_NUMERIC = 1
MODE_ALPHANUMERIC = 2
MODE_BYTE = 4
MODE_KANJI = 8
MODE_ECI = 7
MODE_APPEND = 3
MODE_FNC1_FIRST = 5
MODE_FNC1_SECOND = 9
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_FILE_BYTES = 20 * 1024 * 1024  # a picture file bigger than this is refused
MAX_SIDE = 4096  # and so is a picture wider or taller than this, before any pixel memory is taken
INK = "#000000"
PAPER = "#ffffff"

# Error-correction codewords per block and number of blocks, by level (L, M, Q, H) then version 1..40.
# Index 0 is unused. From ISO/IEC 18004 table 9.
ECC_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
     28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
     26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30,
     28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28,
     30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
BLOCK_COUNT = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8,
     8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
     17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20,
     23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25,
     25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)



# =================================================================================================
# CORE: no GUI below this line until the GUI section.
# =================================================================================================

def make_result(ok, value, error):
    return {"ok": ok, "value": value, "error": error}


def ok_result(value):
    return make_result(True, value, "")


def fail(error):
    return make_result(False, None, error)


# --- Galois field GF(256), polynomial 0x11D ------------------------------------------------------

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


# --- Reed-Solomon --------------------------------------------------------------------------------

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


# --- Version tables ------------------------------------------------------------------------------

def size_for_version(version):
    return version * 4 + 17


def raw_data_modules(version):
    """Modules left for data and error correction once every function pattern is drawn."""
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result = result - ((25 * count - 10) * count - 55)
        if version >= 7:
            result = result - 36
    return result


def level_index(level):
    return EC_LEVELS.index(level)


def data_codeword_count(version, level):
    index = level_index(level)
    return raw_data_modules(version) // 8 - ECC_PER_BLOCK[index][version] * BLOCK_COUNT[index][version]


def alignment_positions(version):
    if version == 1:
        return []
    count = version // 7 + 2
    if version == 32:
        step = 26
    else:
        step = (version * 4 + count * 2 + 1) // (count * 2 - 2) * 2
    positions = [6]
    position = size_for_version(version) - 7
    for i in range(count - 1):
        positions.insert(1, position)
        position = position - step
    return positions


def format_bits(level, mask):
    data = (FORMAT_LEVEL_BITS[level] << 3) | mask
    remainder = data
    for i in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def version_bits(version):
    remainder = version
    for i in range(12):
        remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
    return (version << 12) | remainder


def format_positions(size):
    """Where the 15 format bits go: two copies, each a list of (x, y) for bit 0..14."""
    first = []
    for i in range(6):
        first.append((8, i))
    first.append((8, 7))
    first.append((8, 8))
    first.append((7, 8))
    for i in range(9, 15):
        first.append((14 - i, 8))
    second = []
    for i in range(8):
        second.append((size - 1 - i, 8))
    for i in range(8, 15):
        second.append((8, size - 15 + i))
    return [first, second]


def version_positions(size):
    """Where the 18 version bits go (versions 7 and up): two copies of (x, y) for bit 0..17."""
    first = []
    second = []
    for i in range(18):
        first.append((size - 11 + i % 3, i // 3))
        second.append((i // 3, size - 11 + i % 3))
    return [first, second]


def bit_of(value, index):
    return (value >> index) & 1 == 1


def blank_grid(size, value):
    grid = []
    for y in range(size):
        grid.append([value] * size)
    return grid


def set_function(modules, function, x, y, dark):
    modules[y][x] = dark
    function[y][x] = True


def draw_finder(modules, function, cx, cy):
    size = len(modules)
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            x = cx + dx
            y = cy + dy
            if 0 <= x < size and 0 <= y < size:
                distance = max(abs(dx), abs(dy))
                set_function(modules, function, x, y, distance != 2 and distance != 4)


def draw_alignment(modules, function, cx, cy):
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            set_function(modules, function, cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)


def draw_format(modules, function, bits):
    size = len(modules)
    copies = format_positions(size)
    for copy in copies:
        for i in range(15):
            x, y = copy[i]
            set_function(modules, function, x, y, bit_of(bits, i))
    set_function(modules, function, 8, size - 8, True)


def draw_version(modules, function, version):
    if version < 7:
        return
    bits = version_bits(version)
    copies = version_positions(len(modules))
    for copy in copies:
        for i in range(18):
            x, y = copy[i]
            set_function(modules, function, x, y, bit_of(bits, i))


def function_patterns(version):
    """(modules, function): the grid with every function pattern drawn, and which modules they own."""
    size = size_for_version(version)
    modules = blank_grid(size, False)
    function = blank_grid(size, False)
    for i in range(size):
        set_function(modules, function, 6, i, i % 2 == 0)
        set_function(modules, function, i, 6, i % 2 == 0)
    draw_finder(modules, function, 3, 3)
    draw_finder(modules, function, size - 4, 3)
    draw_finder(modules, function, 3, size - 4)
    positions = alignment_positions(version)
    count = len(positions)
    for i in range(count):
        for j in range(count):
            corner = (i == 0 and j == 0) or (i == 0 and j == count - 1) or (i == count - 1 and j == 0)
            if not corner:
                draw_alignment(modules, function, positions[i], positions[j])
    draw_format(modules, function, 0)
    draw_version(modules, function, version)
    return modules, function


def data_positions(function):
    """Data modules in reading order: two-column zigzag from the bottom right, skipping column 6."""
    size = len(function)
    order = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for step in range(size):
            if upward:
                y = size - 1 - step
            else:
                y = step
            for j in range(2):
                x = right - j
                if not function[y][x]:
                    order.append((x, y))
        right = right - 2
    return order


def mask_applies(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


# --- Blocks --------------------------------------------------------------------------------------

def block_data_lengths(version, level):
    index = level_index(level)
    blocks = BLOCK_COUNT[index][version]
    ecc = ECC_PER_BLOCK[index][version]
    raw = raw_data_modules(version) // 8
    short_count = blocks - raw % blocks
    short_data = raw // blocks - ecc
    lengths = []
    for i in range(blocks):
        if i < short_count:
            lengths.append(short_data)
        else:
            lengths.append(short_data + 1)
    return lengths


def add_error_correction(data, version, level):
    """Data codewords -> every codeword in transmission order (data interleaved, then EC interleaved)."""
    ecc = ECC_PER_BLOCK[level_index(level)][version]
    lengths = block_data_lengths(version, level)
    data_blocks = []
    ec_blocks = []
    start = 0
    for length in lengths:
        block = data[start:start + length]
        data_blocks.append(block)
        ec_blocks.append(rs_remainder(block, ecc))
        start = start + length
    result = []
    longest = lengths[len(lengths) - 1]
    for i in range(longest):
        for block in data_blocks:
            if i < len(block):
                result.append(block[i])
    for i in range(ecc):
        for block in ec_blocks:
            result.append(block[i])
    return result


def split_blocks(codewords, version, level):
    """Inverse of add_error_correction -> list of blocks, each data then EC codewords."""
    ecc = ECC_PER_BLOCK[level_index(level)][version]
    lengths = block_data_lengths(version, level)
    blocks = []
    for length in lengths:
        blocks.append([])
    position = 0
    longest = lengths[len(lengths) - 1]
    for i in range(longest):
        for b in range(len(lengths)):
            if i < lengths[b]:
                blocks[b].append(codewords[position])
                position = position + 1
    for i in range(ecc):
        for b in range(len(lengths)):
            blocks[b].append(codewords[position])
            position = position + 1
    return blocks


# --- Encoder -------------------------------------------------------------------------------------

def append_bits(bits, value, length):
    index = length - 1
    while index >= 0:
        bits.append((value >> index) & 1)
        index = index - 1


def count_bits(mode, version):
    if version <= 9:
        column = 0
    elif version <= 26:
        column = 1
    else:
        column = 2
    if mode == MODE_NUMERIC:
        return (10, 12, 14)[column]
    if mode == MODE_ALPHANUMERIC:
        return (9, 11, 13)[column]
    if mode == MODE_KANJI:
        return (8, 10, 12)[column]
    return (8, 16, 16)[column]


def choose_mode(text):
    if text == "":
        return MODE_BYTE
    numeric = True
    alphanumeric = True
    for character in text:
        if character < "0" or character > "9":
            numeric = False
        if ALPHANUMERIC.find(character) < 0:
            alphanumeric = False
    if numeric:
        return MODE_NUMERIC
    if alphanumeric:
        return MODE_ALPHANUMERIC
    return MODE_BYTE


def payload_bits(text, mode):
    """(bits, character count) for one segment of `text` in `mode`."""
    bits = []
    if mode == MODE_NUMERIC:
        index = 0
        while index < len(text):
            group = text[index:index + 3]
            append_bits(bits, int(group), len(group) * 3 + 1)
            index = index + 3
        return bits, len(text)
    if mode == MODE_ALPHANUMERIC:
        index = 0
        while index + 1 < len(text):
            value = ALPHANUMERIC.index(text[index]) * 45 + ALPHANUMERIC.index(text[index + 1])
            append_bits(bits, value, 11)
            index = index + 2
        if index < len(text):
            append_bits(bits, ALPHANUMERIC.index(text[index]), 6)
        return bits, len(text)
    data = text.encode("utf-8")
    for byte in data:
        append_bits(bits, byte, 8)
    return bits, len(data)


def penalty_score(dark):
    """ISO 18004 mask penalty: long runs, 2x2 blocks, finder-like patterns, dark/light balance."""
    size = len(dark)
    score = 0
    finder_like = (True, False, True, True, True, False, True, False, False, False, False)
    lines = []
    for y in range(size):
        lines.append(dark[y])
    for x in range(size):
        column = []
        for y in range(size):
            column.append(dark[y][x])
        lines.append(column)
    for line in lines:
        run = 1
        for i in range(1, size + 1):
            if i < size and line[i] == line[i - 1]:
                run = run + 1
            else:
                if run >= 5:
                    score = score + 3 + (run - 5)
                run = 1
        padded = [False] * 4 + list(line) + [False] * 4
        for start in range(len(padded) - 10):
            forward = True
            backward = True
            for k in range(11):
                if padded[start + k] != finder_like[k]:
                    forward = False
                if padded[start + k] != finder_like[10 - k]:
                    backward = False
            if forward:
                score = score + 40
            if backward:
                score = score + 40
    dark_count = 0
    for y in range(size):
        for x in range(size):
            if dark[y][x]:
                dark_count = dark_count + 1
            if x + 1 < size and y + 1 < size:
                colour = dark[y][x]
                if dark[y][x + 1] == colour and dark[y + 1][x] == colour and dark[y + 1][x + 1] == colour:
                    score = score + 3
    total = size * size
    score = score + 10 * (abs(dark_count * 100 - total * 50) // (total * 5))
    return score


def encode_text(text, level, min_version, mask):
    """Text -> Result Matrix. mask -1 picks the best of the eight; min_version 1 picks the smallest."""
    if level not in FORMAT_LEVEL_BITS:
        return fail("level must be L, M, Q or H")
    mode = choose_mode(text)
    bits_of_text, count = payload_bits(text, mode)
    version = max(1, min_version)
    found = False
    while version <= 40:
        width = count_bits(mode, version)
        needed = 4 + width + len(bits_of_text)
        if count < (1 << width) and needed <= data_codeword_count(version, level) * 8:
            found = True
            break
        version = version + 1
    if not found:
        return fail("text is too long for a QR code at level " + level)

    capacity = data_codeword_count(version, level) * 8
    bits = []
    append_bits(bits, mode, 4)
    append_bits(bits, count, count_bits(mode, version))
    bits.extend(bits_of_text)
    append_bits(bits, 0, min(4, capacity - len(bits)))
    append_bits(bits, 0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        append_bits(bits, pad, 8)
        pad = pad ^ 0xEC ^ 0x11
    data = []
    for i in range(0, len(bits), 8):
        value = 0
        for k in range(8):
            value = (value << 1) | bits[i + k]
        data.append(value)
    codewords = add_error_correction(data, version, level)

    base, function = function_patterns(version)
    positions = data_positions(function)
    for i in range(len(positions)):
        x, y = positions[i]
        if i < len(codewords) * 8:
            base[y][x] = bit_of(codewords[i >> 3], 7 - (i & 7))

    masks = [mask]
    if mask < 0:
        masks = [0, 1, 2, 3, 4, 5, 6, 7]
    best = None
    best_score = -1
    for candidate in masks:
        grid = []
        for row in base:
            grid.append(list(row))
        for x, y in positions:
            if mask_applies(candidate, x, y):
                grid[y][x] = not grid[y][x]
        draw_format(grid, blank_grid(len(grid), False), format_bits(level, candidate))
        score = penalty_score(grid)
        if best is None or score < best_score:
            best = {"size": len(grid), "dark": grid, "version": version, "level": level, "mask": candidate}
            best_score = score
    return ok_result(best)


# --- Decoder (matrix -> text) --------------------------------------------------------------------

def hamming(a, b):
    value = a ^ b
    count = 0
    while value:
        count = count + (value & 1)
        value = value >> 1
    return count


def read_bits(dark, positions):
    value = 0
    for i in range(len(positions)):
        x, y = positions[i]
        if dark[y][x]:
            value = value | (1 << i)
    return value


def read_format(dark):
    """-> Result (level, mask) from the closer of the two format copies."""
    best = None
    best_distance = 99
    for copy in format_positions(len(dark)):
        found = read_bits(dark, copy)
        for level in EC_LEVELS:
            for mask in range(8):
                distance = hamming(found, format_bits(level, mask))
                if distance < best_distance:
                    best = (level, mask)
                    best_distance = distance
    if best_distance > 3:
        return fail("format information is unreadable")
    return ok_result(best)


def read_version(dark):
    size = len(dark)
    version = (size - 17) // 4
    if version < 7:
        return ok_result(version)
    best = 0
    best_distance = 99
    for copy in version_positions(size):
        found = read_bits(dark, copy)
        for candidate in range(7, 41):
            distance = hamming(found, version_bits(candidate))
            if distance < best_distance:
                best = candidate
                best_distance = distance
    if best_distance > 3:
        return fail("version information is unreadable")
    return ok_result(best)


class BitReader:
    def __init__(self, data):
        self.data = data
        self.position = 0

    def remaining(self):
        return len(self.data) * 8 - self.position

    def read(self, count):
        """Next `count` bits as an int, or -1 when there are not enough."""
        if count > self.remaining():
            return -1
        value = 0
        for i in range(count):
            byte = self.data[self.position >> 3]
            value = (value << 1) | ((byte >> (7 - (self.position & 7))) & 1)
            self.position = self.position + 1
        return value


ECI_CODECS = {1: "latin-1", 3: "latin-1", 4: "iso8859-2", 5: "iso8859-3", 6: "iso8859-4", 7: "iso8859-5",
              8: "iso8859-6", 9: "iso8859-7", 10: "iso8859-8", 11: "iso8859-9", 20: "shift_jis",
              21: "cp1250", 22: "cp1251", 23: "cp1252", 24: "cp1256", 25: "utf-16-be", 26: "utf-8",
              27: "ascii", 28: "big5", 29: "gb18030", 30: "euc_kr"}


def decode_bytes(data, codec):
    if codec != "":
        try:
            return data.decode(codec)
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_segments(data, version):
    """Data codewords -> Result text."""
    reader = BitReader(data)
    text = ""
    codec = ""
    while reader.remaining() >= 4:
        mode = reader.read(4)
        if mode == 0:
            break
        if mode == MODE_ECI:
            first = reader.read(8)
            if first < 0:
                return fail("data ends inside an ECI marker")
            if first & 0x80 == 0:
                designator = first
            elif first & 0xC0 == 0x80:
                designator = ((first & 0x3F) << 8) | reader.read(8)
            else:
                designator = ((first & 0x1F) << 16) | reader.read(16)
            codec = ECI_CODECS.get(designator, "")
            continue
        if mode == MODE_APPEND:
            if reader.read(16) < 0:
                return fail("data ends inside a structured-append header")
            continue
        if mode == MODE_FNC1_FIRST:
            continue
        if mode == MODE_FNC1_SECOND:
            reader.read(8)
            continue
        if mode not in (MODE_NUMERIC, MODE_ALPHANUMERIC, MODE_BYTE, MODE_KANJI):
            return fail("unknown data mode " + str(mode))
        count = reader.read(count_bits(mode, version))
        if count < 0:
            return fail("data ends inside a segment header")
        if mode == MODE_NUMERIC:
            while count > 0:
                digits = min(3, count)
                value = reader.read(digits * 3 + 1)
                if value < 0 or value >= 10 ** digits:
                    return fail("bad numeric data")
                text = text + str(value).zfill(digits)
                count = count - digits
        elif mode == MODE_ALPHANUMERIC:
            while count >= 2:
                value = reader.read(11)
                if value < 0 or value >= 45 * 45:
                    return fail("bad alphanumeric data")
                text = text + ALPHANUMERIC[value // 45] + ALPHANUMERIC[value % 45]
                count = count - 2
            if count == 1:
                value = reader.read(6)
                if value < 0 or value >= 45:
                    return fail("bad alphanumeric data")
                text = text + ALPHANUMERIC[value]
        elif mode == MODE_BYTE:
            raw = bytearray()
            for i in range(count):
                value = reader.read(8)
                if value < 0:
                    return fail("data ends inside a byte segment")
                raw.append(value)
            text = text + decode_bytes(bytes(raw), codec)
        else:
            raw = bytearray()
            for i in range(count):
                value = reader.read(13)
                if value < 0:
                    return fail("data ends inside a kanji segment")
                code = ((value // 0xC0) << 8) | (value % 0xC0)
                if code < 0x1F00:
                    code = code + 0x8140
                else:
                    code = code + 0xC140
                raw.append(code >> 8)
                raw.append(code & 0xFF)
            text = text + decode_bytes(bytes(raw), "shift_jis")
    return ok_result(text)


def decode_matrix(dark):
    """Grid of modules (row, column) -> Result {"text", "version", "level", "mask", "corrected"}."""
    size = len(dark)
    if size < 21 or size > 177 or (size - 17) % 4 != 0:
        return fail("not a QR code size")
    format_read = read_format(dark)
    if not format_read["ok"]:
        return format_read
    level, mask = format_read["value"]
    version_read = read_version(dark)
    if not version_read["ok"]:
        return version_read
    version = version_read["value"]
    if size_for_version(version) != size:
        return fail("version does not match the size")
    base, function = function_patterns(version)
    positions = data_positions(function)
    codewords = []
    value = 0
    count = raw_data_modules(version) // 8 * 8
    for i in range(count):
        x, y = positions[i]
        bit = dark[y][x]
        if mask_applies(mask, x, y):
            bit = not bit
        value = (value << 1) | (1 if bit else 0)
        if i % 8 == 7:
            codewords.append(value)
            value = 0
    ecc = ECC_PER_BLOCK[level_index(level)][version]
    data = []
    corrected = 0
    for block in split_blocks(codewords, version, level):
        fixed = rs_correct(block, ecc)
        if not fixed["ok"]:
            return fail("too many damaged modules to correct")
        corrected = corrected + fixed["value"]["errors"]
        data.extend(fixed["value"]["block"][:len(block) - ecc])
    parsed = parse_segments(bytes(data), version)
    if not parsed["ok"]:
        return parsed
    return ok_result({"text": parsed["value"], "version": version, "level": level, "mask": mask,
                      "corrected": corrected})


def transpose(dark):
    size = len(dark)
    result = blank_grid(size, False)
    for y in range(size):
        for x in range(size):
            result[x][y] = dark[y][x]
    return result


# --- Images --------------------------------------------------------------------------------------

def make_image(width, height, fill):
    return {"width": width, "height": height, "gray": bytearray([fill]) * (width * height), "rgb": None}


def matrix_to_image(matrix, scale, border):
    """A black-on-white picture of the matrix, `scale` pixels per module, `border` modules of quiet zone."""
    size = matrix["size"]
    side = (size + 2 * border) * scale
    image = make_image(side, side, 255)
    gray = image["gray"]
    for y in range(size):
        for x in range(size):
            if matrix["dark"][y][x]:
                top = (y + border) * scale
                left = (x + border) * scale
                for row in range(top, top + scale):
                    start = row * side + left
                    gray[start:start + scale] = bytes(scale)
    return image


# --- Captions: text printed under a code (a short link to type when a camera cannot scan it) --------

# A 5 x 7 pixel font drawn for this program: capitals, digits and the other characters of an address.
GLYPHS = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "/": (".....", "....#", "...#.", "..#..", ".#...", "#....", "....."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
}
SVG_GRID = 16  # font pixels in a drawing are laid out in sixteenths of a module


def caption_layout(text, width, scale):
    """How a caption fits under a code `width` pixels wide at `scale` pixels per module -> (lines,
    pixel). Font pixels are at most half a module. It is one line while that allows a quarter of a
    module per font pixel, else two lines split after the last "/". Never less than 1 pixel."""
    usable = width - 2 * scale
    largest = max(1, scale // 2)
    smallest = max(1, scale // 4)

    def fit(lines):
        longest = 0
        for line in lines:
            longest = max(longest, len(line))
        return min(largest, usable // max(1, 6 * longest - 1))

    lines = [text]
    pixel = fit(lines)
    if pixel < smallest and "/" in text.rstrip("/"):
        cut = text.rstrip("/").rindex("/") + 1
        lines = [text[:cut], text[cut:]]
        pixel = fit(lines)
    return lines, max(1, pixel)


def caption_size(lines, pixel, scale):
    """(width, height) in pixels of a caption: lines of 7 font pixels, 2 between them, and one module
    of margin below."""
    longest = 0
    for line in lines:
        longest = max(longest, len(line))
    return (6 * longest - 1) * pixel, len(lines) * 7 * pixel + (len(lines) - 1) * 2 * pixel + scale


def caption_pixels(lines, pixel, width, top):
    """The top-left corner of every font pixel of a caption, each line centred in `width`."""
    corners = []
    for index in range(len(lines)):
        line = lines[index]
        left = (width - (6 * len(line) - 1) * pixel) // 2
        line_top = top + index * 9 * pixel
        for place in range(len(line)):
            glyph = GLYPHS.get(line[place], GLYPHS[" "])
            for row in range(7):
                for column in range(5):
                    if glyph[row][column] == "#":
                        corners.append((left + (6 * place + column) * pixel, line_top + row * pixel))
    return corners


def svg_number(value):
    """A coordinate for a drawing, as short as it can be: 2.5, 3, 0.3125."""
    text = "%.4f" % value
    return text.rstrip("0").rstrip(".")


def matrix_to_svg(matrix, border, color=INK, caption=""):
    """The matrix as an SVG drawing: one path of unit squares in `color` ("#rrggbb") on white. A
    caption is drawn below the quiet zone as a second path (and repeated as the drawing's <desc>),
    which makes the drawing taller."""
    size = matrix["size"]
    side = size + 2 * border
    height = side
    caption_parts = []
    if caption != "":
        lines, pixel = caption_layout(caption, side * SVG_GRID, SVG_GRID)
        band = caption_size(lines, pixel, SVG_GRID)[1]
        height = side + (band + SVG_GRID - 1) // SVG_GRID
        step = svg_number(pixel / SVG_GRID)
        for corner in caption_pixels(lines, pixel, side * SVG_GRID, side * SVG_GRID):
            caption_parts.append("M" + svg_number(corner[0] / SVG_GRID) + "," + svg_number(corner[1] / SVG_GRID) +
                                 "h" + step + "v" + step + "h-" + step + "z")
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + str(side) + " " + str(height) +
             '" shape-rendering="crispEdges">\n<rect width="100%" height="100%" fill="' + PAPER + '"/>\n<path d="']
    for y in range(size):
        for x in range(size):
            if matrix["dark"][y][x]:
                parts.append("M" + str(x + border) + "," + str(y + border) + "h1v1h-1z")
    parts.append('" fill="' + color + '"/>\n')
    if caption != "":
        parts.append('<path d="' + "".join(caption_parts) + '" fill="' + color + '"/>\n<desc>' +
                     caption.replace("&", "&amp;").replace("<", "&lt;") + "</desc>\n")
    parts.append("</svg>\n")
    return "".join(parts)


def read_svg_matrix(text):
    """An SVG drawing made by matrix_to_svg -> Result module grid (dark[row][column]), ready for
    decode_matrix. Other SVG drawings are refused: this reads squares, it does not draw vectors. The
    code is the first path; a caption below it makes the drawing taller, never wider."""
    if len(text) > MAX_FILE_BYTES:
        return fail("this drawing is too big")
    start = text.find('viewBox="0 0 ')
    begin = text.find('<path d="')
    if start < 0 or begin < 0:
        return fail("not a QR drawing made by this program")
    numbers = text[start + 13:text.find('"', start + 13)].split(" ")
    if len(numbers) != 2 or not numbers[0].isdigit() or not numbers[1].isdigit() or int(numbers[1]) < int(numbers[0]):
        return fail("not a QR drawing made by this program")
    side = int(numbers[0])
    if side < 21 or side > 177 + 2 * 40:
        return fail("not a QR drawing made by this program")
    end = text.find('"', begin + 9)
    squares = text[begin + 9:end].split("z")
    points = []
    low = side
    for square in squares:
        if square == "":
            continue
        if not square.startswith("M") or not square.endswith("h1v1h-1"):
            return fail("not a QR drawing made by this program")
        pair = square[1:len(square) - 7].split(",")
        if len(pair) != 2 or not pair[0].isdigit() or not pair[1].isdigit():
            return fail("not a QR drawing made by this program")
        x = int(pair[0])
        y = int(pair[1])
        if x >= side or y >= side:
            return fail("not a QR drawing made by this program")
        points.append((x, y))
        if x < low:
            low = x
        if y < low:
            low = y
    if len(points) == 0:
        return fail("the drawing has no squares")
    size = side - 2 * low
    if size < 21 or (size - 17) % 4 != 0:
        return fail("not a QR drawing made by this program")
    dark = blank_grid(size, False)
    for point in points:
        column = point[0] - low
        row = point[1] - low
        if column < 0 or row < 0 or column >= size or row >= size:
            return fail("not a QR drawing made by this program")
        dark[row][column] = True
    return ok_result(dark)


def png_chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def write_png(image):
    """Image -> PNG bytes (8-bit grayscale)."""
    width = image["width"]
    rows = bytearray()
    for y in range(image["height"]):
        rows.append(0)
        rows.extend(image["gray"][y * width:(y + 1) * width])
    header = struct.pack(">IIBBBBB", width, image["height"], 8, 0, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
            png_chunk(b"IEND", b""))


def matrix_to_color_png(matrix, scale, border, color, caption=""):
    """The matrix as PNG bytes in two colors: `color` ("#rrggbb") modules on white. A palette PNG
    (colour type 3, 8 bits) whose entry 0 is white and entry 1 is the color. A caption is drawn
    below the quiet zone in the same color; the picture grows taller (and wider, only if it must)."""
    size = matrix["size"]
    side = (size + 2 * border) * scale
    width = side
    height = side
    lines = []
    pixel = 1
    if caption != "":
        lines, pixel = caption_layout(caption, side, scale)
        band = caption_size(lines, pixel, scale)
        width = max(side, band[0] + 2 * scale)
        height = side + band[1]
    canvas = bytearray(width * height)
    left = (width - side) // 2
    for module_y in range(size):
        for module_x in range(size):
            if matrix["dark"][module_y][module_x]:
                x = left + (module_x + border) * scale
                for y in range((module_y + border) * scale, (module_y + border + 1) * scale):
                    canvas[y * width + x:y * width + x + scale] = b"\x01" * scale
    for corner in caption_pixels(lines, pixel, width, side):
        for y in range(corner[1], corner[1] + pixel):
            canvas[y * width + corner[0]:y * width + corner[0] + pixel] = b"\x01" * pixel
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(canvas[y * width:(y + 1) * width])
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    entries = bytes([255, 255, 255, int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)])
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"PLTE", entries) +
            png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + png_chunk(b"IEND", b""))


def paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def unfilter_row(kind, row, previous, step):
    if kind == 0:
        return row
    if kind == 2:
        for i in range(len(row)):
            row[i] = (row[i] + previous[i]) & 0xFF
        return row
    for i in range(len(row)):
        if i >= step:
            left = row[i - step]
        else:
            left = 0
        if kind == 1:
            row[i] = (row[i] + left) & 0xFF
        elif kind == 3:
            row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:
            if i >= step:
                upper_left = previous[i - step]
            else:
                upper_left = 0
            row[i] = (row[i] + paeth(left, previous[i], upper_left)) & 0xFF
    return row


def read_png(data):
    """PNG bytes -> Result Image. Transparent pixels (an alpha channel or a tRNS chunk) are laid over
    white. Pictures in color also keep their colors ("rgb"). Pictures wider or taller than MAX_SIDE
    are refused before any pixel memory is taken, and so is image data that unpacks to more than it
    should."""
    if data[:8] != PNG_SIGNATURE:
        return fail("not a PNG file")
    position = 8
    header = None
    palette = b""
    transparency = b""
    compressed = bytearray()
    while position + 8 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position = position + 12 + length
        if kind == b"IHDR":
            if len(body) != 13:
                return fail("PNG header is damaged")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if header is None:
        return fail("PNG has no header")
    width, height, depth, colour, compression, filtering, interlace = header
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        return fail("the picture is too big (largest side " + str(MAX_SIDE) + " pixels)")
    if interlace != 0:
        return fail("interlaced PNG is not supported; save it without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour, 0)
    if channels == 0 or depth not in (1, 2, 4, 8, 16) or (depth < 8 and colour not in (0, 3)):
        return fail("unsupported PNG colour type")
    bits_per_pixel = channels * depth
    stride = (width * bits_per_pixel + 7) // 8
    step = max(1, bits_per_pixel // 8)
    expected = height * (stride + 1)
    try:
        unpacker = zlib.decompressobj()
        raw = unpacker.decompress(bytes(compressed), expected + 1)
    except zlib.error:
        return fail("PNG data is damaged")
    if len(raw) > expected or len(unpacker.unconsumed_tail) > 0:
        return fail("PNG data is larger than its picture")
    if len(raw) < expected:
        return fail("PNG data is cut short")
    image = make_image(width, height, 255)
    gray = image["gray"]
    rgb = None
    if colour in (2, 3, 6):
        rgb = bytearray(b"\xff") * (3 * width * height)
        image["rgb"] = rgb
    key = transparent_key(colour, depth, transparency)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        kind = raw[offset]
        if kind > 4:
            return fail("PNG data is damaged")
        row = unfilter_row(kind, bytearray(raw[offset + 1:offset + 1 + stride]), previous, step)
        offset = offset + 1 + stride
        previous = row
        if depth == 16:
            row = row[0::2]
        out = y * width
        if depth < 8:
            per_byte = 8 // depth
            top = (1 << depth) - 1
            for x in range(width):
                sample = (row[x // per_byte] >> (8 - depth * (x % per_byte + 1))) & top
                if colour == 3:
                    put_palette(image, out + x, palette, transparency, sample)
                elif sample == key:
                    gray[out + x] = 255
                else:
                    gray[out + x] = sample * 255 // top
        elif colour == 0:
            for x in range(width):
                if row[x] == key:
                    gray[out + x] = 255
                else:
                    gray[out + x] = row[x]
        elif colour == 3:
            for x in range(width):
                put_palette(image, out + x, palette, transparency, row[x])
        elif colour == 4:
            for x in range(width):
                gray[out + x] = over_white(row[2 * x], row[2 * x + 1])
        elif colour == 2:
            for x in range(width):
                i = 3 * x
                if key >= 0 and (row[i] << 16 | row[i + 1] << 8 | row[i + 2]) == key:
                    continue
                gray[out + x] = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                rgb[3 * (out + x):3 * (out + x) + 3] = row[i:i + 3]
        else:
            for x in range(width):
                i = 4 * x
                value = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                gray[out + x] = over_white(value, row[i + 3])
                j = 3 * (out + x)
                rgb[j] = over_white(row[i], row[i + 3])
                rgb[j + 1] = over_white(row[i + 1], row[i + 3])
                rgb[j + 2] = over_white(row[i + 2], row[i + 3])
    return ok_result(image)


def transparent_key(colour, depth, transparency):
    """The one sample value a tRNS chunk makes transparent in a gray (0) or RGB (2) picture, or -1.
    16-bit pictures are read by their high bytes, so their key is compared the same way."""
    if colour == 0 and len(transparency) >= 2:
        value = struct.unpack(">H", transparency[0:2])[0]
        if depth == 16:
            return value >> 8
        return value
    if colour == 2 and len(transparency) >= 6:
        red, green, blue = struct.unpack(">HHH", transparency[0:6])
        if depth == 16:
            red, green, blue = red >> 8, green >> 8, blue >> 8
        return red << 16 | green << 8 | blue
    return -1


def put_palette(image, index, palette, transparency, entry):
    """One palette pixel into the gray and rgb planes, laid over white by its tRNS alpha."""
    i = entry * 3
    if i + 2 >= len(palette):
        image["gray"][index] = 255
        return
    alpha = 255
    if entry < len(transparency):
        alpha = transparency[entry]
    red = over_white(palette[i], alpha)
    green = over_white(palette[i + 1], alpha)
    blue = over_white(palette[i + 2], alpha)
    image["gray"][index] = (red * 299 + green * 587 + blue * 114) // 1000
    if image["rgb"] is not None:
        image["rgb"][3 * index] = red
        image["rgb"][3 * index + 1] = green
        image["rgb"][3 * index + 2] = blue


def palette_gray(palette, index):
    i = index * 3
    if i + 2 >= len(palette):
        return 255
    return (palette[i] * 299 + palette[i + 1] * 587 + palette[i + 2] * 114) // 1000


def over_white(value, alpha):
    return (value * alpha + 255 * (255 - alpha)) // 255


def read_ppm(data):
    """Binary PGM (P5) or PPM (P6) bytes, 8-bit -> Result Image."""
    fields = []
    position = 0
    while len(fields) < 4 and position < len(data):
        while position < len(data) and data[position:position + 1].isspace():
            position = position + 1
        if data[position:position + 1] == b"#":
            while position < len(data) and data[position:position + 1] != b"\n":
                position = position + 1
            continue
        start = position
        while position < len(data) and not data[position:position + 1].isspace():
            position = position + 1
        fields.append(data[start:position])
    if len(fields) < 4 or fields[0] not in (b"P5", b"P6"):
        return fail("not a binary PGM/PPM file")
    if not fields[1].isdigit() or not fields[2].isdigit() or not fields[3].isdigit():
        return fail("not a binary PGM/PPM file")
    width = int(fields[1])
    height = int(fields[2])
    if int(fields[3]) != 255:
        return fail("only 8-bit PGM/PPM is supported")
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        return fail("the picture is too big (largest side " + str(MAX_SIDE) + " pixels)")
    pixels = data[position + 1:]
    channels = 1
    if fields[0] == b"P6":
        channels = 3
    if len(pixels) < width * height * channels:
        return fail("PGM/PPM data is cut short")
    image = make_image(width, height, 255)
    if fields[0] == b"P5":
        image["gray"][:] = pixels[:width * height]
        return ok_result(image)
    gray = image["gray"]
    image["rgb"] = bytearray(pixels[:3 * width * height])
    for i in range(width * height):
        j = 3 * i
        gray[i] = (pixels[j] * 299 + pixels[j + 1] * 587 + pixels[j + 2] * 114) // 1000
    return ok_result(image)


def read_image_bytes(data):
    """PNG, PGM or PPM bytes -> Result Image. A damaged file is a failed Result, never an exception."""
    if len(data) > MAX_FILE_BYTES:
        return fail("the picture file is too big")
    try:
        if data[:8] == PNG_SIGNATURE:
            return read_png(data)
        if data[:2] in (b"P5", b"P6"):
            return read_ppm(data)
    except Exception as error:
        return fail("the picture is damaged (" + type(error).__name__ + ")")
    return fail("use a PNG picture (other formats open through the window)")


def load_image_file(path):
    """A picture file -> Result Image. Files over MAX_FILE_BYTES are refused before they are read."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return fail("the picture file is too big")
        handle = open(path, "rb")
        data = handle.read(MAX_FILE_BYTES + 1)
        handle.close()
    except OSError as error:
        return fail("cannot open " + path + ": " + str(error))
    return read_image_bytes(data)


def shrink_image(image, factor):
    """Every `factor`-th pixel's block averaged into one pixel."""
    width = image["width"] // factor
    height = image["height"] // factor
    result = make_image(width, height, 255)
    source = image["gray"]
    source_width = image["width"]
    area = factor * factor
    for y in range(height):
        for x in range(width):
            total = 0
            for dy in range(factor):
                start = (y * factor + dy) * source_width + x * factor
                total = total + sum(source[start:start + factor])
            result["gray"][y * width + x] = total // area
    return result


# --- Binarizing ----------------------------------------------------------------------------------

def otsu_threshold(gray):
    histogram = [0] * 256
    for value in gray:
        histogram[value] = histogram[value] + 1
    total = len(gray)
    sum_all = 0
    for level in range(256):
        sum_all = sum_all + level * histogram[level]
    sum_background = 0
    weight_background = 0
    best = 127
    best_variance = -1.0
    for level in range(256):
        weight_background = weight_background + histogram[level]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background = sum_background + level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            best = level
    return best


def binarize_global(image):
    """1 = dark, from one threshold for the whole picture."""
    threshold = otsu_threshold(image["gray"])
    bits = bytearray(len(image["gray"]))
    gray = image["gray"]
    for i in range(len(gray)):
        if gray[i] <= threshold:
            bits[i] = 1
    return bits


def binarize_local(image):
    """1 = dark, against the mean of a window around each pixel (copes with shadows and glare).
    Flat areas fall back to the global threshold so a large module is not split."""
    width = image["width"]
    height = image["height"]
    gray = image["gray"]
    radius = max(8, max(width, height) // 12)
    threshold = otsu_threshold(gray)
    integral = [0] * ((width + 1) * (height + 1))
    for y in range(height):
        running = 0
        row = y * width
        above = y * (width + 1)
        here = (y + 1) * (width + 1)
        for x in range(width):
            running = running + gray[row + x]
            integral[here + x + 1] = integral[above + x + 1] + running
    bits = bytearray(width * height)
    for y in range(height):
        top = max(0, y - radius)
        bottom = min(height, y + radius + 1)
        for x in range(width):
            left = max(0, x - radius)
            right = min(width, x + radius + 1)
            total = (integral[bottom * (width + 1) + right] - integral[top * (width + 1) + right] -
                     integral[bottom * (width + 1) + left] + integral[top * (width + 1) + left])
            mean = total / ((bottom - top) * (right - left))
            value = gray[y * width + x]
            if value < mean - 8 or (abs(value - mean) <= 8 and value <= threshold):
                bits[y * width + x] = 1
    return bits


# --- Finding the code ----------------------------------------------------------------------------

def ratio_ok(runs):
    """Five runs dark, light, dark, light, dark in the finder ratio 1:1:3:1:1."""
    total = 0
    for run in runs:
        if run == 0:
            return False
        total = total + run
    if total < 7:
        return False
    module = total / 7.0
    allowed = module * 0.7
    return (abs(runs[0] - module) < allowed and abs(runs[1] - module) < allowed and
            abs(runs[2] - 3 * module) < 3 * allowed and abs(runs[3] - module) < allowed and
            abs(runs[4] - module) < allowed)


def is_dark(bits, width, height, x, y):
    return 0 <= x < width and 0 <= y < height and bits[y * width + x] == 1


def cross_check(bits, width, height, x, y, dx, dy, limit):
    """Runs through dark pixel (x, y) along (dx, dy) -> (centre along the line, total) or None."""
    if not is_dark(bits, width, height, x, y):
        return None
    sides = []
    for direction in (-1, 1):
        counts = [0, 0, 0]
        state = 0
        px = x
        py = y
        if direction == 1:
            px = x + dx
            py = y + dy
        steps = 0
        while 0 <= px < width and 0 <= py < height and steps < limit:
            dark = bits[py * width + px] == 1
            expected = state != 1
            if dark != expected:
                state = state + 1
                if state == 3:
                    break
            counts[state] = counts[state] + 1
            px = px + dx * direction
            py = py + dy * direction
            steps = steps + 1
        if counts[2] == 0:
            return None
        sides.append(counts)
    back = sides[0]
    forward = sides[1]
    runs = [back[2], back[1], back[0] + forward[0], forward[1], forward[2]]
    if not ratio_ok(runs):
        return None
    total = runs[0] + runs[1] + runs[2] + runs[3] + runs[4]
    centre = 1 + (forward[0] - back[0]) / 2.0
    return (centre, total)


def add_candidate(candidates, x, y, module):
    for candidate in candidates:
        if abs(candidate[0] - x) <= module * 2 and abs(candidate[1] - y) <= module * 2:
            count = candidate[3]
            candidate[0] = (candidate[0] * count + x) / (count + 1)
            candidate[1] = (candidate[1] * count + y) / (count + 1)
            candidate[2] = (candidate[2] * count + module) / (count + 1)
            candidate[3] = count + 1
            return
    candidates.append([x, y, module, 1])


def find_finders(bits, width, height):
    """Finder-pattern centres -> list of [x, y, module size, hits], most hits first."""
    candidates = []
    row_step = max(1, height // 400)
    for y in range(0, height, row_step):
        runs = []
        starts = []
        current = bits[y * width]
        length = 0
        start = 0
        for x in range(width + 1):
            if x < width and bits[y * width + x] == current:
                length = length + 1
                continue
            runs.append(length)
            starts.append((start, current))
            if x < width:
                current = bits[y * width + x]
                start = x
                length = 1
        for i in range(len(runs) - 4):
            if starts[i][1] != 1:
                continue
            five = runs[i:i + 5]
            if not ratio_ok(five):
                continue
            total = five[0] + five[1] + five[2] + five[3] + five[4]
            centre_x = starts[i + 2][0] + five[2] / 2.0
            vertical = cross_check(bits, width, height, int(centre_x), y, 0, 1, total * 2)
            if vertical is None:
                continue
            centre_y = y + vertical[0] - 0.5
            horizontal = cross_check(bits, width, height, int(centre_x), int(centre_y), 1, 0, total * 2)
            if horizontal is None:
                continue
            centre_x = int(centre_x) + horizontal[0] - 0.5
            module = (vertical[1] + horizontal[1]) / 14.0
            add_candidate(candidates, centre_x + 0.5, centre_y + 0.5, module)
    ordered = []
    for candidate in candidates:
        ordered.append(candidate)
    ordered.sort(key=candidate_hits, reverse=True)
    return ordered


def candidate_hits(candidate):
    return candidate[3]


def point_distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def order_finders(a, b, c):
    """Three centres -> (top-left, top-right, bottom-left), or None when they don't form an L."""
    ab = point_distance(a, b)
    bc = point_distance(b, c)
    ac = point_distance(a, c)
    if bc >= ab and bc >= ac:
        corner, one, two = a, b, c
    elif ac >= ab:
        corner, one, two = b, a, c
    else:
        corner, one, two = c, a, b
    leg_one = point_distance(corner, one)
    leg_two = point_distance(corner, two)
    if leg_one == 0 or leg_two == 0:
        return None
    if max(leg_one, leg_two) > 1.6 * min(leg_one, leg_two):
        return None
    cross = (one[0] - corner[0]) * (two[1] - corner[1]) - (one[1] - corner[1]) * (two[0] - corner[0])
    cosine = ((one[0] - corner[0]) * (two[0] - corner[0]) + (one[1] - corner[1]) * (two[1] - corner[1]))
    if abs(cosine) / (leg_one * leg_two) > 0.5:
        return None
    if cross < 0:
        one, two = two, one
    return (corner, one, two)


def solve_linear(matrix, values):
    """Gaussian elimination with partial pivoting -> solution list or None."""
    n = len(values)
    rows = []
    for i in range(n):
        rows.append(list(matrix[i]) + [values[i]])
    for column in range(n):
        pivot = column
        for row in range(column + 1, n):
            if abs(rows[row][column]) > abs(rows[pivot][column]):
                pivot = row
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(n):
            if row != column:
                factor = rows[row][column] / rows[column][column]
                for k in range(column, n + 1):
                    rows[row][k] = rows[row][k] - factor * rows[column][k]
    result = []
    for i in range(n):
        result.append(rows[i][n] / rows[i][i])
    return result


def perspective(sources, targets):
    """Homography taking four source points to four target points -> 8 coefficients or None."""
    matrix = []
    values = []
    for i in range(4):
        u, v = sources[i]
        x, y = targets[i]
        matrix.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        values.append(x)
        matrix.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        values.append(y)
    return solve_linear(matrix, values)


def apply_perspective(h, u, v):
    divisor = h[6] * u + h[7] * v + 1.0
    if abs(divisor) < 1e-12:
        return (-1.0, -1.0)
    return ((h[0] * u + h[1] * v + h[2]) / divisor, (h[3] * u + h[4] * v + h[5]) / divisor)


def find_alignment(bits, width, height, guess, across, down, module):
    """Best match for the 5x5 alignment pattern near `guess` -> (x, y) or None.
    Every position with the top score is averaged, so the result sits on the pattern's centre."""
    best_score = 0
    sum_x = 0.0
    sum_y = 0.0
    hits = 0
    reach = int(module * 5)
    step = max(1, int(module / 3))
    for oy in range(-reach, reach + 1, step):
        for ox in range(-reach, reach + 1, step):
            cx = guess[0] + ox
            cy = guess[1] + oy
            score = 0
            for j in range(-2, 3):
                for i in range(-2, 3):
                    x = int(cx + i * across[0] + j * down[0])
                    y = int(cy + i * across[1] + j * down[1])
                    if is_dark(bits, width, height, x, y) == (max(abs(i), abs(j)) != 1):
                        score = score + 1
            if score > best_score:
                best_score = score
                sum_x = 0.0
                sum_y = 0.0
                hits = 0
            if score == best_score:
                sum_x = sum_x + cx
                sum_y = sum_y + cy
                hits = hits + 1
    if best_score < 23 or hits == 0:
        return None
    return (sum_x / hits, sum_y / hits)


def sample_grid(bits, width, height, finders, size):
    """Read a size x size grid of modules from the picture -> grid of bools, or None."""
    top_left, top_right, bottom_left = finders
    span = size - 7.0
    across = ((top_right[0] - top_left[0]) / span, (top_right[1] - top_left[1]) / span)
    down = ((bottom_left[0] - top_left[0]) / span, (bottom_left[1] - top_left[1]) / span)
    sources = [(3.5, 3.5), (size - 3.5, 3.5), (3.5, size - 3.5)]
    targets = [(top_left[0], top_left[1]), (top_right[0], top_right[1]), (bottom_left[0], bottom_left[1])]
    corner = size - 6.5
    if size == 21:
        corner = size - 3.5
    guess = (top_left[0] + (corner - 3.5) * (across[0] + down[0]),
             top_left[1] + (corner - 3.5) * (across[1] + down[1]))
    fourth = guess
    if size > 21:
        module = (abs(across[0]) + abs(across[1]) + abs(down[0]) + abs(down[1])) / 2.0
        found = find_alignment(bits, width, height, guess, across, down, module)
        if found is not None:
            fourth = found
    sources.append((corner, corner))
    targets.append(fourth)
    h = perspective(sources, targets)
    if h is None:
        return None
    grid = blank_grid(size, False)
    for row in range(size):
        for column in range(size):
            x, y = apply_perspective(h, column + 0.5, row + 0.5)
            grid[row][column] = is_dark(bits, width, height, int(x), int(y))
    return grid


def candidate_sizes(finders):
    top_left, top_right, bottom_left = finders
    module = (top_left[2] + top_right[2] + bottom_left[2]) / 3.0
    across = point_distance(top_left, top_right) / module
    down = point_distance(top_left, bottom_left) / module
    estimate = int(round((across + down) / 2.0)) + 7
    remainder = estimate % 4
    if remainder == 0:
        estimate = estimate + 1
    elif remainder == 2:
        estimate = estimate - 1
    elif remainder == 3:
        estimate = estimate - 2
    sizes = []
    for offset in (0, 4, -4, 8, -8):
        size = estimate + offset
        if 21 <= size <= 177:
            sizes.append(size)
    return sizes


def decode_bits(bits, width, height):
    finders = find_finders(bits, width, height)
    top = finders[:8]
    for a in range(len(top)):
        for b in range(a + 1, len(top)):
            for c in range(b + 1, len(top)):
                ordered = order_finders(top[a], top[b], top[c])
                if ordered is None:
                    continue
                for size in candidate_sizes(ordered):
                    grid = sample_grid(bits, width, height, ordered, size)
                    if grid is None:
                        continue
                    for attempt in (grid, transpose(grid)):
                        decoded = decode_matrix(attempt)
                        if decoded["ok"]:
                            corners = []
                            for point in ordered:
                                corners.append([point[0], point[1]])
                            decoded["value"]["corners"] = corners
                            return decoded
    if len(finders) < 3:
        return fail("no QR code found")
    return fail("found a QR code but could not read it")


def decode_image(image):
    """Image -> Result Reading. Big pictures are tried shrunk first, then at full size."""
    attempts = []
    largest = max(image["width"], image["height"])
    factor = largest // 800
    if factor >= 2:
        attempts.append((shrink_image(image, factor), factor))
    attempts.append((image, 1))
    last = fail("no QR code found")
    for picture, scale in attempts:
        for binarize in (binarize_global, binarize_local):
            bits = binarize(picture)
            for attempt in (bits, majority_filter(bits, picture["width"], picture["height"])):
                result = decode_bits(attempt, picture["width"], picture["height"])
                if result["ok"]:
                    for corner in result["value"]["corners"]:
                        corner[0] = corner[0] * scale
                        corner[1] = corner[1] * scale
                    return result
                if last["error"] == "no QR code found":
                    last = result
    return last


def majority_filter(bits, width, height):
    """Each pixel becomes what most of its 3x3 neighbourhood is: removes specks from noisy pictures."""
    result = bytearray(bits)
    for y in range(1, height - 1):
        above = (y - 1) * width
        here = y * width
        below = (y + 1) * width
        for x in range(1, width - 1):
            count = (bits[above + x - 1] + bits[above + x] + bits[above + x + 1] +
                     bits[here + x - 1] + bits[here + x] + bits[here + x + 1] +
                     bits[below + x - 1] + bits[below + x] + bits[below + x + 1])
            if count >= 5:
                result[here + x] = 1
            else:
                result[here + x] = 0
    return result


# --- Picture changes (used by the tests to make harder pictures) ---------------------------------

def rotate_image(image):
    """Quarter turn clockwise."""
    width = image["width"]
    height = image["height"]
    result = make_image(height, width, 255)
    for y in range(height):
        for x in range(width):
            result["gray"][x * height + (height - 1 - y)] = image["gray"][y * width + x]
    return result


def scale_image(image, factor):
    width = max(1, int(image["width"] * factor))
    height = max(1, int(image["height"] * factor))
    result = make_image(width, height, 255)
    for y in range(height):
        source_y = min(image["height"] - 1, int(y / factor))
        for x in range(width):
            source_x = min(image["width"] - 1, int(x / factor))
            result["gray"][y * width + x] = image["gray"][source_y * image["width"] + source_x]
    return result


def add_noise(image, fraction, seed):
    """Flip a fraction of pixels to random grays (seeded, so the same every run)."""
    generator = random.Random(seed)
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"]), "rgb": None}
    count = int(len(result["gray"]) * fraction)
    for i in range(count):
        result["gray"][generator.randrange(len(result["gray"]))] = generator.randrange(256)
    return result


def warp_image(image, corners):
    """Stretch the picture so its corners land on `corners` (TL, TR, BR, BL), white elsewhere."""
    width = image["width"]
    height = image["height"]
    sources = [(0, 0), (width, 0), (width, height), (0, height)]
    inverse = perspective(corners, sources)
    result = make_image(width, height, 255)
    for y in range(height):
        for x in range(width):
            u, v = apply_perspective(inverse, x + 0.5, y + 0.5)
            if 0 <= u < width and 0 <= v < height:
                result["gray"][y * width + x] = image["gray"][int(v) * width + int(u)]
    return result


# --- Links, files and the color of a picture -----------------------------------------------------

def is_link(text):
    lowered = text.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def file_kind(path):
    """"svg" for .svg files, otherwise "png" (the only two kinds this program writes)."""
    if path.lower().endswith(".svg"):
        return "svg"
    return "png"


def picture_bytes(matrix, scale, color, kind, caption=""):
    """The matrix as file contents in `color`: PNG bytes, or SVG text as UTF-8. Four modules of
    quiet zone on every side, and the caption (if any) below."""
    if kind == "svg":
        return matrix_to_svg(matrix, 4, color, caption).encode("utf-8")
    return matrix_to_color_png(matrix, scale, 4, color, caption)


def save_matrix(matrix, path, scale, color=INK, caption=""):
    """Write a .png or .svg file in `color` -> Result path. It is written next to the target first
    and then moved into place, so a failed save never leaves half a picture behind."""
    temporary = path + ".part"
    try:
        handle = open(temporary, "wb")
        handle.write(picture_bytes(matrix, scale, color, file_kind(path), caption))
        handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail(str(error))
    return ok_result(path)


def dark_color(image):
    """The most common color among the picture's dark pixels (gray at or below its Otsu threshold)
    as "#rrggbb". For a two-color QR code that is exactly its color; for a photo, an estimate."""
    gray = image["gray"]
    rgb = image["rgb"]
    threshold = otsu_threshold(gray)
    counts = {}
    for i in range(len(gray)):
        if gray[i] <= threshold:
            if rgb is None:
                key = (gray[i], gray[i], gray[i])
            else:
                key = (rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2])
            counts[key] = counts.get(key, 0) + 1
    best = (0, 0, 0)
    best_count = 0
    for key in sorted(counts):
        if counts[key] > best_count:
            best = key
            best_count = counts[key]
    return "#%02x%02x%02x" % best


def svg_color(text):
    """The fill of the squares in a drawing made by matrix_to_svg, or "" when there is none."""
    begin = text.find('<path d="')
    if begin < 0:
        return ""
    found = text.find('fill="#', text.find('"', begin + 9))
    if found < 0 or len(text) < found + 13:
        return ""
    value = text[found + 6:found + 13].lower()
    for character in value[1:]:
        if character not in "0123456789abcdef":
            return ""
    return value


def read_qr_file(path):
    """A PNG, PGM/PPM or this program's own SVG drawing -> Result Picture
    {"reading": Reading, "format": "png" | "svg" | "other", "color": "#rrggbb", "image": Image or None}.
    Never raises: a damaged, huge or unreadable file is a failed Result."""
    try:
        if file_kind(path) == "svg":
            if os.path.getsize(path) > MAX_FILE_BYTES:
                return fail("the drawing is too big")
            handle = open(path, "r", encoding="utf-8")
            text = handle.read()
            handle.close()
            grid = read_svg_matrix(text)
            if not grid["ok"]:
                return grid
            reading = decode_matrix(grid["value"])
            if not reading["ok"]:
                return reading
            reading["value"]["corners"] = []
            return ok_result({"reading": reading["value"], "format": "svg", "color": svg_color(text) or INK,
                              "image": None})
        loaded = load_image_file(path)
        if not loaded["ok"]:
            return loaded
        reading = decode_image(loaded["value"])
        if not reading["ok"]:
            return reading
        kind = "other"
        if path.lower().endswith(".png"):
            kind = "png"
        return ok_result({"reading": reading["value"], "format": kind, "color": dark_color(loaded["value"]),
                          "image": loaded["value"]})
    except Exception as error:
        return fail("cannot read " + os.path.basename(path) + " (" + type(error).__name__ + ")")


def describe(reading):
    return ("version " + str(reading["version"]) + ", level " + reading["level"] + ", mask " +
            str(reading["mask"]) + ", " + str(reading["corrected"]) + " codeword(s) corrected")

# ==== stamp v1 | author=kjFriday | hmac-sha256=35f9355356085b7d8e6cce50b67887812781a55fac4f7cad4c410e9c611fb173 ====
