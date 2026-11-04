# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/images.py
# About: Pictures: the Image record, PNG and binary PGM/PPM reading within limits, and PNG writing.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Pictures: the Image record, PNG and binary PGM/PPM reading within limits, and PNG writing.

Image {"width": int, "height": int, "gray": bytearray, "rgb": bytearray or None}: one gray byte per
pixel, rows from the top, 0 = black; "rgb" has three bytes per pixel when the picture was in color.
PNGs are written in gray (write_png) or in two colors with an optional caption (matrix_to_color_png).
Files over MAX_FILE_BYTES and pictures over MAX_SIDE pixels a side are refused before their pixels
are read. MAX_FILE_BYTES has its one home here: svg.py and files.py read it as images.MAX_FILE_BYTES,
and setting qr_codec.MAX_FILE_BYTES (as the tests do) sets it here, so a change reaches every reader.

A PNG file (ISO/IEC 15948) is an 8-byte signature and a list of chunks: IHDR (size and pixel format),
PLTE (palette), tRNS (transparency), one or more IDAT (the zlib-compressed pixel rows) and IEND. Before
compression each row gets a filter-type byte and its bytes are stored as differences from a predicted
value (PNG section 9), which makes them compress better; reading undoes that (unfilter_row).

Callers: files.py (saving colour PNGs and loading pictures), locate.py (shrink_image), svg.py
(MAX_FILE_BYTES), logos.py (png_chunk), the Make tab (gui/make_tab.py) and the tests.

