# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/captions.py
# About: Captions: text printed under a code (a short link to type when a camera cannot scan it).
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Captions: text printed under a code (a short link to type when a camera cannot scan it).

GLYPHS is a 5 x 7 pixel font drawn for this program. A caption's lines are centred, 7 font pixels
tall with 2 between them, one character every 6 font pixels. The picture writers (images, logos, svg)
draw captions with these functions.

Units: a "font pixel" is one dot of a glyph; `pixel` is its size in output pixels (or SVG grid units),
and `scale` is the size of one QR module in the same units. Characters missing from GLYPHS (lower
case among them) draw as a space, so a caption is expected in capitals, as short links are written.

Main flow for a picture writer:
1. caption_layout picks one or two lines and the font pixel size for the code's width.
2. caption_size gives the band to add under the code.
3. caption_pixels lists the top-left corner of every dark font pixel to paint.

Callers: images.py, logos.py and svg.py in this package; sheets.py and print_advice.py in the app.
"""


# A 5 x 7 pixel font drawn for this program: capitals, digits and the other characters of an address.
GLYPHS = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "/": (".....", "....#", "...#.", "..#..", ".#...", "#....", "....."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
}


def caption_layout(text, width, scale):
    """How a caption fits under a code `width` pixels wide at `scale` pixels per module -> (lines,
    pixel). Font pixels are at most half a module. It is one line while that allows a quarter of a
    module per font pixel, else two lines split after the last "/". Never less than 1 pixel."""
    # one module of margin on each side
    usable = width - 2 * scale
    largest = max(1, scale // 2)
    smallest = max(1, scale // 4)

    def fit(lines):
        """Largest font pixel (capped at `largest`) at which the longest line fits in `usable`.

        A line of n characters is 6 * n - 1 font pixels wide: 5 per glyph plus 1 between glyphs.
        """
        longest = 0
        for line in lines:
            longest = max(longest, len(line))
        return min(largest, usable // max(1, 6 * longest - 1))

    lines = [text]
    pixel = fit(lines)
    # a trailing "/" is ignored when choosing the cut so the second line is never empty
    if pixel < smallest and "/" in text.rstrip("/"):
        cut = text.rstrip("/").rindex("/") + 1
        lines = [text[:cut], text[cut:]]
        pixel = fit(lines)
    return lines, max(1, pixel)


def caption_size(lines, pixel, scale):
    """(width, height) in pixels of a caption: lines of 7 font pixels, 2 between them, and one module
    of margin below."""
    longest = 0
    for line in lines:
        longest = max(longest, len(line))
    return (6 * longest - 1) * pixel, len(lines) * 7 * pixel + (len(lines) - 1) * 2 * pixel + scale


def caption_pixels(lines, pixel, width, top):
    """The top-left corner of every font pixel of a caption, each line centred in `width`.

    top is the y of the first line, usually the bottom edge of the code; only dark ("#") font pixels
    are listed, as (x, y) tuples in the caller's units.
    """
    corners = []
    for index in range(len(lines)):
        line = lines[index]
        left = (width - (6 * len(line) - 1) * pixel) // 2
        # 9 = 7 rows of glyph + 2 rows of gap between lines
        line_top = top + index * 9 * pixel
        for place in range(len(line)):
            glyph = GLYPHS.get(line[place], GLYPHS[" "])
            for row in range(7):
                for column in range(5):
                    if glyph[row][column] == "#":
                        corners.append((left + (6 * place + column) * pixel, line_top + row * pixel))
    return corners

# ==== stamp v1 | author=kjFriday | hmac-sha256=59e7e72e7afc5371fa3af8e228928dc69081d95e918c4daf8f609e5925324cdf ====
