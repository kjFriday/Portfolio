# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/qr_palette.py
# About: Generic Company QR Palette: QR codes in recommended colors, a registry of where each one...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Generic Company QR Palette: QR codes in recommended colors, a registry of where each one is, and ECP.

Make a QR code for a link in one of the colors that Color Voats' rankers recommend, read QR codes from
pictures, and find any code again by its link or by its color: every answer gives the color, the link
and the path of the picture file. The registry is a relational SQLite database of this program's
own. Other programs ask it through the Environment Context Protocol (ECP, see ECP.md): an MCP server
on stdin/stdout (--mcp, or --ecp, the same) with three tools. A local model is chosen first, and
inference never leaves this computer.

Everything a user may change is plain, human-readable JSON: settings.json (in the program's data
folder, written with every setting and its default on the first run), presets/ and weights/ (how
colors are ranked) and planner.json (how questions become query plans). The options below override
settings.json for one run.

Standard library only, written to port easily like QR Studio and Color Voats: plain functions and
records, explicit loops, failures as Result records, and a CORE that never touches the GUI.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Made     {"id": int, "path": str, "link": str, "color": "#rrggbb", "version": int, "level": str}
  Picture  {"reading": Reading, "format": "png" | "svg" | "other", "color": "#rrggbb", "image": Image or None}
  Shown    {"id", "link", "hex", "name", "family", "path", "exists", "ec_level", "version"}   a result row

Usage
  python qr_palette.py                       open the window
  python qr_palette.py --settings FILE       use FILE instead of settings.json in the data folder
  python qr_palette.py --db FILE             use FILE as the registry
  python qr_palette.py --mcp [--model NAME]  serve ECP's three MCP tools on stdin/stdout; NAME is the default
                                             model for queries that name none (settings.json: inference.model)
  python qr_palette.py --ecp                 the same as --mcp
  python qr_palette.py --inference URL       the local Ollama server: http on 127.0.0.1, ::1 or localhost
  python qr_palette.py --inference-timeout S seconds a model may take to plan
  python qr_palette.py --selftest            run the built-in checks and exit
  python qr_palette.py --version
  python qr_palette.py --smoke FILE          open the window on a scratch registry and default settings, use
                                             it, write a JSON report, close
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import ecp
import local_inference
import mcp_server
import qr_codec
import registry
import settings
import swatch
import textsafe

__version__ = "0.1.0"
APP_NAME = "Generic Company QR Palette"
APP_ID = "GenericCompany.QRPalette"
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FILE = os.path.join(HERE, "icon", "app.ico")
ICON_CREDIT = "Icon: drawn for this project (a pixel QR code in tile colors), AGPL-3.0 like the code."

DB_NAME = "palette.db"
FOLDER_NAME = "QR Palette"
COLOR_VOATS_ID = "GenericCompany.ColorVoats"
DEFAULT_SCALE = 8
PROTOCOL_TIMEOUT = 45.0
WINDOW_TIMEOUT = 300.0
MAX_SOCIAL_BYTES = 5 * 1024 * 1024
TILE = 30
GAP = 4
COLUMNS = 14
PREVIEW = 340


# =================================================================================================
# CORE: no GUI below this line until the GUI section.
# =================================================================================================

def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def data_folder():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", APP_ID)


def default_db_path():
    return os.path.join(data_folder(), DB_NAME)


def default_settings_path():
    return os.path.join(data_folder(), "settings.json")


def default_audit_path():
    return os.path.join(data_folder(), "audit.jsonl")


def apply_settings(values):
    """Put settings.json's values in place across the modules, and load planner.json -> [warnings]."""
    global DEFAULT_SCALE, PROTOCOL_TIMEOUT, WINDOW_TIMEOUT
    warnings = []
    colors = values["colors"]
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
    return warnings + loaded["warnings"]


def make_engine(db_path, inference_url, timeout, values, model):
    """The ECP engine for this run, from settings.json's values (and the command line's choices)."""
    engine = ecp.new_engine(db_path, inference_url, timeout, __version__)
    engine["default_model"] = model
    engine["preset"] = values["colors"]["preset"]
    engine["audit_file"] = values["audit"]["file"] or default_audit_path()
    return engine


def color_voats_path():
    """Where Color Voats keeps its posts and votes (read here, never written)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Generic Company Inc", COLOR_VOATS_ID, "social.json")


def pictures_folder():
    """The user's Pictures folder as Windows knows it (it may be moved, for example into OneDrive),
    else ~/Pictures."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Guid(ctypes.Structure):
                _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD), ("data3", wintypes.WORD),
                            ("data4", ctypes.c_ubyte * 8)]

            pictures = Guid(0x33E28130, 0x4E1E, 0x4676,
                            (ctypes.c_ubyte * 8)(0x83, 0x5A, 0x98, 0x39, 0x5C, 0x3B, 0xC3, 0xBB))
            found = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(pictures), 0, None, ctypes.byref(found)) == 0:
                path = found.value
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path:
                    return path
        except (AttributeError, OSError, ValueError):
            pass
    return os.path.join(os.path.expanduser("~"), "Pictures")


def default_qr_folder():
    return os.path.join(pictures_folder(), FOLDER_NAME)


def slug(text):
    """A short file-name part from a link: "https://shop.example.com/sale" -> "shop-example-com-sale"."""
    lowered = text.lower()
    if "://" in lowered:
        lowered = lowered[lowered.index("://") + 3:]
    parts = []
    word = ""
    for character in lowered:
        if character.isalnum() and character.isascii():
            word = word + character
        elif word != "":
            parts.append(word)
            word = ""
    if word != "":
        parts.append(word)
    if len(parts) > 0 and parts[0] == "www":
        parts = parts[1:]
    name = "-".join(parts)[:40].strip("-")
    return name or "qr-code"


def suggested_name(link, color, kind):
    return slug(link) + "-" + color[1:] + "." + kind


def with_registry(db_path, work):
    """Open the registry read-write, run work(connection), close it -> work's Result."""
    opened = registry.connect(db_path, False)
    if not opened["ok"]:
        return opened
    try:
        return work(opened["value"])
    finally:
        registry.close(opened["value"])


def make_qr(db_path, link, color, level, path, scale):
    """Draw `link` as a QR code in `color`, save it to `path` (.png or .svg), read the file back to
    prove it scans, and register it -> Result Made."""
    text = textsafe.clean(link, None).strip()
    if text == "":
        return fail("type a link or some text first")
    color = swatch.normalize_hex(color)
    if color == "":
        return fail("pick a color first")
    if not swatch.usable(color):
        return fail(color + " is too light to scan on white")
    if level not in registry.EC_LEVELS:
        return fail("unknown error-correction level")
    made = qr_codec.encode_text(text, level, 1, -1)
    if not made["ok"]:
        return made
    matrix = made["value"]
    path = registry.display_path(path)
    saved = qr_codec.save_matrix(matrix, path, scale, color)
    if not saved["ok"]:
        return saved
    picture = qr_codec.read_qr_file(path)
    if not picture["ok"] or picture["value"]["reading"]["text"] != text or picture["value"]["color"] != color:
        try:
            os.remove(path)
        except OSError:
            pass
        return fail("the saved picture did not read back the same, so it was removed")

    def register(connection):
        return registry.save_qr(connection, {"link": text, "color": color, "path": path,
                                             "format": qr_codec.file_kind(path), "ec_level": level,
                                             "version": matrix["version"], "origin": "made"})

    saved_record = with_registry(db_path, register)
    if not saved_record["ok"]:
        return saved_record
    return ok_result({"id": saved_record["value"], "path": path, "link": text, "color": color,
                      "version": matrix["version"], "level": level})


