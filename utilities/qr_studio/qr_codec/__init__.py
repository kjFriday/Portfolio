# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/__init__.py
# About: QR Studio codec: a QR encoder and decoder written from scratch in standard-library Python.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio codec: a QR encoder and decoder written from scratch in standard-library Python.

Reed-Solomon error correction; the encoder (numeric, alphanumeric and byte modes, versions 1-40,
levels L/M/Q/H, mask scoring); the reader (thresholding, finder- and alignment-pattern search,
perspective sampling, format and version recovery); its own PNG and PGM/PPM reader and PNG and SVG
writer. No imaging or barcode library is used: struct and zlib, and random for the picture changes.

Written to be easy to port to another language: plain functions and plain records, explicit loops,
and failures reported as Result records instead of exceptions across layers.

Layout: one module per chapter; each imports only modules above it in this list.
  records        Result records
  gf             GF(256) arithmetic
  reed_solomon   Reed-Solomon codewords and corrections
  tables         levels, version tables, function patterns, data order, masks
  blocks         data split into blocks and interleaved, and back
  encode         text -> Matrix
  decode         Matrix -> text
  images         the Image record, PNG and PGM/PPM reading, PNG and SVG writing
  binarize       gray -> dark and light
  locate         finding a code in a picture: decode_image
  distort        picture changes for the tests and the self-test
QR Palette's qr_codec package is an extended copy (see its PROVENANCE.md). The modules above, except
images and distort, are byte-identical in both programs, so a fix to one belongs in both.

This file re-exports, by name, what qr_studio.py imports from the codec.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Image    {"width": int, "height": int, "gray": bytearray}  one byte per pixel, rows from the top, 0 = black
  Matrix   {"size": int, "dark": [[bool]] (row, column), "version": int, "level": str, "mask": int}
  Reading  {"text": str, "version": int, "level": str, "mask": int, "corrected": int,
            "corners": [[x, y]] finder centres top-left, top-right, bottom-left in image pixels}

Who imports it: qr_studio.py, studio_history.py, studio_clipboard.py, studio_selftest.py, studio_gui.py
and the tests, all by the names below. Start reading the codec at encode.encode_text for making a code
and locate.decode_image for reading one.
"""

# the public names, listed in the same chapter order as the layout above; the tests also reach the
# tables and blocks through these names
from .records import fail, ok_result
from .reed_solomon import rs_correct, rs_remainder
from .tables import (ECC_PER_BLOCK, EC_LEVELS, data_codeword_count, data_positions, format_bits,
                     function_patterns, level_index, raw_data_modules, version_bits)
from .blocks import block_data_lengths
from .encode import encode_text
from .decode import decode_matrix
from .images import load_image_file, make_image, matrix_to_image, matrix_to_svg, read_png, write_png
from .locate import decode_image
from .distort import add_noise, rotate_image, scale_image, warp_image

# ==== stamp v1 | author=kjFriday | hmac-sha256=caafb95c5681608809de9bc0f2fd93b1b5e11cb5c3610a4b6c1e76d49c620ac1 ====
