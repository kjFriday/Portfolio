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
"""

import math
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
    result = {"width": image["width"], "height": image["height"], "gray": bytearray(image["gray"]), "rgb": None}
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


def blur_image(image, size):
    """Each pixel the mean of the `size` x `size` square around it (a box blur; edges repeat)."""
    width = image["width"]
    height = image["height"]
    gray = image["gray"]
    half = size // 2
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
    new_width = int(math.ceil(abs(width * cos_a) + abs(height * sin_a)))
    new_height = int(math.ceil(abs(width * sin_a) + abs(height * cos_a)))
    result = make_image(new_width, new_height, 255)
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
