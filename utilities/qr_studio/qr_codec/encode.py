# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/encode.py
# About: The encoder: text -> Matrix, with the mode, the smallest version that fits and the mask.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""The encoder: text -> Matrix, with the mode, the smallest version that fits and the mask.

One segment per code, in numeric, alphanumeric or byte mode (byte mode is UTF-8 without an ECI
header; kanji is only read). The bits are mode, count, data, terminator and 0xEC/0x11 padding; the
codewords get their error correction and are placed in zigzag order; the eight masks are scored with
the ISO/IEC 18004 penalty unless one is asked for. The mode indicators are shared with the decoder.

Callers: the package's public encode functions (re-exported from __init__.py) and, through them, the
app's making, printing and MCP paths; decode.py imports the mode numbers, ALPHANUMERIC and count_bits.

Main flow of encode_text:
1. Pick the densest mode the whole text allows (choose_mode) and turn the text into bits.
2. Find the smallest version, from min_version up, whose data capacity at the level holds the
   4-bit mode, the character count and the text bits.
3. Add the terminator (up to four 0 bits), zero bits to a byte boundary, and alternating 0xEC / 0x11
   pad bytes to fill the capacity (section 7.4.10).
4. Add Reed-Solomon error correction and interleave the blocks (blocks.py).
5. Draw the function patterns and place the codeword bits in zigzag order, most significant bit first.
6. Apply each candidate mask to the data modules, draw the format information, and keep the grid with
   the lowest penalty.

Records: a Matrix is {"size", "dark", "version", "level", "mask"}, dark[y][x] true for a dark module.

