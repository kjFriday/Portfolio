# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/tables.py
# About: The fixed parts of a QR symbol (ISO/IEC 18004): levels, version tables, patterns, masks.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The fixed parts of a QR symbol (ISO/IEC 18004): levels, version tables, patterns, masks.

Sizes and capacities by version and error-correction level; the BCH-coded format and version
information and where their bits go; the finder, timing and alignment patterns (function_patterns
draws them and says which modules they own); the zigzag order of the data modules; the eight masks.
Grids are lists of rows: grid[y][x].
"""


EC_LEVELS = "LMQH"
FORMAT_LEVEL_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

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

# ==== stamp v1 | author=kjFriday | hmac-sha256=fd741971b3d8161bd705fd7648ee1dce6eb6185490e55fa79f01c4aff7c2346a ====
