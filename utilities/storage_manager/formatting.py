# ==== Generic Company Inc. portfolio ====================================
# Project: storage_manager | File: formatting.py
# About: Storage Manager core: sizes, counts, dates and plurals in words.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Storage Manager core: sizes, counts, dates and plurals in words.

The window shows this text as it is, and the self-test compares some of it exactly.

What it is for: gui.py and gui_views.py build every size, count and date they show with these
helpers, and space_map.py names its "N smaller items" slices with plural. Nothing here touches the
disk; human_date reads the local time zone. Sizes use 1024-based steps with the familiar names
(KB, MB, GB), as Explorer does, not KiB/MiB.
"""

import time


def human_size(count):
    """A byte count in words: 512 -> "512 B", 1536 -> "1.5 KB" (1024-based, one decimal).

    Divides by 1024 until the value is under 1024 or the units run out (PB is the largest). Plain
    bytes are shown whole, without a decimal.
    """
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(count)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value = value / 1024
        index = index + 1
    if index == 0:
        return str(count) + " B"
    return "%.1f %s" % (value, units[index])


def human_count(count):
    """1234567 -> "1,234,567"."""
    return format(count, ",")


def human_date(seconds):
    """seconds -> "2026-10-28", or "unknown" for a time the system cannot show (Windows refuses times
    before 1970 and after the year 3000, and NTFS can hold both)."""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(seconds))
    except (OSError, OverflowError, ValueError):
        return "unknown"


def plural(count, word):
    """plural(1, "file") -> "1 file", plural(3, "copy") -> "3 copies".

    Counts other than 1 get thousands separators (human_count). English rule: a word ending in a
    consonant plus "y" takes "ies" ("copy" -> "copies"), a vowel plus "y" just "s" ("day" -> "days");
    every other word takes "s". Only the last word changes, so "extra copy" -> "extra copies".
    """
    if count == 1:
        return "1 " + word
    if len(word) > 1 and word[len(word) - 1] == "y" and word[len(word) - 2] not in "aeiou":
        return human_count(count) + " " + word[:len(word) - 1] + "ies"
    return human_count(count) + " " + word + "s"


def join_words(parts):
    """["a"] -> "a", ["a", "b", "c"] -> "a, b and c" (no comma before "and"); [] -> ""."""
    text = ""
    index = 0
    while index < len(parts):
        if index > 0 and index == len(parts) - 1:
            text = text + " and "
        elif index > 0:
            text = text + ", "
        text = text + parts[index]
        index = index + 1
    return text


def disk_note(report, links_counted):
    """What "on disk" means for a ScanReport, in one or two sentences. links_counted: hard links have
    been counted once (always where the listing says which names are one file).

    The Overview shows it under the totals. report["saved"] (see disk_summary in scanning.py) says
    where space on disk and the sum of file sizes differ; each non-zero part becomes a clause. With
    no parts the sizes simply agree. When links_counted is False (a Windows scan before the duplicate
    comparison has run), a sentence says hard links will be counted once later.
    """
    saved = report["saved"]
    parts = []
    if saved["compressed"] > 0:
        parts.append(human_size(saved["compressed"]) + " saved by compressed and sparse files")
    if saved["no_data"] > 0:
        parts.append(human_size(saved["no_data"]) + " in files with no data on this disk (such as cloud-only files)")
    if saved["links"] > 0:
        parts.append(human_size(saved["links"]) + " in second names of hard-linked files")
    text = "Sizes are space on disk, which here is what the files add up to."
    if len(parts) > 0:
        text = ("Sizes are space on disk: the files add up to " + human_size(report["file_bytes"]) + ", less "
                + join_words(parts) + ".")
    if not links_counted:
        text = text + " Hard links are counted once when the duplicate comparison is done."
    return text

# ==== stamp v1 | author=kjFriday | hmac-sha256=3dd5f97ec2a34c8ca257ab2211e4459ec1bc7676df2d5974fa10838b600143e2 ====
