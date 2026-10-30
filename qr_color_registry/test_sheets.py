# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_sheets.py
# About: Tests for print sheets: sheets.json, where codes go on a page, the SVG drawings, the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for print sheets: sheets.json, where codes go on a page, the SVG drawings, the hand-written
PDF (its cross-reference table, trailer and content), and reading codes from the registry."""

import json
import os
import re
import shutil
import tempfile
import unittest
import zlib

import qr_codec
import registry
import sheets
import shortlinks

HERE = os.path.dirname(os.path.abspath(__file__))
SHORT = "HTTPS://GO.EXAMPLE.COM/12345678"


def code(text, color, caption):
    return {"matrix": qr_codec.encode_text(text, "M", 1, -1)["value"], "color": color, "caption": caption}


def codes(count):
    found = []
    for index in range(count):
        found.append(code("https://shop.example.com/p/" + str(index), "#3366cc", ""))
    return found


def layout(name):
    return sheets.DEFAULT_SHEETS["layouts"][name]


def grid_of(shape, size):
    """The module grid drawn by a Shape (the code's own runs, not its label) -> dark[row][column]."""
    module = None
    for rect in shape["rects"]:
        if module is None or rect[3] > module:
            module = rect[3]
    left = min(rect[0] for rect in shape["rects"] if rect[3] == module) - sheets.BORDER * module
    top = min(rect[1] for rect in shape["rects"] if rect[3] == module) - sheets.BORDER * module
    dark = qr_codec.blank_grid(size, False)
    for rect in shape["rects"]:
        if abs(rect[3] - module) > 1e-9:
            continue
        row = int(round((rect[1] - top) / module)) - sheets.BORDER
        start = int(round((rect[0] - left) / module)) - sheets.BORDER
        for column in range(start, start + int(round(rect[2] / module))):
            dark[row][column] = True
    return dark


class SheetsFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_sheets_")
        self.path = os.path.join(self.folder, "sheets.json")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, data):
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(json.dumps(data))
        handle.close()

    def test_the_shipped_sheets_file_shows_the_defaults(self):
        handle = open(os.path.join(HERE, "sheets.json"), encoding="utf-8")
        shipped = handle.read()
        handle.close()
        self.assertEqual(shipped, sheets.sheets_text(sheets.DEFAULT_SHEETS))
        loaded = sheets.load_sheets(os.path.join(HERE, "sheets.json"))
        self.assertEqual(loaded["warnings"], [])
        self.assertEqual(sorted(loaded["sheets"]["layouts"]), sorted(sheets.DEFAULT_SHEETS["layouts"]))

    def test_layouts_that_cannot_be_used_are_left_out(self):
        good = dict(layout("A4 poster"))
        too_wide = dict(good, columns=2)
        self.write({"layouts": {"mine": good, "too wide": too_wide, "odd": dict(good, label="yes"),
                                "tiny": dict(good, cell_mm=[2, 2])}})
        loaded = sheets.load_sheets(self.path)
        self.assertEqual(list(loaded["sheets"]["layouts"]), ["mine"])
        self.assertEqual(len(loaded["warnings"]), 3)
        self.assertIn("do not fit", " ".join(loaded["warnings"]))

    def test_a_missing_or_broken_file_means_the_built_in_layouts(self):
        for content in (None, "[1, 2", json.dumps({"layouts": {"bad": {}}})):
            if content is not None:
                handle = open(self.path, "w", encoding="utf-8")
                handle.write(content)
                handle.close()
            loaded = sheets.load_sheets(self.path)
            self.assertEqual(sorted(loaded["sheets"]["layouts"]), sorted(sheets.DEFAULT_SHEETS["layouts"]))
            self.assertGreater(len(loaded["warnings"]), 0)

    def test_checks(self):
        good = layout("A4 labels 3 x 8 (70 x 37 mm)")
        self.assertEqual(sheets.check_layout(good), "")
        for change in ({"page_mm": [210]}, {"margins_mm": [-1, 0]}, {"columns": 0}, {"rows": True},
                       {"cell_mm": [70, 38]}, {"gutter_mm": "none"}, {"label": None}):
            self.assertNotEqual(sheets.check_layout(dict(good, **change)), "", change)


