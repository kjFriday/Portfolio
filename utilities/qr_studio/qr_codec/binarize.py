# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_codec/binarize.py
# About: Binarizing: a gray picture -> one byte per pixel, 1 = dark, for the finder search.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Binarizing: a gray picture -> one byte per pixel, 1 = dark, for the finder search.

binarize_global uses Otsu's threshold for the whole picture. binarize_local compares each pixel with
the mean of a window around it (shadows and glare), falling back to Otsu's threshold in flat areas.
majority_filter removes specks from noisy pictures.

Callers: locate.py tries binarize_global and then binarize_local, each with and without
majority_filter, until a finder pattern search succeeds; files.py uses otsu_threshold to turn a loaded
picture into modules. An image here is a dict with "width", "height" and "gray" (one byte per pixel,
row by row, 0 = black, 255 = white); the bit maps returned use the same row-by-row layout.
"""


def otsu_threshold(gray):
    """Gray level (0..255) that best splits the pixels into a dark and a light class (Otsu's method).

    Otsu's method picks the threshold t that maximises the between-class variance
    w_b * w_f * (mean_b - mean_f)**2, where w_b and w_f count the pixels at or below t and above t and
    mean_b and mean_f are their mean gray levels. A large value means two well separated groups.
    Pixels at or below the result count as dark. A one-level picture returns 127.

    Steps:
    1. Build a 256-bin histogram and the sum of all gray levels.
    2. Sweep t upward, growing the background class one bin at a time with running sums.
    3. Keep the t with the largest between-class variance (the first one on ties).
    """
    histogram = [0] * 256
    for value in gray:
        histogram[value] = histogram[value] + 1
    total = len(gray)
    sum_all = 0
    for level in range(256):
        sum_all = sum_all + level * histogram[level]
    sum_background = 0
    weight_background = 0
    best = 127
    best_variance = -1.0
    for level in range(256):
        weight_background = weight_background + histogram[level]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background = sum_background + level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            best = level
    return best


def binarize_global(image):
    """1 = dark, from one threshold for the whole picture."""
    threshold = otsu_threshold(image["gray"])
    bits = bytearray(len(image["gray"]))
    gray = image["gray"]
    for i in range(len(gray)):
        if gray[i] <= threshold:
            bits[i] = 1
    return bits


def binarize_local(image):
    """1 = dark, against the mean of a window around each pixel (copes with shadows and glare).
    Flat areas fall back to the global threshold so a large module is not split.

    Steps:
    1. Build an integral image (summed-area table): integral[(y + 1) * (width + 1) + x + 1] is the sum of
       every gray value above and left of (x, y), inclusive, so any rectangle's sum is four lookups.
    2. For each pixel, sum the window of radius pixels around it (clipped at the edges) and take its mean.
    3. Mark the pixel dark when it is clearly below the mean, or close to the mean and dark by Otsu.
    """
    width = image["width"]
    height = image["height"]
    gray = image["gray"]
    # the window is about a sixth of the picture across, at least 17 pixels, so it spans several modules
    radius = max(8, max(width, height) // 12)
    threshold = otsu_threshold(gray)
    # one extra row and column of zeros keep the rectangle sums free of edge checks
    integral = [0] * ((width + 1) * (height + 1))
    for y in range(height):
        running = 0
        row = y * width
        above = y * (width + 1)
        here = (y + 1) * (width + 1)
        for x in range(width):
            running = running + gray[row + x]
            integral[here + x + 1] = integral[above + x + 1] + running
    bits = bytearray(width * height)
    for y in range(height):
        top = max(0, y - radius)
        bottom = min(height, y + radius + 1)
        for x in range(width):
            left = max(0, x - radius)
            right = min(width, x + radius + 1)
            total = (integral[bottom * (width + 1) + right] - integral[top * (width + 1) + right] -
                     integral[bottom * (width + 1) + left] + integral[top * (width + 1) + left])
            mean = total / ((bottom - top) * (right - left))
            value = gray[y * width + x]
            # within 8 gray levels of the mean the window is flat (inside one large module or the quiet
            # zone), so the global threshold decides instead of noise
            if value < mean - 8 or (abs(value - mean) <= 8 and value <= threshold):
                bits[y * width + x] = 1
    return bits


def majority_filter(bits, width, height):
    """Each pixel becomes what most of its 3x3 neighbourhood is: removes specks from noisy pictures.

    Returns a new bytearray; the border rows and columns are copied unchanged. 5 of 9 is a majority.
    """
    result = bytearray(bits)
    for y in range(1, height - 1):
        above = (y - 1) * width
        here = y * width
        below = (y + 1) * width
        for x in range(1, width - 1):
            count = (bits[above + x - 1] + bits[above + x] + bits[above + x + 1] +
                     bits[here + x - 1] + bits[here + x] + bits[here + x + 1] +
                     bits[below + x - 1] + bits[below + x] + bits[below + x + 1])
            if count >= 5:
                result[here + x] = 1
            else:
                result[here + x] = 0
    return result

# ==== stamp v1 | author=kjFriday | hmac-sha256=fbcc969b9637a30f543e8e38e2c379a5a32b166b0126d31dd79514609c05f8dc ====
