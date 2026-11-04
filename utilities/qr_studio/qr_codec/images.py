# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/images.py
# About: Pictures: the Image record, PNG and binary PGM/PPM reading, PNG and SVG writing.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Pictures: the Image record, PNG and binary PGM/PPM reading, PNG and SVG writing.

Image {"width": int, "height": int, "gray": bytearray}: one byte per pixel, rows from the top,
0 = black. Colors are read as gray, and transparent pixels are laid over white.
"""

import struct
import zlib

from .records import fail, ok_result


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_image(width, height, fill):
    return {"width": width, "height": height, "gray": bytearray([fill]) * (width * height)}


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


def matrix_to_svg(matrix, border):
    size = matrix["size"]
    side = size + 2 * border
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + str(side) + " " + str(side) +
             '" shape-rendering="crispEdges">\n<rect width="100%" height="100%" fill="#ffffff"/>\n<path d="']
    for y in range(size):
        for x in range(size):
            if matrix["dark"][y][x]:
                parts.append("M" + str(x + border) + "," + str(y + border) + "h1v1h-1z")
    parts.append('" fill="#000000"/>\n</svg>\n')
    return "".join(parts)


def png_chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def write_png(image):
    """Image -> PNG bytes (8-bit grayscale)."""
    width = image["width"]
    rows = bytearray()
    for y in range(image["height"]):
        rows.append(0)
        rows.extend(image["gray"][y * width:(y + 1) * width])
    header = struct.pack(">IIBBBBB", width, image["height"], 8, 0, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
            png_chunk(b"IEND", b""))


def paeth(a, b, c):
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
    """PNG bytes -> Result Image (gray). Transparent pixels are laid over white."""
    if data[:8] != PNG_SIGNATURE:
        return fail("not a PNG file")
    position = 8
    header = None
    palette = b""
    compressed = bytearray()
    while position + 8 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position = position + 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if header is None:
        return fail("PNG has no header")
    width, height, depth, colour, compression, filtering, interlace = header
    if interlace != 0:
        return fail("interlaced PNG is not supported; save it without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour, 0)
    if channels == 0 or depth not in (1, 2, 4, 8, 16) or (depth < 8 and colour not in (0, 3)):
        return fail("unsupported PNG colour type")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error:
        return fail("PNG data is damaged")
    bits_per_pixel = channels * depth
    stride = (width * bits_per_pixel + 7) // 8
    step = max(1, bits_per_pixel // 8)
    if len(raw) < height * (stride + 1):
        return fail("PNG data is cut short")
    image = make_image(width, height, 255)
    gray = image["gray"]
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        kind = raw[offset]
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
                    gray[out + x] = palette_gray(palette, sample)
                else:
                    gray[out + x] = sample * 255 // top
        elif colour == 0:
            gray[out:out + width] = row[:width]
        elif colour == 3:
            for x in range(width):
                gray[out + x] = palette_gray(palette, row[x])
        elif colour == 4:
            for x in range(width):
                gray[out + x] = over_white(row[2 * x], row[2 * x + 1])
        elif colour == 2:
            for x in range(width):
                i = 3 * x
                gray[out + x] = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
        else:
            for x in range(width):
                i = 4 * x
                value = (row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000
                gray[out + x] = over_white(value, row[i + 3])
    return ok_result(image)


def palette_gray(palette, index):
    i = index * 3
    if i + 2 >= len(palette):
        return 255
    return (palette[i] * 299 + palette[i + 1] * 587 + palette[i + 2] * 114) // 1000


def over_white(value, alpha):
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
    width = int(fields[1])
    height = int(fields[2])
    if int(fields[3]) != 255:
        return fail("only 8-bit PGM/PPM is supported")
    pixels = data[position + 1:]
    image = make_image(width, height, 255)
    if fields[0] == b"P5":
        image["gray"][:] = pixels[:width * height]
        return ok_result(image)
    gray = image["gray"]
    for i in range(width * height):
        j = 3 * i
        gray[i] = (pixels[j] * 299 + pixels[j + 1] * 587 + pixels[j + 2] * 114) // 1000
    return ok_result(image)


def read_image_bytes(data):
    if data[:8] == PNG_SIGNATURE:
        return read_png(data)
    if data[:2] in (b"P5", b"P6"):
        return read_ppm(data)
    return fail("use a PNG picture (other formats open through the window)")


def load_image_file(path):
    try:
        handle = open(path, "rb")
        data = handle.read()
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=8f211def56e4dcf4fe8970b2ba073b50500d76d93e3549998d325beaed74896f ====
