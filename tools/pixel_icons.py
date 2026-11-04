# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: tools/pixel_icons.py
# About: Turn a 16x16 Silk icon into a project's pixelated icon set (standard library only).
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Turn a 16x16 Silk icon into a project's pixelated icon set (standard library only).

    python tools/pixel_icons.py            # write icon/ into all nine projects
    python tools/pixel_icons.py company/data_dash  # just one (a project folder, relative to the portfolio root)
    python tools/pixel_icons.py --syso app.res out.syso  # app.res -> a Go .syso (needs Visual Studio C++ tools)

Every size is the original enlarged by whole pixels (nearest-neighbour), so the icons stay pixelated.
Each project gets icon/ with the unedited original, app-32/48/256.png, app.ico (16/32/48 as 32-bit BMP,
256 as PNG), app.res (icon group 1 plus a DPI-aware manifest, for linking into an exe) and README.md
with the credit and SHA-256 of every file. Rust projects also get app-32.rgba (raw pixels for a window
icon) and www/favicon.png. A project drawn with native Win32 controls ("controls") gets a manifest that
also asks for Common Controls 6 (themed controls) and declares asInvoker and Windows 10.

Who uses the output: Rust programs link icon/app.res from their build.rs, Go programs link it as a
rsrc_windows_amd64.syso made with --syso, Rust programs with "rgba" embed app-32.rgba as their window
icon, and test_pixel_icons.py checks that
every committed app.res is exactly what this script makes today. Run it by hand after adding a
project to PROJECTS or changing an icon; the README.md files it writes are not to be hand-edited.

The file formats, all written by hand with struct and zlib:
- PNG (ISO/IEC 15948): signature, then chunks of length, type, data and CRC-32. Pixel rows are
  zlib-compressed, each row led by a filter byte. Only 8-bit, non-interlaced images are read.
- ICO: a directory of 16-byte entries, then each image as a headerless BMP (a DIB) or a whole PNG.
- RES: the compiled form of an .rc script, a list of resources each with a 32-byte header; the
  linker (or cvtres.exe plus the Go linker) puts them into the exe's .rsrc section.
- COFF .syso: an object file the Go linker picks up from a package folder; see fix_syso().

Main flow (main -> write_project -> outputs):
1. Read the Silk original and decode it to RGBA (decode_png).
2. Enlarge it by 2, 3 and 16 (scale) and encode the PNGs, the ICO and the RES.
3. Write them, plus the original and a README.md with a SHA-256 per file, to <project>/icon/.

