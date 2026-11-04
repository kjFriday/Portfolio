# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_codec/binarize.py
# About: Binarizing: a gray picture -> one byte per pixel, 1 = dark, for the finder search.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Binarizing: a gray picture -> one byte per pixel, 1 = dark, for the finder search.

binarize_global uses Otsu's threshold for the whole picture. binarize_local compares each pixel with
the mean of a window around it (shadows and glare), falling back to Otsu's threshold in flat areas.
majority_filter removes specks from noisy pictures.
"""


def otsu_threshold(gray):
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
    Flat areas fall back to the global threshold so a large module is not split."""
    width = image["width"]
    height = image["height"]
    gray = image["gray"]
    radius = max(8, max(width, height) // 12)
    threshold = otsu_threshold(gray)
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
            if value < mean - 8 or (abs(value - mean) <= 8 and value <= threshold):
                bits[y * width + x] = 1
    return bits


def majority_filter(bits, width, height):
    """Each pixel becomes what most of its 3x3 neighbourhood is: removes specks from noisy pictures."""
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=0532875057d25a32637776b489e29f512b29858fb73763759d9813afce4b5fff ====
