# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_qr_codec.py
# About: Tests for the QR codec: QR Studio's tests, ported, plus colors, logos and limits.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for the QR codec: QR Studio's tests, ported, plus colors, logos and limits.

These are QR Studio's codec tests, ported, plus colored output, transparency and limits. qr_codec is
this program's own QR encoder and decoder (ISO/IEC 18004), written without outside libraries. A short
primer for the tests below:

  matrix    a square grid of modules (dark or light), 21 x 21 at version 1 up to 177 x 177 at version 40
            (17 + 4 * version on a side); Matrix is {"dark": rows of bools, "size", "version", "level", ...}
  level     error correction L, M, Q or H: about 7, 15, 25 or 30 percent of codewords recoverable
  codewords the data bytes are split into blocks, and each block gets Reed-Solomon check bytes, computed
            as the remainder of polynomial division over GF(256); n check bytes repair up to n / 2 bad
            bytes in their block
  format    15 bits naming the level and mask, protected by a BCH (15,5) code; version 7 and up also
            carry 18 version bits under a BCH (18,6) code
  mask      one of eight patterns XORed over the data modules so no area is too even; the encoder picks
            the one with the lowest penalty when asked for -1
  image     {"width", "height", "gray": bytearray, "rgb": bytearray or None}: what the decoder reads after
            the finder patterns are found and the grid sampled

Classes, from the arithmetic up: ReedSolomonTests, TableTests, MatrixRoundTripTests (matrix only),
ImageTests (pictures, with distortions), ColorTests (colored PNG and SVG files, transparency),
CaptionTests, LogoTests, RobustnessTests (the wear score) and LimitTests (hostile and damaged files).
Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

import os
import shutil
import struct
import tempfile
import unittest
import zlib

import qr_codec as qr
import swatch

LINK = "https://example.com/generic-company"


def make(text, level):
    """The Matrix for `text` at `level`: the smallest version and the best mask (-1); a refusal fails."""
    result = qr.encode_text(text, level, 1, -1)
    if not result["ok"]:
        raise AssertionError(result["error"])
    return result["value"]


def read(image):
    """Decode an Image -> Result Reading."""
    return qr.decode_image(image)


def png_with(header, chunks):
    """PNG bytes from an IHDR tuple and a list of (kind, body) chunks.

    header is (width, height, bit depth, color type, compression, filter, interlace), as IHDR holds
    them (PNG specification 11.2.2); IEND is added at the end."""
    data = qr.PNG_SIGNATURE + qr.png_chunk(b"IHDR", struct.pack(">IIBBBBB", *header))
    for chunk in chunks:
        data = data + qr.png_chunk(chunk[0], chunk[1])
    return data + qr.png_chunk(b"IEND", b"")


class ReedSolomonTests(unittest.TestCase):
    """Reed-Solomon check bytes over GF(256), and repair up to half their count."""

    def test_spec_example_codewords(self):
        """The check bytes match the worked example in the standard, byte for byte."""
        # ISO/IEC 18004 annex I: "01234567" at 1-M.
        data = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
        self.assertEqual(qr.rs_remainder(data, 10), [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55])

    def test_corrects_up_to_half_the_ec_codewords(self):
        """16 check bytes repair 0 to 8 wrong bytes, and report how many they repaired.

        The damaged bytes sit 7 apart, each XORed with a different value, so no two errors look alike."""
        data = list(range(40))
        block = data + qr.rs_remainder(data, 16)
        for errors in range(9):
            damaged = list(block)
            for i in range(errors):
                damaged[i * 7] = damaged[i * 7] ^ (0x5A + i)
            fixed = qr.rs_correct(damaged, 16)
            self.assertTrue(fixed["ok"], errors)
            self.assertEqual(fixed["value"]["block"], block)
            self.assertEqual(fixed["value"]["errors"], errors)

    def test_too_many_errors_fail(self):
        """6 check bytes repair at most 3, so 6 wrong bytes are refused rather than mis-repaired."""
        data = list(range(20))
        block = data + qr.rs_remainder(data, 6)
        for i in range(6):
            block[i] = block[i] ^ 0xFF
        self.assertFalse(qr.rs_correct(block, 6)["ok"])