Start reading at read_image_bytes for reading and write_png for writing.
"""

import os
import struct
import zlib

from .records import fail, ok_result
from .captions import caption_layout, caption_pixels, caption_size


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_FILE_BYTES = 20 * 1024 * 1024  # a picture file bigger than this is refused
MAX_SIDE = 4096  # and so is a picture wider or taller than this, before any pixel memory is taken


def make_image(width, height, fill):
    """A new gray Image of width x height pixels, every pixel `fill` (0 black .. 255 white), no rgb."""
    return {"width": width, "height": height, "gray": bytearray([fill]) * (width * height), "rgb": None}


def matrix_to_image(matrix, scale, border):
    """A black-on-white picture of the matrix, `scale` pixels per module, `border` modules of quiet zone."""
    size = matrix["size"]
    side = (size + 2 * border) * scale
    image = make_image(side, side, 255)
    gray = image["gray"]
    for y in range(size):
        for x in range(size):
            if matrix["dark"][y][x]:
                top = (y + border) * scale
                left = (x + border) * scale
                for row in range(top, top + scale):
                    start = row * side + left
                    gray[start:start + scale] = bytes(scale)
    return image


def png_chunk(kind, data):
    """One PNG chunk as bytes: data's length (4 bytes, big-endian), the 4-byte kind, data, and a CRC-32.

    The CRC covers the kind and the data, not the length, so a reader can tell a damaged chunk.
    """
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def write_png(image):
    """Image -> PNG bytes (8-bit grayscale).

    Each row is written with filter type 0 (no prediction); a two-tone code compresses well without
    one. The IHDR fields after the size are bit depth 8, colour type 0 (gray), and 0 for the
    compression method, filter method and interlacing.
    """
    width = image["width"]
    rows = bytearray()
    for y in range(image["height"]):
        rows.append(0)
        rows.extend(image["gray"][y * width:(y + 1) * width])
    header = struct.pack(">IIBBBBB", width, image["height"], 8, 0, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
            png_chunk(b"IEND", b""))


def matrix_to_color_png(matrix, scale, border, color, caption=""):
    """The matrix as PNG bytes in two colors: `color` ("#rrggbb") modules on white. A palette PNG
    (colour type 3, 8 bits) whose entry 0 is white and entry 1 is the color. A caption is drawn
    below the quiet zone in the same color; the picture grows taller (and wider, only if it must)."""
    size = matrix["size"]
    side = (size + 2 * border) * scale
    width = side
    height = side
    lines = []
    pixel = 1
    if caption != "":
        lines, pixel = caption_layout(caption, side, scale)
        band = caption_size(lines, pixel, scale)
        width = max(side, band[0] + 2 * scale)
        height = side + band[1]
    canvas = bytearray(width * height)
    left = (width - side) // 2
    for module_y in range(size):
        for module_x in range(size):
            if matrix["dark"][module_y][module_x]:
                x = left + (module_x + border) * scale
                for y in range((module_y + border) * scale, (module_y + border + 1) * scale):
                    canvas[y * width + x:y * width + x + scale] = b"\x01" * scale
    for corner in caption_pixels(lines, pixel, width, side):
        for y in range(corner[1], corner[1] + pixel):
            canvas[y * width + corner[0]:y * width + corner[0] + pixel] = b"\x01" * pixel
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(canvas[y * width:(y + 1) * width])
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    entries = bytes([255, 255, 255, int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)])
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"PLTE", entries) +
            png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + png_chunk(b"IEND", b""))


def paeth(a, b, c):
    """The Paeth predictor (PNG section 9.4): whichever of left a, above b and upper-left c is nearest a + b - c.

    a + b - c is what the byte would be if the picture changed at the same rate along the row as it
    does along the row above (a flat gradient). The neighbour closest to that guess is used, ties going
    to a, then b, then c, exactly as the PNG specification orders them; any other order would decode
    some files wrongly.
    """
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def unfilter_row(kind, row, previous, step):
    """Undo PNG filter type `kind` on one row of bytes, in place, and return it.

    previous is the row above, already unfiltered (all zeros for the first row); step is the bytes per
    whole pixel, at least 1, so "left" means the same channel of the pixel before. A filtered byte holds
    the original minus a prediction, modulo 256, so adding the prediction back (& 0xFF) restores it.
    The five filter types (PNG section 9.2), with left = a, above = b, upper-left = c:
    0 None: no prediction. 1 Sub: a. 2 Up: b. 3 Average: (a + b) // 2. 4 Paeth: paeth(a, b, c).
    Bytes left of the first pixel count as 0. The row must be unfiltered left to right, since each
    byte's prediction uses the restored byte before it.
    """
    if kind == 0:
        return row
    if kind == 2:
        for i in range(len(row)):
            row[i] = (row[i] + previous[i]) & 0xFF
        return row
    for i in range(len(row)):
        if i >= step:
            left = row[i - step]
        else:
            left = 0
        if kind == 1:
            row[i] = (row[i] + left) & 0xFF
        elif kind == 3:
            row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:
            if i >= step:
                upper_left = previous[i - step]
            else:
                upper_left = 0
            row[i] = (row[i] + paeth(left, previous[i], upper_left)) & 0xFF
    return row


def read_png(data):
    """PNG bytes -> Result Image. Transparent pixels (an alpha channel or a tRNS chunk) are laid over
    white. Pictures in color also keep their colors ("rgb"). Pictures wider or taller than MAX_SIDE
    are refused before any pixel memory is taken, and so is image data that unpacks to more than it
    should."""
    if data[:8] != PNG_SIGNATURE:
        return fail("not a PNG file")
    position = 8
    header = None
    palette = b""
    transparency = b""
    compressed = bytearray()
    while position + 8 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position = position + 12 + length
        if kind == b"IHDR":
            if len(body) != 13:
                return fail("PNG header is damaged")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if header is None:
        return fail("PNG has no header")
    width, height, depth, colour, compression, filtering, interlace = header
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        return fail("the picture is too big (largest side " + str(MAX_SIDE) + " pixels)")
    if interlace != 0:
        return fail("interlaced PNG is not supported; save it without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour, 0)
    if channels == 0 or depth not in (1, 2, 4, 8, 16) or (depth < 8 and colour not in (0, 3)):
        return fail("unsupported PNG colour type")
    bits_per_pixel = channels * depth
    stride = (width * bits_per_pixel + 7) // 8
    step = max(1, bits_per_pixel // 8)
    expected = height * (stride + 1)
    try:
        unpacker = zlib.decompressobj()
        raw = unpacker.decompress(bytes(compressed), expected + 1)
    except zlib.error:
        return fail("PNG data is damaged")
    if len(raw) > expected or len(unpacker.unconsumed_tail) > 0:
        return fail("PNG data is larger than its picture")
    if len(raw) < expected:
        return fail("PNG data is cut short")
    image = make_image(width, height, 255)
    gray = image["gray"]
    rgb = None
    if colour in (2, 3, 6):
        rgb = bytearray(b"\xff") * (3 * width * height)
        image["rgb"] = rgb
    key = transparent_key(colour, depth, transparency)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        kind = raw[offset]
        if kind > 4:
            return fail("PNG data is damaged")
        row = unfilter_row(kind, bytearray(raw[offset + 1:offset + 1 + stride]), previous, step)
        offset = offset + 1 + stride
        previous = row
        if depth == 16:
            row = row[0::2]
        out = y * width
        if depth < 8:
            per_byte = 8 // depth
            top = (1 << depth) - 1
            for x in range(width):
                sample = (row[x // per_byte] >> (8 - depth * (x % per_byte + 1))) & top
                if colour == 3:
                    put_palette(image, out + x, palette, transparency, sample)
                elif sample == key:
                    gray[out + x] = 255
                else:
                    gray[out + x] = sample * 255 // top
        elif colour == 0:
            for x in range(width):
                if row[x] == key:
                    gray[out + x] = 255
                else:
                    gray[out + x] = row[x]
        elif colour == 3:
            for x in range(width):
                put_palette(image, out + x, palette, transparency, row[x])
        elif colour == 4:
            for x in range(width):
                gray[out + x] = over_white(row[2 * x], row[2 * x + 1])
        elif colour == 2:
            for x in range(width):
                i = 3 * x
                if key >= 0 and (row[i] << 16 | row[i + 1] << 8 | row[i + 2]) == key:
                    continue
                gray[out + x] = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                rgb[3 * (out + x):3 * (out + x) + 3] = row[i:i + 3]
        else:
            for x in range(width):
                i = 4 * x
                value = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                gray[out + x] = over_white(value, row[i + 3])
                j = 3 * (out + x)
                rgb[j] = over_white(row[i], row[i + 3])
                rgb[j + 1] = over_white(row[i + 1], row[i + 3])
                rgb[j + 2] = over_white(row[i + 2], row[i + 3])
    return ok_result(image)


def transparent_key(colour, depth, transparency):
    """The one sample value a tRNS chunk makes transparent in a gray (0) or RGB (2) picture, or -1.
    16-bit pictures are read by their high bytes, so their key is compared the same way."""
    if colour == 0 and len(transparency) >= 2:
        value = struct.unpack(">H", transparency[0:2])[0]
        if depth == 16:
            return value >> 8
        return value
    if colour == 2 and len(transparency) >= 6:
        red, green, blue = struct.unpack(">HHH", transparency[0:6])
        if depth == 16:
            red, green, blue = red >> 8, green >> 8, blue >> 8
        return red << 16 | green << 8 | blue
    return -1


def put_palette(image, index, palette, transparency, entry):
    """One palette pixel into the gray and rgb planes, laid over white by its tRNS alpha."""
    i = entry * 3
    if i + 2 >= len(palette):
        image["gray"][index] = 255
        return
    alpha = 255
    if entry < len(transparency):
        alpha = transparency[entry]
    red = over_white(palette[i], alpha)
    green = over_white(palette[i + 1], alpha)
    blue = over_white(palette[i + 2], alpha)
    image["gray"][index] = (red * 299 + green * 587 + blue * 114) // 1000
    if image["rgb"] is not None:
        image["rgb"][3 * index] = red
        image["rgb"][3 * index + 1] = green
        image["rgb"][3 * index + 2] = blue


def palette_gray(palette, index):
    """Gray level of palette entry `index` (a PLTE body of R, G, B triples); a missing entry reads as white.

    Gray is the luma of ITU-R BT.601, 0.299 R + 0.587 G + 0.114 B, in integer thousandths: green looks
    brightest to the eye and blue darkest.
    """
    i = index * 3
    if i + 2 >= len(palette):
        return 255
    return (palette[i] * 299 + palette[i + 1] * 587 + palette[i + 2] * 114) // 1000


def over_white(value, alpha):
    """A channel value (0..255) with opacity alpha (0 clear .. 255 opaque) laid over white, rounded down.

    Alpha blending: value * alpha / 255 + 255 * (1 - alpha / 255), done in integers.
    """
    return (value * alpha + 255 * (255 - alpha)) // 255


def read_ppm(data):
    """Binary PGM (P5) or PPM (P6) bytes, 8-bit -> Result Image."""
    fields = []
    position = 0
    while len(fields) < 4 and position < len(data):
        while position < len(data) and data[position:position + 1].isspace():
            position = position + 1
        if data[position:position + 1] == b"#":
            while position < len(data) and data[position:position + 1] != b"\n":
                position = position + 1
            continue
        start = position
        while position < len(data) and not data[position:position + 1].isspace():
            position = position + 1
        fields.append(data[start:position])
    if len(fields) < 4 or fields[0] not in (b"P5", b"P6"):
        return fail("not a binary PGM/PPM file")
    if not fields[1].isdigit() or not fields[2].isdigit() or not fields[3].isdigit():
        return fail("not a binary PGM/PPM file")
    width = int(fields[1])
    height = int(fields[2])
    if int(fields[3]) != 255:
        return fail("only 8-bit PGM/PPM is supported")
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        return fail("the picture is too big (largest side " + str(MAX_SIDE) + " pixels)")
    pixels = data[position + 1:]
    channels = 1
    if fields[0] == b"P6":
        channels = 3
    if len(pixels) < width * height * channels:
        return fail("PGM/PPM data is cut short")
    image = make_image(width, height, 255)
    if fields[0] == b"P5":
        image["gray"][:] = pixels[:width * height]
        return ok_result(image)
    gray = image["gray"]
    image["rgb"] = bytearray(pixels[:3 * width * height])
    for i in range(width * height):
        j = 3 * i
        gray[i] = (pixels[j] * 299 + pixels[j + 1] * 587 + pixels[j + 2] * 114) // 1000
    return ok_result(image)


def read_image_bytes(data):
    """PNG, PGM or PPM bytes -> Result Image. A damaged file is a failed Result, never an exception."""
    if len(data) > MAX_FILE_BYTES:
        return fail("the picture file is too big")
    try:
        if data[:8] == PNG_SIGNATURE:
            return read_png(data)
        if data[:2] in (b"P5", b"P6"):
            return read_ppm(data)
    except Exception as error:
        return fail("the picture is damaged (" + type(error).__name__ + ")")
    return fail("use a PNG picture (other formats open through the window)")


def load_image_file(path):
    """A picture file -> Result Image. Files over MAX_FILE_BYTES are refused before they are read."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return fail("the picture file is too big")
        handle = open(path, "rb")
        data = handle.read(MAX_FILE_BYTES + 1)
        handle.close()
    except OSError as error:
        return fail("cannot open " + path + ": " + str(error))
    return read_image_bytes(data)


def shrink_image(image, factor):
    """Every `factor`-th pixel's block averaged into one pixel."""
    width = image["width"] // factor
    height = image["height"] // factor
    result = make_image(width, height, 255)
    source = image["gray"]
    source_width = image["width"]
    area = factor * factor
    for y in range(height):
        for x in range(width):
            total = 0
            for dy in range(factor):
                start = (y * factor + dy) * source_width + x * factor
                total = total + sum(source[start:start + factor])
            result["gray"][y * width + x] = total // area
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=b1021e127c8e15b8be92746305779f375fdd85b6121c430342a4edb033b4999a ====
