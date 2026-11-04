# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/decode.py
# About: The matrix decoder: a grid of modules -> text, with its version, level and mask.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""The matrix decoder: a grid of modules -> text, with its version, level and mask.

Format and version information take the nearest valid word within 3 bit errors. After unmasking, the
codewords are split into blocks and corrected, and the segments are read: numeric, alphanumeric, byte
and kanji, with ECI, structured-append and FNC1 headers. BitReader is the codec's one class.

Callers: locate.py hands every grid it samples from a picture to decode_matrix (and the transposed grid,
for mirrored pictures); tests decode encoder output directly. A grid is a list of rows, dark[y][x] true
for a dark module. Results are the package's {"ok", "value"} / {"ok", "error"} records (records.py).

Main flow of decode_matrix:
1. Check the size is 21 + 4k modules.
2. Read the EC level and mask from the format information, and the version from the version
   information (versions 7 and up) or the size.
3. Read the data modules in zigzag order, undo the mask, and pack them into codewords.
4. Split the codewords into Reed-Solomon blocks and correct each one.
5. Parse the data codewords into segments and join their text.

Why "nearest within 3 bit errors": the 15-bit format word is a BCH(15,5) code and the 18-bit version
word a BCH(18,6) code. Valid words differ in at least 7 and 8 bits, so any word within 3 bits of a
valid one has exactly one nearest valid word. With only 32 and 34 valid words, trying them all is
simpler than a BCH decoder.

