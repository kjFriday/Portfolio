# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_selftest.py
# About: QR Studio's self-test: a quick pass over the codec, the history and the command-line...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's self-test: quick checks of the codec, the history and the command line.

Run by `python qr_studio.py --selftest`; the full suites are in tests/. Each check prints "  ok   <what>" or
"  FAIL <what>" under a group heading (reed-solomon, encode and decode, pictures, history), then a summary
line, and selftest() returns the exit code: 0 when every check passed, 1 otherwise. It reads and writes no
files.

Who calls it: qr_studio.main for --selftest. It calls the codec, studio_history and studio_options, and
nothing in the window, so it runs without tkinter. A shipped copy can check itself on a machine with no
test tools; tests/ goes deeper and covers the same ground.
"""

from qr_codec import (decode_image, decode_matrix, encode_text, make_image, matrix_to_image, read_png,
                      rotate_image, rs_correct, rs_remainder, write_png)
from studio_history import add_history, is_link
from studio_options import option_value


def check(condition, message, failures):
    """Print one ok or FAIL line for `message`; on a failure also append `message` to `failures`."""
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    """Run every check, print the results and a summary -> exit code 0 (all passed) or 1.

    Steps:
      1. Reed-Solomon: the standard's worked example, then two damaged codewords repaired.
      2. Encode and decode: one text per mode and level through a Matrix and back, and a text too long
         for any version refused.
      3. Pictures: a PNG round trip, then reading the code from the picture straight and turned a
         quarter, and finding nothing in a blank picture.
      4. History and command line: a repeat moves to the top, only web links open, option_value.
    """
    failures = []
    print("reed-solomon")
    # the worked example in ISO/IEC 18004's annex: "01234567" as version 1-M, 16 data codewords
    # (mode, count, digits, terminator, then the 0xEC 0x11 pad bytes) and its 10 EC codewords
    data =[0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
    check(rs_remainder(data, 10) == [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55],
          "spec example EC codewords", failures)
    block = data + rs_remainder(data, 10)
    damaged = list(block)
    # 10 EC codewords repair up to 5 wrong ones; two errors, one data and one pad byte, are well within it
    damaged[2] = damaged[2] ^ 0x33
    damaged[9] = damaged[9] ^ 0x01
    fixed = rs_correct(damaged, 10)
    check(fixed["ok"] and fixed["value"]["block"] == block, "two errors corrected", failures)

    print("encode and decode")
    # numeric, alphanumeric, byte (ASCII) and byte (UTF-8, non-ASCII), one per error-correction level
    for text, level in (("01234567", "M"), ("HELLO WORLD", "Q"), ("https://example.com/", "L"), ("Grüße", "H")):
        made = encode_text(text, level, 1, -1)
        decoded = decode_matrix(made["value"]["dark"])
        check(decoded["ok"] and decoded["value"]["text"] == text, level + " " + text, failures)
    # version 40-L holds at most 2953 bytes, so 3000 fits nowhere
    check(not encode_text("x" * 3000, "L", 1, -1)["ok"], "too long is refused", failures)

    print("pictures")
    matrix = encode_text("Generic Company Inc.", "M", 1, -1)["value"]
    # 4 pixels per module with a 4-module quiet zone: small, but enough for the finder search
    picture = read_png(write_png(matrix_to_image(matrix, 4, 4)))
    check(picture["ok"], "PNG round trip", failures)
    reading = decode_image(picture["value"])
    check(reading["ok"] and reading["value"]["text"] == "Generic Company Inc.", "read a picture", failures)
    reading = decode_image(rotate_image(picture["value"]))
    check(reading["ok"] and reading["value"]["text"] == "Generic Company Inc.", "read a turned picture", failures)
    check(not decode_image(make_image(60, 60, 255))["ok"], "blank picture has no code", failures)

    print("history")
    entries = add_history(add_history([], "read", "a", 1.0), "read", "a", 2.0)
    check(len(entries) == 1 and entries[0]["when"] == 2.0, "repeat moves to the top", failures)
    check(is_link("https://x.test") and not is_link("file:///c:/x"), "only web links open", failures)
    check(option_value(["--smoke", "r.json"], "--smoke") == "r.json", "option value", failures)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1

# ==== stamp v1 | author=kjFriday | hmac-sha256=12cfda630176cc26023dbad3967a4666e14f1a9fe78153917dfad1fe5125ad47 ====
