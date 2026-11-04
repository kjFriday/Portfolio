# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: app_settings.py
# About: The settings in force for this run, put in place by apply_settings from settings.json's...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""The settings in force for this run, put in place by apply_settings from settings.json's values.

qr_palette.main loads settings.json (settings.load) and calls apply_settings once, before it serves ECP,
exports redirect pages or opens the window (--selftest and --version run on the defaults). apply_settings
writes the values that the other modules read as they work: swatch's contrast line, near distance and
rankings folder, registry's limits and time budget, ecp's caps and its cloud rule, mcp_server's rate limit,
and local_inference's timeouts and answer sizes. It also loads planner.json (ecp.configure_planner, which
replaces swatch.FAMILY_WORDS too) and links.json.

The values that belong to the program itself have their one home here. Other modules read them as
app_settings.NAME when they run, never through "from app_settings import NAME", so that they always see
the value in force, and the one a test puts here:
  DEFAULT_SCALE     pixels per module of a saved picture (pictures.pixels_per_module)
  PROTOCOL_TIMEOUT  seconds a model may take to plan a question for --mcp (inference.timeout_seconds)
  WINDOW_TIMEOUT    the same for the window (inference.window_timeout_seconds)
  LINKS             links.json: the local and nonlocal sections, the ID length, tags and templates
  LINK_SECTION      the section new short links use (links.use)
  SCANS_VOTE        whether scans feed the ranking's scans algo (colors.scans_vote)

HERE is the program folder: planner.json, links.json, presets/ and weights/ ship beside this file.
"""

import os

import ecp
import local_inference
import mcp_server
import registry
import shortlinks
import swatch

HERE = os.path.dirname(os.path.abspath(__file__))

# Set from settings.json and links.json at start by apply_settings (these are the defaults).
DEFAULT_SCALE = 8
PROTOCOL_TIMEOUT = 45.0
WINDOW_TIMEOUT = 300.0
LINKS = shortlinks.copy_links(shortlinks.DEFAULT_LINKS)  # links.json, put in place by apply_settings()
LINK_SECTION = "local"  # the section new short links use: settings.json's links.use
SCANS_VOTE = False  # settings.json's colors.scans_vote: scans feed the ranking's scans algo


def apply_settings(values):
    """Put settings.json's values in place across the modules, and load planner.json and links.json
    -> [warnings]."""
    global DEFAULT_SCALE, PROTOCOL_TIMEOUT, WINDOW_TIMEOUT, LINKS, LINK_SECTION, SCANS_VOTE
    warnings = []
    colors = values["colors"]
    SCANS_VOTE = colors["scans_vote"]
    swatch.MIN_CONTRAST = colors["minimum_contrast"]
    swatch.NEAR = colors["near_distance"]
    swatch.RANKING_ROOT = colors["rankings_folder"] or HERE
    if colors["preset"] not in swatch.presets():
        warnings.append("settings: no preset named " + colors["preset"] + " in " +
                        os.path.join(swatch.RANKING_ROOT, "presets") + "; using " + swatch.DEFAULT_PRESET)
        colors["preset"] = swatch.DEFAULT_PRESET
    queries = values["queries"]
    registry.DEFAULT_LIMIT = queries["default_limit"]
    registry.MAX_LIMIT = queries["max_limit"]
    registry.STATEMENT_SECONDS = float(queries["statement_seconds"])
    ecp.QUESTION_LIMIT = queries["question_characters"]
    protocol = values["protocol"]
    ecp.MAX_LINE = protocol["max_message_bytes"]
    ecp.MAX_FIELD_CHARACTERS = protocol["max_field_characters"]
    ecp.MAX_RESULT_CHARACTERS = protocol["max_result_characters"]
    mcp_server.RATE_PER_SECOND = float(protocol["rate_per_second"])
    mcp_server.RATE_BURST = protocol["rate_burst"]
    inference = values["inference"]
    ecp.REQUIRE_CLOUD_DISABLED = inference["require_cloud_disabled"]
    local_inference.LIST_TIMEOUT = float(inference["list_timeout_seconds"])
    local_inference.PLAN_OPTIONS["num_predict"] = inference["max_answer_tokens"]
    local_inference.PLAN_OPTIONS["num_ctx"] = inference["context_tokens"]
    local_inference.RETRY_ANSWER_TOKENS = inference["retry_answer_tokens"]
    local_inference.KEEP_ALIVE = inference["keep_alive"]
    PROTOCOL_TIMEOUT = float(inference["timeout_seconds"])
    WINDOW_TIMEOUT = float(inference["window_timeout_seconds"])
    DEFAULT_SCALE = values["pictures"]["pixels_per_module"]
    planner_path = values["planner"]["file"] or os.path.join(HERE, "planner.json")
    loaded = ecp.load_planner(planner_path)
    ecp.configure_planner(loaded["planner"])
    links = shortlinks.load_links(values["links"]["file"] or os.path.join(HERE, "links.json"))
    LINKS = links["links"]
    LINK_SECTION = values["links"]["use"]
    return warnings + loaded["warnings"] + links["warnings"]

# ==== stamp v1 | author=kjFriday | hmac-sha256=32cdd005f29723a0d8ac36d019b26c2991bb64531db72b0c9197e77a2bb822de ====