class TableTests(unittest.TestCase):
    """The capacity tables and function patterns agree with the standard and with each other."""

    def test_known_capacities(self):
        """Data codeword counts from the standard's capacity table, at the corners and in between."""
        self.assertEqual(qr.data_codeword_count(1, "M"), 16)
        self.assertEqual(qr.data_codeword_count(5, "Q"), 62)
        self.assertEqual(qr.data_codeword_count(10, "M"), 216)
        self.assertEqual(qr.data_codeword_count(40, "L"), 2956)
        self.assertEqual(qr.data_codeword_count(40, "H"), 1276)

    def test_every_version_has_room(self):
        """For every version and level, data plus check codewords fill the data modules exactly.

        raw_data_modules // 8 drops the 0 to 7 remainder bits a version leaves over."""
        for version in range(1, 41):
            for level in qr.EC_LEVELS:
                self.assertGreater(qr.data_codeword_count(version, level), 0)
                lengths = qr.block_data_lengths(version, level)
                ecc = qr.ECC_PER_BLOCK[qr.level_index(level)][version]
                self.assertEqual(sum(lengths) + ecc * len(lengths), qr.raw_data_modules(version) // 8)

    def test_function_patterns_leave_raw_modules(self):
        """Drawing the function patterns leaves exactly raw_data_modules free modules.

        The versions are the edges: 1 (no alignment pattern), 2 (the first), 6 and 7 (version
        information starts at 7), 21 and 40 (the most alignment patterns)."""
        for version in (1, 2, 6, 7, 21, 40):
            modules, function = qr.function_patterns(version)
            self.assertEqual(len(qr.data_positions(function)), qr.raw_data_modules(version))

    def test_format_and_version_codes(self):
        """The BCH-coded format bits (level M, mask 5, after the 0x5412 XOR) and version 7's bits match
        the standard's tables."""
        self.assertEqual(qr.format_bits("M", 5), 0x40CE)
        self.assertEqual(qr.version_bits(7), 0x07C94)


class MatrixRoundTripTests(unittest.TestCase):
    """Encode then decode the module grid directly, with no picture in between."""

    def test_modes_and_levels(self):
        """Numeric, alphanumeric, byte and UTF-8 text, empty text and a long text round-trip at every level.

        The texts pick the encoder's modes: digits only, upper case and a few symbols, then any bytes."""
        texts = ["01234567", "HELLO WORLD", "https://example.com/?q=1", "Grüße, 世界", "", "a" * 300]
        for text in texts:
            for level in qr.EC_LEVELS:
                matrix = make(text, level)
                decoded = qr.decode_matrix(matrix["dark"])
                self.assertTrue(decoded["ok"], (text, level, decoded["error"]))
                self.assertEqual(decoded["value"]["text"], text)
                self.assertEqual(decoded["value"]["level"], level)

    def test_every_version(self):
        """Each of versions 1 to 40, forced by min_version, encodes and decodes."""
        for version in range(1, 41):
            matrix = qr.encode_text("v" + str(version), "M", version, -1)["value"]
            self.assertEqual(matrix["version"], version)
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["text"], "v" + str(version))

    def test_every_mask(self):
        """Each of the eight masks, forced, is the one the decoder reads from the format bits."""
        for mask in range(8):
            matrix = qr.encode_text("MASK TEST", "Q", 1, mask)["value"]
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["mask"], mask)

    def test_damaged_modules_are_corrected(self):
        """Ten flipped modules in one column of a level-H code are repaired, and counted as corrected."""
        matrix = make("Generic Company Inc. order 1042", "H")
        dark = matrix["dark"]
        for i in range(10):
            dark[12 + i][14] = not dark[12 + i][14]
        decoded = qr.decode_matrix(dark)
        self.assertTrue(decoded["ok"])
        self.assertGreater(decoded["value"]["corrected"], 0)

    def test_too_long(self):
        """3000 bytes exceed version 40-L's 2953-byte capacity, and level "Z" does not exist."""
        self.assertFalse(qr.encode_text("x" * 3000, "L", 1, -1)["ok"])
        self.assertFalse(qr.encode_text("x", "Z", 1, -1)["ok"])


