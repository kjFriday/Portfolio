# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_code_studio/test_qr_studio.py
# About: Tests for the QR Studio core.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the QR Studio core. Run: python -m unittest test_qr_studio"""

import os
import shutil
import tempfile
import unittest

import qr_studio as qr


def make(text, level):
    result = qr.encode_text(text, level, 1, -1)
    if not result["ok"]:
        raise AssertionError(result["error"])
    return result["value"]


def read(image):
    return qr.decode_image(image)


class ReedSolomonTests(unittest.TestCase):
    def test_spec_example_codewords(self):
        # ISO/IEC 18004 annex I: "01234567" at 1-M.
        data = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
        self.assertEqual(qr.rs_remainder(data, 10), [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55])

    def test_corrects_up_to_half_the_ec_codewords(self):
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
        data = list(range(20))
        block = data + qr.rs_remainder(data, 6)
        for i in range(6):
            block[i] = block[i] ^ 0xFF
        self.assertFalse(qr.rs_correct(block, 6)["ok"])


class TableTests(unittest.TestCase):
    def test_known_capacities(self):
        self.assertEqual(qr.data_codeword_count(1, "M"), 16)
        self.assertEqual(qr.data_codeword_count(5, "Q"), 62)
        self.assertEqual(qr.data_codeword_count(10, "M"), 216)
        self.assertEqual(qr.data_codeword_count(40, "L"), 2956)
        self.assertEqual(qr.data_codeword_count(40, "H"), 1276)

    def test_every_version_has_room(self):
        for version in range(1, 41):
            for level in qr.LEVELS:
                self.assertGreater(qr.data_codeword_count(version, level), 0)
                lengths = qr.block_data_lengths(version, level)
                ecc = qr.ECC_PER_BLOCK[qr.level_index(level)][version]
                self.assertEqual(sum(lengths) + ecc * len(lengths), qr.raw_data_modules(version) // 8)

    def test_function_patterns_leave_raw_modules(self):
        for version in (1, 2, 6, 7, 21, 40):
            modules, function = qr.function_patterns(version)
            self.assertEqual(len(qr.data_positions(function)), qr.raw_data_modules(version))

    def test_format_and_version_codes(self):
        self.assertEqual(qr.format_bits("M", 5), 0x40CE)
        self.assertEqual(qr.version_bits(7), 0x07C94)


class MatrixRoundTripTests(unittest.TestCase):
    def test_modes_and_levels(self):
        texts = ["01234567", "HELLO WORLD", "https://example.com/?q=1", "Grüße, 世界", "", "a" * 300]
        for text in texts:
            for level in qr.LEVELS:
                matrix = make(text, level)
                decoded = qr.decode_matrix(matrix["dark"])
                self.assertTrue(decoded["ok"], (text, level, decoded["error"]))
                self.assertEqual(decoded["value"]["text"], text)
                self.assertEqual(decoded["value"]["level"], level)

    def test_every_version(self):
        for version in range(1, 41):
            matrix = qr.encode_text("v" + str(version), "M", version, -1)["value"]
            self.assertEqual(matrix["version"], version)
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["text"], "v" + str(version))

    def test_every_mask(self):
        for mask in range(8):
            matrix = qr.encode_text("MASK TEST", "Q", 1, mask)["value"]
            self.assertEqual(qr.decode_matrix(matrix["dark"])["value"]["mask"], mask)

    def test_damaged_modules_are_corrected(self):
        matrix = make("Generic Company Inc. order 1042", "H")
        dark = matrix["dark"]
        for i in range(10):
            dark[12 + i][14] = not dark[12 + i][14]
        decoded = qr.decode_matrix(dark)
        self.assertTrue(decoded["ok"])
        self.assertGreater(decoded["value"]["corrected"], 0)

    def test_too_long(self):
        self.assertFalse(qr.encode_text("x" * 3000, "L", 1, -1)["ok"])
        self.assertFalse(qr.encode_text("x", "Z", 1, -1)["ok"])


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.matrix = make("https://example.com/generic-company", "M")
        self.image = qr.matrix_to_image(self.matrix, 5, 4)

    def check(self, image):
        result = read(image)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["value"]["text"], "https://example.com/generic-company")

    def test_png_round_trip(self):
        loaded = qr.read_png(qr.write_png(self.image))
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["value"]["gray"], self.image["gray"])
        self.check(loaded["value"])

    def test_versions_in_pictures(self):
        for text in ("1", "A" * 60, "b" * 200, "c" * 700):
            matrix = make(text, "L")
            result = read(qr.matrix_to_image(matrix, 3, 4))
            self.assertTrue(result["ok"], (matrix["version"], result["error"]))
            self.assertEqual(result["value"]["text"], text)

    def test_rotations(self):
        image = self.image
        for turn in range(3):
            image = qr.rotate_image(image)
            self.check(image)

    def test_mirrored(self):
        mirrored = qr.make_image(self.image["width"], self.image["height"], 255)
        width = self.image["width"]
        for y in range(self.image["height"]):
            for x in range(width):
                mirrored["gray"][y * width + x] = self.image["gray"][y * width + (width - 1 - x)]
        self.check(mirrored)

    def test_odd_scale(self):
        self.check(qr.scale_image(self.image, 1.37))

    def test_noise(self):
        self.check(qr.add_noise(self.image, 0.02, 7))

    def test_perspective(self):
        side = self.image["width"]
        corners = [(side * 0.08, side * 0.03), (side * 0.95, side * 0.10),
                   (side * 0.90, side * 0.97), (side * 0.03, side * 0.88)]
        self.check(qr.warp_image(self.image, corners))

    def test_low_contrast_gradient(self):
        image = {"width": self.image["width"], "height": self.image["height"], "gray": bytearray(self.image["gray"])}
        width = image["width"]
        for y in range(image["height"]):
            for x in range(width):
                value = image["gray"][y * width + x]
                shade = 60 + x * 80 // width
                image["gray"][y * width + x] = shade + value * 100 // 255
        self.check(image)

    def test_nothing_there(self):
        self.assertFalse(read(qr.make_image(80, 80, 255))["ok"])

    def test_svg(self):
        svg = qr.matrix_to_svg(self.matrix, 4)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("h1v1h-1z", svg)


class HistoryTests(unittest.TestCase):
    def test_round_trip_and_dedupe(self):
        folder = tempfile.mkdtemp(prefix="qr_studio_test_")
        try:
            path = os.path.join(folder, "sub", "history.json")
            entries = qr.add_history([], "read", "one", 1.0)
            entries = qr.add_history(entries, "made", "two", 2.0)
            entries = qr.add_history(entries, "read", "one", 3.0)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["when"], 3.0)
            self.assertTrue(qr.save_history(path, entries)["ok"])
            self.assertEqual(qr.load_history(path), entries)
            self.assertEqual(qr.load_history(os.path.join(folder, "missing.json")), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_links(self):
        self.assertTrue(qr.is_link(" https://example.com"))
        self.assertFalse(qr.is_link("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=83366f21d35d5e4337cc7d49bae610f1e512a1bcaea3abb5b52b402c55160fbb ====
