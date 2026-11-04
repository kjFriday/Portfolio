# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/distort.py
# About: Picture changes: the tests' harder pictures, and the wear the robustness score applies.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Picture changes: the tests' harder pictures, and the wear the robustness score applies.

Noise and grain are seeded, so the same picture comes out every run.

Callers: robustness.py wears a rendered code with blur_image, add_specks, tilt_image, fade_image,
add_grain, scale_image and cover_image and checks it still decodes; the tests use the rest (rotate,
noise, warp) to make camera-like pictures. Every function takes a gray picture dict ("width", "height",
"gray" one byte per pixel row by row, 255 = white) and returns a new one; the input is never changed.
"""

import math
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

    Pixels are picked with replacement, so slightly fewer than fraction of them may change. randrange
    can change between Python versions; the robustness score uses add_specks instead.
    """
    generator = random.Random(seed)
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"]), "rgb": None}
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


def blur_image(image, size):
    """Each pixel the mean of the `size` x `size` square around it (a box blur; edges repeat)."""
    width = image["width"]
    height = image["height"]
    gray = image["gray"]
    half = size // 2
    # separable blur: sum along each row first, then sum those row sums down each column, so each
    # pixel costs 2 * size additions instead of size * size; size is expected to be odd
    across = [0] * (width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            total = 0
            for dx in range(-half, half + 1):
                total = total + gray[row + min(width - 1, max(0, x + dx))]
            across[row + x] = total
    result = make_image(width, height, 255)
    area = size * size
    for y in range(height):
        for x in range(width):
            total = 0
            for dy in range(-half, half + 1):
                total = total + across[min(height - 1, max(0, y + dy)) * width + x]
            # + area // 2 rounds to the nearest gray instead of down
            result["gray"][y * width + x] = (total + area // 2) // area
    return result


def tilt_image(image, degrees):
    """Turned `degrees` about its centre (nearest neighbour), on a canvas just big enough for all of
    it, white where the picture does not reach."""
    angle = math.radians(degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    width = image["width"]
    height = image["height"]
    # bounding box of the turned rectangle
    new_width = int(math.ceil(abs(width * cos_a) + abs(height * sin_a)))
    new_height = int(math.ceil(abs(width * sin_a) + abs(height * cos_a)))
    result = make_image(new_width, new_height, 255)
    # each output pixel centre is turned back by -degrees about the centre to find its source pixel
    for y in range(new_height):
        dy = y + 0.5 - new_height / 2.0
        for x in range(new_width):
            dx = x + 0.5 - new_width / 2.0
            u = cos_a * dx + sin_a * dy + width / 2.0
            v = cos_a * dy - sin_a * dx + height / 2.0
            if 0 <= u < width and 0 <= v < height:
                result["gray"][y * new_width + x] = image["gray"][int(v) * width + int(u)]
    return result


def fade_image(image, factor):
    """Lower contrast, like a faded print: every pixel moves towards white, keeping `factor` (0-1) of
    its distance from white."""
    result = make_image(image["width"], image["height"], 255)
    for i in range(len(image["gray"])):
        result["gray"][i] = 255 - int(round((255 - image["gray"][i]) * factor))
    return result


def add_grain(image, sigma, seed):
    """Sensor grain: every pixel moved by a seeded Gaussian amount. Only random() is used (Box-Muller),
    the one generator Python keeps the same across versions, so a score never changes with Python."""
    generator = random.Random(seed)
    result = make_image(image["width"], image["height"], 255)
    for i in range(len(image["gray"])):
        # Box-Muller: sqrt(-2 ln u1) * cos(2 pi u2) is a standard normal value for uniform u1, u2;
        # 1 - random() lies in (0, 1], so the log never sees 0
        shift = sigma * math.sqrt(-2.0 * math.log(1.0 - generator.random())) * math.cos(2.0 * math.pi *
                                                                                      generator.random())
        result["gray"][i] = min(255, max(0, image["gray"][i] + int(round(shift))))
    return result


def add_specks(image, fraction, seed):
    """A fraction of the pixels set to random grays, like add_noise but with random() only (see
    add_grain), for the robustness score."""
    generator = random.Random(seed)
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"]), "rgb": None}
    total = len(result["gray"])
    for i in range(int(total * fraction)):
        # int(random() * n) instead of randrange keeps the picks stable across Python versions
        result["gray"][int(generator.random() * total)] = int(generator.random() * 256)
    return result


def cover_image(image, box):
    """A white square over part of the picture, like a sticker or a scratch: box is (left, top, side)."""
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"]), "rgb": None}
    left, top, side = box
    for y in range(max(0, top), min(image["height"], top + side)):
        for x in range(max(0, left), min(image["width"], left + side)):
            result["gray"][y * image["width"] + x] = 255
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=bbf163b0ad5fae05e27a1fc5b919fa5a47ff84c77c5e414f35de45115225a240 ====
