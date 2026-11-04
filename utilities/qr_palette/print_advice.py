# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: print_advice.py
# About: Print advice: how big to print a code so that it scans from a given distance.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Print advice: how big to print a code so that it scans from a given distance.

It backs the Print size dialog (gui/dialogs.py); the Find tab reuses MIN_MODULE_MM. Rules of thumb, not guarantees: a module at least MIN_MODULE_MM wide and at least 1/DISTANCE_PER_MODULE of
the scanning distance, and the letters of a printed address at least MIN_CAPTION_MM tall. The printed
address is laid out as in a saved picture, at app_settings.DEFAULT_SCALE pixels per module.

Main flow of print_advice:
1. Check the width and distance are in range.
2. Work out the module size the distance needs.
3. Encode the text at each error-correction level (only H for a logo) and measure the printed picture
   in modules, caption included.
4. Turn the chosen width into a module size, and say whether it fits and the smallest width that would.
"""

import app_settings
import qr_codec
import registry
from common import fail, ok_result

MIN_MODULE_MM = 0.4  # the smallest module most printers and phone cameras handle well
DISTANCE_PER_MODULE = 250  # the 10:1 rule (scan from at most ten times a code's width) for a 25-module code
MIN_CAPTION_MM = 1.5  # the smallest letters of a printed address most people can read


def print_advice(text, width_cm, distance_m, caption, logo_version=0):
    """How a code holding `text`, printed `width_cm` wide (the whole picture, quiet zone included),
    scans from `distance_m` -> Result {"need_mm", "levels": [{"level", "version", "modules",
    "module_mm", "fits", "min_width_cm", "caption_mm"}]}, one per error-correction level. Rules of
    thumb, not guarantees: a module at least MIN_MODULE_MM, and at least 1/DISTANCE_PER_MODULE of the
    scanning distance; the printed address's letters at least MIN_CAPTION_MM tall. A code with a logo
    is only ever level H, at the version place_logo chose: `logo_version`, 0 for no logo.

    need_mm and module_mm are millimetres per module; "modules" is the code's side plus the quiet zone;
    min_width_cm is the narrowest whole picture that meets need_mm; caption_mm is the printed letter
    height, None without a caption. A level whose encoding fails is left out.
    """
    # bool is a subclass of int, so it is refused by name
    for value, low, high, name in ((width_cm, 0.5, 500, "the width is 0.5 to 500 cm"),
                                   (distance_m, 0.05, 50, "the distance is 0.05 to 50 m")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            return fail(name)
    need = max(MIN_MODULE_MM, distance_m * 1000.0 / DISTANCE_PER_MODULE)
    levels = []
    for level in registry.EC_LEVELS:
        if logo_version > 0 and level != "H":
            continue
        made = qr_codec.encode_text(text, level, max(1, logo_version), -1)
        if not made["ok"]:
            continue
        # 4 modules of quiet zone on each side, as save_matrix draws
        side = made["value"]["size"] + 8
        across = side
        caption_mm = None
        if caption != "":
            # a caption wider than the code widens the picture (one module of margin each side), so
            # the printed width covers more modules; across is that width in modules
            lines, pixel = qr_codec.caption_layout(caption, side * app_settings.DEFAULT_SCALE,
                                                   app_settings.DEFAULT_SCALE)
            band = qr_codec.caption_size(lines, pixel, app_settings.DEFAULT_SCALE)
            across = (max(side * app_settings.DEFAULT_SCALE, band[0] + 2 * app_settings.DEFAULT_SCALE) /
                      app_settings.DEFAULT_SCALE)
        module_mm = width_cm * 10.0 / across
        if caption != "":
            # a letter is 7 font pixels tall; pixel / DEFAULT_SCALE is a font pixel in modules
            caption_mm = round(7.0 * pixel / app_settings.DEFAULT_SCALE * module_mm, 2)
        # + 0.05 before rounding to one decimal makes min_width_cm round up (about a ceiling), so the
        # advised width is never short
        levels.append({"level": level, "version": made["value"]["version"], "modules": side,
                       "module_mm": round(module_mm, 2), "fits": module_mm >= need,
                       "min_width_cm": round(need * across / 10.0 + 0.05, 1), "caption_mm": caption_mm})
    if len(levels) == 0:
        return fail("this text is too long for a QR code")
    return ok_result({"need_mm": round(need, 2), "levels": levels})

# ==== stamp v1 | author=kjFriday | hmac-sha256=85f3a1810d6bf8f54a8e24503a62202a3e1cd1aa248ca49fef302b46265e5ebb ====
