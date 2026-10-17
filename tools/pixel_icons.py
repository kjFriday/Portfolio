"""Turn a 16x16 Silk icon into a project's pixelated icon set (standard library only).

    python tools/pixel_icons.py            # write icon/ into all six projects
    python tools/pixel_icons.py data_dash  # just one

Every size is the original enlarged by whole pixels (nearest-neighbour), so the icons stay pixelated.
Each project gets icon/ with the unedited original, app-32/48/256.png, app.ico (16/32/48 as 32-bit BMP,
256 as PNG), app.res (icon group 1 plus a DPI-aware manifest, for linking into an exe) and README.md
with the credit and SHA-256 of every file. Rust projects also get app-32.rgba (raw pixels for a window
icon) and www/favicon.png.
"""

import hashlib
import os
import struct
import sys
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SILK = os.path.join(ROOT, "icons", "silk")
SIGNATURE = b"\x89PNG\r\n\x1a\n"
SIZES = (16, 32, 48, 256)

# project folder -> (Silk file, app id, display name, extras)
PROJECTS = {
    "create_read_update_delete_simple_io_data_base": ("database.png", "ACME.Hub", "ACME CRUD Hub", ()),
    "document_mover_and_changer": ("folder_go.png", "ACME.DocPipe", "ACME Doc Pipeline", ()),
    "content_management_system": ("newspaper.png", "ACME.CMS", "ACME Journal", ()),
    "notification_and_message_hub": ("bell.png", "ACME.Notify", "ACME Notify Hub", ()),
    "simple_ticket_tracker": ("note.png", "ACME.Tickets", "ACME Ticket Tracker", ("rgba", "favicon")),
    "data_dash": ("chart_bar.png", "ACME.Dash", "ACME Data Dash", ("rgba", "favicon")),
}

CREDIT = ("Icon: Silk by Mark James (famfamfam.com/lab/icons/silk), CC BY 2.5 "
          "(creativecommons.org/licenses/by/2.5), enlarged by nearest-neighbour.")


class Image:
    """Width, height and RGBA bytes, row by row from the top."""

    def __init__(self, width, height, rgba):
        if len(rgba) != width * height * 4:
            raise ValueError("pixel data does not match the size")
        self.width, self.height, self.rgba = width, height, bytes(rgba)

    def pixel(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.rgba[i:i + 4])

    def __eq__(self, other):
        return (self.width, self.height, self.rgba) == (other.width, other.height, other.rgba)


# --- PNG ---------------------------------------------------------------------------------------

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunks(data):
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG file")
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if zlib.crc32(kind + body) != struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]:
            raise ValueError(f"bad CRC in {kind!r}")
        yield kind, body
        pos += 12 + length
        if kind == b"IEND":
            return


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unfilter(raw, width, height, bpp):
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
    """8-bit, non-interlaced PNG of colour type 0, 2, 3, 4 or 6 -> Image (RGBA)."""
    header, idat, palette, trns = None, bytearray(), None, None
    for kind, body in _chunks(data):
        if kind == b"IHDR":
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
            alpha = 0 if trns and len(trns) == 6 and p == bytes(trns[1::2]) else 255
            out += p + bytes((alpha,))
        elif ctype == 0:
            alpha = 0 if trns and len(trns) == 2 and p[0] == trns[1] else 255
            out += bytes((p[0], p[0], p[0], alpha))
        else:
            if palette is None:
                raise ValueError("palette image without PLTE")
            alpha = trns[p[0]] if trns and p[0] < len(trns) else 255
            out += bytes(palette[p[0]]) + bytes((alpha,))
    return Image(width, height, out)


