import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pixel_icons as pi  # noqa: E402


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def filtered(rows, bpp, kind):
    """Apply PNG filter `kind` to every row (the inverse of what the decoder undoes)."""
    out, prev = b"", bytes(len(rows[0]))
    for row in rows:
        line = bytearray()
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = {0: 0, 1: a, 2: b, 3: (a + b) // 2, 4: pi._paeth(a, b, c)}[kind]
            line.append((x - pred) & 0xFF)
        out += bytes((kind,)) + bytes(line)
        prev = row
    return out


def png(width, height, ctype, rows, kind=0, extra=b""):
    bpp = pi.CHANNELS[ctype]
    head = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0))
    return pi.SIGNATURE + head + extra + chunk(b"IDAT", zlib.compress(filtered(rows, bpp, kind))) + chunk(b"IEND", b"")


def checker(n=4):
    """n x n RGBA test image with varied colour and alpha."""
    data = bytearray()
    for y in range(n):
        for x in range(n):
            data += bytes(((x * 60) % 256, (y * 70) % 256, (x * y * 13) % 256, 0 if (x + y) % 3 == 0 else 200 + x))
    return pi.Image(n, n, data)


class DecodeTest(unittest.TestCase):
    def test_rgba_all_filters(self):
        img = checker()
        rows = [img.rgba[y * 16:(y + 1) * 16] for y in range(4)]
        for kind in range(5):
            with self.subTest(filter=kind):
                self.assertEqual(pi.decode_png(png(4, 4, 6, rows, kind)), img)

    def test_grey_alpha(self):
        rows = [bytes((10, 255, 20, 0)), bytes((30, 128, 40, 64))]
        img = pi.decode_png(png(2, 2, 4, rows, 4))
        self.assertEqual(img.pixel(0, 0), (10, 10, 10, 255))
        self.assertEqual(img.pixel(1, 1), (40, 40, 40, 64))

    def test_rgb_and_palette(self):
        img = pi.decode_png(png(2, 1, 2, [bytes((1, 2, 3, 4, 5, 6))], 1))
        self.assertEqual(img.pixel(1, 0), (4, 5, 6, 255))
        extra = chunk(b"PLTE", bytes((9, 8, 7, 1, 2, 3))) + chunk(b"tRNS", bytes((0,)))
        img = pi.decode_png(png(2, 1, 3, [bytes((0, 1))], 2, extra))
        self.assertEqual([img.pixel(0, 0), img.pixel(1, 0)], [(9, 8, 7, 0), (1, 2, 3, 255)])

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            pi.decode_png(b"not a png")
        bad = bytearray(png(1, 1, 6, [bytes(4)]))
        bad[30] ^= 1  # inside the IHDR CRC
        with self.assertRaises(ValueError):
            pi.decode_png(bytes(bad))

    def test_silk_originals(self):
        for project, (silk, *_rest) in pi.PROJECTS.items():
            with open(os.path.join(pi.SILK, silk), "rb") as f:
                img = pi.decode_png(f.read())
            with self.subTest(silk=silk):
                self.assertEqual((img.width, img.height), (16, 16))
                self.assertTrue(any(img.pixel(x, y)[3] == 0 for x in range(16) for y in range(16)))
                self.assertTrue(any(img.pixel(x, y)[3] == 255 for x in range(16) for y in range(16)))