class PlacementTests(unittest.TestCase):
    def test_cells_for_every_layout(self):
        for name in sheets.DEFAULT_SHEETS["layouts"]:
            chosen = layout(name)
            per_page = chosen["columns"] * chosen["rows"]
            cells = sheets.place(chosen, per_page + 1)
            self.assertEqual(sheets.page_count(chosen, per_page + 1), 2, name)
            first = cells[0]
            self.assertEqual((first["page"], first["left"], first["top"]),
                             (0, chosen["margins_mm"][1], chosen["margins_mm"][0]), name)
            last = cells[per_page - 1]
            self.assertEqual(last["page"], 0, name)
            self.assertAlmostEqual(last["left"], chosen["margins_mm"][1] + (chosen["columns"] - 1) *
                                   (chosen["cell_mm"][0] + chosen["gutter_mm"][0]), 6)
            self.assertAlmostEqual(last["top"], chosen["margins_mm"][0] + (chosen["rows"] - 1) *
                                   (chosen["cell_mm"][1] + chosen["gutter_mm"][1]), 6)
            self.assertEqual((cells[per_page]["page"], cells[per_page]["left"], cells[per_page]["top"]),
                             (1, first["left"], first["top"]), name)
            for cell in cells:
                self.assertLessEqual(cell["left"] + cell["width"], chosen["page_mm"][0] + 0.01, name)
                self.assertLessEqual(cell["top"] + cell["height"], chosen["page_mm"][1] + 0.01, name)

    def test_the_5160_labels(self):
        cells = sheets.place(layout("US Letter labels 3 x 10 (2 5/8 x 1 in)"), 30)
        self.assertAlmostEqual(cells[1]["left"] - cells[0]["left"], 2.75 * 25.4, 6)  # 2 3/4 inch pitch across
        self.assertAlmostEqual(cells[3]["top"] - cells[0]["top"], 25.4, 6)
        self.assertAlmostEqual(cells[29]["top"] + cells[29]["height"], 279.4 - 12.7, 6)

    def test_a_code_fills_its_cell_and_still_reads(self):
        cell = {"page": 0, "left": 10.0, "top": 20.0, "width": 70.0, "height": 37.0}
        placed = code(SHORT, "#006633", shortlinks.caption(SHORT))
        shape = sheets.code_shape(placed, cell, True)
        self.assertEqual(shape["color"], "#006633")
        for rect in shape["rects"]:
            self.assertGreaterEqual(rect[0], cell["left"] - 1e-9)
            self.assertGreaterEqual(rect[1], cell["top"] - 1e-9)
            self.assertLessEqual(rect[0] + rect[2], cell["left"] + cell["width"] + 1e-9)
            self.assertLessEqual(rect[1] + rect[3], cell["top"] + cell["height"] + 1e-9)
        reading = qr_codec.decode_matrix(grid_of(shape, placed["matrix"]["size"]))
        self.assertTrue(reading["ok"], reading["error"])
        self.assertEqual(reading["value"]["text"], SHORT)
        unlabelled = sheets.code_shape(placed, cell, False)
        self.assertLess(len(unlabelled["rects"]), len(shape["rects"]))
        self.assertGreater(max(rect[3] for rect in unlabelled["rects"]), max(rect[3] for rect in shape["rects"]) - 1e-9)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_sheet_out_")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_pdf_is_well_formed(self):
        chosen = layout("A4 labels 3 x 8 (70 x 37 mm)")
        data = sheets.sheet_pdf(chosen, codes(25))
        self.assertTrue(data.startswith(b"%PDF-1.4\n"))
        self.assertTrue(data.endswith(b"%%EOF\n"))
        table = int(data[data.rindex(b"startxref\n") + 10:data.rindex(b"\n%%EOF")])
        self.assertEqual(data[table:table + 5], b"xref\n")
        header = data[table:].split(b"\n")[1].split(b" ")
        count = int(header[1])
        self.assertEqual(count, 1 + 2 + 2 * 2)  # the free entry, catalog, pages, and two pages of two objects
        entries = data[table:].split(b"\n", 2)[2]
        self.assertEqual(entries[:20], b"0000000000 65535 f \n")
        for number in range(1, count):
            entry = entries[20 * number:20 * number + 20]
            self.assertEqual(len(entry), 20)
            self.assertTrue(entry.endswith(b" 00000 n \n"), entry)
            offset = int(entry[:10])
            self.assertTrue(data[offset:].startswith(str(number).encode("ascii") + b" 0 obj\n"), number)
        trailer = data[data.rindex(b"trailer"):]
        self.assertIn(b"/Size " + str(count).encode("ascii"), trailer)
        self.assertIn(b"/Root 1 0 R", trailer)
        self.assertIn(b"/Count 2", data)
        self.assertIn(b"/MediaBox [0 0 595.276 841.89]", data)
        for match in re.finditer(rb"/Length (\d+) /Filter /FlateDecode >>\nstream\n", data):
            start = match.end()
            stream = data[start:start + int(match.group(1))]
            self.assertEqual(data[start + len(stream):start + len(stream) + 10], b"\nendstream")
            content = zlib.decompress(stream).decode("ascii")
            self.assertIn("0.2 0.4 0.8 rg", content)
            self.assertIn(" re\n", content)
            self.assertTrue(content.endswith("f\n"))
            self.assertNotIn("Tf", content)  # no text: the labels are drawn
        self.assertNotIn(b"/Font", data)
        self.assertNotIn(b"/Image", data)

    def test_the_same_codes_give_the_same_bytes(self):
        chosen = layout("US Letter labels 3 x 10 (2 5/8 x 1 in)")
        labelled = [code(SHORT, "#663399", shortlinks.caption(SHORT))] + codes(3)
        self.assertEqual(sheets.sheet_pdf(chosen, labelled), sheets.sheet_pdf(chosen, labelled))
        self.assertEqual(sheets.sheet_svg(chosen, labelled), sheets.sheet_svg(chosen, labelled))

    def test_files(self):
        chosen = layout("A4 labels 3 x 8 (70 x 37 mm)")
        written = sheets.write_sheet(os.path.join(self.folder, "labels.svg"), chosen, codes(30))
        self.assertTrue(written["ok"], written["error"])
        self.assertEqual(written["value"]["files"], [os.path.join(self.folder, "labels.svg"),
                                                     os.path.join(self.folder, "labels-2.svg")])
        self.assertEqual((written["value"]["pages"], written["value"]["codes"]), (2, 30))
        handle = open(written["value"]["files"][1], encoding="utf-8")
        second = handle.read()
        handle.close()
        self.assertTrue(second.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm"'))
        self.assertEqual(second.count('fill="#3366cc"'), 6)
        written = sheets.write_sheet(os.path.join(self.folder, "poster.pdf"), layout("A4 poster"), codes(2))
        self.assertEqual(written["value"]["pages"], 2)
        self.assertFalse(sheets.write_sheet(os.path.join(self.folder, "x.png"), chosen, codes(1))["ok"])
        self.assertFalse(sheets.write_sheet(os.path.join(self.folder, "x.pdf"), chosen, [])["ok"])
        self.assertEqual(sorted(os.listdir(self.folder)), ["labels-2.svg", "labels.svg", "poster.pdf"])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_sheet_db_")
        self.db = os.path.join(self.folder, "palette.db")
        opened = registry.connect(self.db, False)
        self.numbers = []
        for link, color, short in (("https://example.com/menu", "#006633", None),
                                   (SHORT, "#3366cc", {"code": "12345678", "target": "https://example.com/hours"})):
            entry = {"link": link, "color": color, "path": os.path.join(self.folder, color[1:] + ".png"),
                     "format": "png", "ec_level": "Q", "version": 3, "origin": "made"}
            if short is not None:
                entry["short"] = short
            self.numbers.append(registry.save_qr(opened["value"], entry)["value"])
        registry.close(opened["value"])

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_codes_are_drawn_again_from_the_registry(self):
        found = sheets.codes_from_registry(self.db, list(reversed(self.numbers)) + [999])
        self.assertTrue(found["ok"], found["error"])
        drawn = found["value"]["codes"]
        self.assertEqual([item["color"] for item in drawn], ["#3366cc", "#006633"])
        self.assertEqual([item["caption"] for item in drawn], ["GO.EXAMPLE.COM/12345678", ""])
        self.assertEqual((drawn[0]["matrix"]["level"], drawn[0]["matrix"]["version"]), ("Q", 3))
        self.assertEqual(qr_codec.decode_matrix(drawn[1]["matrix"]["dark"])["value"]["text"], "https://example.com/menu")
        self.assertEqual(len(found["value"]["skipped"]), 1)
        self.assertFalse(sheets.codes_from_registry(os.path.join(self.folder, "none.db"), self.numbers)["ok"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=a9e551e90a63c015374a90694c8fee6266db3f6dec6eca3a3da0235fbde02e0f ====
