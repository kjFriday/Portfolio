# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_qr_codec.py
# About: Tests for the QR codec: QR Studio's tests, ported, plus colored output, transparency and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the QR codec: QR Studio's tests, ported, plus colored output, transparency and limits."""

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
    result = qr.encode_text(text, level, 1, -1)
    if not result["ok"]:
        raise AssertionError(result["error"])
    return result["value"]


def read(image):
    return qr.decode_image(image)


def png_with(header, chunks):
    """PNG bytes from an IHDR tuple and a list of (kind, body) chunks."""
    data = qr.PNG_SIGNATURE + qr.png_chunk(b"IHDR", struct.pack(">IIBBBBB", *header))
    for chunk in chunks:
        data = data + qr.png_chunk(chunk[0], chunk[1])
    return data + qr.png_chunk(b"IEND", b"")


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
            for level in qr.EC_LEVELS:
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
            for level in qr.EC_LEVELS:
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
        self.matrix = make(LINK, "M")
        self.image = qr.matrix_to_image(self.matrix, 5, 4)

    def check(self, image):
        result = read(image)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["value"]["text"], LINK)

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
        self.assertFalse(read(qr.make_image(80, 80, 255))["ok"])

    def test_svg(self):
        svg = qr.matrix_to_svg(self.matrix, 4)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("h1v1h-1z", svg)
        self.assertIn('fill="#000000"', svg)


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.matrix = make(LINK, "M")
        self.folder = tempfile.mkdtemp(prefix="qr_palette_codec_")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_every_usable_color_reads_back_with_its_color(self):
        for color in swatch.usable_colors():
            loaded = qr.read_png(qr.matrix_to_color_png(self.matrix, 3, 4, color))
            self.assertTrue(loaded["ok"], color)
            reading = read(loaded["value"])
            self.assertTrue(reading["ok"], color + ": " + reading["error"])
            self.assertEqual(reading["value"]["text"], LINK)
            self.assertEqual(qr.dark_color(loaded["value"]), color)

    def test_files_keep_text_and_color(self):
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
        grid = qr.read_svg_matrix(qr.matrix_to_svg(self.matrix, 2, "#3366cc"))
        self.assertTrue(grid["ok"])
        self.assertEqual(grid["value"], self.matrix["dark"])
        self.assertEqual(qr.svg_color(qr.matrix_to_svg(self.matrix, 4, "#3366cc")), "#3366cc")

    def test_svg_reader_refuses_other_drawings(self):
        for text in ("", "<svg/>", '<svg viewBox="0 0 30 30"><path d="M1,1h2v2z"/></svg>',
                     '<svg viewBox="0 0 31 30"><path d="M4,4h1v1h-1z"/></svg>',
                     '<svg viewBox="0 0 37 37"><path d="M4,4h1v1h-1zM99,4h1v1h-1z"/></svg>'):
            self.assertFalse(qr.read_svg_matrix(text)["ok"], text)

    def test_gray_pictures_have_a_gray_dark_color(self):
        self.assertEqual(qr.dark_color(qr.matrix_to_image(self.matrix, 3, 4)), "#000000")

    def test_palette_transparency_is_laid_over_white(self):
        png = bytearray(qr.matrix_to_color_png(self.matrix, 3, 4, "#336633"))
        end = png.index(b"IDAT") - 4
        alpha = qr.png_chunk(b"tRNS", bytes([0, 255]))  # the white entry fully transparent
        png = bytes(png[:end]) + alpha + bytes(png[end:])
        loaded = qr.read_png(png)
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["value"]["gray"][0], 255)
        self.assertEqual(read(loaded["value"])["value"]["text"], LINK)

    def test_gray_key_transparency(self):
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
    def setUp(self):
        self.url = "HTTPS://GO.EXAMPLE.COM/12345674"
        self.caption = "GO.EXAMPLE.COM/12345674"
        self.matrix = make(self.url, "M")
        self.folder = tempfile.mkdtemp(prefix="qr_palette_caption_")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_caption_goes_under_the_code_and_the_code_still_reads(self):
        for scale in (2, 3, 8):
            loaded = qr.read_png(qr.matrix_to_color_png(self.matrix, scale, 4, "#3366cc", self.caption))
            self.assertTrue(loaded["ok"])
            side = (self.matrix["size"] + 8) * scale
            self.assertGreater(loaded["value"]["height"], side)
            self.assertGreaterEqual(loaded["value"]["width"], side)
            self.assertEqual(read(loaded["value"])["value"]["text"], self.url, scale)
            self.assertEqual(qr.dark_color(loaded["value"]), "#3366cc")

    def test_drawings_with_a_caption(self):
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
        self.assertEqual(qr.caption_layout(self.caption, 33 * 8, 8), (["GO.EXAMPLE.COM/", "12345674"], 2))
        self.assertEqual(qr.caption_layout("SHORT/1", 33 * 8, 8), (["SHORT/1"], 4))
        self.assertEqual(qr.caption_size(["AB", "C"], 2, 8), (22, 7 * 2 * 2 + 2 * 2 + 8))

    def test_every_character_of_an_address_has_its_own_glyph(self):
        seen = []
        for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-:":
            glyph = qr.GLYPHS[character]
            self.assertEqual(len(glyph), 7, character)
            for row in glyph:
                self.assertEqual(len(row), 5, character)
                self.assertEqual(row.replace("#", "").replace(".", ""), "", character)
            self.assertNotIn(glyph, seen, character)
            seen.append(glyph)


class LimitTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_limits_")
        self.saved_cap = qr.MAX_FILE_BYTES

    def tearDown(self):
        qr.MAX_FILE_BYTES = self.saved_cap
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_huge_sides_are_refused_before_reading_pixels(self):
        png = png_with((100000, 100000, 1, 0, 0, 0, 0), [(b"IDAT", zlib.compress(b"\x00" * 10))])
        result = qr.read_png(png)
        self.assertFalse(result["ok"])
        self.assertIn("too big", result["error"])
        ppm = b"P5 100000 100000 255\n" + b"\x00" * 10
        self.assertFalse(qr.read_ppm(ppm)["ok"])

    def test_data_that_unpacks_too_far_is_refused(self):
        png = png_with((10, 10, 8, 0, 0, 0, 0), [(b"IDAT", zlib.compress(b"\x00" * 5000000))])
        result = qr.read_png(png)
        self.assertFalse(result["ok"])
        self.assertIn("larger than its picture", result["error"])

    def test_damaged_files_fail_without_raising(self):
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
        damaged = png_with((struct.unpack(">I", good[16:20])[0], struct.unpack(">I", good[20:24])[0], 8, 3, 0, 0, 0),
                           [(b"PLTE", bytes([255, 255, 255, 0, 51, 153])), (b"IDAT", zlib.compress(bytes(rows)))])
        self.assertFalse(qr.read_png(damaged)["ok"])
        for data in (b"", b"P6\n", b"P6 x y 255\n", b"P6 4 4 255\n\x00\x01", b"P5 4 4 65535\n", b"\x00" * 64):
            self.assertFalse(qr.read_image_bytes(data)["ok"], data)

    def test_files_over_the_cap_are_not_read(self):
        path = os.path.join(self.folder, "big.png")
        self.assertTrue(qr.save_matrix(make(LINK, "M"), path, 4, "#000000")["ok"])
        qr.MAX_FILE_BYTES = 100
        self.assertIn("too big", qr.load_image_file(path)["error"])
        self.assertFalse(qr.read_qr_file(path)["ok"])

    def test_reading_files_never_raises(self):
        for name in ("missing.png", "missing.svg", ""):
            self.assertFalse(qr.read_qr_file(os.path.join(self.folder, name))["ok"])
        self.assertFalse(qr.read_qr_file(self.folder)["ok"])
        path = os.path.join(self.folder, "not-a-picture.svg")
        handle = open(path, "w", encoding="utf-8")
        handle.write("<svg>nothing here</svg>")
        handle.close()
        self.assertFalse(qr.read_qr_file(path)["ok"])

    def test_links(self):
        self.assertTrue(qr.is_link(" https://example.com"))
        self.assertFalse(qr.is_link("ftp://example.com/file"))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=d26241015c995645ba6fb030800da8663563b76c27e4b832a2d107183ac84d3d ====