class ImageTests(unittest.TestCase):
    """Reading LINK from black-on-white pictures, turned, mirrored, scaled, noisy, warped and shaded."""

    def setUp(self):
        """LINK at level M, drawn at 5 pixels per module with a 4-module quiet zone."""
        self.matrix = make(LINK, "M")
        self.image = qr.matrix_to_image(self.matrix, 5, 4)

    def check(self, image):
        """Assert that `image` reads as LINK."""
        result = read(image)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["value"]["text"], LINK)

    def test_png_round_trip(self):
        """write_png then read_png gives the same gray pixels, which still read."""
        loaded = qr.read_png(qr.write_png(self.image))
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["value"]["gray"], self.image["gray"])
        self.check(loaded["value"])

    def test_versions_in_pictures(self):
        """Small to large versions (1 character up to 700) read from pictures at 3 pixels per module."""
        for text in ("1", "A" * 60, "b" * 200, "c" * 700):
            matrix = make(text, "L")
            result = read(qr.matrix_to_image(matrix, 3, 4))
            self.assertTrue(result["ok"], (matrix["version"], result["error"]))
            self.assertEqual(result["value"]["text"], text)

    def test_rotations(self):
        """The picture reads after one, two and three quarter turns."""
        image = self.image
        for turn in range(3):
            image = qr.rotate_image(image)
            self.check(image)

    def test_mirrored(self):
        """A left-right mirror image still reads (a code seen through glass or printed reversed)."""
        mirrored = qr.make_image(self.image["width"], self.image["height"], 255)
        width = self.image["width"]
        for y in range(self.image["height"]):
            for x in range(width):
                mirrored["gray"][y * width + x] = self.image["gray"][y * width + (width - 1 - x)]
        self.check(mirrored)

    def test_odd_scale(self):
        """Scaled by 1.37, modules are no longer a whole number of pixels, and the grid is still sampled."""
        self.check(qr.scale_image(self.image, 1.37))

    def test_noise(self):
        """2 percent of pixels set to random grays (seed 7) still read."""
        self.check(qr.add_noise(self.image, 0.02, 7))

    def test_perspective(self):
        """A picture stretched to an uneven four-cornered shape, as a camera at an angle sees it, still reads.

        The corners (top-left, top-right, bottom-right, bottom-left) are each moved a few percent of the
        side inwards, by different amounts."""
        side = self.image["width"]
        corners = [(side * 0.08, side * 0.03), (side * 0.95, side * 0.10),
                   (side * 0.90, side * 0.97), (side * 0.03, side * 0.88)]
        self.check(qr.warp_image(self.image, corners))

    def test_low_contrast_gradient(self):
        """A low-contrast picture on a left-to-right shading still reads.

        Each pixel becomes a shade from 60 at the left to just under 140 at the right, plus 100 for a
        light module: dark modules end up about 60 to 140, light ones about 160 to 240."""
        image = {"width": self.image["width"], "height": self.image["height"],
                 "gray": bytearray(self.image["gray"]), "rgb": None}
        width = image["width"]
        for y in range(image["height"]):
            for x in range(width):
                value = image["gray"][y * width + x]
                shade = 60 + x * 80 // width
                image["gray"][y * width + x] = shade + value * 100 // 255
        self.check(image)

    def test_nothing_there(self):
        """A blank white picture is a failed reading, not a crash."""
        self.assertFalse(read(qr.make_image(80, 80, 255))["ok"])

    def test_svg(self):
        """The SVG drawing is one path of unit squares ("h1v1h-1z" after each move) in black by default."""
        svg = qr.matrix_to_svg(self.matrix, 4)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("h1v1h-1z", svg)
        self.assertIn('fill="#000000"', svg)


