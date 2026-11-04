# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: swatch.py
# About: QR Palette colors: the 216-color cube, color names and families, contrast against white...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""QR Palette colors: the 216-color cube, names and families, contrast on white, and ranking.

Colors are lowercase "#rrggbb" strings, as in Color Voats. The cube and OKLab come from Color Voats'
algos.py (copied unchanged into algos.py) and the names from its color_voats.py. Ranking reads the
presets and weights in presets/ and weights/ (plain JSON) through ranking.py. The limits used here
(MIN_CONTRAST, NEAR, RANKING_ROOT) are set from settings.json at start (app_settings.py), and
FAMILY_WORDS from planner.json (ecp.configure_planner).

What it is for: every place that shows, checks or orders a color goes through here. The window's tabs,
making.py, batches.py, registry.py, votes.py, ecp.py and selftest.py call it; it calls algos.py for the
color math and ranking.py for the presets.

Three ideas carry the module:
  1. The cube: the 216 "web-safe" colors, each channel one of 0, 51, 102, 153, 204, 255 (six steps
     of 255 / 5 = 51), so a color's place in the cube is a three-digit number in base 6.
  2. OKLab (Bjorn Ottosson, 2020): a color space built so that straight-line distance follows how
     different two colors look. L is lightness (0 black to 1 white); a runs green (-) to red (+) and
     b blue (-) to yellow (+). Chroma, how colorful, is the length of (a, b); hue is its angle.
     Names, families and "near" all work in OKLab.
  3. WCAG 2.x contrast: relative luminance of each color in linear light, then (lighter + 0.05) /
     (darker + 0.05), from 1:1 to 21:1. A QR code needs its dark modules to stand apart from the
     white background, so only colors at MIN_CONTRAST or above are offered.

Start reading at color_name() and usable().

Records
  Result   {"ok": bool, "error": str, "value": any}
  Voat     {"color": "#rrggbb", "voat": 1 | -1}       what a ranker reads: the votes, oldest first
"""

import math
import os

import algos
import ranking

# Each entry is the upper bound (degrees, exclusive) of a hue band: below 40 is red, 40 up to 85
# orange, and so on round the circle; 320 to 360 is pink.
HUES = ((40.0, "red"), (85.0, "orange"), (125.0, "yellow"), (170.0, "green"), (225.0, "teal"),
        (285.0, "blue"), (320.0, "purple"), (360.0, "pink"))  # OKLab hue angle -> name
# every family color_name() can end in (its last word, lower case)
FAMILIES = ("red", "orange", "brown", "yellow", "olive", "green", "teal", "blue", "purple", "pink",
            "grey", "black", "white")
WHITE = "#ffffff"  # the background every code is drawn on
DEFAULT_PRESET = "mixer"  # the ranking preset used when none is chosen (presets/mixer.json)
HERE = os.path.dirname(os.path.abspath(__file__))  # the program folder

# Set from settings.json and planner.json at start (these are the defaults).
MIN_CONTRAST = 3.0  # WCAG 2.x minimum for graphics against the white background
# (3:1 is WCAG 2.1's non-text contrast level, success criterion 1.4.11)
NEAR = 0.08  # OKLab distance that still counts as "near" a color
RANKING_ROOT = HERE  # the folder that holds presets/ and weights/
# words people type for a family, mapped to the family name (planner.json family_words replaces it)
FAMILY_WORDS = {"gray": "grey", "cyan": "teal", "aqua": "teal", "turquoise": "teal", "violet": "purple",
                "lilac": "purple", "lavender": "purple", "magenta": "pink", "fuchsia": "pink", "navy": "blue",
                "azure": "blue", "maroon": "red", "crimson": "red", "scarlet": "red", "lime": "green",
                "gold": "yellow", "golden": "yellow", "tan": "brown", "beige": "brown", "khaki": "olive"}


def ok_result(value):
    """A successful Result carrying `value`."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with the short phrase `error` and no value."""
    return {"ok": False, "error": error, "value": None}


# --- The cube and OKLab (Color Voats' algos.py) ---------------------------------------------------

def palette():
    """The 216 colors of the 6x6x6 cube as "#rrggbb", red changing slowest.

    So "#000000" is index 0, "#000033" index 1 and "#ffffff" index 215 (see cube_index)."""
    return algos.palette()


