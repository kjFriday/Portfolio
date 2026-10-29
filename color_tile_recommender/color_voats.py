# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: color_tile_recommender/color_voats.py
# About: Generic Company Color Voats: color tiles ranked by your upvoats and downvoats, and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Generic Company Color Voats: color tiles ranked by your upvoats and downvoats, and nothing else.

The window is one board of the 216 colors of the 6x6x6 cube, best first, with no text in it.
Left-click a tile to upvoat it, right-click to downvoat it, Ctrl+Z to take the last voat back.
The order comes from a ranker that factory.py generates from a preset (presets/) and the weights of
the algos it uses (weights/); the window regenerates it first when it is missing or out of date.

Records
  Voat     {"color": "#rrggbb", "voat": 1 | -1}   a voat log is a list of these, oldest first
  Result   {"ok": bool, "error": str, "value": any}

Usage
  python color_voats.py                   open the window (preset "mixer")
  python color_voats.py --preset NAME     rank with presets/NAME
  python color_voats.py --voats FILE      keep the voats in FILE instead of the usual place
  python color_voats.py --selftest        run the built-in checks and exit
  python color_voats.py --version
  python color_voats.py --smoke FILE      open the window, voat in memory, write a JSON report, close
"""

import importlib.util
import json
import os
import sys
import tempfile

import algos
import factory

__version__ = "0.1.0"
APP_NAME = "Generic Company Color Voats"
APP_ID = "GenericCompany.ColorVoats"
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FILE = os.path.join(HERE, "icon", "app.ico")

DEFAULT_PRESET = "mixer"
COLUMNS = 18
TILE = 36
GAP = 4
BACKGROUND = "#808080"  # neutral grey, not one of the 216 colors

# =================================================================================================
# CORE: the voat log and the board's geometry. No GUI here.
# =================================================================================================


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def data_folder():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def voats_path():
    return os.path.join(data_folder(), "voats.json")


def is_color(text):
    if not isinstance(text, str) or len(text) != 7 or text[0] != "#":
        return False
    for character in text[1:]:
        if character not in "0123456789abcdef":
            return False
    return True


def load_voats(path):
    """The voat log in `path`; a missing or broken file is an empty log, and bad entries are dropped."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    clean = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("color"), str):
            continue
        color = entry["color"].lower()
        voat = entry.get("voat")
        if is_color(color) and type(voat) is int and (voat == 1 or voat == -1):
            clean.append({"color": color, "voat": voat})
    return clean


def save_voats(path, voats):
    """Write the voat log through a temporary file, so a failed write never leaves half a log."""
    folder = os.path.dirname(path)
    try:
        if folder != "" and not os.path.isdir(folder):
            os.makedirs(folder)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(voats, handle, indent=1)
        os.replace(temporary, path)
    except OSError as error:
        return fail(str(error))
    return ok_result(path)


def add_voat(voats, color, voat):
    result = list(voats)
    result.append({"color": color, "voat": voat})
    return result


def undo_voat(voats):
    """The log without its last voat; an empty log stays empty."""
    return list(voats[:-1])


def board_size(count, columns, tile, gap):
    """[width, height] of a board of `count` tiles in rows of `columns`."""
    rows = (count + columns - 1) // columns
    return [columns * tile + (columns + 1) * gap, rows * tile + (rows + 1) * gap]