class ColorTests(unittest.TestCase):
    """Colored codes: every usable palette color reads back with its color, in PNG and SVG files."""

    def setUp(self):
        """LINK at level M and a temporary folder."""
        self.matrix = make(LINK, "M")
        self.folder = tempfile.mkdtemp(prefix="qr_palette_codec_")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_every_usable_color_reads_back_with_its_color(self):
        """Each of swatch's usable colors, as a two-color palette PNG, reads as LINK and gives its color back."""
        for color in swatch.usable_colors():
            loaded = qr.read_png(qr.matrix_to_color_png(self.matrix, 3, 4, color))
            self.assertTrue(loaded["ok"], color)
            reading = read(loaded["value"])
            self.assertTrue(reading["ok"], color + ": " + reading["error"])
            self.assertEqual(reading["value"]["text"], LINK)
            self.assertEqual(qr.dark_color(loaded["value"]), color)

    def test_files_keep_text_and_color(self):
        """Saved .png, .svg and upper-case .SVG files read back with text, color and format, and leave no
        .part file behind."""
        for name in ("code.png", "code.svg", "CODE.SVG"):
            path = os.path.join(self.folder, name)
            self.assertTrue(qr.save_matrix(self.matrix, path, 4, "#006633")["ok"])
            self.assertFalse(os.path.exists(path + ".part"))
            picture = qr.read_qr_file(path)
            self.assertTrue(picture["ok"], picture["error"])
            self.assertEqual(picture["value"]["reading"]["text"], LINK)
            self.assertEqual(picture["value"]["color"], "#006633")
            self.assertEqual(picture["value"]["format"], qr.file_kind(path))

    def test_svg_reader_takes_back_the_matrix(self):
        """read_svg_matrix returns the exact module grid of a drawing, and svg_color its fill."""
        grid = qr.read_svg_matrix(qr.matrix_to_svg(self.matrix, 2, "#3366cc"))
        self.assertTrue(grid["ok"])
        self.assertEqual(grid["value"], self.matrix["dark"])
        self.assertEqual(qr.svg_color(qr.matrix_to_svg(self.matrix, 4, "#3366cc")), "#3366cc")

    def test_svg_reader_refuses_other_drawings(self):
        """Refused: empty text, an SVG with no path, a square that is not one module, a viewBox that is
        not square, and a square outside the viewBox."""
        for text in ("", "<svg/>", '<svg viewBox="0 0 30 30"><path d="M1,1h2v2z"/></svg>',
                     '<svg viewBox="0 0 31 30"><path d="M4,4h1v1h-1z"/></svg>',
                     '<svg viewBox="0 0 37 37"><path d="M4,4h1v1h-1zM99,4h1v1h-1z"/></svg>'):
            self.assertFalse(qr.read_svg_matrix(text)["ok"], text)

    def test_gray_pictures_have_a_gray_dark_color(self):
        """A gray-only picture (no rgb) reports black as its dark color."""
        self.assertEqual(qr.dark_color(qr.matrix_to_image(self.matrix, 3, 4)), "#000000")

    def test_palette_transparency_is_laid_over_white(self):
        """A palette PNG whose white entry is made transparent (a tRNS chunk) is read as laid over white.

        For a palette PNG, tRNS holds one alpha byte per palette entry, and it must come before IDAT
        (PNG specification 11.3.2.1), so it is spliced in just ahead of the IDAT chunk's length."""
        png = bytearray(qr.matrix_to_color_png(self.matrix, 3, 4, "#336633"))
        # the 4 bytes before "IDAT" are that chunk's length
        end = png.index(b"IDAT") - 4
        alpha = qr.png_chunk(b"tRNS", bytes([0, 255]))  # the white entry fully transparent
        png = bytes(png[:end]) + alpha + bytes(png[end:])
        loaded = qr.read_png(png)
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["value"]["gray"][0], 255)
        self.assertEqual(read(loaded["value"])["value"]["text"], LINK)

    def test_gray_key_transparency(self):
        """A grayscale PNG whose tRNS names gray 0 as transparent turns every black pixel white.

        For gray PNGs, tRNS holds one 16-bit gray value: pixels of exactly that value are fully
        transparent. The picture is built by hand: color type 0, 8 bits, each row led by filter byte 0
        (none)."""
        image = qr.matrix_to_image(self.matrix, 3, 4)
        width = image["width"]
        rows = bytearray()
        for y in range(image["height"]):
            rows.append(0)
            rows.extend(image["gray"][y * width:(y + 1) * width])
        png = png_with((width, image["height"], 8, 0, 0, 0, 0),
                       [(b"tRNS", struct.pack(">H", 0)), (b"IDAT", zlib.compress(bytes(rows)))])
        loaded = qr.read_png(png)
        self.assertTrue(loaded["ok"])
        self.assertEqual(max(loaded["value"]["gray"]), 255)
        self.assertEqual(min(loaded["value"]["gray"]), 255)  # black was the transparent key


