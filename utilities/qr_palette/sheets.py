# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: sheets.py
# About: QR Palette print sheets: codes laid out on label sheets or posters, as SVG or PDF.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette print sheets: codes laid out on label sheets or posters, as SVG or PDF.

Many codes go on a sheet of labels, or one code on each page as a poster. SVG gives one drawing per
page; PDF gives one file.

The layouts are in sheets.json beside the program, plain JSON like the other settings files, read
fresh each time a sheet is made. Each layout gives a page size, the top-left margins, a grid of cells
(columns x rows, each cell_mm, gutter_mm apart) and whether to print each code's label: the short
address under a code that has one, in the same 5 x 7 font as the pictures.

The PDF is written here by hand (PDF 1.4): every module and every font pixel is a filled rectangle in
the page's content stream, so it needs no fonts and no images, and the same codes always give the same
bytes (no dates, no IDs).

Who calls it: the Find tab's Print sheet (gui/find_tab.py) loads sheets.json with load_sheets() and
prints with print_sheet(); selftest prints one too. It calls registry (read-only), qr_codec to draw each
code again and lay out its label, and shortlinks.caption for the label's text.

Flow (print_sheet)
  1. codes_from_registry() reads the chosen records and draws each code's matrix again.
  2. place() gives each code a cell; code_shape() turns it into filled rectangles in millimetres.
  3. write_sheet() writes the rectangles as SVG pages or as one PDF.

A PDF in brief: numbered objects (here a catalog, a page tree, then a page and its content stream for
each page), a cross-reference table giving each object's byte offset, and a trailer naming the catalog.
A content stream is drawing operators: "r g b rg" sets the fill color, "x y w h re" adds a rectangle
and "f" fills every rectangle added since. PDF measures in points (1/72 inch) from the page's bottom
left.

Start reading at print_sheet().

Records
  Result   {"ok": bool, "error": str, "value": any}
  Sheets   {"about", "layouts": {name: Layout}}                                    sheets.json, checked
  Layout   {"about", "page_mm": [width, height], "margins_mm": [top, left], "columns": int, "rows": int,
            "cell_mm": [width, height], "gutter_mm": [across, down], "label": bool}
  Cell     {"page": int from 0, "left": mm, "top": mm, "width": mm, "height": mm}  from the page's top left
  Code     {"matrix": Matrix (qr_codec), "color": "#rrggbb", "caption": str}       one code to place
  Shape    {"color": "#rrggbb", "rects": [[left, top, width, height]] in mm}       one code, drawn
