# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/logos.py
# About: Logos: a small picture in the middle of a level H code, and the PNG that shows it.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Logos: a small picture in the middle of a level H code, and the PNG that shows it.

place_logo keeps a logo only when the code still reads with the logo's modules left blank.
LOGO_SHARES has its one home here; setting qr_codec.LOGO_SHARES (as the tests do) sets it here.
"""

import math
import struct
import zlib

from .records import fail, ok_result
from .tables import blank_grid, draw_finder, draw_format, draw_version, set_function, size_for_version
from .encode import encode_text
from .decode import decode_matrix
from .captions import caption_layout, caption_pixels, caption_size
from .images import PNG_SIGNATURE, png_chunk


LOGO_SHARES = (0.15, 0.12, 0.09)  # a logo's square, as a share of the code's modules, largest first
MAX_LOGO_SIDE = 1024  # a logo picture may be at most this many pixels wide and tall


def protected_modules(version):
    """The modules a logo must never cover -> grid of bools: the finder patterns with their
    separators, the timing patterns, and the format and version information. Alignment patterns may
    be covered, as on most logo codes: the finder patterns are enough to find the grid."""
    size = size_for_version(version)
    modules = blank_grid(size, False)
    protected = blank_grid(size, False)
    for i in range(size):
        set_function(modules, protected, 6, i, False)
        set_function(modules, protected, i, 6, False)
    draw_finder(modules, protected, 3, 3)
    draw_finder(modules, protected, size - 4, 3)
    draw_finder(modules, protected, 3, size - 4)
    draw_format(modules, protected, 0)
    draw_version(modules, protected, version)
    return protected


def logo_box(matrix, share):
    """The square in the middle of a code for a logo that covers at most `share` of its modules ->
    [row, column, side], or None when no square of at least 5 modules misses the protected modules.
    The side is odd, so the square sits exactly in the middle."""
    size = matrix["size"]
    side = int(math.sqrt(share * size * size))
    if side % 2 == 0:
        side = side - 1
    protected = protected_modules(matrix["version"])
    while side >= 5:
        start = (size - side) // 2
        clear = True
        for row in range(start, start + side):
            for column in range(start, start + side):
                if protected[row][column]:
                    clear = False
        if clear:
            return [start, start, side]
        side = side - 2
    return None


def blank_box(matrix, box):
    """A copy of the matrix with every module in box left light."""
    dark = []
    for row in matrix["dark"]:
        dark.append(list(row))
    for row in range(box[0], box[0] + box[2]):
        for column in range(box[1], box[1] + box[2]):
            dark[row][column] = False
    return {"size": matrix["size"], "dark": dark, "version": matrix["version"], "level": matrix["level"],
            "mask": matrix["mask"]}


def place_logo(text, image):
    """A level H code for `text` with room for a logo picture (an Image) in its middle -> Result
    {"matrix": the code with the logo's square left blank, "logo": Logo}. The largest square of
    LOGO_SHARES whose blank code still reads is taken (the honest test: the logo hides those
    modules), at the smallest version and then one version up; else the logo is refused."""
    if image["width"] > MAX_LOGO_SIDE or image["height"] > MAX_LOGO_SIDE:
        return fail("the logo is too big: pick a picture at most " + str(MAX_LOGO_SIDE) + " pixels a side")
    first = encode_text(text, "H", 1, -1)
    if not first["ok"]:
        return first
    smallest = first["value"]["version"]
    for version in (smallest, smallest + 1):
        made = first
        if version != smallest:
            if version > 40:
                break
            made = encode_text(text, "H", version, -1)
            if not made["ok"]:
                break
        for share in LOGO_SHARES:
            box = logo_box(made["value"], share)
            if box is None:
                continue
            blank = blank_box(made["value"], box)
            reading = decode_matrix(blank["dark"])
            if reading["ok"] and reading["value"]["text"] == text:
                return ok_result({"matrix": blank, "logo": {"image": image, "box": box}})
    return fail("a logo would hide too much of this code: use a shorter link, or Short link")


def logo_pixel(image, x, y):
    """(r, g, b) of one pixel of a logo picture (gray pictures have r = g = b)."""
    index = y * image["width"] + x
    if image["rgb"] is None:
        return image["gray"][index], image["gray"][index], image["gray"][index]
    return image["rgb"][3 * index], image["rgb"][3 * index + 1], image["rgb"][3 * index + 2]


def logo_area(logo, border, scale):
    """Where a logo's picture goes in a picture drawn `scale` units per module with `border` modules of
    quiet zone -> (left, top, width, height): in its square less one module of white margin, as large
    as its proportions allow, centred."""
    row, column, side = logo["box"]
    room = (side - 2) * scale
    image = logo["image"]
    ratio = min(room / float(image["width"]), room / float(image["height"]))
    width = max(1, int(image["width"] * ratio))
    height = max(1, int(image["height"] * ratio))
    return ((column + 1 + border) * scale + (room - width) // 2, (row + 1 + border) * scale + (room - height) // 2,
            width, height)


def matrix_to_logo_png(matrix, scale, border, color, caption, logo):
    """matrix_to_color_png with a logo: truecolor PNG bytes (colour type 2), since a logo has colors
    of its own. The matrix should already have the logo's square blank (place_logo); the logo is
    resampled to fit by nearest neighbour."""
    size = matrix["size"]
    side = (size + 2 * border) * scale
    width = side
    height = side
    lines = []
    pixel = 1
    if caption != "":
        lines, pixel = caption_layout(caption, side, scale)
        band = caption_size(lines, pixel, scale)
        width = max(side, band[0] + 2 * scale)
        height = side + band[1]
    ink = bytes([int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)])
    canvas = bytearray(b"\xff") * (width * height * 3)
    left = (width - side) // 2
    for module_y in range(size):
        for module_x in range(size):
            if matrix["dark"][module_y][module_x]:
                x = left + (module_x + border) * scale
                for y in range((module_y + border) * scale, (module_y + border + 1) * scale):
                    canvas[3 * (y * width + x):3 * (y * width + x + scale)] = ink * scale
    for corner in caption_pixels(lines, pixel, width, side):
        for y in range(corner[1], corner[1] + pixel):
            canvas[3 * (y * width + corner[0]):3 * (y * width + corner[0] + pixel)] = ink * pixel
    area = logo_area(logo, border, scale)
    image = logo["image"]
    for y in range(area[3]):
        source_y = min(image["height"] - 1, (2 * y + 1) * image["height"] // (2 * area[3]))
        for x in range(area[2]):
            source_x = min(image["width"] - 1, (2 * x + 1) * image["width"] // (2 * area[2]))
            start = 3 * ((area[1] + y) * width + left + area[0] + x)
            canvas[start:start + 3] = bytes(logo_pixel(image, source_x, source_y))
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(canvas[3 * y * width:3 * (y + 1) * width])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
            png_chunk(b"IEND", b""))

# ==== stamp v1 | author=kjFriday | hmac-sha256=3cb8aae53af21a367e7025348077a39560922bbea53a6d1bea31d4558cb8b88e ====
