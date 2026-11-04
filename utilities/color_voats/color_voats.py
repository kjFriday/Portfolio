# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: color_voats.py
# About: Generic Company Color Voats: a social feed of colors, ranked for you by your Good and Bad...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Generic Company Color Voats: a feed of colors ranked by your Good and Bad votes.

It works like a social feed. Every post is a color: the 216 colors of the 6x6x6 cube that come with the program, plus colors you
post yourself. A post shows its color, hex code, when it was posted and a caption, with Good, Bad and
Save buttons and a comment section. The Feed tab is sorted For you, by a ranker that factory.py
generates from a preset and its algos' weights, or by New. The Saved tab holds the posts you saved,
and the New post tab shares a color of your own. Everything stays on this computer.

This file is the entry point: the version and the command line. The rest of the program:
  voats_core.py       posts, votes, comments, saves, the store file and the feed's order (no GUI)
  voats_gui.py        the tkinter window, VoatsWindow; imported only when a window opens
  voats_selftest.py   the checks --selftest runs
  algos.py, factory.py, presets/, weights/ and rankers/   the For you ranking (see README.md)

Usage
  python color_voats.py                   open the window (For you ranked by the "mixer" preset)
  python color_voats.py --preset NAME     rank For you with presets/NAME
  python color_voats.py --data FILE       keep posts, votes, comments and saves in FILE
  python color_voats.py --selftest        run the built-in checks and exit
  python color_voats.py --version
  python color_voats.py --smoke FILE      open the window, use it in memory, write a JSON report, close

Exit codes: 0 done (or every self-check passed), 1 the preset's ranker could not be made or loaded (or a
self-check failed), 2 --preset, --data or --smoke without its value.

Main flow of main()
  1. --version and --selftest answer at once, before anything touches the store or tkinter.
  2. The option values are read; a flag given without its value is exit code 2.
  3. load_ranker() makes sure the preset's ranker is current (writing it if not) and loads it.
  4. voats_gui is imported only now and run_gui() opens the window until it closes.
"""

import sys

from voats_core import DEFAULT_PRESET, data_path, load_ranker
from voats_selftest import selftest

# the Dev Console bumps this line together with setup.json's version; keep it the first such line
__version__ = "0.2.0"
APP_NAME = "Generic Company Color Voats"  # printed by --version


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing.

    Only the first occurrence of `name` counts. The value is taken as is, so "--preset --data"
    reads "--data" as the preset's name.
    """
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    """Run the command line `arguments` (see Usage) -> the exit code."""
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        return selftest()
    preset = option_value(arguments, "--preset")
    data_file = option_value(arguments, "--data")
    smoke_path = option_value(arguments, "--smoke")
    if preset is None or data_file is None or smoke_path is None:
        print("--preset needs a name, --data and --smoke a file")
        return 2
    if preset == "":
        preset = DEFAULT_PRESET
    if data_file == "":
        data_file = data_path()
    loaded = load_ranker(preset)
    if not loaded["ok"]:
        print(loaded["error"], file=sys.stderr)
        return 1
    import voats_gui  # it loads tkinter: imported here, so --version and --selftest still run without it
    return voats_gui.run_gui(loaded["value"], preset, data_file, smoke_path, __version__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=167f64d31fa218f908c76d438d8740f4a35279465a81b3dcd36dc1f8e6360301 ====