"""

import json
import os
import zlib

import qr_codec
import registry
import shortlinks

MM_TO_PT = 72.0 / 25.4  # 72 points and 25.4 mm to the inch
BORDER = 4  # modules of quiet zone around every code, as in the pictures
MAX_PAGE_MM = 2000.0  # no layout size may be above 2 m: a bigger one is a typing mistake

# The built-in layouts, used when sheets.json is missing, broken or holds none that work. The about
# texts are data, written out with the layouts.
DEFAULT_SHEETS = {
    "about": "Print sheets: how Print sheet in Find lays codes out on paper. Each layout has page_mm (width and "
             "height of the page), margins_mm (from the top and from the left to the first cell), columns and rows "
             "(the cells on one page), cell_mm (width and height of one cell, such as one label), gutter_mm (the "
             "space between cells across and down) and label (print the short address under codes that have "
             "one). All sizes are in millimetres. A code fills as much of its cell as it can, quiet zone "
             "included. Add your own layouts; edits apply the next time you print.",
    "layouts": {
        "A4 labels 3 x 8 (70 x 37 mm)": {
            "about": "A4 sheets of 24 labels, 70 x 37 mm, with no space between them.",
            "page_mm": [210, 297], "margins_mm": [0.5, 0], "columns": 3, "rows": 8, "cell_mm": [70, 37],
            "gutter_mm": [0, 0], "label": True},
        "US Letter labels 3 x 10 (2 5/8 x 1 in)": {
            "about": "US Letter sheets of 30 address labels, 2 5/8 x 1 inch (the common 5160 layout).",
            "page_mm": [215.9, 279.4], "margins_mm": [12.7, 4.7625], "columns": 3, "rows": 10,
            "cell_mm": [66.675, 25.4], "gutter_mm": [3.175, 0], "label": True},
        "A4 poster": {
            "about": "One big code per A4 page.",
            "page_mm": [210, 297], "margins_mm": [20, 20], "columns": 1, "rows": 1, "cell_mm": [170, 257],
            "gutter_mm": [0, 0], "label": True},
        "US Letter poster": {
            "about": "One big code per US Letter page.",
            "page_mm": [215.9, 279.4], "margins_mm": [20, 20], "columns": 1, "rows": 1, "cell_mm": [175.9, 239.4],
            "gutter_mm": [0, 0], "label": True},
    },
}


def ok_result(value):
    """A successful Result holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the short error phrase `error` and the value None."""
    return {"ok": False, "error": error, "value": None}


# --- sheets.json ---------------------------------------------------------------------------------

def is_number(value):
    """True for an int or a float that is not a bool (bool is a kind of int in Python)."""
    return not isinstance(value, bool) and isinstance(value, (int, float))


def is_pair(value, low):
    """True for [a, b] of numbers, each at least `low` and at most MAX_PAGE_MM."""
    if not isinstance(value, list) or len(value) != 2:
        return False
    for item in value:
        if not is_number(item) or item < low or item > MAX_PAGE_MM:
            return False
    return True


def check_layout(layout):
    """"" when a Layout can be used, else what is wrong with it."""
    if not isinstance(layout, dict):
        return "a layout must be an object"
    if not is_pair(layout.get("page_mm"), 1):
        return "page_mm must be [width, height] in millimetres"
    if not is_pair(layout.get("margins_mm"), 0):
        return "margins_mm must be [top, left] in millimetres"
    if not is_pair(layout.get("cell_mm"), 5):
        return "cell_mm must be [width, height], each at least 5 mm"
    if not is_pair(layout.get("gutter_mm"), 0):
        return "gutter_mm must be [across, down] in millimetres"
    for key in ("columns", "rows"):
        value = layout.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 50:
            return key + " must be a whole number from 1 to 50"
    if not isinstance(layout.get("label"), bool):
        return "label must be true or false"
    page = layout["page_mm"]
    right = layout["margins_mm"][1] + layout["columns"] * layout["cell_mm"][0] + (layout["columns"] - 1) * \
        layout["gutter_mm"][0]
    bottom = layout["margins_mm"][0] + layout["rows"] * layout["cell_mm"][1] + (layout["rows"] - 1) * \
        layout["gutter_mm"][1]
    # 0.01 mm of slack: decimal millimetres do not always add up exactly in floating point
    if right > page[0] + 0.01 or bottom > page[1] + 0.01:
        return "the cells do not fit on the page"
    return ""


def copy_sheets(sheets):
    """A copy of a Sheets record with each layout's dict copied (its lists are shared), so a change to
    the copy's layouts never reaches DEFAULT_SHEETS."""
    layouts = {}
    for name in sheets["layouts"]:
        layouts[name] = dict(sheets["layouts"][name])
    return {"about": sheets["about"], "layouts": layouts}


