# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/distort.py
# About: Picture changes: turned, scaled, noisy and warped copies, for the tests and the self-test.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Picture changes: turned, scaled, noisy and warped copies, for the tests and the self-test.

Noise is seeded, so the same picture comes out every run.

Callers: the tests (tests/test_qr_codec.py) turn, scale, speckle and warp a rendered code to make
camera-like pictures and check it still decodes; the self-test (studio_selftest.py) reads a turned
one. Every function takes a gray picture dict ("width", "height", "gray" one byte per pixel row by row,
255 = white) and returns a new one; the input is never changed. QR Palette's distort.py is a larger
version of this file.
"""

import random

from .images import make_image
from .locate import apply_perspective, perspective


def rotate_image(image):
    """Quarter turn clockwise."""
    width = image["width"]
    height = image["height"]
    # the turned picture swaps width and height
    result = make_image(height, width, 255)
    for y in range(height):
        for x in range(width):
            # source (x, y) lands at column height - 1 - y of row x
            result["gray"][x * height + (height - 1 - y)] = image["gray"][y * width + x]
    return result


def scale_image(image, factor):
    """Resized by `factor` (below 1 shrinks) with nearest-neighbour sampling; at least 1 x 1 pixel.

    Each output pixel copies the source pixel its top-left corner maps back to, clamped to the picture,
    so a shrink drops rows and columns rather than averaging them.
    """
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
    """Flip a fraction of pixels to random grays (seeded, so the same every run).

    Pixels are picked with replacement, so slightly fewer than fraction of them may change.
    """
    generator = random.Random(seed)
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"])}
    count = int(len(result["gray"]) * fraction)
    for i in range(count):
        result["gray"][generator.randrange(len(result["gray"]))] = generator.randrange(256)
    return result


def warp_image(image, corners):
    """Stretch the picture so its corners land on `corners` (TL, TR, BR, BL), white elsewhere.

    The output keeps the input's size. corners are (x, y) pixel positions in the output.

    Steps:
    1. Build the perspective transform (a homography: 8 coefficients, from locate.py) that maps the
       target corners back to the source picture's corners.
    2. For every output pixel centre, map it back into the source and copy that pixel (nearest
       neighbour); points that fall outside the source stay white.
    Mapping backwards leaves no holes, which mapping each source pixel forwards would.
    """
    width = image["width"]
    height = image["height"]
    sources = [(0, 0), (width, 0), (width, height), (0, height)]
    inverse = perspective(corners, sources)
    result = make_image(width, height, 255)
    for y in range(height):
        for x in range(width):
            # + 0.5 samples at the pixel centre
            u, v = apply_perspective(inverse, x + 0.5, y + 0.5)
            if 0 <= u < width and 0 <= v < height:
                result["gray"][y * width + x] = image["gray"][int(v) * width + int(u)]
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=466e6de76f221c341e103f9d41cea5c9e5c82801cdeb6bce79742bbe149cae11 ====
