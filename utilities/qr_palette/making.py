# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: making.py
# About: Making codes: draw a code, save it, read it back to prove it scans, and register it; or...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Making codes: draw a code, save it, read it back to prove it scans, and register it; or draw one again.

make_qr is the Make tab's Save. It cleans the text, checks that the color is dark enough to scan on white,
plans the short link when one is asked for (short_link_ops.plan_short_link), encodes the text (at level H
around a logo, when there is one), saves a PNG or SVG, reads the file back and registers it; a file that
does not read back the same is removed. A Wi-Fi password never reaches the registry: only the text with it
masked, and a keyed hash of the real text that finds the record again when the code is scanned
(masked_entry). redraw_record draws a registered code again in another color, read back before it
replaces the old file. register_picture adds a picture made elsewhere, and forget_record removes a record
(never its file). Also here: the window's previews and robustness scores, drawn by the same codec.

Records
  Made     {"id": int, "path": str, "link": str, "color": "#rrggbb", "version": int, "level": str,
            "short_code": str, "target": str}            link is what the code holds; "" when not short
  Picture  {"reading": Reading, "format": "png" | "svg" | "other", "color": "#rrggbb", "image": Image or None}
"""

import os
import struct

import localkey
import payloads
import qr_codec
import registry
import shortlinks
import swatch
import textsafe
from common import fail, ok_result, with_registry
from short_link_ops import plan_short_link

# The room for a code in the window's previews, in pixels (the Make tab's canvas is PREVIEW + 20 square).
PREVIEW = 340
ROBUSTNESS_SCALE = 4  # pixels per module for the robustness score: decoding is pure Python


def slug(text):
    """A short file-name part from a link: "https://shop.example.com/sale" -> "shop-example-com-sale"."""
    lowered = text.lower()
    if "://" in lowered:
        lowered = lowered[lowered.index("://") + 3:]
    parts = []
    word = ""
    for character in lowered:
        if character.isalnum() and character.isascii():
            word = word + character
        elif word != "":
            parts.append(word)
            word = ""
    if word != "":
        parts.append(word)
    if len(parts) > 0 and parts[0] == "www":
        parts = parts[1:]
    name = "-".join(parts)[:40].strip("-")
    return name or "qr-code"


def suggested_name(link, color, kind):
    """A file name for a code. A secret in the text (a Wi-Fi password) never reaches it."""
    return slug(payloads.stored_form(link)[0]) + "-" + color[1:] + "." + kind


def masked_entry(db_path, text, entry):
    """Fill in a code's Entry from the text it holds -> Result Entry. A secret (a Wi-Fi password) is
    never stored: the Entry gets the text with it masked, and a hash of the real text under the
    registry's local key, which finds the record again when the code is scanned."""
    stored, masked = payloads.stored_form(text)
    entry["link"] = stored
    if masked:
        key = localkey.key_for(db_path)
        if not key["ok"]:
            return key
        entry["payload_hash"] = localkey.tag(key["value"], "payload", text)
    return ok_result(entry)


def make_qr(db_path, link, color, level, path, scale, short=None, logo=None, built=False):
    """Draw `link` as a QR code in `color`, save it to `path` (.png or .svg), read the file back to
    prove it scans, and register it -> Result Made. With `short` (see short_request), `link` is the
    destination: the code holds a short link to it instead, with that address printed under it.
    With `logo` (an Image), the code is level H with the logo in its middle (qr_codec.place_logo).
    With `built`, `link` is a payloads.build text, used exactly as it is: its line ends are part of
    it. Made's link is what the registry keeps, so a Wi-Fi password is masked there too."""
    text = link
    if not built:
        text = textsafe.clean(link, None).strip()
    if text == "":
        return fail("type a link or some text first")
    color = swatch.normalize_hex(color)
    if color == "":
        return fail("pick a color first")
    if not swatch.usable(color):
        return fail(color + " is too light to scan on white")
    if level not in registry.EC_LEVELS:
        return fail("unknown error-correction level")
    target = ""
    code = ""
    caption = ""
    if short is not None:
        checked = shortlinks.check_target(text)
        if not checked["ok"]:
            return checked
        target = checked["value"]
        planned = plan_short_link(db_path, target, color, short)
        if not planned["ok"]:
            return planned
        code = planned["value"]["code"]
        text = planned["value"]["url"]
        caption = shortlinks.caption(text)
    placed_logo = None
    if logo is not None:
        placed = qr_codec.place_logo(text, logo)
        if not placed["ok"]:
            return placed
        matrix = placed["value"]["matrix"]
        placed_logo = placed["value"]["logo"]
        level = "H"
    else:
        made = qr_codec.encode_text(text, level, 1, -1)
        if not made["ok"]:
            return made
        matrix = made["value"]
    path = registry.display_path(path)
    saved = qr_codec.save_matrix(matrix, path, scale, color, caption, placed_logo)
    if not saved["ok"]:
        return saved
    picture = qr_codec.read_qr_file(path)
    if not picture["ok"] or picture["value"]["reading"]["text"] != text or picture["value"]["color"] != color:
        try:
            os.remove(path)
        except OSError:
            pass
        if placed_logo is not None:
            return fail("with this logo the saved picture did not read back the same, so it was removed; try a "
                        "smaller or lighter logo")
        return fail("the saved picture did not read back the same, so it was removed")
    entry = {"color": color, "path": path, "format": qr_codec.file_kind(path), "ec_level": level,
             "version": matrix["version"], "origin": "made"}
    if code != "":
        entry["short"] = {"code": code, "target": target}
    if placed_logo is not None:
        entry["has_logo"] = 1
    filled = masked_entry(db_path, text, entry)
    if not filled["ok"]:
        return filled

    def register(connection):
        return registry.save_qr(connection, entry)

    saved_record = with_registry(db_path, register)
    if not saved_record["ok"]:
        return saved_record
    return ok_result({"id": saved_record["value"], "path": path, "link": entry["link"], "color": color,
                      "version": matrix["version"], "level": level, "short_code": code, "target": target})