def encode_png(img):
    """RGBA PNG, every row unfiltered; no timestamps, so the pixels and chunks are the same every run."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    stride = img.width * 4
    raw = b"".join(b"\x00" + img.rgba[y * stride:(y + 1) * stride] for y in range(img.height))
    return (SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def scale(img, k):
    """Each pixel becomes a k x k block."""
    out = bytearray()
    for y in range(img.height * k):
        row = img.rgba[(y // k) * img.width * 4:(y // k + 1) * img.width * 4]
        for x in range(img.width):
            out += row[x * 4:x * 4 + 4] * k
    return Image(img.width * k, img.height * k, out)


# --- ICO and RES -------------------------------------------------------------------------------

def bmp_entry(img):
    """A 32-bit icon image: BITMAPINFOHEADER (height doubled), BGRA rows bottom-up, then the AND mask."""
    w, h = img.width, img.height
    mask_stride = ((w + 31) // 32) * 4
    pixels, mask = bytearray(), bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(mask_stride)
        for x in range(w):
            r, g, b, a = img.pixel(x, y)
            pixels += bytes((b, g, r, a))
            if a == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + bytes(pixels) + bytes(mask)


def icon_images(original):
    """[(size, image bytes)] for 16, 32, 48 (BMP) and 256 (PNG)."""
    out = []
    for size in SIZES:
        img = scale(original, size // original.width)
        out.append((size, encode_png(img) if size >= 256 else bmp_entry(img)))
    return out


def encode_ico(images):
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    return head + entries + blobs


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

RT_ICON, RT_GROUP_ICON, RT_MANIFEST = 3, 14, 24


def _res_entry(rtype, name, data, flags):
    """One resource in a .res file: a 32-byte header with ordinal type and name, data padded to 4."""
    header = struct.pack("<IIHHHHIHHII", len(data), 32, 0xFFFF, rtype, 0xFFFF, name, 0, flags, 0x0409, 0, 0)
    return header + data + b"\x00" * (-len(data) % 4)


def encode_res(images, manifest=MANIFEST):
    """A .res file with each image as RT_ICON 1..n, RT_GROUP_ICON 1 and (optionally) RT_MANIFEST 1."""
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
    number -1, which Go's linker rejects ("sectnum < 0"); attach them to section 1 as static symbols."""
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
    """app.res -> a Go .syso via the MSVC cvtres.exe (Visual Studio), patched by fix_syso."""
    import glob
    import subprocess
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
    """Raw pixels with an 8-byte header (width, height as little-endian u32)."""
    return struct.pack("<II", img.width, img.height) + img.rgba


# --- projects ----------------------------------------------------------------------------------

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

WHAT = {
    "app-32.png": "32 px (×2)",
    "app-48.png": "48 px (×3)",
    "app-256.png": "256 px (×16)",
    "app.ico": "16/32/48 px as 32-bit BMP, 256 px as PNG",
    "app.res": "RT_GROUP_ICON 1 + DPI-aware manifest, for linking into an exe",
    "app-32.rgba": "32 px raw RGBA (8-byte width/height header) for the window icon",
}


def outputs(original_bytes, extras=()):
    """{relative path: bytes} for one project."""
    img = decode_png(original_bytes)
    if (img.width, img.height) != (16, 16):
        raise ValueError("expected a 16x16 icon")
    images = icon_images(img)
    files = {
        "app-32.png": encode_png(scale(img, 2)),
        "app-48.png": encode_png(scale(img, 3)),
        "app-256.png": encode_png(scale(img, 16)),
        "app.ico": encode_ico(images),
        "app.res": encode_res(images),
    }
    if "rgba" in extras:
        files["app-32.rgba"] = rgba_file(scale(img, 2))
    return files


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_project(project_dir, silk_file, name, extras=()):
    """Write project_dir/icon/ (and www/favicon.png when asked); returns the paths written."""
    with open(os.path.join(SILK, silk_file), "rb") as f:
        original = f.read()
    folder = os.path.join(project_dir, "icon")
    os.makedirs(folder, exist_ok=True)
    files = {f"silk-{silk_file}": original, **outputs(original, extras)}
    rows = []
    for rel, data in files.items():
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(data)
        rows.append(f"| `{rel}` | {WHAT.get(rel, 'original, unedited (16 px)')} | `{sha(data)}` |")
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
