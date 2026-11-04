# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: ranking.py
# About: QR Palette ranking: Color Voats' presets and weights, read from JSON files, ranked with...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette ranking: Color Voats' JSON presets and weights, ranked with its algos.

A preset (presets/NAME.json) names the algo that ranks the colors and what it uses; each algo it feeds
has a weights file (weights/ALGO.json). Both are plain, human-readable JSON, and every file may carry
an "about" text that explains it. Change a number, save, and the next ranking uses it. The rules are
Color Voats' (factory.py); the algos are its algos.py, copied unchanged (see PROVENANCE.md). One algo is
QR Palette's own, here rather than in algos.py: scans, which scores a color by how often its short links
are opened. It takes counts rather than votes, and can stand alone or be one part of a blend.

Callers: swatch.py (preset_names, read_preset and rank, for the board of colors) and its tests. It
calls algos.py for every scorer but scans, and for ordering, blending and the mixer. Files are only
read here, never written.

Main flow:
1. read_preset loads presets/NAME.json, checks its algo and uses, and loads the weights of every
   algo the preset feeds (read_weights, through load).
2. rank turns the preset, the vote log and the scans into every color, best first.

Start reading at read_preset.

Records
  Result  {"ok": bool, "error": str, "value": any}
  Preset  {"name", "file", "about", "algo", "uses" (a table for blend, a list for mixer, [] for one
           scorer), "scorers": [names in use], "weights": {algo: {"file", "data"}}}
  Voat    {"color": "#rrggbb", "voat": 1 | -1}      a vote, oldest first
  Scans   {"#rrggbb": {"scans": int, "links": int}}  a color's scans, and how many short links it has
