# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/robustness.py
# About: Robustness: how much wear a code survives before it is printed.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Robustness: how much wear a code survives before it is printed.

Each WEAR test changes the code's upright picture (distort.py), which must still read back as the
same text. The tests are fixed (seeded noise), so the same picture always scores the same.
"""

from .records import fail, ok_result
from .images import read_png
from .locate import decode_image
from .distort import add_grain, add_specks, blur_image, cover_image, fade_image, scale_image, tilt_image
from .files import picture_bytes


WEAR = ("shrunk to half", "shrunk to a third", "light blur", "heavy blur", "light noise", "heavy noise",
        "tilted 5 degrees", "low contrast", "very low contrast", "covered corner")
COVERED_SHARE = 0.33  # the covered corner's side, as a share of the code's side


def corner_box(reading):
    """The covered corner of a code read from an upright picture -> (left, top, side) in pixels: a
    square COVERED_SHARE of the code's side, one module in from its bottom-right corner (where no
    finder pattern is)."""
    size = 17 + 4 * reading["version"]
    top_left = reading["corners"][0]
    top_right = reading["corners"][1]
    bottom_left = reading["corners"][2]
    module = (top_right[0] - top_left[0]) / float(size - 7)
    right = top_right[0] + 3.5 * module
    bottom = bottom_left[1] + 3.5 * module
    side = int(round(COVERED_SHARE * size * module))
    return int(round(right - module)) - side, int(round(bottom - module)) - side, side


def worn_image(image, name, reading):
    """The picture after one of the WEAR tests; `reading` is the clean picture's, for the covered corner."""
    if name == "shrunk to half":
        return scale_image(image, 0.5)
    if name == "shrunk to a third":
        return scale_image(image, 1.0 / 3.0)
    if name == "light blur":
        return blur_image(image, 3)
    if name == "heavy blur":
        return blur_image(image, 5)
    if name == "light noise":
        return add_specks(image, 0.05, 1)
    if name == "heavy noise":
        return add_specks(image, 0.15, 2)
    if name == "tilted 5 degrees":
        return tilt_image(image, 5)
    if name == "low contrast":
        return add_grain(fade_image(image, 0.3), 12, 3)
    if name == "very low contrast":
        return add_grain(fade_image(image, 0.15), 12, 4)
    return cover_image(image, corner_box(reading))


def robustness(image, text):
    """How much wear a code survives: each WEAR test applied to its upright picture, which must then
    still read as `text` -> Result Score. A picture that does not read even unworn is a failed Result.
    The tests are fixed (seeded noise), so the same picture always scores the same."""
    clean = decode_image(image)
    if not clean["ok"] or clean["value"]["text"] != text:
        return fail("the picture does not read back as it is")
    failed = []
    for name in WEAR:
        reading = decode_image(worn_image(image, name, clean["value"]))
        if not reading["ok"] or reading["value"]["text"] != text:
            failed.append(name)
    return ok_result({"passed": len(WEAR) - len(failed), "tried": len(WEAR), "failed": failed})


def describe_score(score):
    """"8 of 10 passed; failed: shrunk to a third, heavy blur" (or "10 of 10 passed")."""
    said = str(score["passed"]) + " of " + str(score["tried"]) + " passed"
    if len(score["failed"]) > 0:
        said = said + "; failed: " + ", ".join(score["failed"])
    return said


def picture_image(matrix, scale, color, caption="", logo=None):
    """The Image of the PNG picture_bytes would write: `color` on white, with its quiet zone, logo
    and caption, as gray the way a camera would see it."""
    return read_png(picture_bytes(matrix, scale, color, "png", caption, logo))["value"]

# ==== stamp v1 | author=kjFriday | hmac-sha256=93c639e007ea4495a8129b77c19f7aea80dc61db3f7ef4847bbc11d07e4bc0ad ====
