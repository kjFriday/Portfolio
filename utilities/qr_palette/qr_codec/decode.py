# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/decode.py
# About: The matrix decoder: a grid of modules -> text, with its version, level and mask.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The matrix decoder: a grid of modules -> text, with its version, level and mask.

Format and version information take the nearest valid word within 3 bit errors. After unmasking, the
codewords are split into blocks and corrected, and the segments are read: numeric, alphanumeric, byte
and kanji, with ECI, structured-append and FNC1 headers. BitReader is the codec's one class.
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=0898e87d22aa42f652b37e4ccd6202021383d1ab98a0a8d1cbb837d187f08014 ====
