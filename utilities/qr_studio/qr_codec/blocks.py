# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/blocks.py
# About: Blocks: data codewords split into Reed-Solomon blocks and interleaved, and back again.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Blocks: data codewords split into Reed-Solomon blocks and interleaved, and back again.

The short blocks come first; each long block holds one more data codeword (ISO/IEC 18004 table 9).

Why blocks: a large symbol's codewords are cut into several Reed-Solomon blocks, each with its own
error correction codewords, and the blocks are interleaved byte by byte before placement. A smudge
that wipes out a run of neighbouring modules then damages a few codewords in many blocks instead of
many codewords in one block, so each block stays within what its EC codewords can repair.

Callers: encode.py calls add_error_correction after the data codewords are padded; decode.py calls
split_blocks on the codewords read from the grid, corrects each block, and joins the data parts.
Block counts and EC codewords per block come from tables.py.

Main flow of add_error_correction:
1. Work out each block's data length (block_data_lengths).
2. Cut the data into those blocks and compute each block's EC codewords.
3. Emit data codeword 0 of every block, then codeword 1, and so on (short blocks drop out at the end).
4. Emit the EC codewords the same way; every block has the same EC count.
"""

from .reed_solomon import rs_remainder
from .tables import BLOCK_COUNT, ECC_PER_BLOCK, level_index, raw_data_modules


def block_data_lengths(version, level):
    """Data codewords per block, in block order, for a version (1..40) and EC level letter.

    The symbol holds raw total codewords; split across the blocks, raw % blocks of them get one extra
    codeword, and those long blocks come last.
    """
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
    """Data codewords -> every codeword in transmission order (data interleaved, then EC interleaved).

    data must already be padded to the full data capacity of version and level.
    """
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
    # the last block is a long one when any exist, so its length bounds every column
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
    """Inverse of add_error_correction -> list of blocks, each data then EC codewords.

    codewords must hold at least the symbol's total codeword count; reading walks the same column
    order the encoder wrote.
    """
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=be35c9a665ef5f6f41c3820802a9227f6454f3a7917281fa66d517a59fc01e3f ====
