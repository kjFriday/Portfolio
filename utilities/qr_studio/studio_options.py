# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: studio_options.py
# About: QR Studio's command-line reader: the value that follows an option.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""QR Studio's command-line reader: the value that follows an option.

The command line in qr_studio.py reads --read and --smoke with option_value, and the self-test checks it.
qr_studio.py imports the self-test, so the self-test cannot import qr_studio.py back: option_value lives
here, below both. There is no argparse, so there is no --help; flags the program does not know open the
window.
"""


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing."""
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""

# ==== stamp v1 | author=kjFriday | hmac-sha256=c21006128a71915297a40fa678bfd196d0e7e137d75f0e8d2a213382672e4a04 ====
