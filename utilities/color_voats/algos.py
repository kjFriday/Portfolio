# ==== Generic Company Inc. portfolio ====================================
# Project: color_voats | File: algos.py
# About: Color Voats algos: the scorers and aggregators that factory.py builds rankers from.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
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

Who calls it
  factory.py reads SCORERS and AGGREGATORS to check presets and copies the functions in its
  COPY_ORDER into rankers/ranker_<preset>.py with inspect.getsource. voats_core.py uses palette(),
  oklab() for color names and the generated rankers for the For you order. The tests call the
  functions directly, and run_scorer() lets them run a scorer from a weights record.

Main flow of one ranking (what a generated rank() does)
  1. Each scorer the preset uses turns the voat log into one score per color.
  2. The aggregator combines them: blend sums the 0..1 scaled lists with the preset's weights;
     mixer turns each list into tie buckets and stacks them as sort keys from the lead scorer on.
  3. order_by() sorts the colors by those keys, best first, and breaks what is still tied by
     discovery_order(), so no two colors ever compare equal.

Start reading at mixer() and order_by(), then the scorers they call.
"""

import math

# LEVELS: the six channel values of the 6x6x6 "web-safe" cube, 0x00 to 0xff in steps of 0x33 (51).
# SCORERS and AGGREGATORS: the algo names a preset may use; factory.read_preset checks against them.
LEVELS = (0, 51, 102, 153, 204, 255)
SCORERS = ("net", "wilson", "similar", "explore")
AGGREGATORS = ("blend", "mixer")

# Comments above each function sit at column 0 on purpose: inspect.getsource copies only the def
# line down to the end of its body, so these notes stay out of the generated rankers. A comment
# or docstring edit inside a function makes every ranker stale (run python factory.py after it).


def palette():
    """The 216 colors of the 6x6x6 cube as "#rrggbb", red changing slowest."""
    colors = []
    for red in LEVELS:
        for green in LEVELS:
            for blue in LEVELS:
                colors.append("#%02x%02x%02x" % (red, green, blue))
    return colors


# sRGB stores channel values gamma-encoded so that the 256 steps look evenly spaced to the eye.
# Color math needs the light itself, so this undoes the sRGB transfer function (IEC 61966-2-1):
# a short straight segment near black (value / 12.92 up to 0.04045, which avoids an infinite slope
# at 0) and a 2.4 power curve above it, offset by 0.055 so the two pieces meet smoothly.
def linear(channel):
    """An sRGB channel (0-255) as linear light (0..1)."""
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


# OKLab is a perceptual color space: L is lightness (0 black to 1 white), a runs green (-) to red
# (+) and b blue (-) to yellow (+). Straight-line distance in it tracks how different two colors
# look far better than distance in RGB, which is why every scorer that compares colors uses it.
# Steps:
#   1. Decode the three hex channels and make them linear light (linear()).
#   2. Multiply by the first matrix to get the responses of the long, middle and short cones
#      (an LMS space fitted to human vision).
#   3. Take the cube root of each: perceived intensity grows roughly as the cube root of light.
#   4. Multiply by the second matrix to get L, a and b.
# Both matrices are Ottosson's published sRGB constants; the tests check white, black and the
# three primaries against his reference values to four places.
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


# Euclidean distance in OKLab (often called delta E OK). Neighbours in the 216-color cube are
# usually about 0.03 apart; black to white is 1.0.
def distance(first, second):
    """How different two OKLab colors look: the straight-line distance between them."""
    light = first[0] - second[0]
    green_red = first[1] - second[1]
    blue_yellow = first[2] - second[2]
    return math.sqrt(light * light + green_red * green_red + blue_yellow * blue_yellow)


# Farthest-point traversal (the greedy order behind Gonzalez's k-center method): each new pick is
# the color whose nearest already-placed color is farthest away, so any prefix of the order is a
# well spread sample of the whole set. It depends only on the colors, never on the voats, which
# makes it a fixed final tie-break.
# Steps:
#   1. Convert every color to OKLab once.
#   2. Start every color's nearest-placed distance at 1e9 (a stand-in for infinity, far above any
#      OKLab distance between real colors) and pick the darkest color (lowest L, earliest on a tie).
#   3. Repeat once per color: place the current pick, lower each unplaced color's nearest distance
#      if the new pick is closer, and choose the unplaced color with the largest nearest distance
#      (earliest index on a tie, since only a strictly larger value wins).
# `nearest` is updated incrementally, so the whole order costs O(n^2) distance calls, not O(n^3).
# Returns places, not colors: places[i] is the 0-based rank of colors[i].
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


# A lexicographic sort built from plain lists, so it ports to any language.
# Steps:
#   1. For each color build a row: every key's score negated (Python sorts ascending, so the
#      highest score comes first), then its discovery place, then its index.
#   2. Sort the rows; lists compare element by element, which is exactly "by the first key, ties
#      by the next".
#   3. Read each row's last element, the index, back into a color.
# Discovery places are all different, so the index never decides anything: it is only there to
# find the color again. `keys` may be empty, which gives pure discovery order.
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


# Min-max scaling: (value - low) / (high - low). A list whose range is under 1e-9 counts as flat
# (floating-point noise, not a real difference) and becomes all zeros instead of dividing by
# almost nothing, so a scorer with nothing to say adds nothing to a blend and ties everything in
# the mixer.
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


# Counts the voat log per color through a color -> index map, so each voat costs one lookup.
# Any voat value above 0 counts as up and anything else as down. Shared by net() and wilson().
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


# The plainest score: a weighted difference of the counts from tally(). It ignores how many voats
# there are in total, so one upvoat and a hundred upvoats with 99 downvoats score the same; wilson()
# is the scorer that weighs certainty.
def net(colors, voats, up, down):
    """Net voats: upvoats x `up` minus downvoats x `down`."""
    scores = []
    for count in tally(colors, voats):
        scores.append(up * count[0] - down * count[1])
    return scores


# The Wilson score interval (E. B. Wilson, 1927) is a confidence interval for a proportion that
# behaves well with few samples. Ranking by its lower bound asks "what upvoat share does this color
# have at least, with confidence z?", so a color needs many voats before a high share counts.
# With p = upvoats / n and n = all voats on the color:
#   lower = (p + z^2/(2n) - z * sqrt(p(1-p)/n + z^2/(4n^2))) / (1 + z^2/n)
# In the code `share` is p, `spread` is z^2/n and `root` is the square root term. One upvoat at
# z = 1.96 scores about 0.2065 (the self-test and the tests pin that value).
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


# A kernel score: each voat spreads its weight over nearby colors and a color sums what reaches it.
# The kernel (1 - (d/reach)^2)^2 is the biweight (Tukey) shape: 1 at the voated color itself,
# falling smoothly to exactly 0 at `reach` with a flat slope there, so there is no sudden step at
# the edge and colors beyond reach are untouched (the tests check exactly 0 outside).
# Steps:
#   1. Turn each voat into a pull: its color in OKLab and +up or -down.
#   2. For each color, add pull * kernel(distance) over every pull closer than reach.
# A color voated twice pulls twice; an upvoat and a downvoat on one color cancel when up == down.
# Cost is one distance per color-and-voat pair, which cost() charges for.
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


# Rewards distance from everything already voated, up or down alike, so the feed reaches into
# parts of the color space the user has not judged yet.
# Steps:
#   1. Collect the distinct voated colors in OKLab (`seen` skips repeats; the direction of a voat
#      does not matter here).
#   2. For each color, the smallest distance to any of them, starting from `far`, so the score
#      never exceeds far and everything at least far away ties.
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


# A weighted sum of min-max scaled score lists. Scaling first puts scorers with different units
# (voat counts, shares, distances) on one 0..1 footing, so the preset's weights mean "how much
# this scorer counts". `lists` and `weights` are parallel and every list has one score per color;
# `lists` must not be empty (the preset checks guarantee at least one scorer).
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


# Quantizes a score list so the mixer can treat near-equal scores as equal: scale to 0..1, then
# floor(value / tie). With tie = 0.001, scaled scores below 1 fill steps 0 to 999 and the highest
# score (exactly 1 after scaling) gets step 1000 to itself and any colors tied with it.
# Known limitation: the steps have fixed edges, so two scores closer than `tie` that straddle an
# edge land in different steps and are not tied.
def buckets(scores, tie):
    """Scores scaled to 0..1 and cut into steps of `tie`; colors in one step are tied."""
    steps = []
    for value in normalize(scores):
        steps.append(math.floor(value / tie))
    return steps


# A deterministic work estimate instead of a timer, so whether a scorer runs never depends on the
# machine's speed. similar and explore compare every color with every voat (or distinct voated
# color), so they cost colors x voats; max(voat_count, 1) keeps an empty log from costing 0.
# net and wilson walk the colors and the log once each, so they cost colors + voats.
def cost(name, color_count, voat_count):
    """Steps scorer `name` takes on the set, which the mixer's work budget counts: one per color and
    voat for net and wilson, one per color-and-voat pair for similar and explore."""
    if name == "similar" or name == "explore":
        return color_count * max(voat_count, 1)
    return color_count + voat_count


# Replays the voat log from the start with a counter of downvoats in a row. Each time the run
# reaches `streak` the lead moves one place down the chain (modulo its length, so it wraps) and the
# run starts again from 0; any upvoat resets the run. Keeping no state between calls is what makes
# taking a voat back undo its effect on the lead.
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


# The mixer aggregator: a cascade of scorers rather than a weighted sum.
# Steps:
#   1. Find the lead scorer from the voat log (mixer_lead).
#   2. Walk the chain once, starting at the lead and wrapping around: skip a scorer whose cost()
#      is over `budget`, otherwise score the colors and cut the scores into tie steps (buckets).
#   3. Sort by those step lists in chain order (order_by): the lead decides first, the next
#      scorer only orders what the lead left in one step, and so on; discovery order settles the
#      rest. When every scorer is skipped or flat, the result is pure discovery order.
# `score` is passed in rather than called by name so the same code runs in algos (with run_scorer
# and a weights record) and in a generated ranker (with its own score() and constant weights).
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


# Not copied into rankers. The weight keys and their order here mirror factory.WEIGHT_KEYS and the
# score() that factory.score_function writes; a new scorer needs all three updated together.
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=811bf1a3c7753d38bb86ed3b61dd784e7fcc24ac56fe2683710c6248d1786c2e ====
