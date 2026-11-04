# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/distort.py
# About: Picture changes: turned, scaled, noisy and warped copies, for the tests and the self-test.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Picture changes: turned, scaled, noisy and warped copies, for the tests and the self-test.

Noise is seeded, so the same picture comes out every run.
"""

import random

from .images import make_image
from .locate import apply_perspective, perspective


def rotate_image(image):
    """Quarter turn clockwise."""
    width = image["width"]
    height = image["height"]
    result = make_image(height, width, 255)
    for y in range(height):
        for x in range(width):
            result["gray"][x * height + (height - 1 - y)] = image["gray"][y * width + x]
    return result


def scale_image(image, factor):
    width = max(1, int(image["width"] * factor))
    height = max(1, int(image["height"] * factor))
    result = make_image(width, height, 255)
    for y in range(height):
        source_y = min(image["height"] - 1, int(y / factor))
        for x in range(width):
            source_x = min(image["width"] - 1, int(x / factor))
            result["gray"][y * width + x] = image["gray"][source_y * image["width"] + source_x]
    return result


def add_noise(image, fraction, seed):
    """Flip a fraction of pixels to random grays (seeded, so the same every run)."""
    generator = random.Random(seed)
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"])}
    count = int(len(result["gray"]) * fraction)
    for i in range(count):
        result["gray"][generator.randrange(len(result["gray"]))] = generator.randrange(256)
    return result


def warp_image(image, corners):
    """Stretch the picture so its corners land on `corners` (TL, TR, BR, BL), white elsewhere."""
    width = image["width"]
    height = image["height"]
    sources = [(0, 0), (width, 0), (width, height), (0, height)]
    inverse = perspective(corners, sources)
    result = make_image(width, height, 255)
    for y in range(height):
        for x in range(width):
            u, v = apply_perspective(inverse, x + 0.5, y + 0.5)
            if 0 <= u < width and 0 <= v < height:
                result["gray"][y * width + x] = image["gray"][int(v) * width + int(u)]
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=cd7fe7fc700519902e3e794c2b090c6941a8472a2fd39ce896b2dd97fe043ed8 ====