class ScaleTest(unittest.TestCase):
    def test_pixel_exact_blocks(self):
        img = checker()
        for k in (2, 3, 16):
            big = pi.scale(img, k)
            self.assertEqual((big.width, big.height), (4 * k, 4 * k))
            for y in range(big.height):
                for x in range(big.width):
                    self.assertEqual(big.pixel(x, y), img.pixel(x // k, y // k))

    def test_png_round_trip(self):
        img = pi.scale(checker(), 3)
        self.assertEqual(pi.decode_png(pi.encode_png(img)), img)
        self.assertEqual(pi.encode_png(img), pi.encode_png(img))


class IcoResTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(pi.SILK, "bell.png"), "rb") as f:
            self.original = pi.decode_png(f.read())
        self.images = pi.icon_images(self.original)

    def test_ico_directory(self):
        ico = pi.encode_ico(self.images)
        self.assertEqual(struct.unpack("<HHH", ico[:6]), (0, 1, 4))
        for i, size in enumerate(pi.SIZES):
            w, h, _, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", ico[6 + 16 * i:22 + 16 * i])
            blob = ico[offset:offset + length]
            self.assertEqual((w, h), (size % 256, size % 256))
            self.assertEqual((planes, bits), (1, 32))
            if size == 256:
                self.assertEqual(pi.decode_png(blob), pi.scale(self.original, 16))
            else:
                self.assertEqual(struct.unpack("<Iii", blob[:12]), (40, size, size * 2))

    def test_bmp_pixels_and_mask(self):
        blob = dict(self.images)[32]
        big = pi.scale(self.original, 2)
        pixels = blob[40:40 + 32 * 32 * 4]
        mask = blob[40 + 32 * 32 * 4:]
        self.assertEqual(len(mask), 32 * 4)
        for y in range(32):
            for x in range(32):
                r, g, b, a = big.pixel(x, y)
                i = ((31 - y) * 32 + x) * 4  # bottom-up rows
                self.assertEqual(tuple(pixels[i:i + 4]), (b, g, r, a))
                bit = mask[(31 - y) * 4 + x // 8] >> (7 - x % 8) & 1
                self.assertEqual(bit, 1 if a == 0 else 0)

    def test_res_layout(self):
        res = pi.encode_res(self.images)
        pos, found = 0, []
        while pos < len(res):
            size, header, _, rtype, _, name = struct.unpack("<IIHHHH", res[pos:pos + 16])
            self.assertEqual(header, 32)
            found.append((rtype, name, res[pos + 32:pos + 32 + size]))
            pos += 32 + size + (-size % 4)
        self.assertEqual(pos, len(res))
        self.assertEqual([(t, n) for t, n, _ in found], [(0, 0), (3, 1), (3, 2), (3, 3), (3, 4), (14, 1), (24, 1)])
        group = found[5][2]
        self.assertEqual(struct.unpack("<HHH", group[:6]), (0, 1, 4))
        self.assertEqual([found[i][2] for i in range(1, 5)], [blob for _, blob in self.images])
        self.assertIn(b"PerMonitorV2", found[6][2])


class SysoTest(unittest.TestCase):
    def test_absolute_symbols_move_to_section_one(self):
        def sym(name, sect, cls, aux=0):
            return struct.pack("<8sIhHBB", name, 7, sect, 0, cls, aux)
        symbols = sym(b"@comp.id", -1, 3) + sym(b".rsrc$01", 2, 3, 1) + bytes(18) + sym(b"@feat.00", -1, 3)
        header = struct.pack("<HHIIIHH", 0x8664, 0, 0, 20, 4, 0, 0)
        fixed = pi.fix_syso(header + symbols + b"\x04\x00\x00\x00")
        entries = [struct.unpack_from("<8sIhHBB", fixed, 20 + 18 * i) for i in (0, 1, 3)]
        self.assertEqual([(e[2], e[4]) for e in entries], [(1, 3), (2, 3), (1, 3)])
        self.assertEqual(fixed[20 + 18 * 2:20 + 18 * 3], bytes(18))  # the aux record is left alone


class ProjectTest(unittest.TestCase):
    def test_write_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = pi.write_project(tmp, "note.png", "ACME Ticket Tracker", ("rgba", "favicon"))
            names = sorted(os.path.relpath(p, tmp).replace(os.sep, "/") for p in written)
            self.assertEqual(names, ["icon/app-256.png", "icon/app-32.png", "icon/app-32.rgba", "icon/app-48.png",
                                     "icon/app.ico", "icon/app.res", "icon/silk-note.png", "www/favicon.png"])
            with open(os.path.join(tmp, "icon", "README.md"), encoding="utf-8") as f:
                readme = f.read()
            with open(os.path.join(tmp, "icon", "silk-note.png"), "rb") as f:
                original = f.read()
            self.assertIn(pi.sha(original), readme)
            self.assertIn("CC BY 2.5", pi.CREDIT)
            self.assertIn("Creative Commons Attribution 2.5", readme)
            with open(os.path.join(tmp, "icon", "app-32.rgba"), "rb") as f:
                raw = f.read()
            self.assertEqual(struct.unpack("<II", raw[:8]), (32, 32))
            self.assertEqual(raw[8:], pi.scale(pi.decode_png(original), 2).rgba)

    def test_six_distinct_icons(self):
        files = [silk for silk, *_ in pi.PROJECTS.values()]
        self.assertEqual(len(set(files)), 6)
        self.assertEqual(len({app for _, app, *_ in pi.PROJECTS.values()}), 6)


if __name__ == "__main__":
    unittest.main()
