# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/factory.py
# About: Color Voats factory: build a standalone Python ranker from a preset and its algos'...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Color Voats factory: build a standalone Python ranker from a preset and its algos' weights.

    python factory.py              write rankers/ranker_<preset>.py for every preset
    python factory.py NAME ...     only these presets
    python factory.py --check      exit 1 when a ranker is missing or differs from what would be written

Each algo has a weights file, weights/<algo>.toml or weights/<algo>.json (one or the other). A preset,
presets/<name>.toml or .json, names the algo that ranks and feeds it what it uses:

    algo = "blend"    uses = {similar = 0.6, explore = 0.3}   weighted sum of 0..1 scaled scores
    algo = "mixer"    uses = ["net", "wilson", "similar"]     the chain the mixer hands ties down
    algo = "wilson"                                           one scorer alone

The ranker holds the weights as constants and the functions it needs, copied unchanged from algos.py,
so it runs on its own: rank(voats, colors) -> colors best first. The same files always give the same
bytes. Failures are returned as Result records {"ok": bool, "error": str, "value": any}.
"""

import inspect
import json
import math
import os
import re
import sys

import algos

try:
    import tomllib
except ImportError:  # Python 3.10: .json files still work
    tomllib = None

HERE = os.path.dirname(os.path.abspath(__file__))

# the weights each algo's file must hold; blend takes its weights from the preset's uses instead
WEIGHT_KEYS = {"net": ("up", "down"), "wilson": ("z",), "similar": ("reach", "up", "down"),
               "explore": ("far",), "mixer": ("tie", "streak", "budget")}
POSITIVE = ("reach", "far", "tie", "streak", "budget")

# the functions of algos.py a ranker copies: always BASE, then what its algos need, in COPY_ORDER
BASE = ("linear", "oklab", "distance", "discovery_order", "order_by")
NEEDS = {"net": ("tally", "net"), "wilson": ("tally", "wilson"), "similar": ("similar",),
         "explore": ("explore",), "blend": ("normalize", "blend"),
         "mixer": ("normalize", "buckets", "cost", "mixer_lead", "mixer")}
COPY_ORDER = ("linear", "oklab", "distance", "discovery_order", "order_by", "normalize", "tally", "net",
              "wilson", "similar", "explore", "blend", "buckets", "cost", "mixer_lead", "mixer")
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
    """folder/name.toml or folder/name.json under root -> Result {"file": "folder/name.toml", "data": dict}."""
    found = []
    for extension in (".toml", ".json"):
        if os.path.isfile(os.path.join(root, folder, name + extension)):
            found.append(folder + "/" + name + extension)
    if len(found) == 0:
        return fail("missing " + folder + "/" + name + ".toml (or .json)")
    if len(found) > 1:
        return fail("both " + found[0] + " and " + found[1] + ": keep one")
    path = os.path.join(root, found[0])
    try:
        if found[0].endswith(".toml"):
            if tomllib is None:
                return fail(found[0] + ": TOML needs Python 3.11 or newer (or use .json)")
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
        else:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
    except (OSError, ValueError) as error:
        return fail(found[0] + ": " + str(error))
    if not isinstance(data, dict):
        return fail(found[0] + ": expected a table of names and values")
    return ok_result({"file": found[0], "data": data})


def read_weights(root, name):
    """weights/<name>, checked against WEIGHT_KEYS -> Result {"file", "data"}."""
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
    """presets/<name> and the weights of every algo it feeds -> Result Preset record:
    {"name", "file", "algo", "uses" (dict for blend, list for mixer, [] for one scorer),
     "scorers": [names in use], "weights": {algo: {"file", "data"}}}."""
    if not NAME_RE.match(name):
        return fail("preset names are lower-case letters, digits and _: " + repr(name))
    loaded = load(root, "presets", name)
    if not loaded["ok"]:
        return loaded
    file = loaded["value"]["file"]
    data = loaded["value"]["data"]
    for key in data:
        if key not in ("algo", "uses"):
            return fail(file + ": unknown key '" + key + "' (a preset has algo and uses)")
    algo = data.get("algo")
    if algo not in algos.SCORERS and algo not in algos.AGGREGATORS:
        return fail(file + ": algo: unknown algo " + repr(algo) + " (one of " +
                    ", ".join(algos.SCORERS + algos.AGGREGATORS) + ")")
    uses = data.get("uses")
    scorers = []
    if algo == "blend":
        if not isinstance(uses, dict) or len(uses) == 0:
            return fail(file + ": uses: blend needs a table of algos and their weights")
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
    return ok_result({"name": name, "file": file, "algo": algo, "uses": uses, "scorers": scorers,
                      "weights": weights})


def constant(algo, key):
    return algo.upper() + "_" + key.upper()


def score_function(preset):
    lines = ["", "", "def score(name, colors, voats):",
             '    """One scorer by name, with this preset\'s weights -> one float per color."""']
    for scorer in preset["scorers"]:
        arguments = ["colors", "voats"]
        for key in WEIGHT_KEYS[scorer]:
            arguments.append(constant(scorer, key))
        lines.append('    if name == "' + scorer + '":')
        lines.append("        return " + scorer + "(" + ", ".join(arguments) + ")")
    lines.append('    raise ValueError("no scorer " + name + " in this preset")')
    return lines


