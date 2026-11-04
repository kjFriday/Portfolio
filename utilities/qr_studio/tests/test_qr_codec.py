# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: tests/test_qr_codec.py
# About: Tests for QR Studio's codec, the qr_codec package: Reed-Solomon, the tables, matrices and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Tests for QR Studio's codec: Reed-Solomon, the tables, matrices and pictures.

The codec is the qr_codec package. Run from the program folder: python -m unittest discover -s tests
(python -m puts the program folder on the import path, so `import qr_codec` finds the package).

The classes go from the inside out, the order to port and debug in:
  1. ReedSolomonTests        error-correction codewords and repairs, against the standard's example
  2. TableTests              capacities, block layout, function patterns, format and version words
  3. MatrixRoundTripTests    text -> Matrix -> text, with no picture in between
  4. ImageTests              text -> picture -> changed picture -> text, through the whole reader
"""

import unittest

import qr_codec as qr


def make(text, level):
    """Encode `text` at `level` (smallest version, best mask) -> Matrix; a failure fails the test."""
    result = qr.encode_text(text, level, 1, -1)
    if not result["ok"]:
        raise AssertionError(result["error"])
    return result["value"]


def read(image):
    """Look for a code in the Image -> Result Reading (decode_image, under a short name)."""
    return qr.decode_image(image)


class ReedSolomonTests(unittest.TestCase):
    """Reed-Solomon over GF(256): making error-correction codewords and repairing damaged blocks."""

    def test_spec_example_codewords(self):
        """rs_remainder gives the 10 EC codewords printed in the standard's worked example."""
        # ISO/IEC 18004 annex I: "01234567" at 1-M.
        data = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
        self.assertEqual(qr.rs_remainder(data, 10), [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55])

    def test_corrects_up_to_half_the_ec_codewords(self):
        """16 EC codewords repair 0 to 8 wrong codewords, exactly, and count them.

        Reed-Solomon with n EC codewords fixes up to n // 2 errors at unknown places. The errors sit 7
        apart, across data and EC codewords, with a different flip pattern each.
        """
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
        """Six wrong codewords against 6 EC codewords (limit 3) are reported as a failure, not mis-fixed."""
        data = list(range(20))
        block = data + qr.rs_remainder(data, 6)
        for i in range(6):
            block[i] = block[i] ^ 0xFF
        self.assertFalse(qr.rs_correct(block, 6)["ok"])


class TableTests(unittest.TestCase):
    """The version tables against figures from the standard and against each other."""

    def test_known_capacities(self):
        """Data codeword counts match the standard's capacity table at both ends and between."""
        self.assertEqual(qr.data_codeword_count(1, "M"), 16)
        self.assertEqual(qr.data_codeword_count(5, "Q"), 62)
        self.assertEqual(qr.data_codeword_count(10, "M"), 216)
        self.assertEqual(qr.data_codeword_count(40, "L"), 2956)
        self.assertEqual(qr.data_codeword_count(40, "H"), 1276)

    def test_every_version_has_room(self):
        """For all 160 version-level pairs the blocks, data plus EC, fill the codewords exactly.

        A typo in ECC_PER_BLOCK or BLOCK_COUNT would break this sum; the leftover remainder bits
        (raw modules modulo 8) are not codewords and are left out by the floor division.
        """
        for version in range(1, 41):
            for level in qr.EC_LEVELS:
                self.assertGreater(qr.data_codeword_count(version, level), 0)
                lengths = qr.block_data_lengths(version, level)
                ecc = qr.ECC_PER_BLOCK[qr.level_index(level)][version]
                self.assertEqual(sum(lengths) + ecc * len(lengths), qr.raw_data_modules(version) // 8)

    def test_function_patterns_leave_raw_modules(self):
        """The drawn function patterns leave exactly raw_data_modules modules for data.

        The versions chosen cover no alignment pattern (1), the first one (2), the last without
        version blocks (6), the first with them (7), a mid size (21) and the largest (40).
        """
        for version in (1, 2, 6, 7, 21, 40):
            modules, function = qr.function_patterns(version)
            self.assertEqual(len(qr.data_positions(function)), qr.raw_data_modules(version))

    def test_format_and_version_codes(self):
        """The BCH words match the standard's examples: format M with mask 5, and version 7.

        Format: 5 bits (level and mask) plus 10 BCH (15,5) check bits, then XOR 0x5412 so it is never
        all zero. Version: 6 bits plus 12 BCH (18,6) check bits, with no XOR.
        """
        self.assertEqual(qr.format_bits("M", 5), 0x40CE)
        self.assertEqual(qr.version_bits(7), 0x07C94)


class MatrixRoundTripTests(unittest.TestCase):
    """Encoder and matrix decoder against each other, with no picture in between."""

    def test_modes_and_levels(self):
        """Each mode and level round-trips: numeric, alphanumeric, byte, UTF-8 beyond Latin-1, empty, long.

        "a" * 300 forces a version well above 1, so multi-block interleaving is exercised too.
        """
        texts = ["01234567", "HELLO WORLD", "https://example.com/?q=1", "Grüße, 世界", "", "a" * 300]
        for text in texts:
            for level in qr.EC_LEVELS:
                matrix = make(text, level)
                decoded = qr.decode_matrix(matrix["dark"])
                self.assertTrue(decoded["ok"], (text, level, decoded["error"]))
                self.assertEqual(decoded["value"]["text"], text)
                self.assertEqual(decoded["value"]["level"], level)

    def test_every_version(self):
        """A forced minimum version is honoured for 1 to 40, and each decodes (version blocks from 7 up)."""
        for version in range(1, 41):
            matrix = qr.encode_text("v" + str(version), "M", version, -1)["value"]
            self.assertEqual(matrix["version"], version)
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["text"], "v" + str(version))

    def test_every_mask(self):
        """Each of the 8 masks can be forced, and the decoder reads back the same mask from the format bits."""
        for mask in range(8):
            matrix = qr.encode_text("MASK TEST", "Q", 1, mask)["value"]
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["mask"], mask)

    def test_damaged_modules_are_corrected(self):
        """Ten flipped modules in one column of the data area are repaired, and counted as corrected.

        Level H restores about 30 percent; column 14 from row 12 down stays clear of the finders,
        timing lines and format bits in this small version.
        """
        matrix = make("Generic Company Inc. order 1042", "H")
        dark = matrix["dark"]
        for i in range(10):
            dark[12 + i][14] = not dark[12 + i][14]
        decoded = qr.decode_matrix(dark)
        self.assertTrue(decoded["ok"])
        self.assertGreater(decoded["value"]["corrected"], 0)

    def test_too_long(self):
        """Encoding fails cleanly for more than 40-L holds (2953 bytes) and for an unknown level."""
        self.assertFalse(qr.encode_text("x" * 3000, "L", 1, -1)["ok"])
        self.assertFalse(qr.encode_text("x", "Z", 1, -1)["ok"])


