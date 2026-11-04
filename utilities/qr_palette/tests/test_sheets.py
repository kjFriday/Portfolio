# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_sheets.py
# About: Tests for print sheets: sheets.json, where codes go on a page, the SVG drawings, the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for print sheets: sheets.json, placement, SVG, the hand-written PDF, registry codes.

sheets.py lays QR codes out on label sheets or posters and writes them as SVG pages or one PDF it
builds itself (PDF 1.4: objects, a cross-reference table of byte offsets, and a trailer). The PDF test
walks that structure byte by byte, and the placement test decodes a placed code again, so a layout
bug that would print an unreadable code fails here.

What the classes pin:
  1. SheetsFileTests: the shipped sheets.json, layout checks, and falling back to the built-in layouts.
  2. PlacementTests: cell positions on every built-in layout, the 5160 label pitch, and a code that
     fills its cell and still decodes.
  3. OutputTests: the PDF's structure, identical bytes for identical input, and the files written.
  4. RegistryTests: codes drawn again from registry records, and the module-size and logo notes.

Run with the rest of the suite: python -m unittest discover -s tests, in the program folder.
"""

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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/
# a short link as printed: capitals, so it fits QR's alphanumeric mode, and a caption under the code
SHORT = "HTTPS://GO.EXAMPLE.COM/12345678"


def code(text, color, caption):
    """A sheets Code: `text` encoded at level M (version 1 up, mask -1 = the best of the eight), in `color`."""
    return {"matrix": qr_codec.encode_text(text, "M", 1, -1)["value"], "color": color, "caption": caption}


def codes(count):
    """`count` different #3366cc codes without captions, one per product page."""
    found = []
    for index in range(count):
        found.append(code("https://shop.example.com/p/" + str(index), "#3366cc", ""))
    return found


def layout(name):
    """A built-in layout by name, from sheets.DEFAULT_SHEETS."""
    return sheets.DEFAULT_SHEETS["layouts"][name]


def grid_of(shape, size):
    """The module grid drawn by a Shape (the code's own runs, not its label) -> dark[row][column].

    Steps:
    1. The module size is the tallest rectangle: a module run is one module high, a label's font
       pixel is a fraction of one.
    2. Find the code's top-left corner from its module runs. The finder pattern makes row 0 and
       column 0 dark, so the smallest left and top belong to module (0, 0); taking BORDER modules
       off them gives the outer corner of the quiet zone, the origin code_shape measures from.
    3. Turn each module run back into the grid cells it covers."""
    module = None
    for rect in shape["rects"]:
        if module is None or rect[3] > module:
            module = rect[3]
    left = min(rect[0] for rect in shape["rects"] if rect[3] == module) - sheets.BORDER * module
    top = min(rect[1] for rect in shape["rects"] if rect[3] == module) - sheets.BORDER * module
    dark = qr_codec.blank_grid(size, False)
    for rect in shape["rects"]:
        # label runs are shorter than a module: skip them (1e-9 absorbs floating-point noise)
        if abs(rect[3] - module) > 1e-9:
            continue
        row = int(round((rect[1] - top) / module)) - sheets.BORDER
        start = int(round((rect[0] - left) / module)) - sheets.BORDER
        for column in range(start, start + int(round(rect[2] / module))):
            dark[row][column] = True
    return dark


