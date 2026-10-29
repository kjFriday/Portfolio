# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/swatch.py
# About: QR Palette colors: the 216-color cube, color names and families, contrast against white...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette colors: the 216-color cube, color names and families, contrast against white, and ranking.

Colors are lowercase "#rrggbb" strings, as in Color Voats. The cube and OKLab come from Color Voats'
algos.py (copied unchanged into algos.py) and the names from its color_voats.py. Ranking reads the
presets and weights in presets/ and weights/ (plain JSON) through ranking.py. The limits used here
(MIN_CONTRAST, NEAR, RANKING_ROOT, FAMILY_WORDS) are set from settings.json at start.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Voat     {"color": "#rrggbb", "voat": 1 | -1}       what a ranker reads: the votes, oldest first
"""

import math
import os

import algos
import ranking

HUES = ((40.0, "red"), (85.0, "orange"), (125.0, "yellow"), (170.0, "green"), (225.0, "teal"),
        (285.0, "blue"), (320.0, "purple"), (360.0, "pink"))  # OKLab hue angle -> name
FAMILIES = ("red", "orange", "brown", "yellow", "olive", "green", "teal", "blue", "purple", "pink",
            "grey", "black", "white")
WHITE = "#ffffff"
DEFAULT_PRESET = "mixer"
HERE = os.path.dirname(os.path.abspath(__file__))

# Set from settings.json and planner.json at start (these are the defaults).
MIN_CONTRAST = 3.0  # WCAG 2.x minimum for graphics against the white background
NEAR = 0.08  # OKLab distance that still counts as "near" a color
RANKING_ROOT = HERE  # the folder that holds presets/ and weights/
FAMILY_WORDS = {"gray": "grey", "cyan": "teal", "aqua": "teal", "turquoise": "teal", "violet": "purple",
                "lilac": "purple", "lavender": "purple", "magenta": "pink", "fuchsia": "pink", "navy": "blue",
                "azure": "blue", "maroon": "red", "crimson": "red", "scarlet": "red", "lime": "green",
                "gold": "yellow", "golden": "yellow", "tan": "brown", "beige": "brown", "khaki": "olive"}


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


# --- The cube and OKLab (Color Voats' algos.py) ---------------------------------------------------

def palette():
    """The 216 colors of the 6x6x6 cube as "#rrggbb", red changing slowest."""
    return algos.palette()


def linear(channel):
    """An sRGB channel (0-255) as linear light (0..1)."""
    return algos.linear(channel)


def oklab(color):
    """A "#rrggbb" color as [L, a, b] in OKLab."""
    return algos.oklab(color)


def color_distance(first, second):
    """How different two OKLab colors look: the straight-line distance between them."""
    return algos.distance(first, second)


# --- Names and families (from Color Voats' color_voats.py 0.2.0) ---------------------------------

def normalize_hex(text):
    """A color typed as #RRGGBB or rrggbb, as "#rrggbb"; "" when it is not one."""
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
    chroma (how colorful) and hue."""
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
    """A word someone typed ("blues", "Gray", "navy") as one of FAMILIES; "" when it is none."""
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
    return "#%02x%02x%02x" % (red, green, blue)


def cube_index(color):
    """The color's place in palette() (0..215), or -1 when it is not one of the 216."""
    values = channels(color)
    index = 0
    for value in values:
        if value % 51 != 0:
            return -1
        index = index * 6 + value // 51
    return index


def relative_luminance(color):
    """WCAG 2.x relative luminance, 0 (black) to 1 (white)."""
    values = channels(color)
    return 0.2126 * linear(values[0]) + 0.7152 * linear(values[1]) + 0.0722 * linear(values[2])


def contrast(first, second):
    """WCAG 2.x contrast ratio between two colors, 1 to 21."""
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
    """The cube color that looks closest (OKLab distance)."""
    target = oklab(color)
    best = "#000000"
    best_distance = -1.0
    for candidate in palette():
        gap = color_distance(target, oklab(candidate))
        if best_distance < 0 or gap < best_distance:
            best = candidate
            best_distance = gap
    return best


def is_near(first, second):
    return color_distance(oklab(first), oklab(second)) <= NEAR


# --- Ranking (presets and weights in JSON, read fresh each time so edits apply at once) ----------

def presets():
    """The preset names in RANKING_ROOT/presets."""
    return ranking.preset_names(RANKING_ROOT)


def rank_colors(name, voats):
    """All 216 colors, best first, for a preset and a vote log -> Result [hex]."""
    preset = ranking.read_preset(RANKING_ROOT, name)
    if not preset["ok"]:
        return preset
    try:
        return ok_result(ranking.rank(preset["value"], voats, palette()))
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=47879cdfe801133b08361398756439059cb4d65e813c3c44082de2cb07ae8195 ====