def load_sheets(path):
    """sheets.json -> {"sheets": Sheets, "warnings": [str]}. A layout that cannot be used is left out
    and said; a file that is missing or not valid JSON means the built-in layouts."""
    sheets = copy_sheets(DEFAULT_SHEETS)
    try:
        handle = open(path, "r", encoding="utf-8-sig")
        try:
            data = json.loads(handle.read())
        finally:
            handle.close()
    except (OSError, ValueError) as error:
        return {"sheets": sheets, "warnings": ["cannot use " + path + " (" + str(error) + "); using the built-in "
                                               "layouts"]}
    if not isinstance(data, dict) or not isinstance(data.get("layouts"), dict):
        return {"sheets": sheets, "warnings": [path + " must hold an object with layouts; using the built-in "
                                               "layouts"]}
    warnings = []
    layouts = {}
    for name in data["layouts"]:
        layout = data["layouts"][name]
        problem = check_layout(layout)
        if name.strip() == "":
            problem = "a layout needs a name"
        if problem == "":
            kept = dict(layout)
            if not isinstance(kept.get("about"), str):
                kept["about"] = ""
            layouts[name.strip()] = kept
        else:
            warnings.append("sheets: " + json.dumps(name) + ": " + problem)
    if len(layouts) == 0:
        warnings.append("sheets: no usable layouts; using the built-in ones")
        return {"sheets": sheets, "warnings": warnings}
    sheets["layouts"] = layouts
    if isinstance(data.get("about"), str):
        sheets["about"] = data["about"]
    return {"sheets": sheets, "warnings": warnings}


def sheets_text(sheets):
    """sheets.json as people read it: indented, one setting per line."""
    return json.dumps(sheets, indent=2, ensure_ascii=False) + "\n"


# --- Placing codes -------------------------------------------------------------------------------

def place(layout, count):
    """Where `count` codes go, page by page, left to right and top to bottom -> [Cell]."""
    cells = []
    per_page = layout["columns"] * layout["rows"]
    for index in range(count):
        on_page = index % per_page
        column = on_page % layout["columns"]
        row = on_page // layout["columns"]
        cells.append({"page": index // per_page,
                      "left": layout["margins_mm"][1] + column * (layout["cell_mm"][0] + layout["gutter_mm"][0]),
                      "top": layout["margins_mm"][0] + row * (layout["cell_mm"][1] + layout["gutter_mm"][1]),
                      "width": layout["cell_mm"][0], "height": layout["cell_mm"][1]})
    return cells