Types: Image (RGBA pixels). Start reading at outputs().
"""

import hashlib
import os
import struct
import sys
import zlib

# ROOT: the portfolio root. SILK: the unedited Silk originals. SIGNATURE: the 8 bytes every PNG starts
# with (high bit, "PNG", CR LF, Ctrl-Z, LF: they catch 7-bit and line-ending damage in transfer).
# SIZES: the icon sizes in px, all whole multiples of 16.
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SILK = os.path.join(ROOT, "icons", "silk")
SIGNATURE = b"\x89PNG\r\n\x1a\n"
SIZES = (16, 32, 48, 256)

# project folder, relative to the portfolio root -> (Silk file, app id, display name, extras)
# extras: "rgba" writes app-32.rgba, "favicon" writes www/favicon.png, "controls" uses CONTROLS_MANIFEST.
# The app id is not written by this script; test_pixel_icons.py only checks that ids are unique.
PROJECTS = {
    "company/crud_hub": ("database.png", "GenericCompany.Hub", "Generic Company CRUD Hub", ()),
    "company/doc_pipeline": ("folder_go.png", "GenericCompany.DocPipe", "Generic Company Doc Pipeline", ()),
    "company/journal": ("newspaper.png", "GenericCompany.CMS", "Generic Company Journal", ()),
    "company/notify_hub": ("bell.png", "GenericCompany.Notify", "Generic Company Notify Hub", ()),
    "company/ticket_tracker": ("note.png", "GenericCompany.Tickets", "Generic Company Ticket Tracker", ("rgba", "favicon")),
    "company/data_dash": ("chart_bar.png", "GenericCompany.Dash", "Generic Company Data Dash", ("rgba", "favicon")),
    "company/wizard_maker": ("wand.png", "GenericCompany.Wizard", "Generic Company Wizard Maker", ("controls",)),
    "tools/dev_console": ("application_xp_terminal.png", "GenericCompany.DevConsole", "Generic Company Dev Console", ("rgba",)),
    "utilities/storage_manager": ("drive_network.png", "GenericCompany.Storage", "Generic Company Storage Manager", ()),
}

# the attribution the CC BY 2.5 license asks for, in one line
CREDIT = ("Icon: Silk by Mark James (famfamfam.com/lab/icons/silk), CC BY 2.5 "
          "(creativecommons.org/licenses/by/2.5), enlarged by nearest-neighbour.")


class Image:
    """Width, height and RGBA bytes, row by row from the top.

    rgba holds 4 bytes per pixel (red, green, blue, alpha; 0 alpha is fully transparent), left to
    right, top row first, with no padding between rows. Images compare equal when size and every
    byte match.
    """

    def __init__(self, width, height, rgba):
        """Keep an immutable copy of the pixels; raises ValueError when the byte count does not fit."""
        if len(rgba) != width * height * 4:
            raise ValueError("pixel data does not match the size")
        self.width, self.height, self.rgba = width, height, bytes(rgba)

    def pixel(self, x, y):
        """The (r, g, b, a) tuple at column x, row y (0, 0 is the top left)."""
        i = (y * self.width + x) * 4
        return tuple(self.rgba[i:i + 4])

    def __eq__(self, other):
        """Equal when width, height and every pixel byte are the same."""
        return (self.width, self.height, self.rgba) == (other.width, other.height, other.rgba)


# --- PNG ---------------------------------------------------------------------------------------

# PNG colour type -> samples per pixel: 0 grey, 2 RGB, 3 palette index, 4 grey + alpha, 6 RGBA
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunks(data):
    """Yield (type, data) for each chunk of a PNG file, through IEND.

    Each chunk is a 4-byte big-endian length, a 4-byte type such as b"IHDR", the data, and a CRC-32
    of type + data (PNG spec section 5.3). Raises ValueError when the signature is wrong or a CRC
    does not match.
    """
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG file")
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if zlib.crc32(kind + body) != struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]:
            raise ValueError(f"bad CRC in {kind!r}")
        yield kind, body
        pos += 12 + length  # 4 length + 4 type + data + 4 CRC
        if kind == b"IEND":
            return


def _paeth(a, b, c):
    """The Paeth predictor (PNG spec section 9.4): whichever of a, b, c is closest to a + b - c.

    a is the byte to the left, b the byte above, c the byte above-left. a + b - c is a linear guess
    of the current byte; ties go to a, then b, then c, exactly as the spec orders them.
    """
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unfilter(raw, width, height, bpp):
    """Undo PNG row filters on decompressed image data; returns the bare pixel bytes.

    raw holds height rows, each a filter-type byte and then width * bpp bytes; bpp is bytes per
    pixel (here the channel count, as only 8-bit images are read). A filter stores each byte as the
    difference from a prediction made from bytes already decoded (PNG spec section 9.2):
    0 None (no prediction), 1 Sub (left), 2 Up (above), 3 Average (floor of the mean of left and
    above), 4 Paeth (see _paeth). Bytes left of the first pixel and above the first row count as 0.
    All sums are modulo 256. Raises ValueError for any other filter type.
    """
    stride = width * bpp
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
            elif kind != 0:
                raise ValueError(f"unknown filter {kind}")
        out += line
        prev = line
    return bytes(out)


def decode_png(data):
    """8-bit, non-interlaced PNG of colour type 0, 2, 3, 4 or 6 -> Image (RGBA).

    Raises ValueError for anything else (other bit depths, Adam7 interlacing, a bad CRC, a palette
    image without PLTE).

    Steps:
    1. Collect IHDR (size and format), PLTE (palette), tRNS (transparency) and every IDAT.
    2. Join the IDAT data, inflate it with zlib and undo the row filters.
    3. Expand each pixel to RGBA by colour type; tRNS gives grey and RGB images one fully
       transparent colour, and palette images one alpha per palette entry (missing ones are 255).
    """
    header, idat, palette, trns = None, bytearray(), None, None
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            # width, height, bit depth, colour type, compression, filter method, interlace
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
    if header is None:
        raise ValueError("no IHDR")
    width, height, depth, ctype, _, _, interlace = header
    if depth != 8 or ctype not in CHANNELS or interlace:
        raise ValueError(f"unsupported PNG (depth {depth}, colour type {ctype}, interlace {interlace})")
    n = CHANNELS[ctype]
    pixels = _unfilter(zlib.decompress(bytes(idat)), width, height, n)
    out = bytearray()
    for i in range(0, len(pixels), n):
        p = pixels[i:i + n]
        if ctype == 6:
            out += p
        elif ctype == 4:
            out += bytes((p[0], p[0], p[0], p[1]))
        elif ctype == 2:
            # tRNS for RGB is three 16-bit big-endian samples; at 8-bit depth the low bytes are the colour
            alpha = 0 if trns and len(trns) == 6 and p == bytes(trns[1::2]) else 255
            out += p + bytes((alpha,))
        elif ctype == 0:
            # tRNS for grey is one 16-bit sample; its low byte is the transparent grey level
            alpha = 0 if trns and len(trns) == 2 and p[0] == trns[1] else 255
            out += bytes((p[0], p[0], p[0], alpha))
        else:
            if palette is None:
                raise ValueError("palette image without PLTE")
            alpha = trns[p[0]] if trns and p[0] < len(trns) else 255
            out += bytes(palette[p[0]]) + bytes((alpha,))
    return Image(width, height, out)


def encode_png(img):
    """RGBA PNG, every row unfiltered; no timestamps, so the pixels and chunks are the same every run.

    IHDR says 8-bit depth, colour type 6 (RGBA), compression 0 (zlib), filter method 0, no
    interlacing. Each row gets filter byte 0 (None); zlib level 9 keeps the files small.
    """
    def chunk(kind, body):
        """One PNG chunk: big-endian length, type, data and CRC-32 of type + data."""
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    stride = img.width * 4
    raw = b"".join(b"\x00" + img.rgba[y * stride:(y + 1) * stride] for y in range(img.height))
    return (SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def scale(img, k):
    """Each pixel becomes a k x k block.

    This is nearest-neighbour enlargement by a whole factor: output row y repeats source row
    y // k, and each source pixel in it is repeated k times, so no new colours appear.
    """
    out = bytearray()
    for y in range(img.height * k):
        row = img.rgba[(y // k) * img.width * 4:(y // k + 1) * img.width * 4]
        for x in range(img.width):
            out += row[x * 4:x * 4 + 4] * k
    return Image(img.width * k, img.height * k, out)


# --- ICO and RES -------------------------------------------------------------------------------

def bmp_entry(img):
    """A 32-bit icon image: BITMAPINFOHEADER (height doubled), BGRA rows bottom-up, then the AND mask.

    Inside an ICO, a BMP image has no file header and its height counts two stacked images: the
    colour (XOR) image and a 1-bit AND mask. The mask has one bit per pixel, most significant bit
    first, each row padded to a multiple of 32 bits; a 1 bit marks a transparent pixel. Windows uses
    the alpha channel of a 32-bit image, but the mask is still expected, so it is written from alpha.
    """
    w, h = img.width, img.height
    mask_stride = ((w + 31) // 32) * 4  # bytes per mask row, rounded up to whole 32-bit words
    pixels, mask = bytearray(), bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(mask_stride)
        for x in range(w):
            r, g, b, a = img.pixel(x, y)
            pixels += bytes((b, g, r, a))
            if a == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    # BITMAPINFOHEADER: size 40, width, height x2, 1 plane, 32 bits, BI_RGB (0), image size,
    # then pixels-per-metre x/y, colours used and important, all 0
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + bytes(pixels) + bytes(mask)


def icon_images(original):
    """[(size, image bytes)] for 16, 32, 48 (BMP) and 256 (PNG).

    The 256 px image is stored as PNG, which ICO files allow since Windows Vista and which is far
    smaller than a 256 KB BMP. The scale factor assumes a 16 px wide original.
    """
    out = []
    for size in SIZES:
        img = scale(original, size // original.width)
        out.append((size, encode_png(img) if size >= 256 else bmp_entry(img)))
    return out


def encode_ico(images):
    """An .ico file from [(size, image bytes)] as made by icon_images.

    Layout: ICONDIR (reserved 0, type 1 = icon, image count), one 16-byte ICONDIRENTRY per image
    (width, height, colour count 0, reserved 0, planes 1, 32 bits per pixel, byte length, offset
    from the start of the file), then the images in order. A width or height of 0 means 256, as
    the field is one byte.
    """
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    return head + entries + blobs


# The default application manifest: per-monitor DPI awareness, so Windows does not blur the window
# by bitmap-stretching it on high-DPI screens. dpiAware "true/pm" is read by Windows 8.1 and later;
# dpiAwareness "PerMonitorV2" by Windows 10 1703 and later, which then ignore dpiAware.
MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""

# For programs drawn with native Win32 controls: themed controls (Common Controls 6), never elevated
# (asInvoker), Windows 10, and the same DPI awareness as MANIFEST.
# Without the Common-Controls 6.0 dependency Windows loads the old, unthemed comctl32 v5. The
# publicKeyToken is Microsoft's fixed token for that assembly; the supportedOS GUID is the one
# Windows defines for Windows 10 and 11.
CONTROLS_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0"
                        processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""

# resource type ids from winuser.h: RT_ICON (one image), RT_GROUP_ICON (the directory naming them),
# RT_MANIFEST (the application manifest; name 1 is the one Windows reads for an exe)
RT_ICON, RT_GROUP_ICON, RT_MANIFEST = 3, 14, 24


def _res_entry(rtype, name, data, flags):
    """One resource in a .res file: a 32-byte header with ordinal type and name, data padded to 4.

    The header (RESOURCEHEADER) is: data size, header size (32), type as 0xFFFF + ordinal id, name
    as 0xFFFF + ordinal id, data version 0, memory flags, language 0x0409 (English, United States),
    version 0, characteristics 0. 0xFFFF marks a number in place of a string name. flags are the
    legacy memory flags rc.exe writes: 0x0010 MOVEABLE, 0x0020 PURE, 0x1000 DISCARDABLE.
    """
    header = struct.pack("<IIHHHHIHHII", len(data), 32, 0xFFFF, rtype, 0xFFFF, name, 0, flags, 0x0409, 0, 0)
    return header + data + b"\x00" * (-len(data) % 4)


def encode_res(images, manifest=MANIFEST):
    """A .res file with each image as RT_ICON 1..n, RT_GROUP_ICON 1 and (optionally) RT_MANIFEST 1.

    The group icon is a GRPICONDIR: the same 6-byte head as an ICO, then one 14-byte entry per
    image, like an ICONDIRENTRY but ending in the 2-byte RT_ICON id instead of a file offset.
    Explorer shows the first group icon (here the only one, id 1) as the exe's icon. A falsy
    manifest leaves the manifest out.
    """
    out = _res_entry(0, 0, b"", 0)  # the empty entry every .res file starts with
    group = struct.pack("<HHH", 0, 1, len(images))
    for i, (size, blob) in enumerate(images, 1):
        out += _res_entry(RT_ICON, i, blob, 0x1010)
        dim = 0 if size >= 256 else size
        group += struct.pack("<BBBBHHIH", dim, dim, 0, 0, 1, 32, len(blob), i)
    out += _res_entry(RT_GROUP_ICON, 1, group, 0x1030)
    if manifest:
        out += _res_entry(RT_MANIFEST, 1, manifest.encode("utf-8"), 0x0030)
    return out


def fix_syso(coff):
    """Make cvtres.exe output linkable by Go: its absolute symbols (@comp.id, @feat.00) have section
    number -1, which Go's linker rejects ("sectnum < 0"); attach them to section 1 as static symbols.

    COFF layout used here (PE/COFF specification): the 20-byte file header holds
    PointerToSymbolTable at offset 8 and NumberOfSymbols at 12. Each symbol record is 18 bytes:
    name (8), value (4), SectionNumber (signed 16-bit, at +12; -1 is IMAGE_SYM_ABSOLUTE), type (2),
    StorageClass (1, at +16) and NumberOfAuxSymbols (1, at +17). Auxiliary records follow their
    symbol and count toward NumberOfSymbols, so the loop steps over them untouched.
    """
    data = bytearray(coff)
    nsym_ptr, nsym = struct.unpack_from("<II", data, 8)
    i = 0
    while i < nsym:
        off = nsym_ptr + 18 * i
        sect, = struct.unpack_from("<h", data, off + 12)
        if sect < 0:
            struct.pack_into("<h", data, off + 12, 1)
            data[off + 16] = 3  # IMAGE_SYM_CLASS_STATIC
        i += 1 + data[off + 17]
    return bytes(data)


def make_syso(res_path, out_path):
    """app.res -> a Go .syso via the MSVC cvtres.exe (Visual Studio), patched by fix_syso.

    Side effects: runs cvtres.exe and writes out_path. Returns out_path. Raises FileNotFoundError
    when no Visual Studio C++ tools are installed, CalledProcessError when cvtres fails.
    Known limitation: the newest cvtres is picked by sorting paths as text, so version folders of
    different digit counts may not sort in true version order.
    """
    import glob
    import subprocess
    # "Program Files*" covers both Program Files and Program Files (x86)
    found = sorted(glob.glob(r"C:\Program Files*\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*\bin\Hostx64\x64\cvtres.exe"))
    if not found:
        raise FileNotFoundError("cvtres.exe (Visual Studio C++ tools) not found")
    subprocess.run([found[-1], "/nologo", "/machine:x64", f"/out:{out_path}", res_path], check=True)
    with open(out_path, "rb") as f:
        fixed = fix_syso(f.read())
    with open(out_path, "wb") as f:
        f.write(fixed)
    return out_path


def rgba_file(img):
    """Raw pixels with an 8-byte header (width, height as little-endian u32).

    The Rust programs embed this file and hand the pixels straight to their window as its icon,
    with no image decoder needed at run time.
    """
    return struct.pack("<II", img.width, img.height) + img.rgba


# --- projects ----------------------------------------------------------------------------------

# icon/README.md: the credit (CC BY 2.5 asks for attribution and a note of changes) and a table of
# every file with its SHA-256; {rows} is filled by write_project
README = """# icon/