class ImageTests(unittest.TestCase):
    """The whole reader on pictures: clean, turned, mirrored, resized, noisy, tilted and unevenly lit."""

    def setUp(self):
        """One level M link code, drawn at 5 pixels per module with a 4-module quiet zone."""
        self.matrix = make("https://example.com/generic-company", "M")
        self.image = qr.matrix_to_image(self.matrix, 5, 4)

    def check(self, image):
        """Assert that the reader finds setUp's link in `image`."""
        result = read(image)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["value"]["text"], "https://example.com/generic-company")

    def test_png_round_trip(self):
        """write_png then read_png gives back the same gray bytes, and the code still reads."""
        loaded = qr.read_png(qr.write_png(self.image))
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["value"]["gray"], self.image["gray"])
        self.check(loaded["value"])

    def test_versions_in_pictures(self):
        """Small to large codes read from 3-pixel-per-module pictures.

        The lengths step from version 1 up into the version-block range (700 bytes at L), so alignment
        patterns and the version recovery are both exercised.
        """
        for text in ("1", "A" * 60, "b" * 200, "c" * 700):
            matrix = make(text, "L")
            result = read(qr.matrix_to_image(matrix, 3, 4))
            self.assertTrue(result["ok"], (matrix["version"], result["error"]))
            self.assertEqual(result["value"]["text"], text)

    def test_rotations(self):
        """The code reads after one, two and three quarter turns (order_finders sorts the corners out)."""
        image = self.image
        for turn in range(3):
            image = qr.rotate_image(image)
            self.check(image)

    def test_mirrored(self):
        """A left-right mirrored code reads: the decoder also tries the transposed module grid."""
        mirrored = qr.make_image(self.image["width"], self.image["height"], 255)
        width = self.image["width"]
        for y in range(self.image["height"]):
            for x in range(width):
                mirrored["gray"][y * width + x] = self.image["gray"][y * width + (width - 1 - x)]
        self.check(mirrored)

    def test_odd_scale(self):
        """A code at a non-whole 6.85 pixels per module (5 x 1.37) reads, so module edges fall between pixels."""
        self.check(qr.scale_image(self.image, 1.37))

    def test_noise(self):
        """A code with 2 percent of its pixels set to random grays reads (seed 7, the same every run)."""
        self.check(qr.add_noise(self.image, 0.02, 7))

    def test_perspective(self):
        """A code tilted in perspective reads: each corner pulled in by a different 3 to 12 percent."""
        side = self.image["width"]
        corners = [(side * 0.08, side * 0.03), (side * 0.95, side * 0.10),
                   (side * 0.90, side * 0.97), (side * 0.03, side * 0.88)]
        self.check(qr.warp_image(self.image, corners))

    def test_low_contrast_gradient(self):
        """A faded code under a left-to-right light gradient reads.

        Each pixel becomes a base shade from 60 at the left to about 140 at the right, plus its own
        value squeezed to 0..100: black and white differ by only 100 levels, and the background
        brightens across the picture, as under uneven light.
        """
        image = {"width": self.image["width"], "height": self.image["height"], "gray": bytearray(self.image["gray"])}
        width = image["width"]
        for y in range(image["height"]):
            for x in range(width):
                value = image["gray"][y * width + x]
                shade = 60 + x * 80 // width
                image["gray"][y * width + x] = shade + value * 100 // 255
        self.check(image)

    def test_nothing_there(self):
        """A plain white picture gives a failed Result, not an exception or a false reading."""
        self.assertFalse(read(qr.make_image(80, 80, 255))["ok"])

    def test_svg(self):
        """The SVG starts as an SVG document and draws modules as one-unit squares ("h1v1h-1z")."""
        svg = qr.matrix_to_svg(self.matrix, 4)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("h1v1h-1z", svg)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=5eb32df38ab70bf26f4b7aa794e3085a0e9b3907d331e242a4975256223e8aa5 ====