def page_count(layout, count):
    """How many pages `count` codes take on this layout; at least 1."""
    per_page = layout["columns"] * layout["rows"]
    return max(1, (count + per_page - 1) // per_page)


def code_size(code, cell, label):
    """How a code fills its cell -> (module in mm, its height in modules with its label, label lines, font
    pixel in sixteenths of a module).

    The code's side is its matrix plus BORDER modules of quiet zone on each side; the label band is
    caption_size's height in sixteenths, turned into modules. The module is the smaller of the cell's
    width over the side and its height over the whole height, so the code and label fit both ways."""
    side = code["matrix"]["size"] + 2 * BORDER
    grid = qr_codec.SVG_GRID
    lines = []
    pixel = 1
    band = 0
    if label and code["caption"] != "":
        lines, pixel = qr_codec.caption_layout(code["caption"], side * grid, grid)
        band = qr_codec.caption_size(lines, pixel, grid)[1]
    tall = side + band / float(grid)
    return min(cell["width"] / float(side), cell["height"] / tall), tall, lines, pixel


def smallest_module(layout, codes):
    """The smallest module in mm the codes come out at on this layout, for telling when it is too small."""
    smallest = None
    cells = place(layout, len(codes))
    for index in range(len(codes)):
        module = code_size(codes[index], cells[index], layout["label"])[0]
        if smallest is None or module < smallest:
            smallest = module
    return smallest


def code_shape(code, cell, label):
    """A code drawn as large as its cell allows, quiet zone and label included, centred -> Shape.
    Runs of dark modules along a row are one rectangle each; so are runs of a label's font pixels.
    The label is laid out as the pictures lay it out, in sixteenths of a module.

    Steps:
    1. Size the code (code_size) and centre it, label included, in its cell.
    2. Each run of dark modules along a row becomes one rectangle, in millimetres.
    3. The label's font pixels sit below the quiet zone (top = side * grid, in sixteenths); a pixel that
       continues the run on its left widens it. These runs are 3-item lists, still in sixteenths.
    4. Turn the 3-item runs into millimetre rectangles, so every rectangle is [left, top, width, height].
    """
    matrix = code["matrix"]
    size = matrix["size"]
    side = size + 2 * BORDER
    grid = qr_codec.SVG_GRID
    module, tall, lines, pixel = code_size(code, cell, label)
    left = cell["left"] + (cell["width"] - side * module) / 2.0
    top = cell["top"] + (cell["height"] - tall * module) / 2.0
    rects = []
    for y in range(size):
        x = 0
        while x < size:
            if not matrix["dark"][y][x]:
                x = x + 1
                continue
            start = x
            while x < size and matrix["dark"][y][x]:
                x = x + 1
            rects.append([left + (start + BORDER) * module, top + (y + BORDER) * module, (x - start) * module, module])
    unit = module / grid
    previous = None
    for corner in qr_codec.caption_pixels(lines, pixel, side * grid, side * grid):
        if previous is not None and previous[1] == corner[1] and previous[0] + previous[2] == corner[0]:
            previous[2] = previous[2] + pixel  # this font pixel continues the run on its left
            continue
        previous = [corner[0], corner[1], pixel]
        rects.append(previous)
    shape = []
    for rect in rects:
        if len(rect) == 3:  # a run of font pixels, still in sixteenths of a module
            rect = [left + rect[0] * unit, top + rect[1] * unit, rect[2] * unit, pixel * unit]
        shape.append(rect)
    return {"color": code["color"], "rects": shape}


def shapes_by_page(layout, codes):
    """[[Shape] for each page] for the codes in order."""
    pages = []
    for index in range(page_count(layout, len(codes))):
        pages.append([])
    cells = place(layout, len(codes))
    for index in range(len(codes)):
        pages[cells[index]["page"]].append(code_shape(codes[index], cells[index], layout["label"]))
    return pages


# --- SVG -----------------------------------------------------------------------------------------

def number(value):
    """A length for SVG or PDF, as short as it can be: 12.5, 3, 0.333."""
    text = "%.3f" % value
    text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):  # a tiny negative value rounds to "-0.000"
        return "0"
    return text


def sheet_svg(layout, codes):
    """The codes laid out -> [SVG text, one per page], sized in millimetres for printing."""
    width = layout["page_mm"][0]
    height = layout["page_mm"][1]
    drawings = []
    for page in shapes_by_page(layout, codes):
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="' + number(width) + 'mm" height="' + number(height) +
                 'mm" viewBox="0 0 ' + number(width) + " " + number(height) + '" shape-rendering="crispEdges">\n'
                 '<rect width="100%" height="100%" fill="' + qr_codec.PAPER + '"/>\n']
        for shape in page:
            parts.append('<path d="')
            for rect in shape["rects"]:
                parts.append("M" + number(rect[0]) + "," + number(rect[1]) + "h" + number(rect[2]) + "v" +
                             number(rect[3]) + "h-" + number(rect[2]) + "z")
            parts.append('" fill="' + shape["color"] + '"/>\n')
        parts.append("</svg>\n")
        drawings.append("".join(parts))
    return drawings


# --- PDF -----------------------------------------------------------------------------------------

def rgb_text(color):
    """"#3366cc" -> "0.2 0.4 0.8", PDF's fill color operands (each channel from 0 to 1)."""
    values = []
    for start in (1, 3, 5):
        values.append(number(int(color[start:start + 2], 16) / 255.0))
    return " ".join(values)