Start reading at decode_matrix.
"""

from .records import fail, ok_result
from .reed_solomon import rs_correct
from .tables import (ECC_PER_BLOCK, EC_LEVELS, blank_grid, data_positions, format_bits, format_positions,
                     function_patterns, level_index, mask_applies, raw_data_modules, size_for_version,
                     version_bits, version_positions)
from .blocks import split_blocks
from .encode import (ALPHANUMERIC, MODE_ALPHANUMERIC, MODE_APPEND, MODE_BYTE, MODE_ECI, MODE_FNC1_FIRST,
                     MODE_FNC1_SECOND, MODE_KANJI, MODE_NUMERIC, count_bits)


def hamming(a, b):
    """Number of bit positions where the non-negative ints a and b differ (Hamming distance)."""
    value = a ^ b
    count = 0
    while value:
        count = count + (value & 1)
        value = value >> 1
    return count


def read_bits(dark, positions):
    """Int whose bit i is the module at positions[i] ((x, y) pairs); dark modules are 1."""
    value = 0
    for i in range(len(positions)):
        x, y = positions[i]
        if dark[y][x]:
            value = value | (1 << i)
    return value


def read_format(dark):
    """-> Result (level, mask) from the closer of the two format copies.

    Every one of the 4 x 8 valid format words is compared with both copies; the nearest wins, and more
    than 3 differing bits fails. format_bits already includes the 0x5412 mask the standard XORs in.
    """
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
    """-> Result version (1..40).

    Versions 1 to 6 carry no version information, so the size decides (size = 17 + 4 * version).
    Larger symbols compare both 18-bit copies with versions 7..40 and take the nearest within 3 bits.
    """
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
    """Reads a bytes object as a stream of bits, most significant bit of each byte first."""

    def __init__(self, data):
        """Start at bit 0 of data (bytes or another sequence of 0..255 ints)."""
        self.data = data
        self.position = 0

    def remaining(self):
        """Bits not read yet."""
        return len(self.data) * 8 - self.position

    def read(self, count):
        """Next `count` bits as an int, or -1 when there are not enough."""
        if count > self.remaining():
            return -1
        value = 0
        for i in range(count):
            # position >> 3 is the byte, 7 - (position & 7) the bit within it counted from the right
            byte = self.data[self.position >> 3]
            value = (value << 1) | ((byte >> (7 - (self.position & 7))) & 1)
            self.position = self.position + 1
        return value


# ECI (Extended Channel Interpretation) designator -> Python codec for the byte segments that follow.
# The numbers are the AIM ECI assignments: 3 is ISO-8859-1 (1 is its older alias), 4..11 the other
# ISO-8859 parts, 20 Shift JIS, 21..24 Windows code pages, 25 UTF-16BE, 26 UTF-8, 27 ASCII, 28 Big5,
# 29 GB18030, 30 EUC-KR. Designators not listed leave byte segments to the UTF-8 / Latin-1 guess.
ECI_CODECS = {1: "latin-1", 3: "latin-1", 4: "iso8859-2", 5: "iso8859-3", 6: "iso8859-4", 7: "iso8859-5",
              8: "iso8859-6", 9: "iso8859-7", 10: "iso8859-8", 11: "iso8859-9", 20: "shift_jis",
              21: "cp1250", 22: "cp1251", 23: "cp1252", 24: "cp1256", 25: "utf-16-be", 26: "utf-8",
              27: "ascii", 28: "big5", 29: "gb18030", 30: "euc_kr"}


def decode_bytes(data, codec):
    """Text of a byte segment: in codec when one is set and works, else UTF-8, else Latin-1.

    The standard's default for byte mode is ISO-8859-1, but most writers today put UTF-8 there without
    an ECI, so UTF-8 is tried first. Latin-1 accepts any byte, so this never fails.
    """
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
    """Data codewords -> Result text.

    The data is a run of segments, each a 4-bit mode indicator, a character count whose width depends
    on mode and version (count_bits), and the characters (ISO/IEC 18004 section 7.4). Mode 0 is the
    terminator; fewer than 4 bits left also ends the data. Header-only modes (ECI, structured append,
    FNC1) change no text.

    Steps:
    1. Read a mode; stop on the terminator.
    2. ECI: read the designator and remember its codec for later byte segments.
    3. Structured append and FNC1: skip their fixed-size fields.
    4. Otherwise read the count and decode the characters for that mode, appending to the text.
    """
    reader = BitReader(data)
    text = ""
    codec = ""
    while reader.remaining() >= 4:
        mode = reader.read(4)
        if mode == 0:
            break
        if mode == MODE_ECI:
            # the designator takes 1, 2 or 3 bytes; the leading bits 0, 10 or 110 say which
            # (7, 14 or 21 bits of value)
            first = reader.read(8)
            if first < 0:
                return fail("data ends inside an ECI marker")
            if first & 0x80 == 0:
                designator = first
            elif first & 0xC0 == 0x80:
                designator = ((first & 0x3F) << 8) | reader.read(8)
            else:
                designator = ((first & 0x1F) << 16) | reader.read(16)
            # a truncated 2- or 3-byte designator ORs in -1, gives -1, and finds no codec
            codec = ECI_CODECS.get(designator, "")
            continue
        if mode == MODE_APPEND:
            # 4-bit symbol position, 4-bit total and 8-bit parity; each symbol is decoded on its own
            if reader.read(16) < 0:
                return fail("data ends inside a structured-append header")
            continue
        if mode == MODE_FNC1_FIRST:
            continue
        if mode == MODE_FNC1_SECOND:
            # the 8-bit application indicator is read and dropped
            reader.read(8)
            continue
        if mode not in (MODE_NUMERIC, MODE_ALPHANUMERIC, MODE_BYTE, MODE_KANJI):
            return fail("unknown data mode " + str(mode))
        count = reader.read(count_bits(mode, version))
        if count < 0:
            return fail("data ends inside a segment header")
        if mode == MODE_NUMERIC:
            # groups of 3 digits take 10 bits, a final 2 digits 7 bits, a final digit 4 bits
            while count > 0:
                digits = min(3, count)
                value = reader.read(digits * 3 + 1)
                if value < 0 or value >= 10 ** digits:
                    return fail("bad numeric data")
                text = text + str(value).zfill(digits)
                count = count - digits
        elif mode == MODE_ALPHANUMERIC:
            # pairs are 45 * first + second in 11 bits; an odd last character takes 6 bits
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
            # kanji: each 13-bit value packs a Shift JIS double byte (section 7.4.6). The encoder
            # subtracted 0x8140 (or 0xC140 for 0xE040..0xEBBF), then stored high * 0xC0 + low;
            # this undoes both steps.
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
    """Grid of modules (row, column) -> Result {"text", "version", "level", "mask", "corrected"}.

    "corrected" counts the codewords Reed-Solomon repaired over all blocks. Fails with a short reason
    when the size, format, version, error correction or segment data cannot be read.
    """
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
    # the function-pattern map says which modules hold data; the drawn patterns themselves are unused
    base, function = function_patterns(version)
    positions = data_positions(function)
    codewords = []
    value = 0
    # some versions leave 3, 4 or 7 remainder bits after the last codeword; they are not read
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
        # each block is its data codewords followed by ecc EC codewords; keep only the data
        data.extend(fixed["value"]["block"][:len(block) - ecc])
    parsed = parse_segments(bytes(data), version)
    if not parsed["ok"]:
        return parsed
    return ok_result({"text": parsed["value"], "version": version, "level": level, "mask": mask,
                      "corrected": corrected})


def transpose(dark):
    """New grid mirrored about the main diagonal: what a code seen from behind or in a mirror reads as."""
    size = len(dark)
    result = blank_grid(size, False)
    for y in range(size):
        for x in range(size):
            result[x][y] = dark[y][x]
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=a20f6e8a21e5dd60944428de92af6c8617945f96c76146ec630499aa9a18bbb4 ====