def tile_box(index, columns, tile, gap):
    """[left, top, right, bottom] of tile `index`, filled row by row from the top left."""
    left = gap + (index % columns) * (tile + gap)
    top = gap + (index // columns) * (tile + gap)
    return [left, top, left + tile, top + tile]


def tile_at(x, y, count, columns, tile, gap):
    """Index of the tile under (x, y); -1 for a gap or a point off the board."""
    x = int(x) - gap
    y = int(y) - gap
    if x < 0 or y < 0:
        return -1
    column = x // (tile + gap)
    row = y // (tile + gap)
    if column >= columns or x - column * (tile + gap) >= tile or y - row * (tile + gap) >= tile:
        return -1
    index = row * columns + column
    if index >= count:
        return -1
    return index


def load_ranker(name):
    """Generate rankers/ranker_<name>.py when it is missing or out of date, then load it -> Result module."""
    made = factory.ensure(HERE, name)
    if not made["ok"]:
        return made
    path = made["value"]["path"]
    try:
        spec = importlib.util.spec_from_file_location("ranker_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:
        return fail(path + ": " + str(error))
    return ok_result(module)

# =================================================================================================
# SELF-TEST: a quick pass over the core. `python color_voats.py --selftest` (the full suites are test_*.py)
# =================================================================================================


def check(condition, message, failures):
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    failures = []
    colors = algos.palette()
    print("algos")
    check(len(colors) == 216 and len(set(colors)) == 216, "216 different colors", failures)
    white = algos.oklab("#ffffff")
    check(abs(white[0] - 1.0) < 1e-6 and abs(white[1]) < 1e-6 and abs(white[2]) < 1e-6, "white is L 1, a 0, b 0", failures)
    one_up = algos.wilson(["#ff0000"], [{"color": "#ff0000", "voat": 1}], 1.96)[0]
    check(abs(one_up - 0.2065) < 0.001, "Wilson score of one upvoat", failures)
    three_down = [{"color": "#000000", "voat": -1}] * 3
    check(algos.mixer_lead(three_down, 4, 3) == 1, "three downvoats in a row pass the lead on", failures)

    print("factory")
    names = factory.preset_names(HERE)
    check(DEFAULT_PRESET in names, "the default preset is there", failures)
    problems = factory.check(HERE, names)
    check(len(problems) == 0, "every ranker is up to date " + "; ".join(problems), failures)
    loaded = load_ranker(DEFAULT_PRESET)
    check(loaded["ok"], "the default ranker loads " + loaded["error"], failures)
    if loaded["ok"]:
        board = loaded["value"].rank([{"color": colors[200], "voat": 1}], colors)
        check(sorted(board) == sorted(colors), "the board holds every color once", failures)
        check(board[0] == colors[200], "an upvoated color goes first", failures)

    print("voats and board")
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "voats.json")
    voats = add_voat(add_voat([], "#ff0000", 1), "#00ff00", -1)
    check(save_voats(path, voats)["ok"] and load_voats(path) == voats, "voat log round trip", failures)
    check(undo_voat(voats) == voats[:1] and undo_voat([]) == [], "undo takes the last voat back", failures)
    os.remove(path)
    os.rmdir(folder)
    box = tile_box(19, COLUMNS, TILE, GAP)
    check(tile_at((box[0] + box[2]) // 2, (box[1] + box[3]) // 2, 216, COLUMNS, TILE, GAP) == 19, "a tile's centre", failures)
    check(tile_at(box[0] - 1, box[1], 216, COLUMNS, TILE, GAP) == -1, "a gap is no tile", failures)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1

# =================================================================================================
# GUI: tkinter. One canvas of colored rectangles; everything else is the core above.
# =================================================================================================


def windows_identity():
    """Own taskbar button (not Python's) and crisp tiles on scaled displays. Windows only."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def set_icon(window):
    """The pixel icon on the window -> True when it was set."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


def run_gui(ranker, voats_file, smoke_path):
    import tkinter as tk

    windows_identity()
    colors = algos.palette()
    state = {"voats": [], "board": []}
    if smoke_path == "":
        state["voats"] = load_voats(voats_file)

    window = tk.Tk()
    window.title("Generic Company Inc. — Color Voats " + __version__)
    window.configure(background=BACKGROUND)
    window.resizable(False, False)
    icon_set = set_icon(window)
    scale = window.winfo_fpixels("1i") / 96.0
    tile = max(12, int(round(TILE * scale)))
    gap = max(2, int(round(GAP * scale)))
    size = board_size(len(colors), COLUMNS, tile, gap)
    canvas = tk.Canvas(window, width=size[0], height=size[1], background=BACKGROUND,
                       highlightthickness=0, borderwidth=0, cursor="hand2")
    canvas.pack()

    def draw():
        state["board"] = ranker.rank(state["voats"], colors)
        canvas.delete("all")
        for index in range(len(state["board"])):
            box = tile_box(index, COLUMNS, tile, gap)
            canvas.create_rectangle(box[0], box[1], box[2], box[3], fill=state["board"][index], outline="")

    def keep():
        if smoke_path != "":
            return
        saved = save_voats(voats_file, state["voats"])
        if not saved["ok"]:
            print("could not save the voats: " + saved["error"], file=sys.stderr)

    def voat(event, value):
        index = tile_at(event.x, event.y, len(state["board"]), COLUMNS, tile, gap)
        if index < 0:
            return
        state["voats"] = add_voat(state["voats"], state["board"][index], value)
        keep()
        draw()

    def upvoat(event):
        voat(event, 1)

    def downvoat(event):
        voat(event, -1)

    def undo(event):
        if len(state["voats"]) > 0:
            state["voats"] = undo_voat(state["voats"])
            keep()
            draw()

    canvas.bind("<Button-1>", upvoat)
    canvas.bind("<Button-3>", downvoat)
    window.bind("<Control-z>", undo)
    window.bind("<Control-Z>", undo)
    if sys.platform == "darwin":  # Tk 8.6 on macOS reports the right button as 2
        canvas.bind("<Button-2>", downvoat)
        window.bind("<Command-z>", undo)
    draw()

    if smoke_path != "":
        def centre(index):
            box = tile_box(index, COLUMNS, tile, gap)
            return [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2]

        def write_smoke_report():
            window.update_idletasks()
            before = list(state["board"])
            picked = before[-1]
            point = centre(len(before) - 1)
            canvas.event_generate("<Button-1>", x=point[0], y=point[1])
            after_upvoat = list(state["board"])
            point = centre(0)
            canvas.event_generate("<Button-3>", x=point[0], y=point[1])
            downvoated = len(state["voats"]) == 2 and state["voats"][1]["voat"] == -1
            undo(None)
            report = {"app_id": APP_ID, "version": __version__, "title": window.title(), "icon_set": icon_set,
                      "preset": ranker.PRESET, "menu": str(window.cget("menu")), "widgets": [], "tiles": 0,
                      "text_items": 0, "other_items": 0, "board_changed": after_upvoat != before,
                      "upvoated_now_at": after_upvoat.index(picked), "downvoat_counted": downvoated,
                      "undo_restored": len(state["voats"]) == 1 and state["board"] == after_upvoat}
            for child in window.winfo_children():
                report["widgets"].append(child.winfo_class())
            for item in canvas.find_all():
                kind = canvas.type(item)
                if kind == "rectangle":
                    report["tiles"] = report["tiles"] + 1
                elif kind == "text":
                    report["text_items"] = report["text_items"] + 1
                else:
                    report["other_items"] = report["other_items"] + 1
            with open(smoke_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
            window.destroy()

        window.after(800, write_smoke_report)

    window.mainloop()
    return 0


def option_value(arguments, name):
    """The value after `name` in the argument list, "" when absent, None when the value is missing."""
    index = 0
    while index < len(arguments):
        if arguments[index] == name:
            if index + 1 < len(arguments):
                return arguments[index + 1]
            return None
        index = index + 1
    return ""


def main(arguments):
    if "--version" in arguments:
        print(APP_NAME + " " + __version__)
        return 0
    if "--selftest" in arguments:
        return selftest()
    preset = option_value(arguments, "--preset")
    voats_file = option_value(arguments, "--voats")
    smoke_path = option_value(arguments, "--smoke")
    if preset is None or voats_file is None or smoke_path is None:
        print("--preset needs a name, --voats and --smoke a file")
        return 2
    if preset == "":
        preset = DEFAULT_PRESET
    if voats_file == "":
        voats_file = voats_path()
    loaded = load_ranker(preset)
    if not loaded["ok"]:
        print(loaded["error"], file=sys.stderr)
        return 1
    return run_gui(loaded["value"], voats_file, smoke_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=4abf7ec3dda58766f0048a760615420df3bc406af0711a3540c5ad4792769015 ====
