# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/blocks.py
# About: Blocks: data codewords split into Reed-Solomon blocks and interleaved, and back again.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Blocks: data codewords split into Reed-Solomon blocks and interleaved, and back again.

The short blocks come first; each long block holds one more data codeword (ISO/IEC 18004 table 9).
"""

from .reed_solomon import rs_remainder
from .tables import BLOCK_COUNT, ECC_PER_BLOCK, level_index, raw_data_modules


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

# ==== stamp v1 | author=kjFriday | hmac-sha256=0b17978cc0fa98cb87f1fcc9f8c6a46534a0e133a19967f88641fb60152765f7 ====