class CaptionTests(unittest.TestCase):
    """A short link's address printed under its code, in the code's color, in PNG and SVG."""

    def setUp(self):
        """A short link, its caption (the address without the scheme), its level-M code and a folder."""
        self.url = "HTTPS://GO.EXAMPLE.COM/12345674"
        self.caption = "GO.EXAMPLE.COM/12345674"
        self.matrix = make(self.url, "M")
        self.folder = tempfile.mkdtemp(prefix="qr_palette_caption_")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_caption_goes_under_the_code_and_the_code_still_reads(self):
        """At 2, 3 and 8 pixels per module the picture grows taller than the code and its 4-module quiet
        zone, and still reads in its color."""
        for scale in (2, 3, 8):
            loaded = qr.read_png(qr.matrix_to_color_png(self.matrix, scale, 4, "#3366cc", self.caption))
            self.assertTrue(loaded["ok"])
            side = (self.matrix["size"] + 8) * scale
            self.assertGreater(loaded["value"]["height"], side)
            self.assertGreaterEqual(loaded["value"]["width"], side)
            self.assertEqual(read(loaded["value"])["value"]["text"], self.url, scale)
            self.assertEqual(qr.dark_color(loaded["value"]), "#3366cc")

    def test_drawings_with_a_caption(self):
        """An SVG keeps the caption as its <desc> and the code as its first path, so the grid and color
        still read; saved PNG and SVG files with a caption read back too."""
        text = qr.matrix_to_svg(self.matrix, 4, "#006633", self.caption)
        self.assertIn("<desc>" + self.caption + "</desc>", text)
        grid = qr.read_svg_matrix(text)
        self.assertTrue(grid["ok"], grid["error"])
        self.assertEqual(grid["value"], self.matrix["dark"])
        self.assertEqual(qr.svg_color(text), "#006633")
        for name in ("short.png", "short.svg"):
            path = os.path.join(self.folder, name)
            self.assertTrue(qr.save_matrix(self.matrix, path, 4, "#006633", self.caption)["ok"])
            picture = qr.read_qr_file(path)
            self.assertTrue(picture["ok"], picture["error"])
            self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["color"]), (self.url, "#006633"))

    def test_layout(self):
        """Line breaks and font pixel sizes for a caption, worked out by hand.

        33 * 8 is a version-2 code (25 modules) with its quiet zone at 8 pixels per module. The full
        address is too long for one line at a quarter module per font pixel, so it splits after the
        last "/" at 2 pixels; "SHORT/1" fits one line at the cap of half a module (4). A line of n
        glyphs is 6 * n - 1 font pixels wide, so ["AB", "C"] at 2 is 22 pixels wide, and two 7-pixel
        lines, a 2-pixel gap and a module of margin high."""
        self.assertEqual(qr.caption_layout(self.caption, 33 * 8, 8), (["GO.EXAMPLE.COM/", "12345674"], 2))
        self.assertEqual(qr.caption_layout("SHORT/1", 33 * 8, 8), (["SHORT/1"], 4))
        self.assertEqual(qr.caption_size(["AB", "C"], 2, 8), (22, 7 * 2 * 2 + 2 * 2 + 8))

    def test_every_character_of_an_address_has_its_own_glyph(self):
        """Every character a short address can hold has a 5 x 7 glyph of "#" and "." only, and no two
        glyphs are the same."""
        seen = []
        for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-:":
            glyph = qr.GLYPHS[character]
            self.assertEqual(len(glyph), 7, character)
            for row in glyph:
                self.assertEqual(len(row), 5, character)
                self.assertEqual(row.replace("#", "").replace(".", ""), "", character)
            self.assertNotIn(glyph, seen, character)
            seen.append(glyph)


# a short link that makes a small code, and a long link that needs version 7 or more with a logo
SHORT = "HTTPS://GO.EXAMPLE.COM/12345678"
LONG = "https://www.example.com/events/summer-market-2026?day=saturday&stall=14"


def sample_logo(side):
    """A logo for the tests: an orange disc with a dark blue square in it, on white.

    The gray channel uses the ITU-R BT.601 luma weights (0.299, 0.587, 0.114), in thousandths."""
    image = qr.make_image(side, side, 255)
    image["rgb"] = bytearray(b"\xff") * (side * side * 3)
    for y in range(side):
        for x in range(side):
            # distance from the centre of the picture to the centre of this pixel
            dx = x - side / 2.0 + 0.5
            dy = y - side / 2.0 + 0.5
            color = None
            if dx * dx + dy * dy <= (side / 2.0) ** 2:
                color = (240, 140, 20)
            if abs(dx) < side / 5.0 and abs(dy) < side / 5.0:
                color = (20, 40, 120)
            if color is not None:
                index = y * side + x
                image["rgb"][3 * index:3 * index + 3] = bytes(color)
                image["gray"][index] = (299 * color[0] + 587 * color[1] + 114 * color[2]) // 1000
    return image


