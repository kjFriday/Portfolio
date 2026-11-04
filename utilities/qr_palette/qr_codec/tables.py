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

A QR symbol of version v (1..40) is a square of 17 + 4v modules. Some modules are fixed "function
patterns" that help a reader find and measure the code: three finder patterns in the corners, the
timing lines between them, small alignment patterns on larger versions, and the format and version
information. Every other module carries data or error-correction bits. Section numbers below are those
of ISO/IEC 18004 (7.7 placement, 7.8 masking, 7.9 format information, 7.10 version information; annex
E lists the alignment positions).

Callers: encode.py (to draw a symbol and pick a mask), decode.py (to read format and version
information and to find the data modules), blocks.py (the block tables) and locate.py (blank_grid).

Start reading at function_patterns, then data_positions.
"""


# The four error-correction levels, weakest first: L recovers about 7% of codewords, M 15%, Q 25%, H 30%.
# A level's position here is its row in ECC_PER_BLOCK and BLOCK_COUNT.
EC_LEVELS = "LMQH"
# The 2-bit code each level has in the format information (section 7.9.1); note it is not
# the order above.
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
    """Side of a symbol in modules: 17 + 4 * version, so 21 for version 1 up to 177 for version 40."""
    return version * 4 + 17


def raw_data_modules(version):
    """Modules left for data and error correction once every function pattern is drawn.

    A closed form for size * size minus the finders with their separators, the timing lines, the format
    information and the dark module (the 16v^2 + 128v + 64 part), minus the alignment patterns (25
    modules each, less the ones that overlap the timing lines) from version 2, minus the two 18-module
    version blocks from version 7. Version 1 gives 208 (26 codewords).
    """
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result = result - ((25 * count - 10) * count - 55)
        if version >= 7:
            result = result - 36
    return result


def level_index(level):
    """Row of a level letter ("L", "M", "Q" or "H") in ECC_PER_BLOCK and BLOCK_COUNT: 0..3."""
    return EC_LEVELS.index(level)


def data_codeword_count(version, level):
    """How many 8-bit data codewords a version holds at a level.

    The whole codeword count is raw_data_modules // 8 (a few leftover "remainder bits" do not make a
    codeword); the error-correction codewords, per block times the number of blocks, come off it.
    Version 1 at L: 26 - 7 * 1 = 19.
    """
    index = level_index(level)
    return raw_data_modules(version) // 8 - ECC_PER_BLOCK[index][version] * BLOCK_COUNT[index][version]


def alignment_positions(version):
    """Row and column coordinates of the alignment-pattern centres, ascending (annex E).

    Version 1 has none. Larger versions have version // 7 + 2 coordinates: the first is always 6 (in
    line with the timing pattern), the last size - 7 (as far from the far edge as 6 is from the near one), and the
    ones between are an even step apart counted back from the last, so any odd gap ends up between the
    first two. Centres sit at every pair of coordinates (x, y) except the three corners a finder holds.

    Steps:
    1. count = version // 7 + 2 coordinates.
    2. step = the gap from the last coordinate back toward 6, spread over count - 1 gaps and rounded up
       to an even number; version 32 is the one table entry the formula misses (26, not 28).
    3. Start from size - 7 and walk back count - 1 times by step, inserting each value after the 6, so
       the list stays sorted.
    Example: version 7 (size 45) gives [6, 22, 38].
    """
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
    """The 15-bit format information word, as an int, for a level and a mask number (0..7).

    The format information tells a reader the level and the mask before it can read anything else, so
    it is protected by its own small code, a BCH(15,5) code (section 7.9, annex C): the 5 data bits (2
    for the level, 3 for the mask) are followed by 10 check bits, the remainder of data * x^10 divided
    by the generator polynomial x^10 + x^8 + x^5 + x^4 + x^2 + x + 1 (0x537), all arithmetic in GF(2),
    where adding is XOR. Any two of the 32 words differ in at least 7 bits, so a reader can fix 3.

    Steps:
    1. data = level bits << 3 | mask.
    2. Divide bit by bit: shift the remainder left one place; when a 1 reaches bit 10, XOR in the
       generator to clear it. After 10 shifts the remainder holds data * x^10 mod generator.
    3. Join data and remainder, then XOR with 101010000010010 (0x5412) so that no valid word is all
       zeros, which a blank or damaged area could look like.
    """
    data = (FORMAT_LEVEL_BITS[level] << 3) | mask
    remainder = data
    for i in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def version_bits(version):
    """The 18-bit version information word for versions 7..40: 6 version bits, then 12 check bits.

    A BCH(18,6) code (section 7.10, annex D): the check bits are the remainder of version * x^12 divided
    by x^12 + x^11 + x^10 + x^9 + x^8 + x^5 + x^2 + 1 (0x1F25), computed by the same shift-and-XOR long
    division as format_bits. No mask is applied: the version is never 0, so the word is never all zeros.
    Any two words differ in at least 8 bits. Version 7 gives 0x07C94.
    """
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
    """True when bit `index` of value (0 = least significant) is 1."""
    return (value >> index) & 1 == 1


def blank_grid(size, value):
    """A size x size grid (a list of rows) with every cell set to value; the rows are separate lists."""
    grid = []
    for y in range(size):
        grid.append([value] * size)
    return grid


def set_function(modules, function, x, y, dark):
    """Set module (x, y) to dark or light and mark it as a function module, so data never goes there."""
    modules[y][x] = dark
    function[y][x] = True


def draw_finder(modules, function, cx, cy):
    """Draw a finder pattern centred on (cx, cy), with its light separator, clipped to the symbol.

    A finder (section 6.3.3) is 7 x 7 modules: a dark ring, a light ring, then a dark 3 x 3 core, so a
    line through its centre crosses dark, light, dark, light, dark in the ratio 1:1:3:1:1 at any angle.
    That ratio is what a reader looks for (locate.py). Around it runs a one-module light separator
    (section 6.3.4). By Chebyshev distance d = max(|dx|, |dy|) from the centre: d 0..1 dark core, 2 light,
    3 dark, 4 the separator; only d 2 and 4 are light. The parts of the 9 x 9 square that fall off the
    symbol's edge are skipped.
    """
    size = len(modules)
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            x = cx + dx
            y = cy + dy
            if 0 <= x < size and 0 <= y < size:
                distance = max(abs(dx), abs(dy))
                set_function(modules, function, x, y, distance != 2 and distance != 4)


def draw_alignment(modules, function, cx, cy):
    """Draw a 5 x 5 alignment pattern centred on (cx, cy): dark ring, light ring, one dark centre.

    Alignment patterns (section 6.3.6) give a reader extra known points inside larger symbols, so it can
    follow a bent or tilted picture; only the ring at Chebyshev distance 1 is light.
    """
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            set_function(modules, function, cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)


def draw_format(modules, function, bits):
    """Write a 15-bit format word (format_bits) into both of its copies, and set the dark module.

    Bit i goes to copy[i] of format_positions. The module at (8, size - 8), beside the bottom-left
    finder, is always dark (the "dark module") and belongs to no copy.
    """
    size = len(modules)
    copies = format_positions(size)
    for copy in copies:
        for i in range(15):
            x, y = copy[i]
            set_function(modules, function, x, y, bit_of(bits, i))
    set_function(modules, function, 8, size - 8, True)


def draw_version(modules, function, version):
    """Write the version word (version_bits) into its two 6 x 3 blocks; versions below 7 have none.

    One block sits left of the top-right finder and one above the bottom-left finder, each the
    other's mirror image across the diagonal (version_positions).
    """
    if version < 7:
        return
    bits = version_bits(version)
    copies = version_positions(len(modules))
    for copy in copies:
        for i in range(18):
            x, y = copy[i]
            set_function(modules, function, x, y, bit_of(bits, i))


def function_patterns(version):
    """(modules, function): the grid with every function pattern drawn, and which modules they own.

    modules[y][x] is True for a dark module; function[y][x] is True where a function pattern sits, so
    data placement and masking skip it.

    Steps:
    1. Draw the timing patterns: row 6 and column 6 alternate dark and light, dark on even indices.
       They let a reader count the module grid between the finders.
    2. Draw the three finders (centres 3 modules in from the top-left, top-right and bottom-left
       corners), over the timing lines' ends.
    3. Draw an alignment pattern at every pair of alignment_positions except the three that would land
       on a finder.
    4. Reserve the format areas by drawing format word 0 (the encoder draws the real word once it has
       chosen a mask), then draw the version information.
    """
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
    """Data modules in reading order: two-column zigzag from the bottom right, skipping column 6.

    Section 7.7.3: the codeword bits fill columns in pairs, right column of the pair first, moving up
    the first pair, down the next, and so on to the left edge. Function modules are stepped over.
    Column 6 is the vertical timing pattern, so the pair after columns 7-8 is columns 4-5.
    Returns a list of (x, y); its order is the same for the encoder and the decoder.
    """
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
    """True when mask pattern `mask` (0..7) flips the data module at column x, row y.

    Masking (section 7.8) XORs a fixed pattern over the data modules so the symbol avoids large blank
    areas and shapes that look like finders; the encoder tries all eight and keeps the one with the
    lowest penalty, and the format information tells the reader which to undo. The conditions are the
    standard's, with i = row (y) and j = column (x): mask 0 is a checkerboard, 1 horizontal stripes, 2
    vertical stripes every third column, 3 diagonals, 4 a pattern of 3 x 2 blocks, and 5 to 7 mixes
    of the products x * y mod 2 and mod 3.
    """
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=edf33e60841a2e2a38c2a03d25f7420b3e7c19837b2818563edcfdd9f3dab4d1 ====
