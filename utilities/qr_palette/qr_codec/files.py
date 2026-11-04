# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/files.py
# About: Links, picture files and the color of a picture: what the program saves, and reads back.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Links, picture files and the color of a picture: what the program saves, and reads back.

save_matrix writes a .png or .svg in a color, with an optional caption and logo; read_qr_file reads a
PNG, PGM/PPM or one of this codec's own SVG drawings, and never raises.

Callers: the app's GUI tabs (make, read, find), the short-link and print code and the MCP server go
through the package's re-exports. This module glues together the writers (images.py, logos.py,
svg.py) and the readers (images.py loaders, locate.py for pictures, svg.py for drawings, decode.py).

Main flow of read_qr_file:
1. An .svg file is parsed back into its module grid and decoded directly; no picture search is needed.
2. Anything else is loaded as a picture and searched for a code (locate.decode_image).
3. The result also carries the code's dark color, so a redraw can keep it.

Records: a Picture is {"reading", "format", "color", "image"}; a Reading is decode_matrix's value plus
"corners" (where the code was found in the picture; empty for an SVG).
"""

import os

from .records import fail, ok_result
from .decode import decode_matrix
from . import images
from .images import load_image_file, matrix_to_color_png
from .binarize import otsu_threshold
from .locate import decode_image
from .logos import matrix_to_logo_png
from .svg import INK, matrix_to_svg, read_svg_matrix, svg_color


def is_link(text):
    """True when text, ignoring case and surrounding spaces, starts with http:// or https://."""
    lowered = text.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def file_kind(path):
    """"svg" for .svg files, otherwise "png" (the only two kinds this program writes)."""
    if path.lower().endswith(".svg"):
        return "svg"
    return "png"


def picture_bytes(matrix, scale, color, kind, caption="", logo=None):
    """The matrix as file contents in `color`: PNG bytes, or SVG text as UTF-8. Four modules of
    quiet zone on every side, the logo (if any) in the middle, and the caption (if any) below."""
    if kind == "svg":
        return matrix_to_svg(matrix, 4, color, caption, logo).encode("utf-8")
    if logo is not None:
        return matrix_to_logo_png(matrix, scale, 4, color, caption, logo)
    return matrix_to_color_png(matrix, scale, 4, color, caption)


def save_matrix(matrix, path, scale, color=INK, caption="", logo=None):
    """Write a .png or .svg file in `color` -> Result path. It is written next to the target first
    and then moved into place, so a failed save never leaves half a picture behind.

    scale is pixels per module for a PNG (an SVG ignores it). Side effects: creates path + ".part",
    then replaces path with it.
    """
    temporary = path + ".part"
    try:
        handle = open(temporary, "wb")
        # Known limitation: if write fails the handle stays open until garbage collection, so on Windows
        # the os.remove below can fail and leave the .part file behind (the target is still untouched).
        handle.write(picture_bytes(matrix, scale, color, file_kind(path), caption, logo))
        handle.close()
        # os.replace is atomic on one volume and overwrites an existing file on Windows too
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
            # a gray-only picture (PGM) has rgb None; rgb is otherwise 3 bytes per pixel
            if rgb is None:
                key = (gray[i], gray[i], gray[i])
            else:
                key = (rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2])
            counts[key] = counts.get(key, 0) + 1
    best = (0, 0, 0)
    best_count = 0
    # sorted, so a tie always picks the same (lowest) color whatever the dict order
    for key in sorted(counts):
        if counts[key] > best_count:
            best = key
            best_count = counts[key]
    return "#%02x%02x%02x" % best


def read_qr_file(path):
    """A PNG, PGM/PPM or this program's own SVG drawing -> Result Picture
    {"reading": Reading, "format": "png" | "svg" | "other", "color": "#rrggbb", "image": Image or None}.
    Never raises: a damaged, huge or unreadable file is a failed Result."""
    try:
        if file_kind(path) == "svg":
            # the same size cap as pictures, checked before reading the text into memory
            if os.path.getsize(path) > images.MAX_FILE_BYTES:
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
    # the broad catch is the "never raises" promise: a malformed file may trip any parser error
    except Exception as error:
        return fail("cannot read " + os.path.basename(path) + " (" + type(error).__name__ + ")")


def describe(reading):
    """One line for a Reading, e.g. "version 2, level M, mask 3, 0 codeword(s) corrected"."""
    return ("version " + str(reading["version"]) + ", level " + reading["level"] + ", mask " +
            str(reading["mask"]) + ", " + str(reading["corrected"]) + " codeword(s) corrected")

# ==== stamp v1 | author=kjFriday | hmac-sha256=0603e4be01dd87abd9386bae2a76101b75f9168b2121c9b2817166e9899d7795 ====