def picture_from_image(image):
    """An Image (from the window's own picture reader) -> Result Picture."""
    reading = qr_codec.decode_image(image)
    if not reading["ok"]:
        return reading
    return ok_result({"reading": reading["value"], "format": "other", "color": qr_codec.dark_color(image),
                      "image": image})


def register_picture(db_path, path, color):
    """Add a QR code picture made elsewhere (PNG or this program's SVG) to the registry, in `color`
    -> Result record id."""
    color = swatch.normalize_hex(color)
    if color == "":
        return fail("the color must be #rrggbb")
    picture = qr_codec.read_qr_file(path)
    if not picture["ok"]:
        return picture
    if picture["value"]["format"] not in registry.FORMATS:
        return fail("only PNG and SVG pictures can be registered; save it as PNG first")
    reading = picture["value"]["reading"]

    def register(connection):
        return registry.save_qr(connection, {"link": reading["text"], "color": color, "path": registry.display_path(path),
                                             "format": picture["value"]["format"], "ec_level": reading["level"],
                                             "version": reading["version"], "origin": "registered"})

    return with_registry(db_path, register)


def forget_record(db_path, number):
    def forget(connection):
        return registry.forget_qr(connection, number)

    return with_registry(db_path, forget)


def vote_color(db_path, color, voat):
    def cast(connection):
        return registry.vote(connection, color, voat)

    return with_registry(db_path, cast)


def read_json_file(path, limit):
    try:
        if os.path.getsize(path) > limit:
            return fail(path + " is too big")
        handle = open(path, "r", encoding="utf-8")
        data = json.load(handle)
        handle.close()
    except (OSError, ValueError) as error:
        return fail("cannot read " + path + ": " + str(error))
    return ok_result(data)


def import_color_voats(db_path, social_path):
    """Color Voats' votes into the registry (the newer vote wins per color) -> Result how many changed."""
    loaded = read_json_file(social_path, MAX_SOCIAL_BYTES)
    if not loaded["ok"]:
        return loaded
    data = loaded["value"]
    if not isinstance(data, dict) or not isinstance(data.get("votes"), dict):
        return fail("no votes in " + social_path)

    def bring(connection):
        return registry.import_votes(connection, data["votes"])

    return with_registry(db_path, bring)


def board(db_path, preset):
    """The usable colors best first for a preset, and the votes -> Result {"order", "votes", "places"}."""
    def read(connection):
        return ok_result({"log": registry.vote_log(connection), "votes": registry.vote_map(connection)})

    read_votes = with_registry(db_path, read)
    if not read_votes["ok"]:
        return read_votes
    ranked = swatch.rank_colors(preset, read_votes["value"]["log"])
    if not ranked["ok"]:
        return ranked
    return ok_result({"order": swatch.usable_board(ranked["value"]), "votes": read_votes["value"]["votes"],
                      "places": swatch.rank_places(ranked["value"])})


def shown_from_row(row, exists):
    return {"id": row["id"], "link": row["link"], "hex": row["hex"], "name": row["name"], "family": row["family"],
            "path": row["path"], "exists": exists, "ec_level": row["ec_level"], "version": row["version"]}


def shown_from_record(record):
    """An ECP Record as a result row. Records carry no EC level or version, so the preview is drawn at
    M, as small as the link allows."""
    return {"id": record["id"], "link": record["payload_url"], "hex": record["hex"], "name": record["color_name"],
            "family": record["color_family"], "path": record["file_path"], "exists": record["exists"],
            "ec_level": "M", "version": 1}


def search(db_path, by, value, near, limit):
    """The window's own lookup by QR code or by color (no model needed) -> Result [Shown]."""
    text = textsafe.clean(value, None).strip()
    if text == "":
        return fail("type what to look for")
    found_plan = ecp.find_plan(by, text, near, limit)
    if not found_plan["ok"]:
        return found_plan

    def read(connection):
        return ok_result(registry.all_rows(connection))

    rows = with_registry(db_path, read)
    if not rows["ok"]:
        return rows
    shown = []
    for row in registry.find_rows(rows["value"], ecp.plan_filters(found_plan["value"]), found_plan["value"]["limit"]):
        shown.append(shown_from_row(row, registry.file_state(row["path"], False)))
    return ok_result(shown)


def matches_for_text(db_path, text, path):
    """Records holding exactly this text, or registered at this file -> Result [Shown]."""
    def read(connection):
        return ok_result(registry.all_rows(connection))

    rows = with_registry(db_path, read)
    if not rows["ok"]:
        return rows
    key = ""
    if path != "":
        key = registry.path_key(path)
    shown = []
    for row in rows["value"]:
        if row["link"] == text or (key != "" and row["path_key"] == key):
            shown.append(shown_from_row(row, registry.file_state(row["path"], False)))
    return ok_result(shown)


