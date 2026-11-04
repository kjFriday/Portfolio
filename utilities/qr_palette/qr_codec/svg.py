# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/svg.py
# About: SVG drawings of codes, in color with an optional caption and logo, and reading them back.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""SVG drawings of codes, in color with an optional caption and logo, and reading them back.

matrix_to_svg's text is a format: read_svg_matrix and svg_color read a drawing back through exact
substrings, so the code's squares stay the first path and the background rect comes before it.
"""

from .records import fail, ok_result
from .tables import blank_grid
from .captions import caption_layout, caption_pixels, caption_size
from . import images
from .logos import logo_area, logo_pixel


INK = "#000000"
PAPER = "#ffffff"
SVG_GRID = 16  # font pixels in a drawing are laid out in sixteenths of a module
LOGO_CELLS = 4  # a logo in a drawing is cut into squares of a quarter of a module


def svg_number(value):
    """A coordinate for a drawing, as short as it can be: 2.5, 3, 0.3125."""
    text = "%.4f" % value
    return text.rstrip("0").rstrip(".")


def matrix_to_svg(matrix, border, color=INK, caption="", logo=None):
    """The matrix as an SVG drawing: one path of unit squares in `color` ("#rrggbb") on white. A
    logo (place_logo) follows as paths of its own colors; a caption is drawn below the quiet zone
    as one more path (and repeated as the drawing's <desc>), which makes the drawing taller. The
    code's squares always stay the first path, the one read_svg_matrix reads."""
    size = matrix["size"]
    side = size + 2 * border
    height = side
    caption_parts = []
    if caption != "":
        lines, pixel = caption_layout(caption, side * SVG_GRID, SVG_GRID)
        band = caption_size(lines, pixel, SVG_GRID)[1]
        height = side + (band + SVG_GRID - 1) // SVG_GRID
        step = svg_number(pixel / SVG_GRID)
        for corner in caption_pixels(lines, pixel, side * SVG_GRID, side * SVG_GRID):
            caption_parts.append("M" + svg_number(corner[0] / SVG_GRID) + "," + svg_number(corner[1] / SVG_GRID) +
                                 "h" + step + "v" + step + "h-" + step + "z")
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + str(side) + " " + str(height) +
             '" shape-rendering="crispEdges">\n<rect width="100%" height="100%" fill="' + PAPER + '"/>\n<path d="']
    for y in range(size):
        for x in range(size):
            if matrix["dark"][y][x]:
                parts.append("M" + str(x + border) + "," + str(y + border) + "h1v1h-1z")
    parts.append('" fill="' + color + '"/>\n')
    if logo is not None:
        parts.append(logo_paths(logo, border))
    if caption != "":
        parts.append('<path d="' + "".join(caption_parts) + '" fill="' + color + '"/>\n<desc>' +
                     caption.replace("&", "&amp;").replace("<", "&lt;") + "</desc>\n")
    parts.append("</svg>\n")
    return "".join(parts)


def logo_paths(logo, border):
    """A logo for a drawing: squares of 1/LOGO_CELLS module, runs along a row merged, one path per
    color (cut to 4 bits a channel, written #rgb), white left out -> the <path> elements as text."""
    area = logo_area(logo, border, LOGO_CELLS)
    image = logo["image"]
    runs = {}
    step = svg_number(1.0 / LOGO_CELLS)
    for y in range(area[3]):
        source_y = min(image["height"] - 1, (2 * y + 1) * image["height"] // (2 * area[3]))
        current = None
        start = 0
        for x in range(area[2] + 1):
            color = None
            if x < area[2]:
                source_x = min(image["width"] - 1, (2 * x + 1) * image["width"] // (2 * area[2]))
                red, green, blue = logo_pixel(image, source_x, source_y)
                color = "#%x%x%x" % (red >> 4, green >> 4, blue >> 4)
            if color == current:
                continue
            if current is not None and current != "#fff":
                if current not in runs:
                    runs[current] = []
                length = svg_number((x - start) / float(LOGO_CELLS))
                runs[current].append("M" + svg_number((area[0] + start) / float(LOGO_CELLS)) + "," +
                                     svg_number((area[1] + y) / float(LOGO_CELLS)) + "h" + length + "v" + step +
                                     "h-" + length + "z")
            current = color
            start = x
    parts = []
    for color in sorted(runs):
        parts.append('<path d="' + "".join(runs[color]) + '" fill="' + color + '"/>\n')
    return "".join(parts)


def read_svg_matrix(text):
    """An SVG drawing made by matrix_to_svg -> Result module grid (dark[row][column]), ready for
    decode_matrix. Other SVG drawings are refused: this reads squares, it does not draw vectors. The
    code is the first path; a caption below it makes the drawing taller, never wider."""
    if len(text) > images.MAX_FILE_BYTES:
        return fail("this drawing is too big")
    start = text.find('viewBox="0 0 ')
    begin = text.find('<path d="')
    if start < 0 or begin < 0:
        return fail("not a QR drawing made by this program")
    numbers = text[start + 13:text.find('"', start + 13)].split(" ")
    if len(numbers) != 2 or not numbers[0].isdigit() or not numbers[1].isdigit() or int(numbers[1]) < int(numbers[0]):
        return fail("not a QR drawing made by this program")
    side = int(numbers[0])
    if side < 21 or side > 177 + 2 * 40:
        return fail("not a QR drawing made by this program")
    end = text.find('"', begin + 9)
    squares = text[begin + 9:end].split("z")
    points = []
    low = side
    for square in squares:
        if square == "":
            continue
        if not square.startswith("M") or not square.endswith("h1v1h-1"):
            return fail("not a QR drawing made by this program")
        pair = square[1:len(square) - 7].split(",")
        if len(pair) != 2 or not pair[0].isdigit() or not pair[1].isdigit():
            return fail("not a QR drawing made by this program")
        x = int(pair[0])
        y = int(pair[1])
        if x >= side or y >= side:
            return fail("not a QR drawing made by this program")
        points.append((x, y))
        if x < low:
            low = x
        if y < low:
            low = y
    if len(points) == 0:
        return fail("the drawing has no squares")
    size = side - 2 * low
    if size < 21 or (size - 17) % 4 != 0:
        return fail("not a QR drawing made by this program")
    dark = blank_grid(size, False)
    for point in points:
        column = point[0] - low
        row = point[1] - low
        if column < 0 or row < 0 or column >= size or row >= size:
            return fail("not a QR drawing made by this program")
        dark[row][column] = True
    return ok_result(dark)


def svg_color(text):
    """The fill of the squares in a drawing made by matrix_to_svg, or "" when there is none."""
    begin = text.find('<path d="')
    if begin < 0:
        return ""
    found = text.find('fill="#', text.find('"', begin + 9))
    if found < 0 or len(text) < found + 13:
        return ""
    value = text[found + 6:found + 13].lower()
    for character in value[1:]:
        if character not in "0123456789abcdef":
            return ""
    return value

# ==== stamp v1 | author=kjFriday | hmac-sha256=5235e8a4bacec8b97809f18fc605049f972991d77157cb299a717b223ff898dd ====
