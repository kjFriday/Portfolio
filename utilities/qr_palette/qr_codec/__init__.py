# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/__init__.py
# About: QR Palette codec: QR Studio's QR encoder and decoder, with colored output.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette codec: QR Studio's QR encoder and decoder, with colored output.

Standard library only (struct and zlib; math and random for the picture changes). Copied from QR
Studio's CORE section (see PROVENANCE.md) and extended with two-color PNG and SVG output, reading back
this codec's own SVG drawings, the dark color of a picture, PNG transparency (tRNS), limits on how
much a picture may cost to read, and a robustness score: how much wear a code survives.

Written to be easy to port to another language, like QR Studio: plain functions and plain records,
explicit loops, and failures reported as Result records instead of exceptions across layers.

Layout: one module per chapter; each imports only modules above it in this list.
  records        Result records
  gf             GF(256) arithmetic
  reed_solomon   Reed-Solomon codewords and corrections
  tables         levels, version tables, function patterns, data order, masks
  blocks         data split into blocks and interleaved, and back
  encode         text -> Matrix
  decode         Matrix -> text
  captions       the caption font and layout, for the picture writers below
  images         the Image record, PNG and PGM/PPM reading within limits, PNG writing
  binarize       gray -> dark and light
  locate         finding a code in a picture: decode_image
  distort        picture changes: the tests' harder pictures and the robustness score's wear
  logos          a logo in the middle of a code
  svg            SVG drawings, and reading them back
  files          links, picture files and their color: save_matrix, read_qr_file
  robustness     how much wear a code survives
QR Studio's qr_codec package has the same modules from records to distort, without captions. All of
them except images and distort are byte-identical in both programs, so a fix to one belongs in both.

`import qr_codec` gives every name the program and its tests use, re-exported below by name, as when
the codec was one file. Two settings that the tests change keep their one home in the module whose
functions read them: MAX_FILE_BYTES in images and LOGO_SHARES in logos. A copy here would not reach
those functions, so the package forwards them instead (SETTING_HOMES and CodecPackage, at the end):
reading, setting or deleting qr_codec.MAX_FILE_BYTES or qr_codec.LOGO_SHARES does it in the home
module, and every reader sees the change. The module robustness shares its name with its main
function: qr_codec.robustness is the function.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Image    {"width": int, "height": int, "gray": bytearray, "rgb": bytearray or None}
           one gray byte per pixel, rows from the top, 0 = black; "rgb" has three bytes per pixel
           when the picture was in color, else None
  Matrix   {"size": int, "dark": [[bool]] (row, column), "version": int, "level": str, "mask": int}
  Reading  {"text": str, "version": int, "level": str, "mask": int, "corrected": int,
            "corners": [[x, y]] finder centres top-left, top-right, bottom-left in image pixels}
  Score    {"passed": int, "tried": int, "failed": [the names of the WEAR tests the code failed]}
  Logo     {"image": Image, "box": [row, column, side]}   a picture drawn in the middle of a code, inside a
           square of side modules (one module of white margin around it) whose modules are left blank
"""

import sys
import types

from .reed_solomon import rs_correct, rs_remainder
from .tables import (ECC_PER_BLOCK, EC_LEVELS, blank_grid, data_codeword_count, data_positions, format_bits,
                     function_patterns, level_index, raw_data_modules, version_bits)
from .blocks import block_data_lengths
from .encode import MODE_ALPHANUMERIC, choose_mode, encode_text
from .decode import decode_matrix
from .captions import GLYPHS, caption_layout, caption_pixels, caption_size
from .images import (PNG_SIGNATURE, load_image_file, make_image, matrix_to_color_png, matrix_to_image,
                     png_chunk, read_image_bytes, read_png, read_ppm, write_png)
from .locate import decode_image
from .distort import (add_grain, add_noise, blur_image, cover_image, fade_image, rotate_image, scale_image,
                      tilt_image, warp_image)
from .logos import MAX_LOGO_SIDE, place_logo, protected_modules
from .svg import INK, PAPER, SVG_GRID, matrix_to_svg, read_svg_matrix, svg_color
from .files import dark_color, describe, file_kind, is_link, picture_bytes, read_qr_file, save_matrix
from .robustness import COVERED_SHARE, WEAR, corner_box, describe_score, picture_image, robustness, worn_image
from . import images, logos


# The settings that code outside the codec changes through the package (the tests do), by name ->
# their one home: the module whose functions read them.
SETTING_HOMES = {"MAX_FILE_BYTES": images, "LOGO_SHARES": logos}


class CodecPackage(types.ModuleType):
    """The qr_codec package object: a name in SETTING_HOMES is read, set and deleted in its home."""

    def __getattr__(self, name):
        """Value of a forwarded setting from its home module; AttributeError for any other unknown name."""
        # Python calls this only for a name the package itself does not hold.
        if name in SETTING_HOMES:
            return getattr(SETTING_HOMES[name], name)
        raise AttributeError("module '" + self.__name__ + "' has no attribute '" + name + "'")

    def __setattr__(self, name, value):
        """Set a forwarded setting in its home module; any other name is set on the package as usual."""
        if name in SETTING_HOMES:
            setattr(SETTING_HOMES[name], name, value)
        else:
            types.ModuleType.__setattr__(self, name, value)

    def __delattr__(self, name):
        """Delete a forwarded setting in its home module; any other name is deleted from the package."""
        if name in SETTING_HOMES:
            delattr(SETTING_HOMES[name], name)
        else:
            types.ModuleType.__delattr__(self, name)

    def __dir__(self):
        """The package's own names plus the forwarded settings, so dir() and completion list them."""
        names = types.ModuleType.__dir__(self)
        for name in SETTING_HOMES:
            names.append(name)
        return names


# swapping the class of the live module object (allowed since Python 3.5) keeps every existing
# reference to the package and adds the forwarding above
sys.modules[__name__].__class__ = CodecPackage

# ==== stamp v1 | author=kjFriday | hmac-sha256=7c621a567e4dfc5e691408bab8114131c21d0d26d10bd14f1db60acfef3a922c ====
