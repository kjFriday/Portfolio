# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/ranking.py
# About: QR Palette ranking: Color Voats' presets and weights, read from JSON files, ranked with...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette ranking: Color Voats' presets and weights, read from JSON files, ranked with its algos.

A preset (presets/NAME.json) names the algo that ranks the colors and what it uses; each algo it feeds
has a weights file (weights/ALGO.json). Both are plain, human-readable JSON, and every file may carry
an "about" text that explains it. Change a number, save, and the next ranking uses it. The rules are
Color Voats' (factory.py); the algos are its algos.py, copied unchanged (see PROVENANCE.md).

Records
  Result  {"ok": bool, "error": str, "value": any}
  Preset  {"name", "file", "about", "algo", "uses" (a table for blend, a list for mixer, [] for one
           scorer), "scorers": [names in use], "weights": {algo: {"file", "data"}}}
  Voat    {"color": "#rrggbb", "voat": 1 | -1}      a vote, oldest first
"""

import json
import math
import os
import re

import algos

# the weights each algo's file must hold; blend takes its weights from the preset's uses instead
WEIGHT_KEYS = {"net": ("up", "down"), "wilson": ("z",), "similar": ("reach", "up", "down"),
               "explore": ("far",), "mixer": ("tie", "streak", "budget")}
POSITIVE = ("reach", "far", "tie", "streak", "budget")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def is_number(value):
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, float)):
        return False
    return math.isfinite(value)


def load(root, folder, name):
    """root/folder/name.json -> Result {"file": "folder/name.json", "data": dict, "about": str}. The
    "about" text is kept apart from the data."""
    file = folder + "/" + name + ".json"
    path = os.path.join(root, folder, name + ".json")
    if not os.path.isfile(path):
        return fail("missing " + file)
    try:
        handle = open(path, "r", encoding="utf-8-sig")
        try:
            text = handle.read()
        finally:
            handle.close()
        data = json.loads(text)
    except (OSError, ValueError) as error:
        return fail(file + ": " + str(error))
    if not isinstance(data, dict):
        return fail(file + ": expected an object of names and values")
    about = data.get("about", "")
    if not isinstance(about, str):
        return fail(file + ": about must be text")
    values = {}
    for key in data:
        if key != "about":
            values[key] = data[key]
    return ok_result({"file": file, "data": values, "about": about})


def read_weights(root, name):
    """weights/<name>.json, checked against WEIGHT_KEYS -> Result {"file", "data", "about"}."""
    loaded = load(root, "weights", name)
    if not loaded["ok"]:
        return loaded
    file = loaded["value"]["file"]
    data = loaded["value"]["data"]
    for key in data:
        if key not in WEIGHT_KEYS[name]:
            return fail(file + ": unknown weight '" + key + "' (" + name + " takes " + ", ".join(WEIGHT_KEYS[name]) + ")")
    for key in WEIGHT_KEYS[name]:
        if key not in data:
            return fail(file + ": missing weight '" + key + "'")
        if not is_number(data[key]):
            return fail(file + ": weight '" + key + "' must be a number")
        if key in POSITIVE and data[key] <= 0:
            return fail(file + ": weight '" + key + "' must be above 0")
    return loaded


def read_preset(root, name):
    """presets/<name>.json and the weights of every algo it feeds -> Result Preset."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return fail("preset names are lower-case letters, digits and _: " + repr(name))
    loaded = load(root, "presets", name)
    if not loaded["ok"]:
        return loaded
    file = loaded["value"]["file"]
    data = loaded["value"]["data"]
    for key in data:
        if key not in ("algo", "uses"):
            return fail(file + ": unknown key '" + key + "' (a preset has about, algo and uses)")
    algo = data.get("algo")
    if algo not in algos.SCORERS and algo not in algos.AGGREGATORS:
        return fail(file + ": algo: unknown algo " + repr(algo) + " (one of " +
                    ", ".join(algos.SCORERS + algos.AGGREGATORS) + ")")
    uses = data.get("uses")
    scorers = []
    if algo == "blend":
        if not isinstance(uses, dict) or len(uses) == 0:
            return fail(file + ": uses: blend needs an object of algos and their weights")
        for scorer in uses:
            if scorer not in algos.SCORERS:
                return fail(file + ": uses: unknown algo " + repr(scorer) + " (one of " + ", ".join(algos.SCORERS) + ")")
            if not is_number(uses[scorer]):
                return fail(file + ": uses: the weight of " + scorer + " must be a number")
            scorers.append(scorer)
    elif algo == "mixer":
        if not isinstance(uses, list) or len(uses) == 0:
            return fail(file + ": uses: the mixer needs a list of algos")
        for scorer in uses:
            if scorer not in algos.SCORERS:
                return fail(file + ": uses: unknown algo " + repr(scorer) + " (one of " + ", ".join(algos.SCORERS) + ")")
            if scorer in scorers:
                return fail(file + ": uses: " + scorer + " is listed twice")
            scorers.append(scorer)
    else:
        if uses is not None:
            return fail(file + ": uses: only blend and mixer take uses")
        uses = []
        scorers.append(algo)
    fed = list(scorers)
    if algo == "mixer":
        fed.append("mixer")
    weights = {}
    for which in fed:
        read = read_weights(root, which)
        if not read["ok"]:
            return read
        weights[which] = read["value"]
    return ok_result({"name": name, "file": file, "about": loaded["value"]["about"], "algo": algo, "uses": uses,
                      "scorers": scorers, "weights": weights})


def preset_names(root):
    """The presets in root/presets, by name."""
    names = []
    folder = os.path.join(root, "presets")
    if not os.path.isdir(folder):
        return names
    for entry in sorted(os.listdir(folder)):
        if entry.endswith(".json") and NAME_RE.match(entry[:len(entry) - 5]):
            names.append(entry[:len(entry) - 5])
    return names


def rank(preset, voats, colors):
    """Every color, best first, for a preset and a vote log (Color Voats' algos, unchanged)."""
    weights = {}
    for name in preset["weights"]:
        weights[name] = preset["weights"][name]["data"]

    def score(name, colors, voats):
        return algos.run_scorer(name, colors, voats, weights[name])

    if preset["algo"] == "blend":
        lists = []
        mix = []
        for name in preset["uses"]:
            lists.append(score(name, colors, voats))
            mix.append(preset["uses"][name])
        return algos.order_by(colors, [algos.blend(lists, mix)])
    if preset["algo"] == "mixer":
        mixer = weights["mixer"]
        return algos.mixer(colors, voats, preset["uses"], mixer["tie"], mixer["streak"], mixer["budget"], score)
    return algos.order_by(colors, [score(preset["algo"], colors, voats)])

# ==== stamp v1 | author=kjFriday | hmac-sha256=ec8219ab53099f29b63d1518218edc838c82f90fb90b5bd0399ff46dbcc1d1b3 ====