def preview_png(link, color, level, version):
    """A small PNG of a record's code, drawn again from its link (for previews in the window)."""
    made = qr_codec.encode_text(link, level, version, -1)
    if not made["ok"]:
        made = qr_codec.encode_text(link, "M", 1, -1)
    if not made["ok"]:
        return b""
    scale = max(1, (PREVIEW - 20) // (made["value"]["size"] + 8))
    return qr_codec.matrix_to_color_png(made["value"], scale, 4, color)


def reveal_command_line(path):
    """Explorer's command line that shows a file selected (paths quoted: Explorer splits at "," and "=")."""
    return 'explorer /select,"' + path + '"'


# =================================================================================================
# SELF-TEST: a quick pass over the core. `python qr_palette.py --selftest` (the full suite is test_*.py)
# =================================================================================================

def check(condition, message, failures):
    if condition:
        print("  ok   " + message)
    else:
        print("  FAIL " + message)
        failures.append(message)


def selftest():
    failures = []
    folder = tempfile.mkdtemp(prefix="qr_palette_selftest_")
    try:
        print("colors")
        check(len(swatch.usable_colors()) == 118, "118 of the 216 colors are dark enough to scan", failures)
        check(swatch.rank_colors("mixer", [])["value"][0] == "#000000", "no votes ranks in discovery order", failures)
        check(swatch.color_name("#006666") == "Muted teal", "colors have Color Voats' names", failures)

        print("codes")
        db_path = os.path.join(folder, "palette.db")
        made = make_qr(db_path, "https://example.com/selftest", "#3366cc", "M", os.path.join(folder, "a.png"), 4)
        check(made["ok"], "a blue PNG code is made, read back and registered", failures)
        made_svg = make_qr(db_path, "https://example.com/selftest", "#006633", "Q", os.path.join(folder, "a.svg"), 4)
        check(made_svg["ok"], "a green SVG code is made, read back and registered", failures)
        check(not make_qr(db_path, "x", "#ffff00", "M", os.path.join(folder, "b.png"), 4)["ok"],
              "a color too light to scan is refused", failures)
        found = search(db_path, "color", "blue", False, 20)
        check(found["ok"] and len(found["value"]) == 1 and found["value"][0]["path"] == made["value"]["path"],
              "found again by color, with its path", failures)
        found = search(db_path, "qr_code", "https://example.com/selftest", False, 20)
        check(found["ok"] and len(found["value"]) == 2, "found again by its link", failures)
        check(vote_color(db_path, "#3366cc", 1)["value"] == 1 and board(db_path, "mixer")["value"]["order"][0] == "#3366cc",
              "a Good vote moves the color to the top", failures)

        print("ecp and mcp")
        engine = ecp.new_engine(db_path, "http://127.0.0.1:1", 1.0, __version__)
        asked = ecp.query(engine, "blue", "", ecp.new_call("selftest", {}, None))
        check(not asked["ok"] and asked["kind"] == "args_invalid", "no query before a local model is chosen", failures)
        check(not local_inference.parse_endpoint("http://example.com:11434")["ok"], "inference must be on loopback",
              failures)
        server = mcp_server.new_server(engine)
        mcp_server.handle(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-11-25"}})
        mcp_server.handle(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = mcp_server.handle(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = []
        for tool in tools["result"]["tools"]:
            names.append(tool["name"])
        check(names == ["ecp_list_models", "ecp_select_model", "ecp_query"], "ECP's MCP server lists its three tools",
              failures)
        check(option_value(["--db", "x.db"], "--db") == "x.db", "option value", failures)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print("")
    if len(failures) == 0:
        print("all checks passed")
        return 0
    print(str(len(failures)) + " check(s) failed")
    return 1


# =================================================================================================
# GUI: tkinter. Everything here only calls the CORE functions above.
# =================================================================================================

def windows_identity():
    """Own taskbar button (not Python's) and crisp text on scaled displays. Windows only."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def set_icon(window):
    """The pixel icon on the window and its dialogs -> True when it was set."""
    if not os.path.isfile(ICON_FILE):
        return False
    try:
        window.iconbitmap(default=ICON_FILE)
    except Exception:
        return False
    return True


def picture_through_tk(tk, path):
    """Any picture Tk can open (GIF, PNG, PPM) -> Result Image, by way of a temporary PPM."""
    try:
        photo = tk.PhotoImage(file=path)
    except Exception:
        return fail("cannot open this picture; save it as PNG")
    handle, temporary = tempfile.mkstemp(suffix=".ppm")
    os.close(handle)
    try:
        photo.write(temporary, format="ppm")
        return qr_codec.load_image_file(temporary)
    except Exception as error:
        return fail(str(error))
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def clipboard_picture(path):
    """Save the picture on the clipboard as a PNG -> Result path. Windows only (PowerShell)."""
    if os.name != "nt":
        return fail("pasting a picture needs Windows")
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$i = [Windows.Forms.Clipboard]::GetImage(); if ($i -eq $null) { exit 3 }; "
              "$i.Save('" + path.replace("'", "''") + "', [Drawing.Imaging.ImageFormat]::Png)")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                              text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        return fail(str(error))
    if done.returncode != 0 or not os.path.isfile(path):
        return fail("there is no picture on the clipboard")
    return ok_result(path)


def run_gui(db_path, engine, smoke_path, config, warnings):
    """The window. `config` is the Settings record (settings.json); the window saves the preset, the
    model and the picture folder into it as they change, and nothing else. Its Ask box uses the same
    ECP engine as the MCP server, so it is planned, grounded and audited the same way."""
    import base64
    import threading
    import tkinter as tk
    import webbrowser
    from tkinter import ttk, filedialog, messagebox

    windows_identity()
    opened = registry.connect(db_path, False)
    if not opened["ok"]:
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror(APP_NAME, opened["error"])
        window.destroy()
        return 1
    registry.close(opened["value"])
    if smoke_path == "":
        written = settings.write_defaults(config)
        if not written["ok"]:
            warnings.append(written["error"])
    values = config["values"]
    preset = values["colors"]["preset"]
    folder = values["pictures"]["folder"] or default_qr_folder()

    state = {"job": None, "job_label": "", "job_number": 0, "finished": [], "picked": "", "order": [], "votes": {},
             "places": {}, "make_after": None, "matrix": None, "photos": {}, "swatches": {}, "picture": None,
             "picture_path": "", "picture_source": "", "results": [], "folder": folder, "models": [],
             "engine": engine, "model_id": "", "inference": "checking",
             "remembered_model": values["inference"]["model"]}

    window = tk.Tk()
    window.title("Generic Company Inc. — QR Palette " + __version__)
    window.geometry("1100x740")
    window.minsize(940, 640)
    icon_set = set_icon(window)
    status = tk.StringVar(value="Ready")
    footer = tk.StringVar(value="")

    # --- Jobs: one slow task at a time, off the window's thread -----------------------------------
    def poll_job():
        while len(state["finished"]) > 0:
            number, done, outcome = state["finished"].pop(0)
            if number == state["job_number"] and state["job"] is not None:
                state["job"] = None
                done(outcome)
                return
        if state["job"] is not None:
            window.after(100, poll_job)

    def start_job(label, work, done):
        if state["job"] is not None:
            status.set("Busy: " + state["job_label"] + "…")
            return False
        state["job_number"] = state["job_number"] + 1
        number = state["job_number"]
        state["job_label"] = label

        def runner():
            try:
                outcome = work()
            except Exception as error:
                outcome = fail(label + " failed: " + str(error))
            state["finished"].append((number, done, outcome))

        status.set(label + "…")
        state["job"] = threading.Thread(target=runner, daemon=True)
        state["job"].start()
        window.after(100, poll_job)
        return True

    def cancel_job():
        if state["job"] is not None:
            state["job"] = None
            state["job_number"] = state["job_number"] + 1
            status.set("Cancelled " + state["job_label"].lower())

    def save_setting(section, key, value):
        if smoke_path != "":
            return
        saved = settings.save(config, [(section, key, value)])
        if not saved["ok"]:
            status.set(saved["error"])

    def refresh_footer():
        def read(connection):
            return ok_result(registry.counts(connection))

        counted = with_registry(db_path, read)
        records = 0
        if counted["ok"]:
            records = counted["value"]["records"]
        footer.set(str(records) + " QR code(s)  ·  local inference: " + state["inference"] + "  ·  registry: " +
                   db_path)

    def swatch_image(color):
        if color not in state["swatches"]:
            image = tk.PhotoImage(width=16, height=16)
            image.put(color, to=(0, 0, 16, 16))
            state["swatches"][color] = image
        return state["swatches"][color]

    def photo_from_png(png):
        if png == b"":
            return None
        return tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))

    # --- Menu -------------------------------------------------------------------------------------
    menu = tk.Menu(window)
    file_menu = tk.Menu(menu, tearoff=0)
    help_menu = tk.Menu(menu, tearoff=0)

    def import_votes():
        path = color_voats_path()
        if not os.path.isfile(path):
            path = filedialog.askopenfilename(title="Color Voats' social.json", filetypes=[("JSON", "*.json")])
            if not path:
                return
        brought = import_color_voats(db_path, path)
        if brought["ok"]:
            status.set("Imported " + str(brought["value"]) + " vote(s) from Color Voats")
            redraw_board()
        else:
            messagebox.showerror("Import votes", brought["error"])

    def show_about():
        messagebox.showinfo("About " + APP_NAME, APP_NAME + " " + __version__ + "\n\n"
                            "Makes QR codes in recommended colors, reads them from pictures, and finds any code "
                            "again by its link or its color, with the path of its picture. Other programs can ask "
                            "through the Environment Context Protocol (ECP), with a local model only.\n\n" +
                            ICON_CREDIT + "\n\nCopyright (c) 2026 kjFriday. AGPL-3.0-only.")

    def open_settings():
        if config["state"] == "missing":
            settings.write_defaults(config)
        if os.name != "nt" or not os.path.isfile(config["path"]):
            messagebox.showinfo("Settings", "The settings are in\n\n" + config["path"])
            return
        try:
            os.startfile(config["path"])
        except OSError:
            subprocess.Popen(["notepad", config["path"]])
        status.set("Settings take effect the next time QR Palette starts")

    file_menu.add_command(label="Import votes from Color Voats…", command=import_votes)
    file_menu.add_command(label="Open settings.json", command=open_settings)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=window.destroy)
    help_menu.add_command(label="About", command=show_about)
    menu.add_cascade(label="File", menu=file_menu)
    menu.add_cascade(label="Help", menu=help_menu)
    window.config(menu=menu)

    tabs = ttk.Notebook(window)
    # The two status lines are packed from the bottom first, so a tall tab can never push them out of sight.
    ttk.Label(window, textvariable=footer, anchor="w", foreground="#555555").pack(side="bottom", fill="x", padx=8,
                                                                                   pady=(0, 6))
    ttk.Label(window, textvariable=status, anchor="w").pack(side="bottom", fill="x", padx=8)
    tabs.pack(fill="both", expand=True, padx=6, pady=6)

    # --- Make tab ---------------------------------------------------------------------------------
    make_tab = ttk.Frame(tabs, padding=8)
    tabs.add(make_tab, text="Make")
    make_bar = ttk.Frame(make_tab)
    make_bar.pack(fill="x")
    ttk.Label(make_bar, text="Link").pack(side="left")
    link_text = tk.StringVar(value="")
    link_entry = ttk.Entry(make_bar, textvariable=link_text, width=56)
    link_entry.pack(side="left", padx=6)
    ttk.Label(make_bar, text="Preset").pack(side="left", padx=(12, 0))
    preset_box = ttk.Combobox(make_bar, values=swatch.presets(), width=10, state="readonly")
    preset_box.set(preset)
    preset_box.pack(side="left", padx=6)
    ttk.Label(make_bar, text="Error correction").pack(side="left", padx=(12, 0))
    level_names = {"L": "L (7%)", "M": "M (15%)", "Q": "Q (25%)", "H": "H (30%)"}
    level_box = ttk.Combobox(make_bar, values=["L (7%)", "M (15%)", "Q (25%)", "H (30%)"], width=8, state="readonly")
    level_box.set(level_names[values["pictures"]["error_correction"]])
    level_box.pack(side="left", padx=6)
    make_body = ttk.Frame(make_tab)
    make_body.pack(fill="both", expand=True, pady=(8, 0))
    tile_side = ttk.Frame(make_body)
    tile_side.pack(side="left", fill="y")
    ttk.Label(tile_side, text="Colors that scan, best first for the preset and your votes").pack(anchor="w")
    rows_needed = (len(swatch.usable_colors()) + COLUMNS - 1) // COLUMNS
    tiles = tk.Canvas(tile_side, width=COLUMNS * (TILE + GAP) + GAP, height=rows_needed * (TILE + GAP) + GAP,
                      background="#f4f4f4", highlightthickness=1, highlightbackground="#c8c8c8", cursor="hand2")
    tiles.pack(anchor="w", pady=4)
    picked_text = tk.StringVar(value="Click a color for the code.")
    ttk.Label(tile_side, textvariable=picked_text).pack(anchor="w")
    vote_bar = ttk.Frame(tile_side)
    vote_bar.pack(anchor="w", pady=4)
    good_button = ttk.Button(vote_bar, text="Good", width=10)
    bad_button = ttk.Button(vote_bar, text="Bad", width=10)
    good_button.pack(side="left")
    bad_button.pack(side="left", padx=6)
    ttk.Label(tile_side, text="One vote per color; press it again to take it back.", foreground="#555555").pack(anchor="w")
    preview_side = ttk.Frame(make_body, padding=(16, 0, 0, 0))
    preview_side.pack(side="left", fill="both", expand=True)
    preview = tk.Canvas(preview_side, width=PREVIEW + 20, height=PREVIEW + 20, background="#ffffff", highlightthickness=1,
                        highlightbackground="#c8c8c8")
    preview.pack(anchor="nw")
    make_info = tk.StringVar(value="Type a link and pick a color.")
    ttk.Label(preview_side, textvariable=make_info, wraplength=380, justify="left").pack(anchor="w", pady=4)
    save_bar = ttk.Frame(preview_side)
    save_bar.pack(anchor="w")

    def chosen_level():
        return level_box.get()[:1] or "M"

    def tile_box(index):
        column = index % COLUMNS
        row = index // COLUMNS
        left = GAP + column * (TILE + GAP)
        top = GAP + row * (TILE + GAP)
        return left, top, left + TILE, top + TILE

    def draw_tiles():
        tiles.delete("all")
        for index in range(len(state["order"])):
            color = state["order"][index]
            box = tile_box(index)
            outline = ""
            width = 0
            if color == state["picked"]:
                outline = "#111111"
                width = 3
            tiles.create_rectangle(box[0], box[1], box[2], box[3], fill=color, outline=outline, width=width)
            mark = state["votes"].get(color, 0)
            if mark != 0:
                symbol = "+"
                if mark < 0:
                    symbol = "−"
                tiles.create_text(box[2] - 6, box[1] + 7, text=symbol, fill="#ffffff", font=("Segoe UI", 9, "bold"))

    def redraw_board():
        ranked = board(db_path, preset_box.get())
        if not ranked["ok"]:
            status.set(ranked["error"])
            return
        state["order"] = ranked["value"]["order"]
        state["votes"] = ranked["value"]["votes"]
        state["places"] = ranked["value"]["places"]
        draw_tiles()
        show_picked()

    def show_picked():
        color = state["picked"]
        if color == "":
            picked_text.set("Click a color for the code.")
            return
        vote_now = {1: "  ·  you said Good", -1: "  ·  you said Bad"}.get(state["votes"].get(color, 0), "")
        picked_text.set(swatch.color_name(color) + "  " + color + "  ·  rank " + str(state["places"].get(color)) +
                        "  ·  contrast " + ("%.1f" % swatch.contrast(color, swatch.WHITE)) + ":1" + vote_now)

    def pick_tile(event):
        index = -1
        for candidate in range(len(state["order"])):
            box = tile_box(candidate)
            if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
                index = candidate
        if index < 0:
            return
        state["picked"] = state["order"][index]
        draw_tiles()
        show_picked()
        refresh_preview()

    def cast_vote(voat):
        if state["picked"] == "":
            status.set("Pick a color first")
            return
        cast = vote_color(db_path, state["picked"], voat)
        if not cast["ok"]:
            status.set(cast["error"])
            return
        status.set({1: "Good vote saved", -1: "Bad vote saved", 0: "Vote taken back"}[cast["value"]] + " for " +
                   state["picked"])
        redraw_board()

    def refresh_preview():
        state["make_after"] = None
        preview.delete("all")
        state["photos"]["preview"] = None
        state["matrix"] = None
        text = textsafe.clean(link_text.get(), None).strip()
        if text == "":
            make_info.set("Type a link and pick a color.")
            return
        made = qr_codec.encode_text(text, chosen_level(), 1, -1)
        if not made["ok"]:
            make_info.set(made["error"] + ".")
            return
        state["matrix"] = made["value"]
        color = state["picked"] or qr_codec.INK
        scale = max(1, PREVIEW // (made["value"]["size"] + 8))
        photo = photo_from_png(qr_codec.matrix_to_color_png(made["value"], scale, 4, color))
        state["photos"]["preview"] = photo
        preview.create_image((PREVIEW + 20) // 2, (PREVIEW + 20) // 2, image=photo)
        side = (made["value"]["size"] + 8) * DEFAULT_SCALE
        hint = ""
        if state["picked"] == "":
            hint = " Pick a color to save it."
        make_info.set("Version " + str(made["value"]["version"]) + ", level " + made["value"]["level"] + ". PNG will be " +
                      str(side) + " px square." + hint)

    def schedule_preview(event=None):
        if state["make_after"] is not None:
            window.after_cancel(state["make_after"])
        state["make_after"] = window.after(250, refresh_preview)

    def save_as(kind):
        text = textsafe.clean(link_text.get(), None).strip()
        if text == "" or state["picked"] == "":
            make_info.set("Type a link and pick a color first.")
            return
        try:
            os.makedirs(state["folder"], exist_ok=True)
        except OSError:
            state["folder"] = os.path.expanduser("~")
        label = {"png": "PNG picture", "svg": "SVG drawing"}[kind]
        path = filedialog.asksaveasfilename(title="Save QR code", initialdir=state["folder"],
                                            initialfile=suggested_name(text, state["picked"], kind),
                                            defaultextension="." + kind, filetypes=[(label, "*." + kind)])
        if not path:
            return
        color = state["picked"]
        level = chosen_level()

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Save QR code", outcome["error"])
                status.set("Not saved")
                return
            state["folder"] = os.path.dirname(outcome["value"]["path"])
            if os.path.normcase(state["folder"]) != os.path.normcase(default_qr_folder()):
                save_setting("pictures", "folder", state["folder"])
            status.set("Saved and registered: " + outcome["value"]["path"])
            refresh_footer()
            refresh_used()

        start_job("Saving", lambda: make_qr(db_path, text, color, level, path, DEFAULT_SCALE), done)

    def change_preset(event=None):
        save_setting("colors", "preset", preset_box.get())
        state["engine"]["preset"] = preset_box.get()
        redraw_board()

    tiles.bind("<Button-1>", pick_tile)
    link_entry.bind("<KeyRelease>", schedule_preview)
    level_box.bind("<<ComboboxSelected>>", schedule_preview)
    preset_box.bind("<<ComboboxSelected>>", change_preset)
    good_button.config(command=lambda: cast_vote(1))
    bad_button.config(command=lambda: cast_vote(-1))
    ttk.Button(save_bar, text="Save PNG…", command=lambda: save_as("png")).pack(side="left")
    ttk.Button(save_bar, text="Save SVG…", command=lambda: save_as("svg")).pack(side="left", padx=6)

    # --- Read tab ---------------------------------------------------------------------------------
    read_tab = ttk.Frame(tabs, padding=8)
    tabs.add(read_tab, text="Read")
    read_bar = ttk.Frame(read_tab)
    read_bar.pack(fill="x")
    read_body = ttk.Frame(read_tab)
    read_body.pack(fill="both", expand=True, pady=(8, 0))
    picture_canvas = tk.Canvas(read_body, width=380, height=380, background="#f4f4f4", highlightthickness=1,
                               highlightbackground="#c8c8c8")
    picture_canvas.pack(side="left", anchor="n")
    read_side = ttk.Frame(read_body, padding=(12, 0, 0, 0))
    read_side.pack(side="left", fill="both", expand=True)
    ttk.Label(read_side, text="Text in the code").pack(anchor="w")
    read_text = tk.Text(read_side, height=5, wrap="word")
    read_text.pack(fill="x")
    read_details = tk.StringVar(value="Open or paste a picture with a QR code in it.")
    ttk.Label(read_side, textvariable=read_details, wraplength=520, justify="left").pack(anchor="w", pady=4)
    detected_row = ttk.Frame(read_side)
    detected_row.pack(anchor="w")
    detected_swatch = tk.Canvas(detected_row, width=22, height=22, highlightthickness=1, highlightbackground="#c8c8c8")
    detected_swatch.pack(side="left")
    detected_text = tk.StringVar(value="")
    ttk.Label(detected_row, textvariable=detected_text).pack(side="left", padx=6)
    ttk.Label(read_side, text="In the registry").pack(anchor="w", pady=(10, 0))
    read_table = ttk.Treeview(read_side, columns=("hex", "path"), show="tree headings", height=6)
    read_table.heading("#0", text="Color")
    read_table.heading("hex", text="Hex")
    read_table.heading("path", text="Path")
    read_table.column("#0", width=150, stretch=False)
    read_table.column("hex", width=80, stretch=False)
    read_table.column("path", width=360)
    read_table.pack(fill="both", expand=True)
    read_buttons = ttk.Frame(read_side)
    read_buttons.pack(anchor="w", pady=6)

    def show_reading(outcome):
        picture_canvas.delete("all")
        detected_swatch.delete("all")
        detected_text.set("")
        read_text.delete("1.0", "end")
        for item in read_table.get_children():
            read_table.delete(item)
        state["picture"] = None
        if not outcome["ok"]:
            read_details.set(outcome["error"] + ".")
            status.set("Nothing read from " + state["picture_source"])
            return
        picture = outcome["value"]["picture"]
        state["picture"] = picture
        reading = picture["reading"]
        read_text.insert("1.0", reading["text"])
        read_details.set("Read: " + qr_codec.describe(reading) + ".")
        detected_swatch.create_rectangle(0, 0, 24, 24, fill=picture["color"], outline="")
        detected_text.set("detected ≈ " + picture["color"] + " (" + swatch.color_name(picture["color"]) + ")")
        png = preview_png(reading["text"], picture["color"], reading["level"], reading["version"])
        photo = None
        if picture["format"] != "svg" and state["picture_path"].lower().endswith((".png", ".gif")):
            try:
                photo = tk.PhotoImage(file=state["picture_path"])
                factor = 1
                while photo.width() // factor > 380 or photo.height() // factor > 380:
                    factor = factor + 1
                if factor > 1:
                    photo = photo.subsample(factor, factor)
            except Exception:
                photo = None
        if photo is None:
            photo = photo_from_png(png)
        state["photos"]["picture"] = photo
        if photo is not None:
            picture_canvas.create_image(190, 190, image=photo)
        for shown in outcome["value"]["matches"]:
            read_table.insert("", "end", iid="r" + str(shown["id"]), text=" " + shown["name"],
                              image=swatch_image(shown["hex"]), values=(shown["hex"], shown["path"]))
        found = len(outcome["value"]["matches"])
        status.set("Read a QR code from " + state["picture_source"] + "; " + str(found) + " in the registry")

    def read_path(path, source):
        state["picture_path"] = path
        state["picture_source"] = source
        image = None
        if path.lower().endswith(".gif"):
            loaded = picture_through_tk(tk, path)
            if not loaded["ok"]:
                read_details.set(loaded["error"] + ".")
                return
            image = loaded["value"]

        def work():
            if image is not None:
                picture = picture_from_image(image)
            else:
                picture = qr_codec.read_qr_file(path)
            if not picture["ok"]:
                return picture
            own_path = ""
            if source != "the clipboard":
                own_path = path
            matches = matches_for_text(db_path, picture["value"]["reading"]["text"], own_path)
            if not matches["ok"]:
                return matches
            return ok_result({"picture": picture["value"], "matches": matches["value"]})

        start_job("Reading " + source, work, show_reading)

    def open_picture():
        path = filedialog.askopenfilename(title="Open a QR code picture",
                                          filetypes=[("Pictures", "*.png *.svg *.gif *.ppm *.pgm"), ("All files", "*.*")])
        if path:
            read_path(registry.display_path(path), os.path.basename(path))

    def paste_picture():
        temporary = os.path.join(tempfile.gettempdir(), "qr_palette_clipboard.png")
        if os.path.isfile(temporary):
            os.remove(temporary)
        saved = clipboard_picture(temporary)
        if not saved["ok"]:
            read_details.set(saved["error"] + ".")
            return
        read_path(temporary, "the clipboard")

    def register_shown():
        picture = state["picture"]
        if picture is None:
            status.set("Read a picture first")
            return
        if state["picture_source"] == "the clipboard":
            messagebox.showinfo("Register", "A pasted picture has no file of its own. Save it as a PNG, then open it.")
            return
        if picture["format"] not in registry.FORMATS:
            messagebox.showinfo("Register", "Only PNG and SVG pictures can be registered. Save it as PNG first.")
            return
        ask = tk.Toplevel(window)
        ask.title("Register this picture")
        ask.transient(window)
        ttk.Label(ask, text="The color of this QR code (detected ≈ " + picture["color"] + "):",
                  padding=10).pack(anchor="w")
        value = tk.StringVar(value=picture["color"])
        ttk.Entry(ask, textvariable=value, width=12).pack(anchor="w", padx=10)

        def confirm():
            color = swatch.normalize_hex(value.get())
            if color == "":
                messagebox.showerror("Register", "Type the color as #rrggbb.", parent=ask)
                return
            ask.destroy()

            def done(outcome):
                if not outcome["ok"]:
                    messagebox.showerror("Register", outcome["error"])
                    return
                status.set("Registered " + state["picture_path"])
                refresh_footer()
                refresh_used()

            start_job("Registering", lambda: register_picture(db_path, state["picture_path"], color), done)

        ttk.Button(ask, text="Register", command=confirm).pack(anchor="e", padx=10, pady=10)

    def find_read_text():
        text = read_text.get("1.0", "end-1c").strip()
        if text != "":
            selector.set("qr_code")
            show_selector()
            find_text.set(text)
            tabs.select(find_tab)
            run_search()

    def open_read_link():
        text = read_text.get("1.0", "end-1c").strip()
        if not qr_codec.is_link(text):
            read_details.set("Only http:// and https:// links can be opened.")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + text):
            webbrowser.open(text)

    ttk.Button(read_bar, text="Open picture…", command=open_picture).pack(side="left")
    ttk.Button(read_bar, text="Paste picture", command=paste_picture).pack(side="left", padx=6)
    ttk.Label(read_bar, text="PNG, SVG (made here), GIF or PPM.").pack(side="left", padx=8)
    ttk.Button(read_buttons, text="Register this picture…", command=register_shown).pack(side="left")
    ttk.Button(read_buttons, text="Find it", command=find_read_text).pack(side="left", padx=6)
    ttk.Button(read_buttons, text="Open link", command=open_read_link).pack(side="left")

    # --- Find tab ---------------------------------------------------------------------------------
    find_tab = ttk.Frame(tabs, padding=8)
    tabs.add(find_tab, text="Find")
    selector = tk.StringVar(value="qr_code")
    selector_row = ttk.Frame(find_tab)
    selector_row.pack(fill="x")
    ttk.Label(selector_row, text="Find by").pack(side="left")
    qr_row = ttk.Frame(find_tab)
    color_row = ttk.Frame(find_tab)
    find_text = tk.StringVar(value="")
    ttk.Label(qr_row, text="Link or path").pack(side="left")
    find_entry = ttk.Entry(qr_row, textvariable=find_text, width=60)
    find_entry.pack(side="left", padx=6)
    color_text = tk.StringVar(value="")
    near_choice = tk.BooleanVar(value=False)
    ttk.Label(color_row, text="Color").pack(side="left")
    color_entry = ttk.Entry(color_row, textvariable=color_text, width=10)
    color_entry.pack(side="left", padx=6)
    ttk.Checkbutton(color_row, text="near", variable=near_choice).pack(side="left")
    ttk.Label(color_row, text="or family").pack(side="left", padx=(12, 0))
    family_box = ttk.Combobox(color_row, values=[""] + list(swatch.FAMILIES), width=9, state="readonly")
    family_box.pack(side="left", padx=6)
    used_canvas = tk.Canvas(find_tab, height=26, highlightthickness=0, cursor="hand2")
    ask_row = ttk.Frame(find_tab)
    ttk.Label(ask_row, text="Ask (local model)").pack(side="left")
    model_box = ttk.Combobox(ask_row, values=[], width=24, state="readonly")
    model_box.pack(side="left", padx=6)
    question = tk.StringVar(value="")
    question_entry = ttk.Entry(ask_row, textvariable=question, width=36)
    question_entry.pack(side="left", padx=6)
    plan_text = tk.StringVar(value="Pick a local model to ask in plain English, e.g. \"blue codes that link to the shop\".")
    results = ttk.Treeview(find_tab, columns=("hex", "link", "path", "exists"), show="tree headings", height=8)
    results.heading("#0", text="Color")
    results.heading("hex", text="Hex")
    results.heading("link", text="Link")
    results.heading("path", text="Path")
    results.heading("exists", text="File")
    results.column("#0", width=140, stretch=False)
    results.column("hex", width=74, stretch=False)
    results.column("link", width=300)
    results.column("path", width=380)
    results.column("exists", width=60, stretch=False)
    detail = ttk.Frame(find_tab)
    detail_preview = tk.Canvas(detail, width=170, height=170, background="#ffffff", highlightthickness=1,
                               highlightbackground="#c8c8c8")
    detail_preview.pack(side="left")
    detail_side = ttk.Frame(detail, padding=(10, 0, 0, 0))
    detail_side.pack(side="left", fill="both", expand=True)
    detail_text = tk.StringVar(value="Select a result to see it here.")
    ttk.Label(detail_side, textvariable=detail_text, wraplength=700, justify="left").pack(anchor="w")
    detail_buttons = ttk.Frame(detail_side)
    detail_buttons.pack(anchor="w", pady=8)

    def show_selector():
        qr_row.pack_forget()
        color_row.pack_forget()
        if selector.get() == "qr_code":
            qr_row.pack(fill="x", pady=4, after=selector_row)
        else:
            color_row.pack(fill="x", pady=4, after=selector_row)

    def show_results(shown_list, note):
        state["results"] = shown_list
        for item in results.get_children():
            results.delete(item)
        for index in range(len(shown_list)):
            shown = shown_list[index]
            exists = {True: "yes", False: "missing", None: "?"}[shown["exists"]]
            results.insert("", "end", iid=str(index), text=" " + shown["name"], image=swatch_image(shown["hex"]),
                           values=(shown["hex"], shown["link"].replace("\n", " "), shown["path"], exists))
        detail_preview.delete("all")
        detail_text.set("Select a result to see it here.")
        status.set(note)

    def run_search():
        by = selector.get()
        if by == "qr_code":
            value = find_text.get()
            near = False
        else:
            value = color_text.get().strip() or family_box.get()
            near = near_choice.get()

        def done(outcome):
            if not outcome["ok"]:
                show_results([], outcome["error"])
                return
            plan_text.set("Found by " + {"qr_code": "QR code", "color": "color"}[by] + ": " + value)
            show_results(outcome["value"], str(len(outcome["value"])) + " QR code(s) found")

        start_job("Searching", lambda: search(db_path, by, value, near, registry.MAX_LIMIT), done)

    def pick_used(event):
        for item in used_canvas.find_overlapping(event.x, event.y, event.x, event.y):
            color = used_canvas.gettags(item)
            if len(color) > 0 and color[0].startswith("#"):
                selector.set("color")
                show_selector()
                color_text.set(color[0])
                family_box.set("")
                run_search()
                return

    def refresh_used():
        def read(connection):
            return ok_result(registry.colors_in_use(connection))

        used = with_registry(db_path, read)
        used_canvas.delete("all")
        if not used["ok"]:
            return
        left = 0
        used_canvas.create_text(left, 13, text="In use:", anchor="w")
        left = 52
        for entry in used["value"][:30]:
            used_canvas.create_rectangle(left, 3, left + 20, 23, fill=entry["hex"], outline="#888888", tags=(entry["hex"],))
            left = left + 24

    def selected_shown():
        chosen = results.selection()
        if len(chosen) == 0:
            return None
        return state["results"][int(chosen[0])]

    def show_detail(event=None):
        shown = selected_shown()
        detail_preview.delete("all")
        if shown is None:
            return
        photo = photo_from_png(preview_png(shown["link"], shown["hex"], shown["ec_level"], shown["version"]))
        state["photos"]["detail"] = photo
        if photo is not None:
            factor = 1
            while photo.width() // factor > 168:
                factor = factor + 1
            if factor > 1:
                photo = photo.subsample(factor, factor)
                state["photos"]["detail"] = photo
            detail_preview.create_image(86, 86, image=photo)
        detail_text.set(shown["name"] + "  " + shown["hex"] + "\nLink: " + textsafe.clean(shown["link"], 300) +
                        "\nPath: " + shown["path"])

    def open_shown_picture():
        shown = selected_shown()
        if shown is None:
            return
        if not os.path.isfile(shown["path"]):
            status.set("The picture is not at " + shown["path"] + " any more")
            return
        try:
            os.startfile(shown["path"])
        except (AttributeError, OSError) as error:
            status.set(str(error))

    def reveal_shown():
        shown = selected_shown()
        if shown is None:
            return
        if os.name != "nt":
            status.set("Show in folder needs Windows")
            return
        try:
            subprocess.Popen(reveal_command_line(shown["path"]))
        except OSError as error:
            status.set(str(error))

    def copy_shown(key):
        shown = selected_shown()
        if shown is None:
            return
        window.clipboard_clear()
        window.clipboard_append(shown[key])
        status.set("Copied the " + key)

    def open_shown_link():
        shown = selected_shown()
        if shown is None:
            return
        if not qr_codec.is_link(shown["link"]):
            status.set("Only http:// and https:// links can be opened")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + shown["link"]):
            webbrowser.open(shown["link"].strip())

    def forget_shown():
        shown = selected_shown()
        if shown is None:
            return
        if not messagebox.askyesno("Forget record", "Remove this record from the registry? The picture file stays "
                                                    "where it is.\n\n" + shown["path"]):
            return

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Forget record", outcome["error"])
                return
            remaining = []
            for other in state["results"]:
                if other["id"] != shown["id"]:
                    remaining.append(other)
            show_results(remaining, "Record removed; the file was not touched")
            refresh_footer()
            refresh_used()

        start_job("Forgetting", lambda: forget_record(db_path, shown["id"]), done)

    def find_from_picture(paste):
        if paste:
            temporary = os.path.join(tempfile.gettempdir(), "qr_palette_clipboard.png")
            if os.path.isfile(temporary):
                os.remove(temporary)
            saved = clipboard_picture(temporary)
            if not saved["ok"]:
                status.set(saved["error"])
                return
            path = temporary
        else:
            path = filedialog.askopenfilename(title="Find a QR code by its picture",
                                              filetypes=[("Pictures", "*.png *.svg *.ppm *.pgm"), ("All files", "*.*")])
            if not path:
                return
            path = registry.display_path(path)

        def work():
            picture = qr_codec.read_qr_file(path)
            if not picture["ok"]:
                return picture
            own_path = path
            if paste:
                own_path = ""
            matches = matches_for_text(db_path, picture["value"]["reading"]["text"], own_path)
            if not matches["ok"]:
                return matches
            return ok_result({"text": picture["value"]["reading"]["text"], "matches": matches["value"]})

        def done(outcome):
            if not outcome["ok"]:
                show_results([], outcome["error"])
                return
            find_text.set(outcome["value"]["text"])
            plan_text.set("Found by the QR code in the picture: " + textsafe.clean(outcome["value"]["text"], 120))
            show_results(outcome["value"]["matches"], str(len(outcome["value"]["matches"])) + " QR code(s) hold this text")

        start_job("Reading the picture", work, done)

    client_info = {"name": APP_NAME + " window", "version": __version__}

    def refresh_models():
        def done(result):
            if not result["ok"]:
                state["inference"] = "not available"
                model_box.config(values=[])
                plan_text.set("Local inference is not available (" + result["kind"] + ": " + result["detail"] +
                              "). Finding by QR code or color still works.")
            else:
                names = []
                for model in result["value"]["models"]:
                    names.append(model["name"])
                state["models"] = result["value"]["models"]
                model_box.config(values=names)
                state["inference"] = str(len(names)) + " model(s) on Ollama"
                if not result["value"]["cloud_disabled"]:
                    state["inference"] = state["inference"] + ", cloud features on"
                remembered = state.get("remembered_model", "")
                if remembered in names and model_box.get() == "":
                    model_box.set(remembered)
                    choose_model()
                    refresh_footer()
                    return
            refresh_footer()
            status.set("Ready")

        start_job("Listing local models",
                  lambda: ecp.list_models(state["engine"], ecp.new_call("window_list_models", client_info, None)), done)

    def choose_model(event=None):
        name = model_box.get()
        if name == "":
            return

        def done(result):
            if not result["ok"]:
                state["model_id"] = ""
                plan_text.set("Cannot use " + name + " (" + result["kind"] + ": " + result["detail"] + ")")
                return
            state["model_id"] = result["value"]["model_id"]
            save_setting("inference", "model", name)
            note = ""
            for model in state["models"]:
                if model["name"] == name and model["note"] != "":
                    note = " (" + model["note"] + ")"
            plan_text.set("Selected " + name + note + ", pinned to its digest. Ask away.")
            status.set("Ready")

        start_job("Loading " + name,
                  lambda: ecp.select_model(state["engine"], name, ecp.new_call("window_select_model", client_info, None)),
                  done)

    def ask():
        text = question.get().strip()
        if text == "":
            return
        if state["model_id"] == "":
            plan_text.set("Pick a local model first.")
            return

        def done(result):
            if not result["ok"]:
                show_results([], result["kind"] + ": " + result["detail"])
                plan_text.set("Ask failed (" + result["kind"] + "): " + result["detail"])
                return
            answer = result["value"]
            shown_list = []
            for record in answer["records"]:
                shown_list.append(shown_from_record(record))
            used = answer["plan_used"]
            plan = {}
            for key in ecp.PLAN_FIELDS:
                plan[key] = used[key]
            lines = "Plan (" + used["planner"] + "): " + json.dumps(plan) + "  —  " + answer["summary"]
            if len(used["clamped"]) > 0:
                lines = lines + "\nChanged by grounding: " + "; ".join(used["clamped"])
            plan_text.set(lines + "\nAudit line " + str(answer["audit_id"]))
            show_results(shown_list, answer["summary"])

        model_id = state["model_id"]
        start_job("Asking " + model_id.split("@")[0],
                  lambda: ecp.query(state["engine"], text, model_id, ecp.new_call("window_ask", client_info, None)), done)

    radio_bar = ttk.Frame(selector_row)
    radio_bar.pack(side="left", padx=6)
    ttk.Radiobutton(radio_bar, text="QR code", variable=selector, value="qr_code", command=show_selector).pack(side="left")
    ttk.Radiobutton(radio_bar, text="Color", variable=selector, value="color", command=show_selector).pack(side="left", padx=6)
    ttk.Button(selector_row, text="Find", command=run_search).pack(side="left", padx=6)
    ttk.Button(qr_row, text="Open picture…", command=lambda: find_from_picture(False)).pack(side="left", padx=6)
    ttk.Button(qr_row, text="Paste picture", command=lambda: find_from_picture(True)).pack(side="left")
    used_canvas.pack(fill="x", pady=(2, 6))
    ask_row.pack(fill="x", pady=4)
    ttk.Button(ask_row, text="Refresh", command=refresh_models).pack(side="left")
    ttk.Button(ask_row, text="Ask", command=ask).pack(side="left", padx=6)
    ttk.Button(ask_row, text="Cancel", command=cancel_job).pack(side="left")
    ttk.Label(find_tab, textvariable=plan_text, wraplength=1040, justify="left", foreground="#333333").pack(anchor="w",
                                                                                                         pady=(0, 6))
    results.pack(fill="both", expand=True)
    detail.pack(fill="x", pady=(8, 0))
    ttk.Button(detail_buttons, text="Open picture", command=open_shown_picture).pack(side="left")
    ttk.Button(detail_buttons, text="Show in folder", command=reveal_shown).pack(side="left", padx=6)
    ttk.Button(detail_buttons, text="Copy path", command=lambda: copy_shown("path")).pack(side="left")
    ttk.Button(detail_buttons, text="Copy link", command=lambda: copy_shown("link")).pack(side="left", padx=6)
    ttk.Button(detail_buttons, text="Open link", command=open_shown_link).pack(side="left")
    ttk.Button(detail_buttons, text="Forget record", command=forget_shown).pack(side="left", padx=6)
    results.bind("<<TreeviewSelect>>", show_detail)
    find_entry.bind("<Return>", lambda event: run_search())
    color_entry.bind("<Return>", lambda event: run_search())
    def pick_family(event=None):
        color_text.set("")
        run_search()

    family_box.bind("<<ComboboxSelected>>", pick_family)
    question_entry.bind("<Return>", lambda event: ask())
    model_box.bind("<<ComboboxSelected>>", choose_model)
    used_canvas.bind("<Button-1>", pick_used)
    show_selector()

    redraw_board()
    refresh_used()
    refresh_footer()
    if smoke_path == "":
        refresh_models()
        if len(warnings) > 0:
            messagebox.showwarning("Settings", "Some settings could not be used, so their defaults are in place:\n\n" +
                                   "\n".join(warnings[:12]) + "\n\nSettings file: " + config["path"])

    if smoke_path != "":
        def write_smoke_report():
            report = {"app_id": APP_ID, "version": __version__, "title": window.title(), "icon_set": icon_set,
                      "tabs": [], "tiles": len(tiles.find_all()), "records": 0, "codec_ok": False,
                      "found_by_color": 0, "inference": {"reachable": False, "models": 0}}
            for tab_id in tabs.tabs():
                report["tabs"].append(tabs.tab(tab_id, "text"))
            work_folder = tempfile.mkdtemp(prefix="qr_palette_smoke_")
            try:
                state["picked"] = state["order"][0]
                link_text.set("https://example.com/smoke")
                refresh_preview()
                made = make_qr(db_path, link_text.get(), state["picked"], "M", os.path.join(work_folder, "smoke.png"), 4)
                report["codec_ok"] = made["ok"]
                found = search(db_path, "color", state["picked"], False, 20)
                if found["ok"]:
                    report["found_by_color"] = len(found["value"])

                def read(connection):
                    return ok_result(registry.counts(connection)["records"])

                counted = with_registry(db_path, read)
                if counted["ok"]:
                    report["records"] = counted["value"]
                if engine["endpoint"] is not None:
                    listed = local_inference.list_models(engine["endpoint"], local_inference.LIST_TIMEOUT, "")
                    report["inference"]["reachable"] = listed["ok"]
                    if listed["ok"]:
                        report["inference"]["models"] = len(listed["value"])
            finally:
                shutil.rmtree(work_folder, ignore_errors=True)
            handle = open(smoke_path, "w", encoding="utf-8")
            json.dump(report, handle, indent=2)
            handle.close()
            window.destroy()

        window.after(800, write_smoke_report)

    window.mainloop()
    return 0


# =================================================================================================
# CLI
# =================================================================================================

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
    values = {}
    for name in ("--db", "--inference", "--inference-timeout", "--model", "--smoke", "--settings"):
        value = option_value(arguments, name)
        if value is None:
            print(name + " needs a value")
            return 2
        values[name] = value
    scratch = ""
    if values["--smoke"] != "":
        scratch = tempfile.mkdtemp(prefix="qr_palette_smoke_")
    settings_path = values["--settings"]
    if settings_path == "" and scratch != "":
        settings_path = os.path.join(scratch, "settings.json")  # a smoke run never touches your settings
    if settings_path == "":
        settings_path = default_settings_path()
    config = settings.load(os.path.abspath(settings_path))
    warnings = config["warnings"] + apply_settings(config["values"])
    serving = "--ecp" in arguments or "--mcp" in arguments
    if serving:
        for warning in warnings:
            sys.stderr.write("warning: " + warning + "\n")
    db_path = values["--db"]
    if db_path == "" and scratch != "":
        db_path = os.path.join(scratch, DB_NAME)
    if db_path == "":
        db_path = config["values"]["registry"] or default_db_path()
    db_path = os.path.abspath(db_path)
    timeout = 0.0
    if values["--inference-timeout"] != "":
        try:
            timeout = float(values["--inference-timeout"])
        except ValueError:
            timeout = -1.0
        if not 0 < timeout <= 3600:
            print("--inference-timeout needs a number of seconds (up to 3600)")
            return 2
    inference_url = values["--inference"]
    if inference_url != "" and not local_inference.parse_endpoint(inference_url)["ok"]:
        print(local_inference.parse_endpoint(inference_url)["error"])
        return 2
    if inference_url == "":
        inference_url = config["values"]["inference"]["url"]
        if serving and not local_inference.parse_endpoint(inference_url)["ok"]:
            print("settings: inference.url: " + local_inference.parse_endpoint(inference_url)["error"])
            return 2
    model = values["--model"] or config["values"]["inference"]["model"]
    if serving:
        engine = make_engine(db_path, inference_url, timeout or PROTOCOL_TIMEOUT, config["values"], model)
        return mcp_server.serve_stdio(mcp_server.new_server(engine))
    try:
        engine = make_engine(db_path, inference_url, timeout or WINDOW_TIMEOUT, config["values"], model)
        if scratch != "":
            engine["audit_file"] = os.path.join(scratch, "audit.jsonl")  # nor your audit log
        return run_gui(db_path, engine, values["--smoke"], config, warnings)
    finally:
        if scratch != "":
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ==== stamp v1 | author=kjFriday | hmac-sha256=437fd8caa04df420caae3e9f2693798a331ad74215dd23c2d78c61b9493e71e1 ====
