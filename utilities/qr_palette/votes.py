# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: votes.py
# About: Votes and the board: Good and Bad votes on colors, votes brought in from Color Voats, and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Votes and the board: Good and Bad votes on colors, Color Voats imports, the ranked board.

A vote is kept per color in the registry (registry.vote: pressing the same vote again takes it back).
board ranks the usable colors for a preset with those votes, and with the scans of each color's short
links when settings.json's colors.scans_vote is on (app_settings.SCANS_VOTE), through swatch.rank_colors.

Who calls it: the Make tab (gui/make_tab.py) casts votes with vote_color() and shows board(); the
window's File > Import votes from Color Voats (gui/window.py) brings in Color Voats' social.json with
import_color_voats(); selftest.py uses vote_color() and board(), and the tests all three. It calls registry for the votes and scans, through
common.with_registry (one read-write connection per call, closed again), and swatch for the ranking.

Flow (board)
  1. Open the registry and read the vote log (oldest first), each color's vote now, and, when
     SCANS_VOTE is on, the scans per color.
  2. Rank all 216 cube colors with the preset (swatch.rank_colors).
  3. Keep only the usable colors for the board, and number every color's place.

Records
  Result  {"ok": bool, "error": str, "value": any}
  Board   {"order": [usable "#rrggbb", best first], "votes": {"#rrggbb": 1 | -1},
           "places": {"#rrggbb": place from 1, for all 216 colors}}
"""

import json
import os

import app_settings
import registry
import swatch
from common import fail, ok_result, with_registry

# The most social.json may hold (5 MiB); a bigger file is refused before it is read into memory.
MAX_SOCIAL_BYTES = 5 * 1024 * 1024


def vote_color(db_path, color, voat):
    """Vote Good (1) or Bad (-1) for `color` -> Result the color's vote now: 1, -1, or 0 when it was taken back.

    `color` must be "#rrggbb" in lower case and `voat` 1 or -1; registry.vote refuses anything else.
    Side effect: writes the votes table of the registry at `db_path` (made if it is not there yet)."""
    def cast(connection):
        """Cast the vote on the open connection -> registry.vote's Result."""
        return registry.vote(connection, color, voat)

    return with_registry(db_path, cast)


def read_json_file(path, limit):
    """Parse a UTF-8 JSON file of at most `limit` bytes -> Result of the parsed data.

    Fails, naming the file, when it is too big, cannot be read, or is not valid JSON.
    Known limitation: when json.load raises, the handle is left for the garbage collector to close."""
    try:
        if os.path.getsize(path) > limit:
            return fail(path + " is too big")
        handle = open(path, "r", encoding="utf-8")
        data = json.load(handle)
        handle.close()
    except (OSError, ValueError) as error:
        return fail("cannot read " + path + ": " + str(error))
    return ok_result(data)


def import_color_voats(db_path, social_path):
    """Color Voats' votes into the registry (the newer vote wins per color) -> Result how many changed.

    `social_path` is Color Voats' social.json; only its "votes" object ({"#rrggbb": {"voat", "when"}})
    is read, and registry.import_votes skips entries that are not usable. Importing the same file twice
    changes nothing the second time.

    Steps:
    1. Read the file (at most MAX_SOCIAL_BYTES) and check it holds a "votes" object.
    2. Hand the votes to registry.import_votes in one transaction on a read-write connection."""
    loaded = read_json_file(social_path, MAX_SOCIAL_BYTES)
    if not loaded["ok"]:
        return loaded
    data = loaded["value"]
    if not isinstance(data, dict) or not isinstance(data.get("votes"), dict):
        return fail("no votes in " + social_path)

    def bring(connection):
        """Import the file's votes on the open connection -> registry.import_votes' Result."""
        return registry.import_votes(connection, data["votes"])

    return with_registry(db_path, bring)


def board(db_path, preset):
    """The usable colors best first for a preset, and the votes -> Result {"order", "votes", "places"}.

    `preset` names a file in presets/ (swatch.RANKING_ROOT). The registry is opened read-write through
    with_registry, which makes it when it is missing; only reads are done. A preset that cannot be read
    fails with its error.

    Steps:
    1. Read the vote log, the vote map and (only with SCANS_VOTE on) the scans per color; None for the
       scans means they do not count, so presets that use the scans algo see none.
    2. Rank all 216 colors; "order" keeps the usable ones, "places" numbers all of them."""
    def read(connection):
        """Read what the ranking needs on the open connection -> Result {"log", "votes", "scans"}."""
        counts = None
        if app_settings.SCANS_VOTE:
            counts = registry.color_scans(connection)
        return ok_result({"log": registry.vote_log(connection), "votes": registry.vote_map(connection), "scans": counts})

    read_votes = with_registry(db_path, read)
    if not read_votes["ok"]:
        return read_votes
    ranked = swatch.rank_colors(preset, read_votes["value"]["log"], read_votes["value"]["scans"])
    if not ranked["ok"]:
        return ranked
    return ok_result({"order": swatch.usable_board(ranked["value"]), "votes": read_votes["value"]["votes"],
                      "places": swatch.rank_places(ranked["value"])})

# ==== stamp v1 | author=kjFriday | hmac-sha256=8a27fc032dd3f09e5418f4f41914f2646bd82c6916a9324b76c45a41a3fa4b02 ====