{name}'s icon is **{silk}** from the Silk icon set by Mark James
(famfamfam.com/lab/icons/silk), licensed under
[Creative Commons Attribution 2.5](http://creativecommons.org/licenses/by/2.5/).

Change made: the 16×16 original is enlarged by whole pixels (nearest-neighbour) to 32, 48 and 256 px, so
every size stays pixelated. `{original}` is the unedited original.

Generated by `tools/pixel_icons.py` in the portfolio repo; do not edit by hand.

| File | What | SHA-256 |
|---|---|---|
{rows}
"""

# README "What" column per output file; the original's row text is supplied in write_project
WHAT = {
    "app-32.png": "32 px (×2)",
    "app-48.png": "48 px (×3)",
    "app-256.png": "256 px (×16)",
    "app.ico": "16/32/48 px as 32-bit BMP, 256 px as PNG",
    "app.res": "RT_GROUP_ICON 1 + DPI-aware manifest, for linking into an exe",
    "app-32.rgba": "32 px raw RGBA (8-byte width/height header) for the window icon",
}
# the app.res row for a "controls" project, whose manifest says more
WHAT_CONTROLS_RES = "RT_GROUP_ICON 1 + DPI-aware, Common Controls 6, asInvoker manifest, for linking into an exe"


def outputs(original_bytes, extras=()):
    """{relative path: bytes} for one project.

    original_bytes is the Silk PNG file; extras as in PROJECTS ("rgba", "controls"; "favicon" is
    handled by write_project). Raises ValueError unless the original is 16 x 16. Pure: writes nothing.
    """
    img = decode_png(original_bytes)
    if (img.width, img.height) != (16, 16):
        raise ValueError("expected a 16x16 icon")
    images = icon_images(img)
    files = {
        "app-32.png": encode_png(scale(img, 2)),
        "app-48.png": encode_png(scale(img, 3)),
        "app-256.png": encode_png(scale(img, 16)),
        "app.ico": encode_ico(images),
        "app.res": encode_res(images, CONTROLS_MANIFEST if "controls" in extras else MANIFEST),
    }
    if "rgba" in extras:
        files["app-32.rgba"] = rgba_file(scale(img, 2))
    return files


def sha(data):
    """SHA-256 of data as 64 lowercase hex digits, for the README table."""
    return hashlib.sha256(data).hexdigest()


def write_project(project_dir, silk_file, name, extras=()):
    """Write project_dir/icon/ (and www/favicon.png when asked); returns the paths written.

    silk_file is a file name in SILK, name the program's display name for the README. Creates the
    folders as needed and overwrites existing files. README.md is written with LF endings and is
    not in the returned list.

    Steps:
    1. Read the original and build every output (outputs), plus a copy of the original.
    2. Write each file and collect a README row with its SHA-256.
    3. Write README.md, then the favicon (the 32 px PNG) if "favicon" is in extras.
    """
    with open(os.path.join(SILK, silk_file), "rb") as f:
        original = f.read()
    folder = os.path.join(project_dir, "icon")
    os.makedirs(folder, exist_ok=True)
    files = {f"silk-{silk_file}": original, **outputs(original, extras)}
    what = {**WHAT, "app.res": WHAT_CONTROLS_RES} if "controls" in extras else WHAT
    rows = []
    for rel, data in files.items():
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(data)
        rows.append(f"| `{rel}` | {what.get(rel, 'original, unedited (16 px)')} | `{sha(data)}` |")
    written = [os.path.join(folder, rel) for rel in files]
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(README.format(name=name, silk=silk_file, original=f"silk-{silk_file}", rows="\n".join(rows)))
    if "favicon" in extras:
        www = os.path.join(project_dir, "www")
        os.makedirs(www, exist_ok=True)
        with open(os.path.join(www, "favicon.png"), "wb") as f:
            f.write(files["app-32.png"])
        written.append(os.path.join(www, "favicon.png"))
    return written


def main(argv):
    """Command line: "--syso RES OUT" makes a .syso; else write the named projects (all if none).

    Prints each path written, relative to the portfolio root. A project folder that is not in
    PROJECTS raises KeyError.
    """
    if argv[:1] == ["--syso"]:  # --syso app.res out.syso
        print(make_syso(argv[1], argv[2]))
        return
    names = argv or list(PROJECTS)
    for project in names:
        silk_file, _, name, extras = PROJECTS[project]
        for path in write_project(os.path.join(ROOT, project), silk_file, name, extras):
            print(os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main(sys.argv[1:])

# ==== stamp v1 | author=kjFriday | hmac-sha256=4c14dc9b79c663fcca9e36e9b1b9caa47f12e39e6b50dc4195b635905380b50e ====
