# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/algos.py
# About: Color Voats algos: the scorers and aggregators that factory.py builds rankers from.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Color Voats algos: the scorers and aggregators that factory.py builds rankers from.

factory.py copies these functions, unchanged, into every generated ranker, so each one stays
self-contained: plain values in and out, only `math` from outside, no module state, and no helper
that is missing from factory.COPY_ORDER.

Records
  Voat     {"color": "#rrggbb", "voat": 1 | -1}   one upvoat or downvoat; a voat log is oldest first

Scorers: (colors, voats, <weights>) -> one float per color, higher is better
  net       upvoats x up - downvoats x down                            weights up, down
  wilson    lower bound of the upvoat share at confidence z           weight  z
  similar   pull of nearby voats in OKLab, exactly 0 beyond reach      weights reach, up, down
  explore   distance to the nearest voated color, capped at far        weight  far

Aggregators: scorers -> one order of the colors, best first
  blend     weighted sum of the scorers' scores, each scaled to 0..1   weights: the preset's uses
  mixer     the lead scorer ranks and hands what it leaves tied to the next one; `streak`
            downvoats in a row pass the lead on; a scorer over `budget` steps is skipped
                                                                       weights tie, streak, budget
Every order ends with discovery order, so it is total and the same on every run.
"""

import math

LEVELS = (0, 51, 102, 153, 204, 255)
SCORERS = ("net", "wilson", "similar", "explore")
AGGREGATORS = ("blend", "mixer")


def palette():
    """The 216 colors of the 6x6x6 cube as "#rrggbb", red changing slowest."""
    colors = []
    for red in LEVELS:
        for green in LEVELS:
            for blue in LEVELS:
                colors.append("#%02x%02x%02x" % (red, green, blue))
    return colors


def linear(channel):
    """An sRGB channel (0-255) as linear light (0..1)."""
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def oklab(color):
    """A "#rrggbb" color as [L, a, b] in OKLab (Bjorn Ottosson, 2020), where equal distances look
    about equally different."""
    red = linear(int(color[1:3], 16))
    green = linear(int(color[3:5], 16))
    blue = linear(int(color[5:7], 16))
    long_cone = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1.0 / 3.0)
    middle_cone = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1.0 / 3.0)
    short_cone = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1.0 / 3.0)
    return [0.2104542553 * long_cone + 0.7936177850 * middle_cone - 0.0040720468 * short_cone,
            1.9779984951 * long_cone - 2.4285922050 * middle_cone + 0.4505937099 * short_cone,
            0.0259040371 * long_cone + 0.7827717662 * middle_cone - 0.8086757660 * short_cone]


def distance(first, second):
    """How different two OKLab colors look: the straight-line distance between them."""
    light = first[0] - second[0]
    green_red = first[1] - second[1]
    blue_yellow = first[2] - second[2]
    return math.sqrt(light * light + green_red * green_red + blue_yellow * blue_yellow)


def discovery_order(colors):
    """Each color's place in farthest-point order: the darkest color first, then always the color
    farthest from every color placed so far (the earlier one on a tie). The first places spread over
    the whole space, and as the last tie-break of every ranking it makes each order total."""
    count = len(colors)
    labs = []
    for color in colors:
        labs.append(oklab(color))
    places = [0] * count
    placed = [False] * count
    nearest = [0.0] * count
    current = 0
    for index in range(count):
        nearest[index] = 1e9
        if labs[index][0] < labs[current][0]:
            current = index
    for place in range(count):
        placed[current] = True
        places[current] = place
        farthest = -1
        for index in range(count):
            if not placed[index]:
                gap = distance(labs[index], labs[current])
                if gap < nearest[index]:
                    nearest[index] = gap
                if farthest < 0 or nearest[index] > nearest[farthest]:
                    farthest = index
        current = farthest
    return places


def order_by(colors, keys):
    """`colors` best first: by the first list of scores in `keys` (higher first), ties by the next
    list, and so on, then by discovery order."""
    places = discovery_order(colors)
    rows = []
    for index in range(len(colors)):
        row = []
        for key in keys:
            row.append(-key[index])
        row.append(places[index])
        row.append(index)
        rows.append(row)
    rows.sort()
    ordered = []
    for row in rows:
        ordered.append(colors[row[-1]])
    return ordered


def normalize(scores):
    """Scores scaled to 0..1, lowest to highest. A flat list, which can't order anything, is all 0."""
    if len(scores) == 0:
        return []
    low = scores[0]
    high = scores[0]
    for value in scores:
        if value < low:
            low = value
        if value > high:
            high = value
    scaled = []
    for value in scores:
        if high - low < 1e-9:
            scaled.append(0.0)
        else:
            scaled.append((value - low) / (high - low))
    return scaled


def tally(colors, voats):
    """[upvoats, downvoats] for each color. Voats on colors outside the set are left out."""
    where = {}
    for index in range(len(colors)):
        where[colors[index]] = index
    counts = []
    for color in colors:
        counts.append([0, 0])
    for voat in voats:
        if voat["color"] in where:
            if voat["voat"] > 0:
                counts[where[voat["color"]]][0] += 1
            else:
                counts[where[voat["color"]]][1] += 1
    return counts


