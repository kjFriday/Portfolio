# ==== Generic Company Inc. portfolio ====================================
# Project: qr_studio | File: qr_studio.py
# About: Generic Company QR Studio: read QR codes from pictures and make new ones.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Generic Company QR Studio: read QR codes from pictures and make new ones.

Self-contained: Python 3 standard library only. The whole QR codec (Reed-Solomon, encoder,
finder-pattern detector, sampler and decoder) is written from scratch in the qr_codec package
beside this file; no imaging or barcode library is used.

This file is the entry point: the version and the command line. The rest of the program:
  qr_codec/             the QR codec, one module per chapter of the standard (see its __init__.py)
  studio_history.py     the history of codes read and made; links, saving a code, describing a reading
  studio_clipboard.py   pictures to and from the Windows clipboard, through PowerShell
  studio_options.py     option_value, which reads the command line (the self-test checks it too)
  studio_selftest.py    the checks --selftest runs
  studio_gui.py         the tkinter window, StudioWindow; imported only when a window opens
  tests/                the unit tests: python -m unittest discover -s tests

Written to be easy to port to another language:
  * Plain functions and plain records (dicts with fixed keys: Result, Image, Matrix and Reading are
    listed in qr_codec/__init__.py, Entry in studio_history.py). The window is the one class.
  * Explicit loops; no decorators, generators, comprehension chains or dynamic attributes.
  * The codec and the modules under the window never touch the GUI. Port them first, then rewrite
    studio_gui.py in any toolkit.
  * Core functions report failure with a Result record instead of raising across layers.

Usage
  python qr_studio.py                     open the window
  python qr_studio.py --selftest          run the built-in checks and exit
  python qr_studio.py --version
  python qr_studio.py --smoke FILE        open the window, write a JSON report to FILE, close
  python qr_studio.py --read IMAGE        print the text of the QR code in a PNG, PGM or PPM file
  python qr_studio.py --make TEXT OUT     write TEXT as a QR code to OUT (.png or .svg)

Exit codes: 0 done (or every check passed), 1 nothing read, or the code could not be made or saved (or a
check failed), 2 --read, --smoke or --make without its values. Flags it does not know open the window.
"""

import sys

if __name__ == "__main__":
    # Run as a program, QR Studio writes nothing beside itself, as when it was one file: the modules it
    # imports below are compiled in memory rather than cached in __pycache__ folders. An uninstaller
    # removes only the files it installed, so such folders would stay behind.
    sys.dont_write_bytecode = True

from qr_codec import decode_image, encode_text, load_image_file
from studio_history import save_matrix
from studio_options import option_value
from studio_selftest import selftest

__version__ = "0.1.0"
APP_NAME = "Generic Company QR Studio"


def run_gui(smoke_path):
    """Open the window and run it until it closes -> exit code 0. See studio_gui.StudioWindow."""
    import studio_gui  # it loads tkinter: imported here, so the command line and --selftest run without it
    return studio_gui.StudioWindow(smoke_path, APP_NAME, __version__).run()


def command_read(path):
    """--read: print the text of the code in the picture at `path` -> exit code (1 when nothing was read)."""
    loaded = load_image_file(path)
    if not loaded["ok"]:
        print(loaded["error"])
        return 1
    reading = decode_image(loaded["value"])
    if not reading["ok"]:
        print(reading["error"])
        return 1
    sys.stdout.write(reading["value"]["text"] + "\n")
    return 0


def command_make(arguments):
    """--make TEXT OUT: write TEXT as a level M code, 8 pixels per module, to OUT (.png or .svg) -> exit code."""
    index = arguments.index("--make")
    if index + 2 >= len(arguments):
        print("--make needs TEXT and an output file")
        return 2
    made = encode_text(arguments[index + 1], "M", 1, -1)
    if not made["ok"]:
        print(made["error"])
        return 1
    saved = save_matrix(made["value"], arguments[index + 2], 8)
    if not saved["ok"]:
        print(saved["error"])
        return 1
    print("wrote " + arguments[index + 2])
    return 0


def main(arguments):
    """Run the command line `arguments` (see Usage) -> the exit code. The first of --version, --selftest,
    --make and --read that is present wins; otherwise the window opens, as a smoke run with --smoke FILE."""
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        return selftest()
    if "--make" in arguments:
        return command_make(arguments)
    read_path = option_value(arguments, "--read")
    if read_path is None:
        print("--read needs a picture")
        return 2
    if read_path != "":
        return command_read(read_path)
    smoke_path = option_value(arguments, "--smoke")
    if smoke_path is None:
        print("--smoke needs a file")
        return 2
    return run_gui(smoke_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=8118d7ed24d2e822899bf9543ef1f9db859064e6b40758925e6c43170f2c287d ====
