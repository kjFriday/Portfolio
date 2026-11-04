# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: factory.py
# About: Color Voats factory: build a standalone Python ranker from a preset and its algos'...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# ========================================================================

"""Color Voats factory: build a standalone Python ranker from a preset and its weights.

Each ranker is one file, rankers/ranker_<preset>.py, made from a preset and its algos' weights.

    python factory.py             write rankers/ranker_<preset>.py for every preset
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

Who calls it: the command line above; voats_core.load_ranker (through ensure()) at every launch and
preset switch; voats_selftest and the tests (check(), generate(), read_preset()). It calls algos.py
for the algo names and, through inspect.getsource, for the text of the functions it copies.

Main flow of generate()
  1. read_preset() loads presets/<name>, checks its shape, and read_weights() loads and checks the
     weights of every algo it feeds (load() finds the .toml or .json file).
  2. The header comments, the ranker docstring and the constants are written: PRESET, ALGO, MIX
     (blend) or CHAIN (mixer), then one ALGO_KEY constant per weight, such as SIMILAR_REACH.
  3. The needed algos functions are copied: BASE always, plus NEEDS of each scorer and aggregator,
     emitted in COPY_ORDER so callees come before callers and the output order never varies.
  4. score_function() and rank_function() write the two entry points the window calls.
ensure() writes the text only when the file differs; check() only compares.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Loaded   {"file": "folder/name.toml", "data": dict}          what load() and read_weights() give
  Preset   {"name", "file", "algo", "uses", "scorers", "weights": {algo: Loaded}}   see read_preset()

Start reading at generate().
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

# the program folder: presets/, weights/ and rankers/ sit beside this file
HERE = os.path.dirname(os.path.abspath(__file__))

# the weights each algo's file must hold; blend takes its weights from the preset's uses instead.
# The key order is also the order the generated score() passes them in, matching the algos'
# parameters (and algos.run_scorer).
WEIGHT_KEYS = {"net": ("up", "down"), "wilson": ("z",), "similar": ("reach", "up", "down"),
               "explore": ("far",), "mixer": ("tie", "streak", "budget")}
# weights that must be above 0: reach and tie are divisors (similar, buckets), a far of 0 scores every
# color 0, a streak of 0 passes the lead on at every downvoat, and a budget of 0 skips every scorer
POSITIVE = ("reach", "far", "tie", "streak", "budget")

# the functions of algos.py a ranker copies: always BASE, then what its algos need, in COPY_ORDER
BASE = ("linear", "oklab", "distance", "discovery_order", "order_by")
NEEDS = {"net": ("tally", "net"), "wilson": ("tally", "wilson"), "similar": ("similar",),
         "explore": ("explore",), "blend": ("normalize", "blend"),
         "mixer": ("normalize", "buckets", "cost", "mixer_lead", "mixer")}
# every copyable function once, callees before callers; a fixed order keeps the output byte-stable
COPY_ORDER = ("linear", "oklab", "distance", "discovery_order", "order_by", "normalize", "tally", "net",
              "wilson", "similar", "explore", "blend", "buckets", "cost", "mixer_lead", "mixer")
# a preset name becomes a file name and a module name, so it is a plain identifier: no paths, no capitals
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def ok_result(value):
    """A Result that worked, holding `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A Result that failed, with `error` saying why."""
    return {"ok": False, "error": error, "value": None}


def is_number(value):
    """True for a finite int or float. A bool is not a number (Python counts True as an int), and
    TOML's nan and inf are refused, since they would break every comparison in the algos."""
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, float)):
        return False
    return math.isfinite(value)


def load(root, folder, name):
    """folder/name.toml or folder/name.json under root -> Result {"file": "folder/name.toml", "data": dict}.

    Exactly one of the two must exist, so it is never unclear which file is in force. "file" is the
    path relative to root with "/" separators: it goes into error messages and into the ranker's
    header, so the output is the same on every operating system. Errors: missing, both present,
    TOML without tomllib, unreadable or unparsable, or not a table at the top.
    """
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
    except (OSError, ValueError) as error:  # TOMLDecodeError and JSONDecodeError are both ValueErrors
        return fail(found[0] + ": " + str(error))
    if not isinstance(data, dict):
        return fail(found[0] + ": expected a table of names and values")
    return ok_result({"file": found[0], "data": data})


def read_weights(root, name):
    """weights/<name>, checked against WEIGHT_KEYS -> Result {"file", "data"}.

    `name` must be a key of WEIGHT_KEYS (read_preset only passes known algos). The file must hold
    exactly the algo's keys, each a finite number, and the POSITIVE ones above 0. Each error names
    the file and the weight.
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
    """presets/<name> and the weights of every algo it feeds -> Result Preset record:
    {"name", "file", "algo", "uses" (dict for blend, list for mixer, [] for one scorer),
     "scorers": [names in use], "weights": {algo: {"file", "data"}}}.

    Steps:
      1. Refuse a name that is not a plain identifier (NAME_RE), before it touches a path.
      2. Load the preset; it may hold only algo and uses.
      3. Check uses by algo: blend needs a table of known scorers with number weights, mixer a list
         of known scorers without repeats, and a single scorer takes no uses at all.
      4. Read the weights of every scorer in use, plus the mixer's own weights for a mixer.
    The first problem found is returned; nothing is collected.
    """
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
    """The name of the ranker constant holding weight `key` of `algo`: ("similar", "reach") -> SIMILAR_REACH."""
    return algo.upper() + "_" + key.upper()


def score_function(preset):
    """The source lines of the ranker's score(name, colors, voats): one `if name == ...` branch per
    scorer in use, calling the copied scorer with its weight constants in WEIGHT_KEYS order, and a
    ValueError for any other name. The leading "" lines are the two blank lines before a def."""
    lines =["", "", "def score(name, colors, voats):",
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
    """The source lines of the ranker's rank(voats, colors), the function the window calls.

    blend: score each scorer in MIX, blend the lists with MIX's weights and order by the sum.
    mixer: hand everything to the copied mixer() with CHAIN, the mixer constants and score.
    a single scorer: order by that scorer's scores alone.
    """
    lines =["", "", "def rank(voats, colors):",
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
    """The source of rankers/ranker_<name>.py -> Result text.

    Pure: reads the preset and weights files under `root` and algos.py's source, writes nothing.
    The text ends with one newline and uses "\\n" line endings. See the module doc for the steps.
    """
    read = read_preset(root, name)
    if not read["ok"]:
        return read
    preset = read["value"]
    # the header: line 1's "do not edit" wording is what makes tools/stamp.py treat rankers as
    # generated and leave them unstamped, and test_factory checks how it starts
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
    # the constants: MIX keeps the preset's key order (tomllib and json keep file order), and repr()
    # writes each float so it reads back exactly
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
    # the copied code: getsource gives each function's text from its def line to the end of its body,
    # unchanged, so a ranker runs exactly the code the tests run through algos
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
    """Every preset in presets/, by name, sorted. A name with both a .toml and a .json file is listed
    once (generating it then reports the clash); [] when there is no presets/ folder."""
    names = []
    folder = os.path.join(root, "presets")
    if os.path.isdir(folder):
        for entry in sorted(os.listdir(folder)):
            stem, extension = os.path.splitext(entry)
            if (extension == ".toml" or extension == ".json") and stem not in names:
                names.append(stem)
    return names


def ranker_path(root, name):
    """Where the ranker of preset `name` lives: rankers/ranker_<name>.py under `root`."""
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
    -> Result {"path", "written": bool}.

    Side effects: may create rankers/ and (over)write the ranker file, always with "\\n" line
    endings, so the bytes match generate() on every platform. An unchanged file is not touched,
    which keeps its timestamp and lets a read-only install run as long as its rankers are current.
    """
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
    """What is wrong with these presets' rankers: failures to generate, and missing or stale files.

    Returns one message per problem ([] when all is well) and writes nothing. A missing file reads as
    None, so it is reported as stale too.
    """
    problems = []
    for name in names:
        made = generate(root, name)
        if not made["ok"]:
            problems.append(made["error"])
        elif written_text(ranker_path(root, name)) != made["value"]:
            problems.append("stale: rankers/ranker_" + name + ".py (run: python factory.py " + name + ")")
    return problems


def main(arguments):
    """Run the command line `arguments` (see the module doc) -> the exit code.

    Every argument other than --check is a preset name; with none, every preset is used.
    --check prints each problem and returns 1 if there is any, otherwise a count and 0.
    Without --check each ranker is written if needed and reported as wrote or unchanged;
    the result is 1 when any preset failed (its error is printed) or there are no presets.
    """
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=e505c96e3da7a2301ab062b3ff37a86dd902693809eda69e65399b6b6904441e ====