def page_content(page, height):
    """One page's content stream: for each code its color, then its rectangles, filled together.
    PDF measures in points from the bottom left; the shapes are in millimetres from the top left."""
    lines = []
    for shape in page:
        lines.append(rgb_text(shape["color"]) + " rg")
        for rect in shape["rects"]:
            # a rectangle's bottom edge, counted up from the page's bottom: height - top - its height
            lines.append(number(rect[0] * MM_TO_PT) + " " + number((height - rect[1] - rect[3]) * MM_TO_PT) + " " +
                         number(rect[2] * MM_TO_PT) + " " + number(rect[3] * MM_TO_PT) + " re")
        lines.append("f")  # fill all the rectangles of this code at once
    return ("\n".join(lines) + "\n").encode("ascii")


def sheet_pdf(layout, codes):
    """The codes laid out -> PDF 1.4 bytes: a catalog, a page tree, and for every page a page object
    and its compressed content stream; then the cross-reference table and the trailer.

    Objects are numbered from 1: the catalog is 1, the page tree 2, and page i (from 0) is 3 + 2i with
    its content stream at 4 + 2i. "N 0 R" refers to object N.

    Steps:
    1. Build every object's bytes; each content stream is zlib-compressed (/FlateDecode).
    2. Write the header, then each object as "N 0 obj ... endobj", noting its byte offset.
    3. Write the cross-reference table, the trailer and startxref, the table's own offset.
    """
    width = number(layout["page_mm"][0] * MM_TO_PT)
    height = number(layout["page_mm"][1] * MM_TO_PT)
    pages = shapes_by_page(layout, codes)
    objects = []
    kids = []
    for index in range(len(pages)):
        kids.append(str(3 + 2 * index) + " 0 R")
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(("<< /Type /Pages /Kids [" + " ".join(kids) + "] /Count " + str(len(pages)) + " >>").encode("ascii"))
    for index in range(len(pages)):
        stream = zlib.compress(page_content(pages[index], layout["page_mm"][1]), 9)
        objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + width + " " + height + "] /Contents " +
                        str(4 + 2 * index) + " 0 R /Resources << >> >>").encode("ascii"))
        objects.append(("<< /Length " + str(len(stream)) + " /Filter /FlateDecode >>\nstream\n").encode("ascii") +
                       stream + b"\nendstream")
    # the second line is a comment of four bytes above 127, which marks the file as binary for tools
    # that move files between systems (PDF 1.4 reference, section 3.4.1)
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index in range(len(objects)):
        offsets.append(len(data))
        data.extend(str(index + 1).encode("ascii") + b" 0 obj\n" + objects[index] + b"\nendobj\n")
    table = len(data)
    data.extend(("xref\n0 " + str(len(objects) + 1) + "\n").encode("ascii"))
    # every entry is exactly 20 bytes: a 10-digit offset, a 5-digit generation, n (in use) or f (free)
    # and a two-byte line end; object 0 is always free, with generation 65535
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        data.extend(("%010d 00000 n \n" % offset).encode("ascii"))
    data.extend(("trailer\n<< /Size " + str(len(objects) + 1) + " /Root 1 0 R >>\nstartxref\n" + str(table) +
                 "\n%%EOF\n").encode("ascii"))
    return bytes(data)


# --- Codes from the registry ---------------------------------------------------------------------