class LogoTests(unittest.TestCase):
    """Codes with a logo in the middle: level H, a blank square that spares the function patterns."""

    def setUp(self):
        """A temporary folder."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_logo_")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_logo_code_reads_back_in_a_sample_of_usable_colors(self):
        """Every 20th usable color, as PNG and SVG with the logo drawn in, reads back with its text and color."""
        placed = qr.place_logo(SHORT, sample_logo(48))
        self.assertTrue(placed["ok"], placed["error"])
        for color in swatch.usable_colors()[::20]:
            for kind in ("png", "svg"):
                path = os.path.join(self.folder, color[1:] + "." + kind)
                self.assertTrue(qr.save_matrix(placed["value"]["matrix"], path, 4, color, "", placed["value"]["logo"])["ok"])
                picture = qr.read_qr_file(path)
                self.assertTrue(picture["ok"], color + " " + kind + ": " + picture["error"])
                self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["color"]), (SHORT, color))

    def test_the_logo_square(self):
        """The logo's square is level H, at most 15 percent of the modules, centred, blank, and covers no
        finder, timing, format or version module.

        LONG needs version 7 or more, where the code's central alignment pattern sits under the square;
        alignment patterns may be covered."""
        for text in (SHORT, LONG):
            placed = qr.place_logo(text, sample_logo(48))["value"]
            matrix = placed["matrix"]
            row, column, side = placed["logo"]["box"]
            self.assertEqual(matrix["level"], "H")
            self.assertLessEqual(side * side, 0.15 * matrix["size"] * matrix["size"])
            self.assertEqual((row * 2 + side, column), (matrix["size"], row))  # in the very middle
            protected = qr.protected_modules(matrix["version"])
            for y in range(row, row + side):
                for x in range(column, column + side):
                    self.assertFalse(matrix["dark"][y][x])
                    self.assertFalse(protected[y][x])
        self.assertGreaterEqual(qr.place_logo(LONG, sample_logo(48))["value"]["matrix"]["version"], 7)  # over an
        # alignment pattern, which may be covered

    def test_too_much_logo_is_refused(self):
        """A logo share of half the code cannot read, so it is refused; a logo picture over MAX_LOGO_SIDE
        pixels is refused as too big."""
        saved = qr.LOGO_SHARES
        try:
            qr.LOGO_SHARES = (0.5,)
            refused = qr.place_logo(LONG, sample_logo(48))
            self.assertFalse(refused["ok"])
            self.assertIn("hide too much", refused["error"])
        finally:
            qr.LOGO_SHARES = saved
        self.assertIn("too big", qr.place_logo(SHORT, qr.make_image(qr.MAX_LOGO_SIDE + 1, 10, 0))["error"])

    def test_the_code_stays_the_first_path_of_a_drawing(self):
        """With a logo, the SVG's first path is still the code, the logo's colors follow in 3-digit hex
        with no white, and a PNG becomes truecolor with the logo's own pixels in the middle.

        png[25] is the IHDR color type: 8 signature bytes, then the chunk's length (4), its type (4),
        width (4), height (4) and bit depth (1)."""
        placed = qr.place_logo(SHORT, sample_logo(48))["value"]
        svg = qr.matrix_to_svg(placed["matrix"], 4, "#3366cc", "GO.EXAMPLE.COM/12345678", placed["logo"])
        self.assertEqual(qr.svg_color(svg), "#3366cc")
        self.assertIn('fill="#f81"', svg)  # the disc, cut to 4 bits a channel
        self.assertIn('fill="#127"', svg)  # the square
        self.assertNotIn('fill="#fff"', svg)
        self.assertEqual(qr.decode_matrix(qr.read_svg_matrix(svg)["value"])["value"]["text"], SHORT)
        png = qr.picture_bytes(placed["matrix"], 4, "#3366cc", "png", "", placed["logo"])
        self.assertEqual(png[25], 2)  # truecolor: the logo has colors of its own
        image = qr.read_png(png)["value"]
        middle = (image["height"] // 2) * image["width"] + image["width"] // 2
        self.assertEqual(bytes(image["rgb"][3 * middle:3 * middle + 3]), bytes((20, 40, 120)))


class RobustnessTests(unittest.TestCase):
    """The wear score: ten fixed kinds of damage (qr.WEAR), each of which the picture must survive."""

    def picture(self, level, color):
        """SHORT at `level` as the Image its PNG would be, 4 pixels per module, in `color`."""
        return qr.picture_image(make(SHORT, level), 4, color)

    def test_the_wear_is_the_same_every_time(self):
        """Each kind of wear gives the same pixels twice: the noise is seeded."""
        image = self.picture("H", "#000000")
        clean = read(image)["value"]
        for name in qr.WEAR:
            first = qr.worn_image(image, name, clean)
            second = qr.worn_image(image, name, clean)
            self.assertEqual((first["width"], first["height"], first["gray"]),
                             (second["width"], second["height"], second["gray"]), name)

    def test_a_fixed_code_scores_the_same(self):
        """A black level-H SHORT scores exactly 9 of 10, failing only "shrunk to a third", and the score
        reads as one line of text.

        A change here means the decoder or the wear changed; the expected score is pinned on purpose."""
        score = qr.robustness(self.picture("H", "#000000"), SHORT)
        self.assertTrue(score["ok"], score["error"])
        self.assertEqual(score["value"], {"passed": 9, "tried": 10, "failed": ["shrunk to a third"]})
        self.assertEqual(qr.describe_score(score["value"]), "9 of 10 passed; failed: shrunk to a third")
        self.assertEqual(qr.describe_score({"passed": 10, "tried": 10, "failed": []}), "10 of 10 passed")

    def test_more_error_correction_scores_at_least_as_well(self):
        """Level H passes at least as many as level L, and survives the covered corner that L does not."""
        low = qr.robustness(self.picture("L", "#3366cc"), SHORT)["value"]
        high = qr.robustness(self.picture("H", "#3366cc"), SHORT)["value"]
        self.assertGreaterEqual(high["passed"], low["passed"])
        self.assertIn("covered corner", low["failed"])
        self.assertNotIn("covered corner", high["failed"])

    def test_a_picture_that_does_not_read_is_not_scored(self):
        """No score for a blank picture, or for a picture that reads as different text."""
        self.assertFalse(qr.robustness(qr.make_image(80, 80, 255), SHORT)["ok"])
        self.assertFalse(qr.robustness(self.picture("M", "#000000"), "HTTPS://GO.EXAMPLE.COM/1")["ok"])

    def test_the_kinds_of_wear(self):
        """Each distortion on its own: a 0-degree tilt changes nothing, a 5-degree one needs a wider
        canvas, a half fade lifts black to 127, a blur leaves an even gray even, a cover whitens its box,
        grain keeps the size, and the covered corner is COVERED_SHARE of the code's side."""
        image = self.picture("M", "#000000")
        self.assertEqual(qr.tilt_image(image, 0)["gray"], image["gray"])
        tilted = qr.tilt_image(image, 5)
        self.assertGreater(tilted["width"], image["width"])
        self.assertEqual(min(qr.fade_image(image, 0.5)["gray"]), 127)
        self.assertEqual(qr.blur_image(qr.make_image(9, 9, 40), 5)["gray"], qr.make_image(9, 9, 40)["gray"])
        covered = qr.cover_image(image, (0, 0, 10))
        self.assertEqual(min(covered["gray"][0:10]), 255)
        self.assertEqual(len(qr.add_grain(image, 12, 3)["gray"]), len(image["gray"]))
        box = qr.corner_box(read(image)["value"])
        self.assertEqual(box[2], round(qr.COVERED_SHARE * 25 * 4))  # version 2: 25 modules of 4 pixels