def redraw_record(db_path, number, color, scale):
    """Draw registered code `number` again in `color` (a PNG at `scale` pixels per module) over its
    own file -> Result Made. The new drawing is read back before it replaces the old one; its link,
    error-correction level and short link stay as they were."""
    color = swatch.normalize_hex(color)
    if color == "" or not swatch.usable(color):
        return fail("pick a color dark enough to scan on white")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= 40:
        return fail("the size is 1 to 40 pixels per module")

    def read(connection):
        row = registry.row_by_id(connection, number)
        if row is None:
            return fail("there is no record " + str(number))
        return ok_result(row)

    found = with_registry(db_path, read)
    if not found["ok"]:
        return found
    row = found["value"]
    if row["payload_hash"] is not None:
        return fail(os.path.basename(row["path"]) + " holds a Wi-Fi password the registry does not keep, so it "
                    "cannot be drawn again here; make it again in the Make tab")
    if row["has_logo"]:
        return fail(os.path.basename(row["path"]) + " has a logo the registry does not keep, and redrawing would lose "
                    "it; make it again in the Make tab")
    made = qr_codec.encode_text(row["link"], row["ec_level"], 1, -1)
    if not made["ok"]:
        return made
    caption = ""
    if row["short_code"] != "":
        caption = shortlinks.caption(row["link"])
    folder, name = os.path.split(row["path"])
    if not os.path.isdir(folder):
        return fail("the folder of " + row["path"] + " is not there any more")
    trial = os.path.join(folder, ".redraw-" + name)
    saved = qr_codec.save_matrix(made["value"], trial, scale, color, caption)
    if not saved["ok"]:
        return saved
    picture = qr_codec.read_qr_file(trial)
    if not picture["ok"] or picture["value"]["reading"]["text"] != row["link"] or picture["value"]["color"] != color:
        try:
            os.remove(trial)
        except OSError:
            pass
        return fail("the new drawing did not read back the same; " + row["path"] + " was left as it was")
    try:
        os.replace(trial, row["path"])
    except OSError as error:
        return fail("cannot replace " + row["path"] + ": " + str(error))
    entry = {"link": row["link"], "color": color, "path": row["path"], "format": qr_codec.file_kind(row["path"]),
             "ec_level": row["ec_level"], "version": made["value"]["version"], "origin": "made"}
    if row["short_code"] != "":
        entry["short"] = {"code": row["short_code"], "target": row["target"]}

    def register(connection):
        return registry.save_qr(connection, entry)

    saved_record = with_registry(db_path, register)
    if not saved_record["ok"]:
        return saved_record
    return ok_result({"id": saved_record["value"], "path": row["path"], "link": row["link"], "color": color,
                      "version": made["value"]["version"], "level": row["ec_level"], "short_code": row["short_code"],
                      "target": row["target"]})


def picture_from_image(image):
    """An Image (from the window's own picture reader) -> Result Picture."""
    reading = qr_codec.decode_image(image)
    if not reading["ok"]:
        return reading
    return ok_result({"reading": reading["value"], "format": "other", "color": qr_codec.dark_color(image),
                      "image": image})


def register_picture(db_path, path, color):
    """Add a QR code picture made elsewhere (PNG or this program's SVG) to the registry, in `color`
    -> Result record id."""
    color = swatch.normalize_hex(color)
    if color == "":
        return fail("the color must be #rrggbb")
    picture = qr_codec.read_qr_file(path)
    if not picture["ok"]:
        return picture
    if picture["value"]["format"] not in registry.FORMATS:
        return fail("only PNG and SVG pictures can be registered; save it as PNG first")
    reading = picture["value"]["reading"]
    entry = {"color": color, "path": registry.display_path(path), "format": picture["value"]["format"],
             "ec_level": reading["level"], "version": reading["version"], "origin": "registered"}
    filled = masked_entry(db_path, reading["text"], entry)
    if not filled["ok"]:
        return filled

    def register(connection):
        return registry.save_qr(connection, entry)

    return with_registry(db_path, register)


def forget_record(db_path, number):
    def forget(connection):
        return registry.forget_qr(connection, number)

    return with_registry(db_path, forget)


def preview_png(link, color, level, version, caption=""):
    """A small PNG of a record's code, drawn again from its link (for previews in the window), as
    large as fits in PREVIEW - 20 pixels with its caption."""
    made = qr_codec.encode_text(link, level, version, -1)
    if not made["ok"]:
        made = qr_codec.encode_text(link, "M", 1, -1)
    if not made["ok"]:
        return b""
    return fitted_png(made["value"], color, caption, PREVIEW - 20)


def fitted_png(matrix, color, caption, room, logo=None):
    """The code as PNG bytes at the largest scale whose picture, caption included, fits `room` pixels."""
    scale = max(1, room // (matrix["size"] + 8))
    while True:
        png = qr_codec.picture_bytes(matrix, scale, color, "png", caption, logo)
        width, height = struct.unpack(">II", png[16:24])
        if scale == 1 or (width <= room and height <= room):
            return png
        scale = scale - 1


def robustness_score(matrix, text, color, caption, logo=None):
    """How much wear the code in `matrix` survives, drawn as its PNG would be -> Result Score."""
    return qr_codec.robustness(qr_codec.picture_image(matrix, ROBUSTNESS_SCALE, color, caption, logo), text)

# ==== stamp v1 | author=kjFriday | hmac-sha256=04288c64aa77e8d755cbb90d13dbc723383d7afee60debee751bcae00b37c0db ====