class SheetsFileTests(unittest.TestCase):
    """load_sheets and check_layout, on sheets.json files written into a temporary folder."""

    def setUp(self):
        """Make the folder and name sheets.json in it."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_sheets_")
        self.path = os.path.join(self.folder, "sheets.json")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, data):
        """Write `data` as the test's sheets.json."""
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(json.dumps(data))
        handle.close()

    def test_the_shipped_sheets_file_shows_the_defaults(self):
        """The sheets.json beside the program is exactly sheets_text(DEFAULT_SHEETS) and loads without warnings."""
        handle = open(os.path.join(HERE, "sheets.json"), encoding="utf-8")
        shipped = handle.read()
        handle.close()
        self.assertEqual(shipped, sheets.sheets_text(sheets.DEFAULT_SHEETS))
        loaded = sheets.load_sheets(os.path.join(HERE, "sheets.json"))
        self.assertEqual(loaded["warnings"], [])
        self.assertEqual(sorted(loaded["sheets"]["layouts"]), sorted(sheets.DEFAULT_SHEETS["layouts"]))

    def test_layouts_that_cannot_be_used_are_left_out(self):
        """Of four layouts only the good one is kept, with a warning for each of the other three.

        "too wide" puts two 170 mm cells on a 210 mm page; "odd" has label "yes" (not a bool); "tiny"
        has 2 mm cells, under the 5 mm check_layout allows."""
        good = dict(layout("A4 poster"))
        too_wide = dict(good, columns=2)
        self.write({"layouts": {"mine": good, "too wide": too_wide, "odd": dict(good, label="yes"),
                                "tiny": dict(good, cell_mm=[2, 2])}})
        loaded = sheets.load_sheets(self.path)
        self.assertEqual(list(loaded["sheets"]["layouts"]), ["mine"])
        self.assertEqual(len(loaded["warnings"]), 3)
        self.assertIn("do not fit", " ".join(loaded["warnings"]))

    def test_a_missing_or_broken_file_means_the_built_in_layouts(self):
        """A missing file, broken JSON, and a file whose only layout is unusable all mean the built-in layouts, with a warning."""
        for content in (None, "[1, 2", json.dumps({"layouts": {"bad": {}}})):
            if content is not None:
                handle = open(self.path, "w", encoding="utf-8")
                handle.write(content)
                handle.close()
            loaded = sheets.load_sheets(self.path)
            self.assertEqual(sorted(loaded["sheets"]["layouts"]), sorted(sheets.DEFAULT_SHEETS["layouts"]))
            self.assertGreater(len(loaded["warnings"]), 0)

    def test_checks(self):
        """check_layout accepts a built-in layout and refuses each single fault in it.

        The faults: a page with one size, a negative margin, no columns, a bool for rows, cells that
        no longer fit (8 rows of 38 mm plus the margin is 304.5 mm on a 297 mm page), a gutter as
        text, and no label setting."""
        good = layout("A4 labels 3 x 8 (70 x 37 mm)")
        self.assertEqual(sheets.check_layout(good), "")
        for change in ({"page_mm": [210]}, {"margins_mm": [-1, 0]}, {"columns": 0}, {"rows": True},
                       {"cell_mm": [70, 38]}, {"gutter_mm": "none"}, {"label": None}):
            self.assertNotEqual(sheets.check_layout(dict(good, **change)), "", change)