def linear(channel):
    """An sRGB channel (0-255) as linear light (0..1).

    This undoes sRGB's gamma curve (IEC 61966-2-1): stored values are spaced for the eye, while light
    adds up only in linear terms, so luminance and OKLab both start here."""
    return algos.linear(channel)


def oklab(color):
    """A "#rrggbb" color as [L, a, b] in OKLab.

    L runs 0 (black) to 1 (white); a and b are roughly -0.4 to 0.4 for sRGB colors."""
    return algos.oklab(color)


def color_distance(first, second):
    """How different two OKLab colors look: the straight-line distance between them.

    Both arguments are [L, a, b] lists from oklab(), not hex strings."""
    return algos.distance(first, second)


# --- Names and families (from Color Voats' color_voats.py 0.2.0) ---------------------------------

def normalize_hex(text):
    """A color typed as #RRGGBB or rrggbb, as "#rrggbb"; "" when it is not one.

    Surrounding spaces are ignored; three-digit shorthand such as #fff is not accepted."""
    if not isinstance(text, str):
        return ""
    value = text.strip().lower()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return ""
    for character in value:
        if character not in "0123456789abcdef":
            return ""
    return "#" + value


def color_name(color):
    """A plain name for a color, such as "Dark teal" or "Light grey", from its OKLab lightness,
    chroma (how colorful) and hue.

    Steps:
      1. Below chroma 0.03 a color reads as no hue at all: name it by lightness alone, White, Light
         grey, Grey, Dark grey or Black.
      2. Otherwise take the hue angle of (a, b) in degrees, 0 to 360, and find its band in HUES.
      3. Dark orange is brown and dark yellow is olive (below L 0.6), as people name them.
      4. Add "dark" (L below 0.45), else "light" (L above 0.8 and chroma below 0.15), else "muted"
         (chroma below 0.08).
    The thresholds are Color Voats' own, tuned by eye on the 216 cube colors."""
    lab = oklab(color)
    lightness = lab[0]
    chroma = math.sqrt(lab[1] * lab[1] + lab[2] * lab[2])
    if chroma < 0.03:
        if lightness > 0.97:
            return "White"
        if lightness < 0.2:
            return "Black"
        if lightness > 0.75:
            return "Light grey"
        if lightness < 0.45:
            return "Dark grey"
        return "Grey"
    # atan2(b, a) gives -180..180 degrees; % 360 folds it onto 0..360 so the bands in HUES apply
    hue = math.degrees(math.atan2(lab[2], lab[1])) % 360.0
    name = "pink"
    for bound in HUES:
        if hue < bound[0]:
            name = bound[1]
            break
    if name == "orange" and lightness < 0.6:
        name = "brown"
    if name == "yellow" and lightness < 0.6:
        name = "olive"
    if lightness < 0.45:
        name = "dark " + name
    elif lightness > 0.8 and chroma < 0.15:
        name = "light " + name
    elif chroma < 0.08:
        name = "muted " + name
    return name.capitalize()


def family(color):
    """The family a color belongs to: the last word of its name ("Dark teal" -> "teal")."""
    words = color_name(color).lower().split(" ")
    return words[len(words) - 1]


def family_of_word(word):
    """A word someone typed ("blues", "Gray", "navy") as one of FAMILIES; "" when it is none.

    Tries the word as it is, then through FAMILY_WORDS, then both again with one trailing "s" taken
    off for plurals. ecp.py uses it to read a family out of a question."""
    value = word.strip().lower()
    if value in FAMILIES:
        return value
    if value in FAMILY_WORDS:
        return FAMILY_WORDS[value]
    if value.endswith("s"):
        single = value[:len(value) - 1]
        if single in FAMILIES:
            return single
        if single in FAMILY_WORDS:
            return FAMILY_WORDS[single]
    return ""


# --- Channels, the cube index and contrast -------------------------------------------------------

def channels(color):
    """"#rrggbb" -> [red, green, blue], each 0-255."""
    return [int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)]


def hex_of(red, green, blue):
    """Three channels (each 0-255) -> "#rrggbb" in lower case, the inverse of channels()."""
    return "#%02x%02x%02x" % (red, green, blue)