Start reading at encode_text.
"""

from .records import fail, ok_result
from .tables import (FORMAT_LEVEL_BITS, bit_of, blank_grid, data_codeword_count, data_positions, draw_format,
                     format_bits, function_patterns, mask_applies)
from .blocks import add_error_correction


# The 45 characters of alphanumeric mode; a character's value is its index here (section 7.4.5).
ALPHANUMERIC = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
# The 4-bit mode indicators that start each segment (section 7.4.1, table 2). 0 is the terminator.
MODE_NUMERIC = 1
MODE_ALPHANUMERIC = 2
MODE_BYTE = 4
MODE_KANJI = 8
MODE_ECI = 7
MODE_APPEND = 3
MODE_FNC1_FIRST = 5
MODE_FNC1_SECOND = 9


def append_bits(bits, value, length):
    """Append the low `length` bits of value to the bit list, most significant first; 0 length adds none."""
    index = length - 1
    while index >= 0:
        bits.append((value >> index) & 1)
        index = index - 1


def count_bits(mode, version):
    """Width in bits of a segment's character count for a mode and version (section 7.4.1, table 3).

    Larger symbols get wider counts in three steps: versions 1-9, 10-26 and 27-40. Any mode not
    numeric, alphanumeric or kanji gets the byte-mode widths.
    """
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
    """The densest single mode that holds all of text: numeric, then alphanumeric, else byte.

    Empty text uses byte mode. Mixed-mode segmentation is not attempted, so "ABC123abc" is all byte.
    """
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
    """(bits, character count) for one segment of `text` in `mode`.

    Byte mode counts UTF-8 bytes, not characters, since the count field is read as a byte count.
    """
    bits = []
    if mode == MODE_NUMERIC:
        # 3 digits in 10 bits, a final 2 in 7, a final 1 in 4
        index = 0
        while index < len(text):
            group = text[index:index + 3]
            append_bits(bits, int(group), len(group) * 3 + 1)
            index = index + 3
        return bits, len(text)
    if mode == MODE_ALPHANUMERIC:
        # pairs as 45 * first + second in 11 bits, a final single character in 6
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
    """ISO 18004 mask penalty: long runs, 2x2 blocks, finder-like patterns, dark/light balance.

    Lower is better. The four rules (section 7.8.3) and their weights:
    1. A run of 5 or more same-colour modules in a row or column scores 3, plus 1 per module past 5.
    2. Every 2 x 2 block of one colour scores 3 (overlapping blocks each count).
    3. Dark-light-dark-dark-dark-light-dark (1:1:3:1:1) with 4 light modules on one side scores 40,
       because a reader could mistake it for a finder pattern. Outside the symbol counts as light.
    4. Every full 5 percent the dark share strays from 50 percent scores 10.
    """
    size = len(dark)
    score = 0
    # the 1:1:3:1:1 finder ratio followed by 4 light modules; matched forwards and backwards
    finder_like = (True, False, True, True, True, False, True, False, False, False, False)
    # every row, then every column, so rules 1 and 3 run once over both directions
    lines = []
    for y in range(size):
        lines.append(dark[y])
    for x in range(size):
        column = []
        for y in range(size):
            column.append(dark[y][x])
        lines.append(column)
    for line in lines:
        # rule 1; i == size flushes the last run
        run = 1
        for i in range(1, size + 1):
            if i < size and line[i] == line[i - 1]:
                run = run + 1
            else:
                if run >= 5:
                    score = score + 3 + (run - 5)
                run = 1
        # rule 3; 4 light modules of quiet zone on each end let a pattern touch the edge
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
    # rule 2 and the dark count for rule 4 in one pass
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
    # rule 4 in integers: |100 * dark / total - 50| // 5, scaled through by total to avoid floats
    score = score + 10 * (abs(dark_count * 100 - total * 50) // (total * 5))
    return score


def encode_text(text, level, min_version, mask):
    """Text -> Result Matrix. mask -1 picks the best of the eight; min_version 1 picks the smallest.

    level is "L", "M", "Q" or "H" (7, 15, 25 or 30 percent of codewords recoverable). Fails when the
    level is unknown or the text does not fit version 40 at that level.
    """
    if level not in FORMAT_LEVEL_BITS:
        return fail("level must be L, M, Q or H")
    mode = choose_mode(text)
    bits_of_text, count = payload_bits(text, mode)
    version = max(1, min_version)
    found = False
    # --- smallest version that fits ---
    while version <= 40:
        width = count_bits(mode, version)
        # 4 mode bits + count field + data; the count must also fit its field
        needed = 4 + width + len(bits_of_text)
        if count < (1 << width) and needed <= data_codeword_count(version, level) * 8:
            found = True
            break
        version = version + 1
    if not found:
        return fail("text is too long for a QR code at level " + level)

    # --- data codewords ---
    capacity = data_codeword_count(version, level) * 8
    bits = []
    append_bits(bits, mode, 4)
    append_bits(bits, count, count_bits(mode, version))
    bits.extend(bits_of_text)
    # the terminator is shortened when fewer than 4 bits of capacity are left
    append_bits(bits, 0, min(4, capacity - len(bits)))
    append_bits(bits, 0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        append_bits(bits, pad, 8)
        # XOR with both values swaps 0xEC and 0x11 each time
        pad = pad ^ 0xEC ^ 0x11
    data = []
    for i in range(0, len(bits), 8):
        value = 0
        for k in range(8):
            value = (value << 1) | bits[i + k]
        data.append(value)
    codewords = add_error_correction(data, version, level)

    # --- placement ---
    base, function = function_patterns(version)
    positions = data_positions(function)
    for i in range(len(positions)):
        x, y = positions[i]
        # modules past the last codeword are the remainder bits and stay light (0) before masking
        if i < len(codewords) * 8:
            base[y][x] = bit_of(codewords[i >> 3], 7 - (i & 7))

    # --- masking ---
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
        # the format bits depend on the mask and are never masked themselves; the blank function
        # grid is a throwaway, since only the drawn modules matter here
        draw_format(grid, blank_grid(len(grid), False), format_bits(level, candidate))
        score = penalty_score(grid)
        # strict < keeps the lowest-numbered mask on ties
        if best is None or score < best_score:
            best = {"size": len(grid), "dark": grid, "version": version, "level": level, "mask": candidate}
            best_score = score
    return ok_result(best)

# ==== stamp v1 | author=kjFriday | hmac-sha256=e95ab6b9c83318caf29f6833a7eb9715402c5feef0cbc943c2e9d4f88cd37eb6 ====
