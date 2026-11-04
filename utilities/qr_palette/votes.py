# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: votes.py
# About: Votes and the board: Good and Bad votes on colors, votes brought in from Color Voats, and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Votes and the board: Good and Bad votes on colors, votes brought in from Color Voats, and the ranked board.

A vote is kept per color in the registry (registry.vote: pressing the same vote again takes it back).
board ranks the usable colors for a preset with those votes, and with the scans of each color's short
links when settings.json's colors.scans_vote is on (app_settings.SCANS_VOTE), through swatch.rank_colors.
"""

import json
import os

import app_settings
import registry
import swatch
from common import fail, ok_result, with_registry

MAX_SOCIAL_BYTES = 5 * 1024 * 1024


def vote_color(db_path, color, voat):
    def cast(connection):
        return registry.vote(connection, color, voat)

    return with_registry(db_path, cast)


def read_json_file(path, limit):
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
    """Color Voats' votes into the registry (the newer vote wins per color) -> Result how many changed."""
    loaded = read_json_file(social_path, MAX_SOCIAL_BYTES)
    if not loaded["ok"]:
        return loaded
    data = loaded["value"]
    if not isinstance(data, dict) or not isinstance(data.get("votes"), dict):
        return fail("no votes in " + social_path)

    def bring(connection):
        return registry.import_votes(connection, data["votes"])

    return with_registry(db_path, bring)


def board(db_path, preset):
    """The usable colors best first for a preset, and the votes -> Result {"order", "votes", "places"}."""
    def read(connection):
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