"""

import json
import math
import os
import re

import algos

# the weights each algo's file must hold; blend takes its weights from the preset's uses instead
WEIGHT_KEYS = {"net": ("up", "down"), "wilson": ("z",), "similar": ("reach", "up", "down"),
               "explore": ("far",), "mixer": ("tie", "streak", "budget"), "scans": ("prior_links", "prior_rate")}
# weights that must be above 0: each is a distance, a tolerance, a count or a divisor, where 0 or less makes no sense
POSITIVE = ("reach", "far", "tie", "streak", "budget", "prior_links")
# every algo that scores colors on its own: Color Voats' scorers and QR Palette's scans
SCORERS = algos.SCORERS + ("scans",)
# a preset name is also a file name, so only lower-case letters, digits and _ (no path, no dots)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def ok_result(value):
    """A successful Result holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the message `error` and no value."""
    return {"ok": False, "error": error, "value": None}


def is_number(value):
    """True when `value` is a finite int or float from JSON.

    bool is a subclass of int in Python, so true and false are ruled out first; NaN and infinity
    (which Python's json module accepts) are ruled out by isfinite.
    """
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, float)):
        return False
    return math.isfinite(value)


def load(root, folder, name):
    """root/folder/name.json -> Result {"file": "folder/name.json", "data": dict, "about": str}. The
    "about" text is kept apart from the data.

    root: the program folder; folder: "presets" or "weights"; name: the file name without .json.
    Reads the file only. A missing file, a file that is not JSON, JSON that is not an object, or an
    "about" that is not text gives a failed Result naming the file.

    Steps:
    1. Build the short name used in messages (always with "/") and the real path.
    2. Read and parse the file.
    3. Check that it is an object and that "about", when present, is text.
    4. Copy every other key into the data.
    """
    file = folder + "/" + name + ".json"
    path = os.path.join(root, folder, name + ".json")
    if not os.path.isfile(path):
        return fail("missing " + file)
    try:
        # utf-8-sig also reads a file that a Windows editor saved with a byte-order mark
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
    """weights/<name>.json, checked against WEIGHT_KEYS -> Result {"file", "data", "about"}.

    root: the program folder; name: an algo with a weights file (a key of WEIGHT_KEYS). Reads the
    file only.

    Steps:
    1. Load the file (load).
    2. Refuse a key the algo does not take, so a misspelt weight is not silently ignored.
    3. Require every weight the algo takes, as a finite number, above 0 for those in POSITIVE.
    """
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
    """presets/<name>.json and the weights of every algo it feeds -> Result Preset.

    root: the program folder; name: the preset's name (a file name without .json). Reads files
    only. Any problem gives a failed Result naming the file and the key at fault.

    Steps:
    1. Check the name (NAME_RE), then load the file (load); a preset holds only about, algo and uses.
    2. Check algo: one of SCORERS (one scorer) or algos.AGGREGATORS (blend or mixer).
    3. Check uses by algo:
       - blend: an object of scorers and their weights, in any of SCORERS;
       - mixer: a list of Color Voats' scorers, each once (scans is refused: the chain is Color Voats');
       - one scorer: no uses, and the scorer is the algo itself.
    4. Read the weights of every scorer in use, and the mixer's own weights for a mixer.
    """
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
    if algo not in SCORERS and algo not in algos.AGGREGATORS:
        return fail(file + ": algo: unknown algo " + repr(algo) + " (one of " +
                    ", ".join(SCORERS + algos.AGGREGATORS) + ")")
    uses = data.get("uses")
    scorers = []
    if algo == "blend":
        if not isinstance(uses, dict) or len(uses) == 0:
            return fail(file + ": uses: blend needs an object of algos and their weights")
        for scorer in uses:
            if scorer not in SCORERS:
                return fail(file + ": uses: unknown algo " + repr(scorer) + " (one of " + ", ".join(SCORERS) + ")")
            if not is_number(uses[scorer]):
                return fail(file + ": uses: the weight of " + scorer + " must be a number")
            scorers.append(scorer)
    elif algo == "mixer":
        if not isinstance(uses, list) or len(uses) == 0:
            return fail(file + ": uses: the mixer needs a list of algos")
        for scorer in uses:
            if scorer == "scans":
                return fail(file + ": uses: the mixer's chain is Color Voats' own; put scans in a blend instead")
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
    # the mixer has weights of its own (tie, streak, budget); blend's are the numbers in uses
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
    """The presets in root/presets, by name.

    root: the program folder. Returns the names sorted, without .json; a missing folder gives [].
    Files whose name read_preset would refuse are left out, so every name listed can be asked for.
    """
    names = []
    folder = os.path.join(root, "presets")
    if not os.path.isdir(folder):
        return names
    for entry in sorted(os.listdir(folder)):
        # entry[:len(entry) - 5] is the name without its 5-character ".json"
        if entry.endswith(".json") and NAME_RE.match(entry[:len(entry) - 5]):
            names.append(entry[:len(entry) - 5])
    return names


def scans_scores(colors, scans, prior_links, prior_rate):
    """One score per color: its scans per short link, pulled towards `prior_rate` as if it had
    `prior_links` more links, so one lucky code does not outrank a color that has proved itself. With no
    scans at all every color ties: a blend then ignores this list.

    colors: "#rrggbb" strings; scans: a Scans record (colors missing from it count as 0 scans on 0
    links); prior_links (above 0) and prior_rate: the weights from weights/scans.json. Returns one
    float per color, in the order of `colors`.
    """
    scores = []
    for color in colors:
        counted = scans.get(color, {"scans": 0, "links": 0})
        # prior_links is above 0 (read_weights checks it), so the division is always safe
        scores.append((counted["scans"] + prior_links * prior_rate) / (counted["links"] + prior_links))
    return scores


def rank(preset, voats, colors, scans=None):
    """Every color, best first, for a preset, a vote log and scans (None or {} when they are not to
    count). The algos are Color Voats', unchanged, apart from scans.

    preset: a Preset from read_preset; voats: Voat records, oldest first; colors: "#rrggbb" strings;
    scans: a Scans record or None. Returns the colors reordered; nothing is read or written.

    Steps:
    1. Take each algo's weights out of the preset.
    2. blend: score with every scorer in uses and order by their weighted sum.
    3. mixer: let algos.mixer run the chain, with score as its way to run one scorer.
    4. one scorer: order by its scores.
    """
    weights = {}
    for name in preset["weights"]:
        weights[name] = preset["weights"][name]["data"]

    def score(name, colors, voats):
        """One float per color from scorer `name`: scans here, any other through algos.run_scorer.

        A closure over `weights` and `scans`, so algos.mixer can call it with the arguments it knows.
        """
        if name == "scans":
            return scans_scores(colors, scans or {}, weights[name]["prior_links"], weights[name]["prior_rate"])
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=65e9bdf92a7d982e76e306e42cb0469e5d38400f4ceb23be1b599c7d277f5eaa ====