def codes_from_registry(db_path, numbers):
    """The codes registered under `numbers` (record ids), in that order, ready to place -> Result
    {"codes": [Code], "skipped": [str], "without_logo": how many are drawn without the logo their pictures
    have, which the registry does not keep}. Each is drawn again from the text it holds, at its own level
    and at least its own version, with its short address as its label. A code whose text is masked (a
    Wi-Fi password the registry does not keep) is read from its picture instead, or left out. The
    registry is only read, on the read-only rail, and closed before any code is drawn.

    Steps:
    1. Read every chosen Row in one read-only visit.
    2. For each: skip a record that is gone; count a logo the sheet cannot show.
    3. A masked code's text comes from reading its picture file again.
    4. Encode the text (mask -1: the best of the eight) and add its short address as the caption.
    """
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    rows = []
    try:
        for number in numbers:
            rows.append((number, registry.row_by_id(opened["value"], number)))
    except Exception as error:
        return fail("cannot read the registry: " + str(error))
    finally:
        registry.close(opened["value"])
    codes = []
    skipped = []
    without_logo = 0
    for number, row in rows:
        if row is None:
            skipped.append("record " + str(number) + " is no longer in the registry")
            continue
        if row["has_logo"]:
            without_logo = without_logo + 1
        text = row["link"]
        if row["payload_hash"] is not None:
            picture = qr_codec.read_qr_file(row["path"])
            if not picture["ok"]:
                skipped.append(os.path.basename(row["path"]) + ": the registry does not keep its Wi-Fi password, and "
                               "its picture cannot be read")
                continue
            text = picture["value"]["reading"]["text"]
        made = qr_codec.encode_text(text, row["ec_level"], row["version"], -1)
        if not made["ok"]:
            skipped.append(os.path.basename(row["path"]) + ": " + made["error"])
            continue
        caption = ""
        if row["short_code"] != "":
            caption = shortlinks.caption(row["link"])
        codes.append({"matrix": made["value"], "color": row["hex"], "caption": caption})
    return ok_result({"codes": codes, "skipped": skipped, "without_logo": without_logo})


# --- Files ---------------------------------------------------------------------------------------

def page_paths(path, pages):
    """The files for a sheet of `pages` pages: the path itself, then name-2.svg, name-3.svg, ..."""
    paths = [path]
    stem, extension = os.path.splitext(path)
    for number_of_page in range(2, pages + 1):
        paths.append(stem + "-" + str(number_of_page) + extension)
    return paths


def write_file(path, data):
    """Write bytes to `path` through PATH.part and os.replace, so a failed write leaves no half file
    -> Result path."""
    temporary = path + ".part"
    try:
        handle = open(temporary, "wb")
        try:
            handle.write(data)
        finally:
            handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot write " + path + ": " + str(error))
    return ok_result(path)


def print_sheet(db_path, numbers, layout, path):
    """The registered codes `numbers` on a sheet at `path` -> Result {"files", "pages", "codes", "skipped",
    "without_logo", "smallest_module_mm"}. smallest_module_mm lets the window warn when codes come
    out too small to scan."""
    found = codes_from_registry(db_path, numbers)
    if not found["ok"]:
        return found
    written = write_sheet(path, layout, found["value"]["codes"])
    if not written["ok"]:
        return written
    written["value"]["skipped"] = found["value"]["skipped"]
    written["value"]["without_logo"] = found["value"]["without_logo"]
    written["value"]["smallest_module_mm"] = round(smallest_module(layout, found["value"]["codes"]), 2)
    return written


def write_sheet(path, layout, codes):
    """Write the codes laid out to `path`: .pdf as one PDF, .svg as one drawing per page -> Result
    {"files": [paths], "pages": int, "codes": int}."""
    problem = check_layout(layout)
    if problem != "":
        return fail(problem)
    if len(codes) == 0:
        return fail("choose the codes to print first")
    if path.lower().endswith(".pdf"):
        written = write_file(path, sheet_pdf(layout, codes))
        if not written["ok"]:
            return written
        return ok_result({"files": [path], "pages": page_count(layout, len(codes)), "codes": len(codes)})
    if not path.lower().endswith(".svg"):
        return fail("a sheet is a .pdf or .svg file")
    drawings = sheet_svg(layout, codes)
    paths = page_paths(path, len(drawings))
    for index in range(len(drawings)):
        written = write_file(paths[index], drawings[index].encode("utf-8"))
        if not written["ok"]:
            return written
    return ok_result({"files": paths, "pages": len(drawings), "codes": len(codes)})

# ==== stamp v1 | author=kjFriday | hmac-sha256=64be7b429a1466b5624cba71eb7b788872cadf1eba89721c7e3df75894e5fcce ====