class PlacementTests(unittest.TestCase):
    """place(), page_count() and code_shape()."""

    def test_cells_for_every_layout(self):
        """On every built-in layout, one code more than a page holds makes two pages, and every cell stays on its page.

        The first cell sits at the margins, the last of page 0 one pitch (cell plus gutter) per
        column and row further, and the extra code starts page 1 where the first did. 0.01 mm of
        slack covers floating-point sums of decimal millimetres."""
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
        """The US Letter 3 x 10 layout matches the 5160 label sheet in inches.

        Labels repeat every 2 3/4 inch across (2 5/8 label plus 1/8 gutter) and every inch down, and
        the last row ends half an inch (12.7 mm) above the bottom of the 11-inch (279.4 mm) page."""
        cells = sheets.place(layout("US Letter labels 3 x 10 (2 5/8 x 1 in)"), 30)
        self.assertAlmostEqual(cells[1]["left"] - cells[0]["left"], 2.75 * 25.4, 6)  # 2 3/4 inch pitch across
        self.assertAlmostEqual(cells[3]["top"] - cells[0]["top"], 25.4, 6)
        self.assertAlmostEqual(cells[29]["top"] + cells[29]["height"], 279.4 - 12.7, 6)

    def test_a_code_fills_its_cell_and_still_reads(self):
        """A labelled code stays inside its 70 x 37 mm cell and decodes to its text; without the label its modules are no smaller.

        The 1e-9 slack is for floating-point rounding. The unlabelled shape has fewer rectangles (no
        font pixels), and its module, which no longer shares the cell's height with a label, is at
        least as big."""
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
    """sheet_pdf, sheet_svg and write_sheet."""

    def setUp(self):
        """Make the temporary folder for written sheets."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_sheet_out_")

    def tearDown(self):
        """Remove the folder."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_pdf_is_well_formed(self):
        """25 codes on 24-label A4 sheets make a valid two-page PDF 1.4 whose every offset and length is right.

        Steps:
        1. The file starts with the PDF 1.4 header and ends with %%EOF.
        2. startxref names the byte where the "xref" table starts; its first line gives the count.
        3. Entry 0 is the free entry; every other 20-byte entry points at "N 0 obj" for its number.
        4. The trailer gives /Size and the catalog (object 1) as /Root.
        5. Each content stream's /Length is exact (endstream follows at once) and it inflates to
           drawing operators: the fill color of #3366cc (51/255 = 0.2, 102/255 = 0.4, 204/255 = 0.8),
           rectangles, a final fill, and no text.
        595.276 x 841.89 points is A4 (210 x 297 mm at 72 points to 25.4 mm)."""
        chosen = layout("A4 labels 3 x 8 (70 x 37 mm)")
        data = sheets.sheet_pdf(chosen, codes(25))
        self.assertTrue(data.startswith(b"%PDF-1.4\n"))
        self.assertTrue(data.endswith(b"%%EOF\n"))
        # the number between "startxref\n" (10 bytes) and the final "\n%%EOF"
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
        """The same codes give byte-identical PDF and SVG output (no dates or IDs), labels included."""
        chosen = layout("US Letter labels 3 x 10 (2 5/8 x 1 in)")
        labelled = [code(SHORT, "#663399", shortlinks.caption(SHORT))] + codes(3)
        self.assertEqual(sheets.sheet_pdf(chosen, labelled), sheets.sheet_pdf(chosen, labelled))
        self.assertEqual(sheets.sheet_svg(chosen, labelled), sheets.sheet_svg(chosen, labelled))

    def test_files(self):
        """write_sheet writes one SVG per page (labels.svg, labels-2.svg) or one PDF, and refuses other types and no codes.

        30 codes on 24 labels leave 6 for page 2, so it holds six #3366cc paths. The refusals write
        nothing, and no .part file is left behind."""
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
    """codes_from_registry and print_sheet against a small registry."""

    def setUp(self):
        """A registry with two level-Q, version-3 codes: a plain link in green, then a short link in blue.

        The picture files are never written: the codes are drawn again from the registry's text.
        "12345678" is only digits; the registry does not check the Damm digit."""
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
        """Remove the folder and the registry in it."""
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_codes_are_drawn_again_from_the_registry(self):
        """Records come back in the order asked, at their own level and version, with the short address as caption.

        Record 999 does not exist and is skipped with a note; a missing registry fails."""
        found = sheets.codes_from_registry(self.db, list(reversed(self.numbers)) + [999])
        self.assertTrue(found["ok"], found["error"])
        drawn = found["value"]["codes"]
        self.assertEqual([item["color"] for item in drawn], ["#3366cc", "#006633"])
        self.assertEqual([item["caption"] for item in drawn], ["GO.EXAMPLE.COM/12345678", ""])
        self.assertEqual((drawn[0]["matrix"]["level"], drawn[0]["matrix"]["version"]), ("Q", 3))
        self.assertEqual(qr_codec.decode_matrix(drawn[1]["matrix"]["dark"])["value"]["text"], "https://example.com/menu")
        self.assertEqual(len(found["value"]["skipped"]), 1)
        self.assertFalse(sheets.codes_from_registry(os.path.join(self.folder, "none.db"), self.numbers)["ok"])

    def test_a_sheet_says_how_small_its_modules_are(self):
        """print_sheet reports the smallest module and how many codes print without their logo.

        A poster gives modules over 3 mm; an 800-character link on a one-inch label gives modules
        under 0.4 mm, the case the window warns about. Marking both records has_logo makes without_logo 2,
        since the registry keeps no logo to draw."""
        path = os.path.join(self.folder, "sheet.pdf")
        printed = sheets.print_sheet(self.db, self.numbers, layout("A4 poster"), path)
        self.assertGreater(printed["value"]["smallest_module_mm"], 3)
        long_code = code("https://shop.example.com/" + "p/" * 400, "#3366cc", "")
        tiny = sheets.smallest_module(layout("US Letter labels 3 x 10 (2 5/8 x 1 in)"), [long_code])
        self.assertLess(tiny, 0.4)
        self.assertEqual(printed["value"]["without_logo"], 0)
        opened = registry.connect(self.db, False)
        opened["value"].execute("UPDATE qr_codes SET has_logo = 1")
        registry.close(opened["value"])
        self.assertEqual(sheets.print_sheet(self.db, self.numbers, layout("A4 poster"), path)["value"]["without_logo"], 2)

    def test_a_sheet_of_registered_codes(self):
        """Two records and a missing one print as one PDF page of two codes, one skipped; a sheet left with no codes fails."""
        path = os.path.join(self.folder, "sheet.pdf")
        printed = sheets.print_sheet(self.db, self.numbers + [999], layout("A4 labels 3 x 8 (70 x 37 mm)"), path)
        self.assertTrue(printed["ok"], printed["error"])
        self.assertEqual((printed["value"]["files"], printed["value"]["pages"], printed["value"]["codes"]), ([path], 1, 2))
        self.assertEqual(len(printed["value"]["skipped"]), 1)
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(sheets.print_sheet(self.db, [999], layout("A4 poster"), os.path.join(self.folder, "x.pdf"))["ok"])


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=4045707c959e10ed2b6f0a06462191cd746c18f7ca5217ca7f523758eee186ca ====