class LimitTests(unittest.TestCase):
    """Hostile and damaged input: oversized pictures, decompression bombs, cut and corrupt files."""

    def setUp(self):
        """A temporary folder, and qr.MAX_FILE_BYTES saved, since one test lowers it (qr_codec forwards
        the setting to its home in the images module)."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_limits_")
        self.saved_cap = qr.MAX_FILE_BYTES

    def tearDown(self):
        """Restore the file size cap and remove the folder."""
        qr.MAX_FILE_BYTES = self.saved_cap
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_huge_sides_are_refused_before_reading_pixels(self):
        """A PNG or PGM claiming 100000 x 100000 pixels is refused from its header, before any memory
        for pixels is taken."""
        png = png_with((100000, 100000, 1, 0, 0, 0, 0), [(b"IDAT", zlib.compress(b"\x00" * 10))])
        result = qr.read_png(png)
        self.assertFalse(result["ok"])
        self.assertIn("too big", result["error"])
        ppm = b"P5 100000 100000 255\n" + b"\x00" * 10
        self.assertFalse(qr.read_ppm(ppm)["ok"])

    def test_data_that_unpacks_too_far_is_refused(self):
        """A decompression bomb: a 10 x 10 picture needs 110 bytes of rows, so 5 MB of zeros is refused."""
        png = png_with((10, 10, 8, 0, 0, 0, 0), [(b"IDAT", zlib.compress(b"\x00" * 5000000))])
        result = qr.read_png(png)
        self.assertFalse(result["ok"])
        self.assertIn("larger than its picture", result["error"])

    def test_damaged_files_fail_without_raising(self):
        """Cut-off PNGs, a row with an unknown filter type and malformed PPM headers are failed Results.

        Steps:
        1. Cut a good PNG every 7 bytes; no cut may raise, and any cut in the first half must fail.
        2. Unpack its rows, set the first row's filter byte to 9 (PNG defines 0 to 4) and pack it again
           as a palette PNG of white and #003399 at the same width and height.
        3. Feed a list of broken PNM headers and plain zeros."""
        good = qr.matrix_to_color_png(make(LINK, "M"), 2, 4, "#003399")
        for cut in range(0, len(good), 7):
            result = qr.read_image_bytes(good[:cut])  # never raises, even when it is cut anywhere
            if cut <= len(good) // 2:
                self.assertFalse(result["ok"], cut)
        bad_filter = bytearray(good)
        data_start = bad_filter.index(b"IDAT") + 4
        length = struct.unpack(">I", bytes(bad_filter[data_start - 8:data_start - 4]))[0]
        rows = bytearray(zlib.decompress(bytes(bad_filter[data_start:data_start + length])))
        rows[0] = 9
        # good[16:20] and good[20:24] are the IHDR width and height
        damaged = png_with((struct.unpack(">I", good[16:20])[0], struct.unpack(">I", good[20:24])[0], 8, 3, 0, 0, 0),
                           [(b"PLTE", bytes([255, 255, 255, 0, 51, 153])), (b"IDAT", zlib.compress(bytes(rows)))])
        self.assertFalse(qr.read_png(damaged)["ok"])
        # an empty file, a header cut short, sides that are not numbers, pixels cut short, 16-bit gray
        # (a maximum over 255), and bytes of no known format
        for data in (b"", b"P6\n", b"P6 x y 255\n", b"P6 4 4 255\n\x00\x01", b"P5 4 4 65535\n", b"\x00" * 64):
            self.assertFalse(qr.read_image_bytes(data)["ok"], data)

    def test_files_over_the_cap_are_not_read(self):
        """With the size cap lowered to 100 bytes, a real code's file is refused before it is read."""
        path = os.path.join(self.folder, "big.png")
        self.assertTrue(qr.save_matrix(make(LINK, "M"), path, 4, "#000000")["ok"])
        qr.MAX_FILE_BYTES = 100
        self.assertIn("too big", qr.load_image_file(path)["error"])
        self.assertFalse(qr.read_qr_file(path)["ok"])

    def test_reading_files_never_raises(self):
        """Missing files, an empty name, a folder and an SVG with no code are failed Results, not exceptions."""
        for name in ("missing.png", "missing.svg", ""):
            self.assertFalse(qr.read_qr_file(os.path.join(self.folder, name))["ok"])
        self.assertFalse(qr.read_qr_file(self.folder)["ok"])
        path = os.path.join(self.folder, "not-a-picture.svg")
        handle = open(path, "w", encoding="utf-8")
        handle.write("<svg>nothing here</svg>")
        handle.close()
        self.assertFalse(qr.read_qr_file(path)["ok"])

    def test_links(self):
        """is_link takes http(s) addresses, with surrounding spaces, and not other schemes."""
        self.assertTrue(qr.is_link(" https://example.com"))
        self.assertFalse(qr.is_link("ftp://example.com/file"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=fc4eafa571c24138a2bb8a02599223a71c0c89f1d69ebc10a113a761fefe7fa2 ====