def net(colors, voats, up, down):
    """Net voats: upvoats x `up` minus downvoats x `down`."""
    scores = []
    for count in tally(colors, voats):
        scores.append(up * count[0] - down * count[1])
    return scores


def wilson(colors, voats, z):
    """Wilson score: the lower bound of a color's share of upvoats at confidence `z` (1.96 is 95 %),
    0 for a color with no voats. Five upvoats out of five beat one out of one."""
    scores = []
    for count in tally(colors, voats):
        total = count[0] + count[1]
        if total == 0:
            scores.append(0.0)
        else:
            share = count[0] / total
            spread = z * z / total
            root = math.sqrt(share * (1.0 - share) / total + spread / (4.0 * total))
            scores.append((share + spread / 2.0 - z * root) / (1.0 + spread))
    return scores


def similar(colors, voats, reach, up, down):
    """Color similarity: every voat pulls on the colors near it in OKLab by (1 - (d / reach)^2)^2,
    which is exactly 0 at `reach` and beyond; an upvoat pulls up by `up`, a downvoat down by `down`."""
    pulls = []
    for voat in voats:
        weight = up
        if voat["voat"] < 0:
            weight = -down
        pulls.append([oklab(voat["color"]), weight])
    scores = []
    for color in colors:
        lab = oklab(color)
        total = 0.0
        for pull in pulls:
            gap = distance(lab, pull[0]) / reach
            if gap < 1.0:
                strength = 1.0 - gap * gap
                total = total + pull[1] * strength * strength
        scores.append(total)
    return scores


def explore(colors, voats, far):
    """Exploration: a color's distance to the nearest voated color, capped at `far`, so new ground
    comes first. With no voats every color scores `far`: a full tie."""
    seen = {}
    voated = []
    for voat in voats:
        if voat["color"] not in seen:
            seen[voat["color"]] = True
            voated.append(oklab(voat["color"]))
    scores = []
    for color in colors:
        lab = oklab(color)
        nearest = far
        for other in voated:
            gap = distance(lab, other)
            if gap < nearest:
                nearest = gap
        scores.append(nearest)
    return scores


def blend(lists, weights):
    """One score per color: the weighted sum of `lists`, each scaled to 0..1 first, so a list that
    can't order anything adds nothing."""
    total = []
    for value in lists[0]:
        total.append(0.0)
    for which in range(len(lists)):
        scaled = normalize(lists[which])
        for index in range(len(scaled)):
            total[index] = total[index] + weights[which] * scaled[index]
    return total


def buckets(scores, tie):
    """Scores scaled to 0..1 and cut into steps of `tie`; colors in one step are tied."""
    steps = []
    for value in normalize(scores):
        steps.append(math.floor(value / tie))
    return steps


def cost(name, color_count, voat_count):
    """Steps scorer `name` takes on the set, which the mixer's work budget counts: one per color and
    voat for net and wilson, one per color-and-voat pair for similar and explore."""
    if name == "similar" or name == "explore":
        return color_count * max(voat_count, 1)
    return color_count + voat_count


def mixer_lead(voats, chain_length, streak):
    """Which scorer of the chain leads: every `streak` downvoats in a row pass the lead to the next
    one (after the last comes the first again), and an upvoat resets the run. It is read from the
    voat log alone, so taking a voat back takes its effect back too."""
    lead = 0
    run = 0
    for voat in voats:
        if voat["voat"] < 0:
            run = run + 1
            if run >= streak:
                lead = (lead + 1) % chain_length
                run = 0
        else:
            run = 0
    return lead


def mixer(colors, voats, chain, tie, streak, budget, score):
    """The mixer: `colors` best first by the chain of scorers, starting at the lead (mixer_lead).
    When a scorer stalls it hands on: colors it leaves tied (within `tie`) go to the next scorer,
    and a scorer that needs more than `budget` steps (cost) is skipped. `score(name, colors, voats)`
    runs one scorer by name."""
    lead = mixer_lead(voats, len(chain), streak)
    keys = []
    for step in range(len(chain)):
        name = chain[(lead + step) % len(chain)]
        if cost(name, len(colors), len(voats)) <= budget:
            keys.append(buckets(score(name, colors, voats), tie))
    return order_by(colors, keys)


def run_scorer(name, colors, voats, weights):
    """Scorer `name` with a weights record as read from weights/<name>.toml -> one float per color.
    For tests and tools; a generated ranker has its own score() with the weights as constants."""
    if name == "net":
        return net(colors, voats, weights["up"], weights["down"])
    if name == "wilson":
        return wilson(colors, voats, weights["z"])
    if name == "similar":
        return similar(colors, voats, weights["reach"], weights["up"], weights["down"])
    if name == "explore":
        return explore(colors, voats, weights["far"])
    raise ValueError("unknown scorer: " + name)

# ==== stamp v1 | author=kjFriday | hmac-sha256=e9c3128032dbe6cf45a119aab3839284eb088677964107b57b85942464d40737 ====