def rank_function(preset):
    lines = ["", "", "def rank(voats, colors):",
             '    """`colors` best first for the voat log `voats`, under the ' + preset["name"] + ' preset."""']
    if preset["algo"] == "blend":
        lines.append("    lists = []")
        lines.append("    weights = []")
        lines.append("    for name in MIX:")
        lines.append("        lists.append(score(name, colors, voats))")
        lines.append("        weights.append(MIX[name])")
        lines.append("    return order_by(colors, [blend(lists, weights)])")
    elif preset["algo"] == "mixer":
        lines.append("    return mixer(colors, voats, CHAIN, MIXER_TIE, MIXER_STREAK, MIXER_BUDGET, score)")
    else:
        lines.append('    return order_by(colors, [score("' + preset["algo"] + '", colors, voats)])')
    return lines


def generate(root, name):
    """The source of rankers/ranker_<name>.py -> Result text."""
    read = read_preset(root, name)
    if not read["ok"]:
        return read
    preset = read["value"]
    files = []
    for which in preset["weights"]:
        files.append(preset["weights"][which]["file"])
    lines = ["# Generated by factory.py - do not edit. Preset: " + preset["file"],
             "# Weights: " + ", ".join(files),
             "# The functions are copied unchanged from algos.py. Regenerate: python factory.py " + name,
             '"""Ranker for the ' + name + ' preset: rank(voats, colors) -> colors best first."""',
             "",
             "import math",
             "",
             'PRESET = "' + name + '"',
             'ALGO = "' + preset["algo"] + '"']
    if preset["algo"] == "blend":
        parts = []
        for scorer in preset["uses"]:
            parts.append('"' + scorer + '": ' + repr(preset["uses"][scorer]))
        lines.append("MIX = {" + ", ".join(parts) + "}")
    if preset["algo"] == "mixer":
        parts = []
        for scorer in preset["uses"]:
            parts.append('"' + scorer + '"')
        lines.append("CHAIN = [" + ", ".join(parts) + "]")
    for which in preset["weights"]:
        for key in WEIGHT_KEYS[which]:
            lines.append(constant(which, key) + " = " + repr(preset["weights"][which]["data"][key]))
    wanted = list(BASE)
    needers = list(preset["scorers"])
    if preset["algo"] in algos.AGGREGATORS:
        needers.append(preset["algo"])
    for needer in needers:
        for function in NEEDS[needer]:
            wanted.append(function)
    for function in COPY_ORDER:
        if function in wanted:
            lines.append("")
            lines.append("")
            lines.append(inspect.getsource(getattr(algos, function)).rstrip("\n"))
    lines = lines + score_function(preset) + rank_function(preset)
    return ok_result("\n".join(lines) + "\n")


def preset_names(root):
    """Every preset in presets/, by name, sorted."""
    names = []
    folder = os.path.join(root, "presets")
    if os.path.isdir(folder):
        for entry in sorted(os.listdir(folder)):
            stem, extension = os.path.splitext(entry)
            if (extension == ".toml" or extension == ".json") and stem not in names:
                names.append(stem)
    return names


def ranker_path(root, name):
    return os.path.join(root, "rankers", "ranker_" + name + ".py")


def written_text(path):
    """The file's text with line endings as "\\n" (so a CRLF checkout still matches), None if unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def ensure(root, name):
    """Write rankers/ranker_<name>.py when it is missing or differs from what generate() makes
    -> Result {"path", "written": bool}."""
    made = generate(root, name)
    if not made["ok"]:
        return made
    path = ranker_path(root, name)
    if written_text(path) == made["value"]:
        return ok_result({"path": path, "written": False})
    try:
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(made["value"])
    except OSError as error:
        return fail(path + ": " + str(error))
    return ok_result({"path": path, "written": True})


def check(root, names):
    """What is wrong with these presets' rankers: failures to generate, and missing or stale files."""
    problems = []
    for name in names:
        made = generate(root, name)
        if not made["ok"]:
            problems.append(made["error"])
        elif written_text(ranker_path(root, name)) != made["value"]:
            problems.append("stale: rankers/ranker_" + name + ".py (run: python factory.py " + name + ")")
    return problems


def main(arguments):
    names = []
    for argument in arguments:
        if argument != "--check":
            names.append(argument)
    if len(names) == 0:
        names = preset_names(HERE)
    if len(names) == 0:
        print("no presets in presets/")
        return 1
    if "--check" in arguments:
        problems = check(HERE, names)
        for problem in problems:
            print(problem)
        if len(problems) > 0:
            return 1
        print(str(len(names)) + " ranker(s) up to date")
        return 0
    failures = 0
    for name in names:
        made = ensure(HERE, name)
        if not made["ok"]:
            print(made["error"])
            failures = failures + 1
        elif made["value"]["written"]:
            print("wrote     rankers/ranker_" + name + ".py")
        else:
            print("unchanged rankers/ranker_" + name + ".py")
    if failures > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=2041b7f34d8e535e7d3be9ebc8a586cd91fac9f488a9c3dc0f7b9874521749b2 ====