def cube_index(color):
    """The color's place in palette() (0..215), or -1 when it is not one of the 216.

    Each channel that is a multiple of 51 is one base-6 digit (value // 51, 0 to 5), red first, so
    the index is red * 36 + green * 6 + blue: the same order palette() lists them in."""
    values = channels(color)
    index = 0
    for value in values:
        if value % 51 != 0:
            return -1
        index = index * 6 + value // 51
    return index


def relative_luminance(color):
    """WCAG 2.x relative luminance, 0 (black) to 1 (white).

    The weights are the sRGB / ITU-R BT.709 luminance coefficients: green looks brightest, blue
    darkest. They apply to linear light, so each channel goes through linear() first."""
    values = channels(color)
    return 0.2126 * linear(values[0]) + 0.7152 * linear(values[1]) + 0.0722 * linear(values[2])


def contrast(first, second):
    """WCAG 2.x contrast ratio between two colors, 1 to 21.

    (lighter + 0.05) / (darker + 0.05): the 0.05 stands for ambient light on the screen, and keeps
    black from dividing by zero. The order of the arguments does not matter."""
    one = relative_luminance(first)
    two = relative_luminance(second)
    if one < two:
        one, two = two, one
    return (one + 0.05) / (two + 0.05)


def usable(color):
    """True when a QR code drawn in this color on white has enough contrast to scan (compared exactly,
    no rounding: at the default 3:1, #0099ff at 2.9998 is out)."""
    return contrast(color, WHITE) >= MIN_CONTRAST


def usable_colors():
    """The cube colors a QR code can be drawn in, in palette order (118 of the 216 at 3:1)."""
    colors = []
    for color in palette():
        if usable(color):
            colors.append(color)
    return colors


def nearest_cube(color):
    """The cube color that looks closest (OKLab distance).

    A plain scan of all 216; on a tie the earlier one in palette order wins."""
    target = oklab(color)
    best = "#000000"
    best_distance = -1.0
    for candidate in palette():
        gap = color_distance(target, oklab(candidate))
        if best_distance < 0 or gap < best_distance:
            best = candidate
            best_distance = gap
    return best


def nearest_usable(color):
    """The usable cube color that looks closest (OKLab distance), for a color too light to scan."""
    target = oklab(color)
    best = "#000000"
    best_distance = -1.0
    for candidate in usable_colors():
        gap = color_distance(target, oklab(candidate))
        if best_distance < 0 or gap < best_distance:
            best = candidate
            best_distance = gap
    return best


def is_near(first, second):
    """True when two "#rrggbb" colors are within NEAR of each other in OKLab (they look alike)."""
    return color_distance(oklab(first), oklab(second)) <= NEAR


# --- Ranking (presets and weights in JSON, read fresh each time so edits apply at once) ----------

def presets():
    """The preset names in RANKING_ROOT/presets."""
    return ranking.preset_names(RANKING_ROOT)


def rank_colors(name, voats, scans=None):
    """All 216 colors, best first, for a preset, a vote log and scans (None: they do not count)
    -> Result [hex].

    `name` is a preset in RANKING_ROOT/presets, read fresh from disk on every call. `voats` is the
    Voat list, oldest first. A preset that cannot be read, or whose weights break the arithmetic,
    fails instead of raising."""
    preset = ranking.read_preset(RANKING_ROOT, name)
    if not preset["ok"]:
        return preset
    try:
        return ok_result(ranking.rank(preset["value"], voats, palette(), scans))
    except (ArithmeticError, ValueError, TypeError) as error:
        return fail("cannot rank with preset " + name + ": " + str(error))


def rank_places(order):
    """A ranked list of colors -> {color: place}, the best being 1."""
    places = {}
    for index in range(len(order)):
        places[order[index]] = index + 1
    return places


def usable_board(order):
    """A ranked list of all 216 colors -> only the usable ones, still best first."""
    board = []
    for color in order:
        if usable(color):
            board.append(color)
    return board

# ==== stamp v1 | author=kjFriday | hmac-sha256=710fbe3b0b8c6d27650f6dc22c0c8b7068c7162755f7f305dbbcb0188dc98f5a ====
