# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: qr_palette.py
# About: Generic Company QR Palette: QR codes in recommended colors, a registry of where each one...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Generic Company QR Palette: QR codes in recommended colors, a registry of where each one is, and ECP.

Make a QR code for a link in one of the colors that Color Voats' rankers recommend, read QR codes from
pictures, and find any code again by its link or by its color: every answer gives the color, the link
and the path of the picture file. The registry is a relational SQLite database of this program's
own. Other programs ask it through the Environment Context Protocol (ECP, see ECP.md): an MCP server
on stdin/stdout (--mcp, or --ecp, the same) with three tools. A local model is chosen first, and
inference never leaves this computer.

A code can hold a short link instead of its destination (shortlinks.py): a short address with the
address printed under the code, whose destination can change later without reprinting. Short links
come in two sections, switched in the Make tab: local (this computer or your own network, for
trying codes) and nonlocal (your internet address, for printing). The window exports each
section's redirect pages for a web server to serve.

A code can also hold a Wi-Fi network, a contact card, a calendar event and more (payloads.py), with a
logo in its middle. Whole print runs come from a list; label sheets and posters come from sheets.py. The
registry keeps each short link's history, scheduled changes and scan counts (scans.py), publish.py puts
the redirect pages where a web host serves them, and tag digits under a local key (localkey.py) tell
your printed codes from others.

Everything a user may change is plain, human-readable JSON: settings.json (in the program's data
folder, written with every setting and its default on the first run), presets/ and weights/ (how
colors are ranked), planner.json (how questions become query plans), links.json (short links) and
sheets.json (print sheets). The options below override settings.json for one run.

Standard library only, written to port easily like QR Studio and Color Voats: plain functions and
records, explicit loops, failures as Result records, and a CORE that never touches the GUI.

Records
  Result   {"ok": bool, "error": str, "value": any}
  Made     {"id": int, "path": str, "link": str, "color": "#rrggbb", "version": int, "level": str,
            "short_code": str, "target": str}            link is what the code holds; "" when not short
  Picture  {"reading": Reading, "format": "png" | "svg" | "other", "color": "#rrggbb", "image": Image or None}
  Shown    {"id", "link", "hex", "name", "family", "path", "exists", "ec_level", "version", "short_code",
            "target", "scans": registry's ScanCount or None, "has_logo": bool}        a result row
  BatchRow {"row": its row in the file, "link", "color", "label", "file", "problem": "" when it can be made}
  BatchReport {"made": int, "skipped": int, "report": path of its CSV, "stopped": bool, "rows": one dict per
            row, the columns of BATCH_COLUMNS}

Usage
  python qr_palette.py                       open the window
  python qr_palette.py --settings FILE       use FILE instead of settings.json in the data folder
  python qr_palette.py --db FILE             use FILE as the registry
  python qr_palette.py --mcp [--model NAME]  serve ECP's three MCP tools on stdin/stdout; NAME is the default
                                             model for queries that name none (settings.json: inference.model)
  python qr_palette.py --ecp                 the same as --mcp
  python qr_palette.py --inference URL       the local Ollama server: http on 127.0.0.1, ::1 or localhost
  python qr_palette.py --inference-timeout S seconds a model may take to plan
  python qr_palette.py --export-redirects DIR [--section local|nonlocal]
                                             write a redirect page for every short link of the section in use
                                             (or the one given) into DIR, then exit
  python qr_palette.py --selftest            run the built-in checks and exit
  python qr_palette.py --version
  python qr_palette.py --smoke FILE          open the window on a scratch registry and default settings, use
                                             it, write a JSON report, close
"""

import csv
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import audit
import ecp
import local_inference
import localkey
import mcp_server
import payloads
import publish
import qr_codec
import registry
import scans
import settings
import sheets
import shortlinks
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
MIN_MODULE_MM = 0.4  # the smallest module most printers and phone cameras handle well
DISTANCE_PER_MODULE = 250  # the 10:1 rule (scan from at most ten times a code's width) for a 25-module code
MIN_CAPTION_MM = 1.5  # the smallest letters of a printed address most people can read
ROBUSTNESS_SCALE = 4  # pixels per module for the robustness score: decoding is pure Python
MAX_BATCH_BYTES = 20 * 1024 * 1024  # a list of codes bigger than this is refused
MAX_BATCH_ROWS = 10000
BATCH_COLUMNS = ("row", "status", "reason", "link", "color", "label", "path", "short_id", "note")
WINDOWS_DEVICES = ("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                   "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9")
CSV_COLUMNS = ("id", "color", "color_name", "family", "link", "destination", "short_id", "section", "path", "format",
               "ec_level", "version", "origin", "created", "scans_total", "scans_30_days", "password_masked", "has_logo")
LINKS = shortlinks.copy_links(shortlinks.DEFAULT_LINKS)  # links.json, put in place by apply_settings()
LINK_SECTION = "local"  # the section new short links use: settings.json's links.use
SCANS_VOTE = False  # settings.json's colors.scans_vote: scans feed the ranking's scans algo


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
    """Put settings.json's values in place across the modules, and load planner.json and links.json
    -> [warnings]."""
    global DEFAULT_SCALE, PROTOCOL_TIMEOUT, WINDOW_TIMEOUT, LINKS, LINK_SECTION, SCANS_VOTE
    warnings = []
    colors = values["colors"]
    SCANS_VOTE = colors["scans_vote"]
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
    links = shortlinks.load_links(values["links"]["file"] or os.path.join(HERE, "links.json"))
    LINKS = links["links"]
    LINK_SECTION = values["links"]["use"]
    return warnings + loaded["warnings"] + links["warnings"]


def make_engine(db_path, inference_url, timeout, values, model):
    """The ECP engine for this run, from settings.json's values (and the command line's choices)."""
    engine = ecp.new_engine(db_path, inference_url, timeout, __version__)
    engine["default_model"] = model
    engine["preset"] = values["colors"]["preset"]
    engine["audit_file"] = values["audit"]["file"] or default_audit_path()
    engine["links"] = LINKS
    engine["scans_vote"] = values["colors"]["scans_vote"]
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
    """A file name for a code. A secret in the text (a Wi-Fi password) never reaches it."""
    return slug(payloads.stored_form(link)[0]) + "-" + color[1:] + "." + kind


def with_registry(db_path, work):
    """Open the registry read-write, run work(connection), close it -> work's Result."""
    opened = registry.connect(db_path, False)
    if not opened["ok"]:
        return opened
    try:
        return work(opened["value"])
    finally:
        registry.close(opened["value"])


def short_request(code, section):
    """What make_qr needs for a short link: the base of links.json's `section` ("local" or
    "nonlocal"), the ID length, and the ID to use for a new one (the window keeps one ready, so its
    preview shows the code that will be saved)."""
    return {"base": LINKS[section]["base"], "digits": LINKS["id_digits"], "code": code, "section": section}


def fresh_code(db_path, digits):
    """A new short-link ID, tagged when links.json says so and the registry's key can be had; an ID without
    a tag works just the same, so a key that cannot be made never stops a code being made."""
    key = None
    if LINKS["tag_ids"]:
        found = localkey.key_for(db_path)
        if found["ok"]:
            key = found["value"]
    return shortlinks.new_code(digits, key)


def plan_short_link(db_path, target, color, short):
    """The short link a code for `target` in `color` prints -> Result {"code", "url", "made": bool}:
    the one already made on short["base"] for this destination in this color, else a new one there
    with short["code"] (or a fresh ID when that one is not valid or already used). Local and nonlocal
    short links to the same destination are separate, since they print different addresses."""
    def plan(connection):
        found = registry.short_link_for(connection, target, color, short["base"])
        if found is not None:
            return ok_result({"code": found["code"], "url": found["url"], "made": True})
        code = short["code"]
        tries = 0
        while not shortlinks.is_valid_code(code) or registry.code_taken(connection, code):
            tries = tries + 1
            if tries > 50:
                return fail("cannot find a free short-link ID; raise id_digits in links.json")
            code = fresh_code(db_path, short["digits"])
        return ok_result({"code": code, "url": shortlinks.short_url(short["base"], code), "made": False})

    return with_registry(db_path, plan)


def masked_entry(db_path, text, entry):
    """Fill in a code's Entry from the text it holds -> Result Entry. A secret (a Wi-Fi password) is
    never stored: the Entry gets the text with it masked, and a hash of the real text under the
    registry's local key, which finds the record again when the code is scanned."""
    stored, masked = payloads.stored_form(text)
    entry["link"] = stored
    if masked:
        key = localkey.key_for(db_path)
        if not key["ok"]:
            return key
        entry["payload_hash"] = localkey.tag(key["value"], "payload", text)
    return ok_result(entry)


def make_qr(db_path, link, color, level, path, scale, short=None, logo=None, built=False):
    """Draw `link` as a QR code in `color`, save it to `path` (.png or .svg), read the file back to
    prove it scans, and register it -> Result Made. With `short` (see short_request), `link` is the
    destination: the code holds a short link to it instead, with that address printed under it.
    With `logo` (an Image), the code is level H with the logo in its middle (qr_codec.place_logo).
    With `built`, `link` is a payloads.build text, used exactly as it is: its line ends are part of
    it. Made's link is what the registry keeps, so a Wi-Fi password is masked there too."""
    text = link
    if not built:
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
    target = ""
    code = ""
    caption = ""
    if short is not None:
        checked = shortlinks.check_target(text)
        if not checked["ok"]:
            return checked
        target = checked["value"]
        planned = plan_short_link(db_path, target, color, short)
        if not planned["ok"]:
            return planned
        code = planned["value"]["code"]
        text = planned["value"]["url"]
        caption = shortlinks.caption(text)
    placed_logo = None
    if logo is not None:
        placed = qr_codec.place_logo(text, logo)
        if not placed["ok"]:
            return placed
        matrix = placed["value"]["matrix"]
        placed_logo = placed["value"]["logo"]
        level = "H"
    else:
        made = qr_codec.encode_text(text, level, 1, -1)
        if not made["ok"]:
            return made
        matrix = made["value"]
    path = registry.display_path(path)
    saved = qr_codec.save_matrix(matrix, path, scale, color, caption, placed_logo)
    if not saved["ok"]:
        return saved
    picture = qr_codec.read_qr_file(path)
    if not picture["ok"] or picture["value"]["reading"]["text"] != text or picture["value"]["color"] != color:
        try:
            os.remove(path)
        except OSError:
            pass
        if placed_logo is not None:
            return fail("with this logo the saved picture did not read back the same, so it was removed; try a "
                        "smaller or lighter logo")
        return fail("the saved picture did not read back the same, so it was removed")
    entry = {"color": color, "path": path, "format": qr_codec.file_kind(path), "ec_level": level,
             "version": matrix["version"], "origin": "made"}
    if code != "":
        entry["short"] = {"code": code, "target": target}
    if placed_logo is not None:
        entry["has_logo"] = 1
    filled = masked_entry(db_path, text, entry)
    if not filled["ok"]:
        return filled

    def register(connection):
        return registry.save_qr(connection, entry)

    saved_record = with_registry(db_path, register)
    if not saved_record["ok"]:
        return saved_record
    return ok_result({"id": saved_record["value"], "path": path, "link": entry["link"], "color": color,
                      "version": matrix["version"], "level": level, "short_code": code, "target": target})


def retarget_link(db_path, code, link):
    """Send short link `code` to `link` from now on -> Result True. Export the pages to publish it."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def change(connection):
        return registry.retarget(connection, code, checked["value"])

    changed = with_registry(db_path, change)
    if changed["ok"] and not changed["value"]:
        return fail("there is no short link " + code)
    return changed


def undo_link_change(db_path, code):
    """Send short link `code` back where it went before its latest change -> Result its target now."""
    def undo(connection):
        return registry.undo_last_change(connection, code)

    return with_registry(db_path, undo)


def schedule_link_change(db_path, code, link, from_day):
    """Send short link `code` to `link` from `from_day` on -> Result the schedule's id."""
    checked = shortlinks.check_target(link)
    if not checked["ok"]:
        return checked

    def schedule(connection):
        return registry.schedule_change(connection, code, checked["value"], from_day)

    return with_registry(db_path, schedule)


def cancel_link_change(db_path, number):
    def cancel(connection):
        return registry.cancel_scheduled(connection, number)

    return with_registry(db_path, cancel)


def link_history(db_path, code):
    """A short link's past and future -> Result {"changes": [Change], "coming": [Scheduled]}."""
    def read(connection):
        return ok_result({"changes": registry.link_changes(connection, code),
                          "coming": registry.scheduled(connection, code)})

    return with_registry(db_path, read)


def due_link_changes(db_path, today):
    """The scheduled changes whose day has come -> Result [Scheduled]."""
    def read(connection):
        return ok_result(registry.due_changes(connection, today))

    return with_registry(db_path, read)


def apply_due_changes(db_path, today):
    """Make the scheduled changes whose day has come -> Result how many."""
    def apply(connection):
        return registry.apply_due(connection, today)

    return with_registry(db_path, apply)


def import_scan_file(db_path, path):
    """Scan counts from an analytics CSV or a server log into the registry -> Result {"kind", "source",
    "read", "ignored", "days", "scans": how many counted, "unknown": [IDs that are not short links here]}.
    Importing the same file again changes nothing."""
    read = scans.read_file(path)
    if not read["ok"]:
        return read
    value = read["value"]

    def bring(connection):
        return registry.import_scans(connection, value["counts"], value["source"])

    saved = with_registry(db_path, bring)
    if not saved["ok"]:
        return saved
    counted = 0
    for key in value["counts"]:
        if key[0] not in saved["value"]["unknown"]:
            counted = counted + value["counts"][key]
    return ok_result({"kind": value["kind"], "source": value["source"], "read": value["read"],
                      "ignored": value["ignored"], "days": saved["value"]["days"], "scans": counted,
                      "unknown": saved["value"]["unknown"]})


def export_redirects(db_path, folder, section, day=""):
    """Write a redirect page for every short link of `section` ("local" or "nonlocal") into `folder`
    (shortlinks.export_pages), with the destination in force on `day` ("" for today) -> Result. The
    registry is only read, on the read-only rail."""
    if day == "":
        day = registry.today_text()
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        rows = registry.short_links_on(opened["value"], day)
    except Exception as error:
        return fail("cannot read the short links: " + str(error))
    finally:
        registry.close(opened["value"])
    return shortlinks.export_pages(folder, rows, LINKS[section]["base"], LINKS["tags"])


def publish_rows(db_path, day):
    """The short links as they should be published on `day` ("" for today) -> Result [ShortLink]."""
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        return ok_result(registry.short_links_on(opened["value"], day or registry.today_text()))
    except Exception as error:
        return fail("cannot read the short links: " + str(error))
    finally:
        registry.close(opened["value"])


def publish_plan(db_path, day=""):
    """What publishing the nonlocal pages would change, with nothing touched -> Result publish.Changes."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = LINKS["nonlocal"]["publish"]
    return publish.plan_pages(target["folder"], target["kind"], rows["value"], LINKS["nonlocal"]["base"], LINKS["tags"])


def publish_now(db_path, day=""):
    """Publish the nonlocal pages where links.json says -> Result of publish.publish."""
    rows = publish_rows(db_path, day)
    if not rows["ok"]:
        return rows
    target = LINKS["nonlocal"]["publish"]
    return publish.publish(target["folder"], target["kind"], rows["value"], LINKS["nonlocal"]["base"], LINKS["tags"])


def tamper_verdict(db_path, text):
    """What the Read tab says about a scanned link -> {"line": str, "warning": bool}, "" for a link that
    has nothing to do with your addresses. A warning is for an address that only looks like yours, or
    an ID on your address that is not yours. Limits: two tag digits are right by chance 1 time in 100."""
    verdict = {"line": "", "warning": False}
    if not qr_codec.is_link(text):
        return verdict
    bases = (LINKS["local"]["base"], LINKS["nonlocal"]["base"])
    imitated = shortlinks.lookalike(text, bases)
    if imitated != "":
        verdict["line"] = ("Careful: this address only looks like your " + imitated + ". It goes somewhere else, "
                           "so it may be a sticker over your code.")
        verdict["warning"] = True
        return verdict
    lifted = text.upper()
    section = ""
    for name in shortlinks.SECTIONS:
        if lifted.startswith(LINKS[name]["base"]):
            section = name
    if section == "":
        return verdict
    code = text.split("?")[0].rstrip("/").split("/")[-1]
    if not code.isdigit() or not code.isascii():
        return verdict

    def read(connection):
        return ok_result(registry.code_taken(connection, code))

    known = with_registry(db_path, read)
    standing = shortlinks.code_standing(code, localkey.read_key(localkey.key_path(db_path)), known["ok"] and known["value"])
    if standing == "tagged":
        verdict["line"] = "Made with your key: short link " + code + " (" + section + ")."
    elif standing == "untagged":
        verdict["line"] = ("A short link of yours without a tag (" + section + "): made before tags, or with another "
                           "key.")
    elif standing == "unverified":
        verdict["line"] = "A short link in your registry (" + section + "). Its tag cannot be checked: no key here."
    elif standing == "unknown":
        verdict["line"] = "On your address, but not in this registry, and its tag cannot be checked: no key here."
    else:
        verdict["line"] = ("Not yours: this ID is on your address (" + section + "), but it is not in this registry and "
                           "its tag or check digit is wrong. It may be a sticker over your code.")
        verdict["warning"] = True
    return verdict


def short_note(shown):
    """A short link's section for the window: " (local)", " (nonlocal)", or "" when its address is
    on neither section's base any more."""
    section = shortlinks.section_of(LINKS, shown["link"])
    if section == "":
        return ""
    return " (" + section + ")"


def local_pages_folder():
    """Where the local pages are exported to be served: links.json's local export folder, else
    "local pages" in the program's data folder."""
    return LINKS["local"]["export_folder"] or os.path.join(data_folder(), "local pages")


def default_backup_path():
    return os.path.join(data_folder(), "backups", "palette-" + time.strftime("%Y%m%d-%H%M%S") + ".db")


def safe_cell(value):
    """A spreadsheet cell that is never read as a formula: text that starts with = + - @, a tab or a
    carriage return gets a leading apostrophe."""
    text = ""
    if value is not None:
        text = str(value)
    if text != "" and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def export_registry(db_path, path, today=""):
    """The registry as CSV (one row per QR code, for spreadsheets) or JSON (codes, short links with
    their history, schedules and scans, and votes), by `path`'s extension -> Result {"path", "codes",
    "short_links"}. Scans up to `today` ("" for today). Read on the read-only rail, and written next to
    its place first. A Wi-Fi password is never here: the registry only has it masked."""
    kind = os.path.splitext(path)[1].lower()
    if kind not in (".csv", ".json"):
        return fail("export to a .csv or a .json file")
    opened = registry.connect(db_path, True)
    if not opened["ok"]:
        return opened
    try:
        codes = registry.all_rows(opened["value"])
        links = registry.short_links(opened["value"])
        votes = registry.vote_entries(opened["value"])
        kept = registry.history_entries(opened["value"])
        totals = registry.scan_totals(opened["value"], today or registry.today_text())
    except Exception as error:
        return fail("cannot read the registry: " + str(error))
    finally:
        registry.close(opened["value"])
    rows = []
    for row in codes:
        section = ""
        if row["short_code"] != "":
            section = shortlinks.section_of(LINKS, row["link"])
        scanned = totals.get(row["short_code"], {"total": "", "recent": ""})
        if row["short_code"] != "" and row["short_code"] not in totals:
            scanned = {"total": 0, "recent": 0}
        rows.append({"id": row["id"], "color": row["hex"], "color_name": row["name"], "family": row["family"],
                     "link": row["link"], "destination": row["target"] or row["link"], "short_id": row["short_code"],
                     "section": section, "path": row["path"], "format": row["format"], "ec_level": row["ec_level"],
                     "version": row["version"], "origin": row["origin"], "created": row["created"],
                     "scans_total": scanned["total"], "scans_30_days": scanned["recent"],
                     "password_masked": "yes" if row["payload_hash"] is not None else "",
                     "has_logo": "yes" if row["has_logo"] else ""})
    temporary = path + ".part"
    try:
        if kind == ".csv":
            handle = open(temporary, "w", encoding="utf-8-sig", newline="")
            try:
                writer = csv.writer(handle)
                writer.writerow(CSV_COLUMNS)
                for row in rows:
                    cells = []
                    for key in CSV_COLUMNS:
                        cells.append(safe_cell(row[key]))
                    writer.writerow(cells)
            finally:
                handle.close()
        else:
            data = {"program": APP_NAME + " " + __version__, "exported": registry.now_text(), "codes": rows,
                    "short_links": links, "short_link_changes": kept["short_link_changes"],
                    "scheduled_changes": kept["scheduled_changes"], "scans": kept["scans"], "votes": votes}
            handle = open(temporary, "w", encoding="utf-8", newline="\n")
            try:
                handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            finally:
                handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot write " + path + ": " + str(error))
    return ok_result({"path": path, "codes": len(rows), "short_links": len(links)})


def print_advice(text, width_cm, distance_m, caption, logo_version=0):
    """How a code holding `text`, printed `width_cm` wide (the whole picture, quiet zone included),
    scans from `distance_m` -> Result {"need_mm", "levels": [{"level", "version", "modules",
    "module_mm", "fits", "min_width_cm", "caption_mm"}]}, one per error-correction level. Rules of
    thumb, not guarantees: a module at least MIN_MODULE_MM, and at least 1/DISTANCE_PER_MODULE of the
    scanning distance; the printed address's letters at least MIN_CAPTION_MM tall. A code with a logo
    is only ever level H, at the version place_logo chose: `logo_version`, 0 for no logo."""
    for value, low, high, name in ((width_cm, 0.5, 500, "the width is 0.5 to 500 cm"),
                                   (distance_m, 0.05, 50, "the distance is 0.05 to 50 m")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            return fail(name)
    need = max(MIN_MODULE_MM, distance_m * 1000.0 / DISTANCE_PER_MODULE)
    levels = []
    for level in registry.EC_LEVELS:
        if logo_version > 0 and level != "H":
            continue
        made = qr_codec.encode_text(text, level, max(1, logo_version), -1)
        if not made["ok"]:
            continue
        side = made["value"]["size"] + 8
        across = side
        caption_mm = None
        if caption != "":
            lines, pixel = qr_codec.caption_layout(caption, side * DEFAULT_SCALE, DEFAULT_SCALE)
            band = qr_codec.caption_size(lines, pixel, DEFAULT_SCALE)
            across = max(side * DEFAULT_SCALE, band[0] + 2 * DEFAULT_SCALE) / DEFAULT_SCALE
        module_mm = width_cm * 10.0 / across
        if caption != "":
            caption_mm = round(7.0 * pixel / DEFAULT_SCALE * module_mm, 2)
        levels.append({"level": level, "version": made["value"]["version"], "modules": side,
                       "module_mm": round(module_mm, 2), "fits": module_mm >= need,
                       "min_width_cm": round(need * across / 10.0 + 0.05, 1), "caption_mm": caption_mm})
    if len(levels) == 0:
        return fail("this text is too long for a QR code")
    return ok_result({"need_mm": round(need, 2), "levels": levels})


def redraw_record(db_path, number, color, scale):
    """Draw registered code `number` again in `color` (a PNG at `scale` pixels per module) over its
    own file -> Result Made. The new drawing is read back before it replaces the old one; its link,
    error-correction level and short link stay as they were."""
    color = swatch.normalize_hex(color)
    if color == "" or not swatch.usable(color):
        return fail("pick a color dark enough to scan on white")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= 40:
        return fail("the size is 1 to 40 pixels per module")

    def read(connection):
        row = registry.row_by_id(connection, number)
        if row is None:
            return fail("there is no record " + str(number))
        return ok_result(row)

    found = with_registry(db_path, read)
    if not found["ok"]:
        return found
    row = found["value"]
    if row["payload_hash"] is not None:
        return fail(os.path.basename(row["path"]) + " holds a Wi-Fi password the registry does not keep, so it "
                    "cannot be drawn again here; make it again in the Make tab")
    if row["has_logo"]:
        return fail(os.path.basename(row["path"]) + " has a logo the registry does not keep, and redrawing would lose "
                    "it; make it again in the Make tab")
    made = qr_codec.encode_text(row["link"], row["ec_level"], 1, -1)
    if not made["ok"]:
        return made
    caption = ""
    if row["short_code"] != "":
        caption = shortlinks.caption(row["link"])
    folder, name = os.path.split(row["path"])
    if not os.path.isdir(folder):
        return fail("the folder of " + row["path"] + " is not there any more")
    trial = os.path.join(folder, ".redraw-" + name)
    saved = qr_codec.save_matrix(made["value"], trial, scale, color, caption)
    if not saved["ok"]:
        return saved
    picture = qr_codec.read_qr_file(trial)
    if not picture["ok"] or picture["value"]["reading"]["text"] != row["link"] or picture["value"]["color"] != color:
        try:
            os.remove(trial)
        except OSError:
            pass
        return fail("the new drawing did not read back the same; " + row["path"] + " was left as it was")
    try:
        os.replace(trial, row["path"])
    except OSError as error:
        return fail("cannot replace " + row["path"] + ": " + str(error))
    entry = {"link": row["link"], "color": color, "path": row["path"], "format": qr_codec.file_kind(row["path"]),
             "ec_level": row["ec_level"], "version": made["value"]["version"], "origin": "made"}
    if row["short_code"] != "":
        entry["short"] = {"code": row["short_code"], "target": row["target"]}

    def register(connection):
        return registry.save_qr(connection, entry)

    saved_record = with_registry(db_path, register)
    if not saved_record["ok"]:
        return saved_record
    return ok_result({"id": saved_record["value"], "path": row["path"], "link": row["link"], "color": color,
                      "version": made["value"]["version"], "level": row["ec_level"], "short_code": row["short_code"],
                      "target": row["target"]})


def read_batch_csv(path):
    """A print run from a CSV file with a header row -> Result [BatchRow]. The headers link and color
    are needed, label and file are optional, in any order and either case. The file may be UTF-8 (with
    or without a byte-order mark) or a spreadsheet's Windows-1252, separated by commas, semicolons or
    tabs. Every row comes back in order, those that cannot be made with their "problem" filled in."""
    try:
        if os.path.getsize(path) > MAX_BATCH_BYTES:
            return fail(os.path.basename(path) + " is too big for a list of codes")
        handle = open(path, "rb")
        try:
            data = handle.read()
        finally:
            handle.close()
    except OSError as error:
        return fail("cannot read " + path + ": " + str(error))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            return fail(os.path.basename(path) + " is not UTF-8 or Windows-1252 text")
    first = text.split("\n", 1)[0]
    separator = ","
    for candidate in (";", "\t"):
        if candidate in first and "," not in first:
            separator = candidate
    rows = []
    try:
        lines = csv.reader(io.StringIO(text, newline=""), delimiter=separator)
        headers = None
        for cells in lines:
            if headers is None:
                if len(cells) == 0 or "".join(cells).strip() == "":
                    continue
                headers = []
                for cell in cells:
                    headers.append(cell.strip().lower())
                if "link" not in headers or "color" not in headers:
                    return fail("the first row must name the columns: link, color, and optionally label and file")
                continue
            if "".join(cells).strip() == "":
                continue
            if len(rows) >= MAX_BATCH_ROWS:
                return fail("a list may hold at most " + str(MAX_BATCH_ROWS) + " codes")
            found = {"link": "", "color": "", "label": "", "file": ""}
            for index in range(min(len(headers), len(cells))):
                if headers[index] in found:
                    found[headers[index]] = textsafe.clean(cells[index], None).strip()
            found["row"] = lines.line_num
            found["problem"] = ""
            given = found["color"]
            found["color"] = swatch.normalize_hex(given)
            if found["link"] == "":
                found["problem"] = "no link"
            elif given == "":
                found["problem"] = "no color"
            elif found["color"] == "":
                found["problem"] = textsafe.clean(given, 40) + " is not a #rrggbb color"
            rows.append(found)
    except csv.Error as error:
        return fail("cannot read " + os.path.basename(path) + " as CSV: " + str(error))
    if len(rows) == 0:
        return fail(os.path.basename(path) + " holds no rows of codes")
    return ok_result(rows)


def batch_file_problem(name):
    """"" when a list's file column is a plain file name for this computer, else what is wrong: it
    may not lead outside the chosen folder or be a name Windows keeps for itself."""
    if name in (".", "..") or name != os.path.basename(name) or "/" in name or "\\" in name:
        return "the file column must be a file name, not a path"
    stem = name.split(".", 1)[0].strip().upper()
    if stem == "" or stem in WINDOWS_DEVICES or name.endswith((".", " ")):
        return "the file column's name cannot be used on Windows"
    for character in name:
        if character in '<>:"|?*':
            return "the file column's name cannot be used on Windows"
    return ""


def batch_path(row, color, kind, folder, taken):
    """Where a row's picture goes -> (path, problem). From its file column, else its label (if any)
    and suggested_name; a name that is in the folder or already used by this run gets -2, -3, ...,
    because make_qr replaces a file that is already there."""
    name = row["file"]
    if name != "":
        problem = batch_file_problem(name)
        if problem != "":
            return "", problem
        if not name.lower().endswith((".png", ".svg")):
            name = name + "." + kind
    else:
        name = suggested_name(row["link"], color, kind)
        if row["label"] != "":
            name = slug(row["label"]) + "-" + name
    stem, extension = os.path.splitext(name)
    candidate = name
    number = 1
    while os.path.exists(os.path.join(folder, candidate)) or candidate.casefold() in taken:
        number = number + 1
        candidate = stem + "-" + str(number) + extension
    taken.add(candidate.casefold())
    return os.path.join(folder, candidate), ""


def make_batch(db_path, rows, folder, kind, level, scale, section, snap=False, watch=None, when=""):
    """Make a code for every BatchRow, with a report beside the pictures -> Result BatchReport. `kind`
    is "png" or "svg" (a row's file column may say otherwise). `section` is the short-link section
    to print ("" for none); the same destination in the same color shares its short link, as ever. A
    color too light to scan is skipped with the reason, or with `snap` replaced by the nearest that
    scans. A row the same as an earlier one is skipped. `watch(done, total)`, called before each row,
    may return True to stop: the rest are reported as not made. `when` names the report (the time)."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        return fail("cannot use the folder " + folder + ": " + str(error))
    report = []
    seen = {}
    taken = set()
    made_count = 0
    stopped = False
    for index in range(len(rows)):
        row = rows[index]
        line = {"row": row["row"], "status": "skipped", "reason": row["problem"], "link": row["link"],
                "color": row["color"], "label": row["label"], "path": "", "short_id": "", "note": ""}
        line["link"] = payloads.stored_form(row["link"])[0]  # a report never holds a Wi-Fi password
        report.append(line)
        if not stopped and watch is not None and watch(index, len(rows)):
            stopped = True
        if stopped:
            line["reason"] = "stopped before this row"
            continue
        if line["reason"] != "":
            continue
        same = (row["link"], row["color"], row["label"], row["file"])
        if same in seen:
            line["reason"] = "the same as row " + str(seen[same])
            continue
        seen[same] = row["row"]
        color = row["color"]
        if not swatch.usable(color):
            if not snap:
                line["reason"] = color + " is too light to scan on white"
                continue
            color = swatch.nearest_usable(color)
            line["note"] = "color " + row["color"] + " was too light to scan: used " + color
            line["color"] = color
        path, problem = batch_path(row, color, kind, folder, taken)
        if problem != "":
            line["reason"] = problem
            continue
        short = None
        if section != "":
            short = short_request("", section)
        made = make_qr(db_path, row["link"], color, level, path, scale, short)
        if not made["ok"]:
            line["reason"] = made["error"]
            continue
        line["status"] = "made"
        line["path"] = made["value"]["path"]
        line["short_id"] = made["value"]["short_code"]
        made_count = made_count + 1
    written = write_batch_report(folder, report, when or time.strftime("%Y%m%d-%H%M%S"))
    if not written["ok"]:
        return written
    return ok_result({"made": made_count, "skipped": len(report) - made_count, "report": written["value"],
                      "rows": report, "stopped": stopped})


def write_batch_report(folder, report, when):
    """The batch's report as a CSV beside its pictures, never over an earlier one -> Result path."""
    path = os.path.join(folder, "made-" + when + ".csv")
    number = 1
    while os.path.exists(path):
        number = number + 1
        path = os.path.join(folder, "made-" + when + "-" + str(number) + ".csv")
    temporary = path + ".part"
    try:
        handle = open(temporary, "w", encoding="utf-8-sig", newline="")
        try:
            writer = csv.writer(handle)
            writer.writerow(BATCH_COLUMNS)
            for line in report:
                cells = []
                for key in BATCH_COLUMNS:
                    cells.append(safe_cell(line[key]))
                writer.writerow(cells)
        finally:
            handle.close()
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return fail("cannot write the report " + path + ": " + str(error))
    return ok_result(path)


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
    entry = {"color": color, "path": registry.display_path(path), "format": picture["value"]["format"],
             "ec_level": reading["level"], "version": reading["version"], "origin": "registered"}
    filled = masked_entry(db_path, reading["text"], entry)
    if not filled["ok"]:
        return filled

    def register(connection):
        return registry.save_qr(connection, entry)

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
        counts = None
        if SCANS_VOTE:
            counts = registry.color_scans(connection)
        return ok_result({"log": registry.vote_log(connection), "votes": registry.vote_map(connection), "scans": counts})

    read_votes = with_registry(db_path, read)
    if not read_votes["ok"]:
        return read_votes
    ranked = swatch.rank_colors(preset, read_votes["value"]["log"], read_votes["value"]["scans"])
    if not ranked["ok"]:
        return ranked
    return ok_result({"order": swatch.usable_board(ranked["value"]), "votes": read_votes["value"]["votes"],
                      "places": swatch.rank_places(ranked["value"])})


def shown_from_row(row, exists, totals=None):
    """A registry Row as a result row. `totals` is registry.scan_totals's answer, when it was read."""
    count = None
    if totals is not None and row["short_code"] != "":
        count = totals.get(row["short_code"], {"total": 0, "recent": 0})
    return {"id": row["id"], "link": row["link"], "hex": row["hex"], "name": row["name"], "family": row["family"],
            "path": row["path"], "exists": exists, "ec_level": row["ec_level"], "version": row["version"],
            "short_code": row["short_code"], "target": row["target"], "scans": count, "has_logo": bool(row["has_logo"])}


def shown_from_record(record):
    """An ECP Record as a result row. Records carry no EC level or version, so the preview is drawn at
    M, as small as the link allows. A short link's ID is the last part of the address it prints."""
    code = ""
    if record["target_url"] != "":
        code = record["payload_url"].rstrip("/").split("/")[-1]
    return {"id": record["id"], "link": record["payload_url"], "hex": record["hex"], "name": record["color_name"],
            "family": record["color_family"], "path": record["file_path"], "exists": record["exists"],
            "ec_level": "M", "version": 1, "short_code": code, "target": record["target_url"], "scans": None,
            "has_logo": False}


def destination(shown):
    """Where a result's code sends people: its short link's destination, or the link it holds."""
    return shown["target"] or shown["link"]


def search(db_path, by, value, near, limit, today=""):
    """The window's own lookup by QR code or by color (no model needed) -> Result [Shown], with each
    short link's scans up to `today` ("" for today)."""
    text = textsafe.clean(value, None).strip()
    if text == "":
        return fail("type what to look for")
    found_plan = ecp.find_plan(by, text, near, limit)
    if not found_plan["ok"]:
        return found_plan

    def read(connection):
        return ok_result({"rows": registry.all_rows(connection),
                          "totals": registry.scan_totals(connection, today or registry.today_text())})

    found = with_registry(db_path, read)
    if not found["ok"]:
        return found
    shown = []
    for row in registry.find_rows(found["value"]["rows"], ecp.plan_filters(found_plan["value"]),
                                  found_plan["value"]["limit"]):
        shown.append(shown_from_row(row, registry.file_state(row["path"], False), found["value"]["totals"]))
    return ok_result(shown)


def matches_for_text(db_path, text, path):
    """Records holding exactly this text, or registered at this file -> Result [Shown]. A masked record
    is found by the keyed hash of the real text, when this registry's key is here."""
    def read(connection):
        return ok_result(registry.all_rows(connection))

    rows = with_registry(db_path, read)
    if not rows["ok"]:
        return rows
    key = ""
    if path != "":
        key = registry.path_key(path)
    tag = ""
    if payloads.stored_form(text)[1]:
        secret = localkey.read_key(localkey.key_path(db_path))
        if secret is not None:
            tag = localkey.tag(secret, "payload", text)
    shown = []
    for row in rows["value"]:
        same = row["link"] == text or (tag != "" and row["payload_hash"] == tag)
        if same or (key != "" and row["path_key"] == key):
            shown.append(shown_from_row(row, registry.file_state(row["path"], False)))
    return ok_result(shown)


def preview_png(link, color, level, version, caption=""):
    """A small PNG of a record's code, drawn again from its link (for previews in the window), as
    large as fits in PREVIEW - 20 pixels with its caption."""
    made = qr_codec.encode_text(link, level, version, -1)
    if not made["ok"]:
        made = qr_codec.encode_text(link, "M", 1, -1)
    if not made["ok"]:
        return b""
    return fitted_png(made["value"], color, caption, PREVIEW - 20)


def fitted_png(matrix, color, caption, room, logo=None):
    """The code as PNG bytes at the largest scale whose picture, caption included, fits `room` pixels."""
    scale = max(1, room // (matrix["size"] + 8))
    while True:
        png = qr_codec.picture_bytes(matrix, scale, color, "png", caption, logo)
        width, height = struct.unpack(">II", png[16:24])
        if scale == 1 or (width <= room and height <= room):
            return png
        scale = scale - 1


def robustness_score(matrix, text, color, caption, logo=None):
    """How much wear the code in `matrix` survives, drawn as its PNG would be -> Result Score."""
    return qr_codec.robustness(qr_codec.picture_image(matrix, ROBUSTNESS_SCALE, color, caption, logo), text)


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
        sample = "HTTPS://GO.EXAMPLE.COM/12345678"
        worn = qr_codec.robustness(qr_codec.picture_image(qr_codec.encode_text(sample, "H", 1, -1)["value"], 4,
                                                          "#000000"), sample)
        check(worn["ok"] and worn["value"]["passed"] == 9, "a code's robustness is scored (9 of 10 for this one)",
              failures)
        logo = make_qr(db_path, "https://example.com/logo", "#663399", "M", os.path.join(folder, "logo.png"), 4, None,
                       qr_codec.make_image(16, 16, 40))
        check(logo["ok"] and logo["value"]["level"] == "H", "a code with a logo in the middle is level H and reads back",
              failures)
        printed = sheets.print_sheet(db_path, [made["value"]["id"], made_svg["value"]["id"]],
                                     sheets.DEFAULT_SHEETS["layouts"]["A4 poster"], os.path.join(folder, "sheet.pdf"))
        check(printed["ok"] and printed["value"]["pages"] == 2, "codes are printed on a sheet as a PDF", failures)
        run = make_batch(db_path, [{"row": 2, "link": "https://example.com/list", "color": "#660099", "label": "x",
                                    "file": "", "problem": ""},
                                   {"row": 3, "link": "https://example.com/list", "color": "#ffff00", "label": "y",
                                    "file": "", "problem": ""}], os.path.join(folder, "run"), "png", "M", 4, "", False,
                         None, "selftest")
        check(run["ok"] and run["value"]["made"] == 1 and run["value"]["skipped"] == 1 and
              os.path.isfile(run["value"]["report"]), "a list makes its codes and reports the row it skipped", failures)
        wifi = payloads.build("wifi", {"ssid": "Cafe", "password": "selftest-secret"})["value"]
        joined = make_qr(db_path, wifi["text"], "#663399", "M", os.path.join(folder, "wifi.png"), 4, None, None, True)
        found = matches_for_text(db_path, wifi["text"], "")
        check(joined["ok"] and joined["value"]["link"] == wifi["stored"] and found["ok"] and len(found["value"]) == 1,
              "a Wi-Fi code keeps its password out of the registry, and is still found by scanning it", failures)
        found = search(db_path, "color", "blue", False, 20)
        check(found["ok"] and len(found["value"]) == 1 and found["value"][0]["path"] == made["value"]["path"],
              "found again by color, with its path", failures)
        found = search(db_path, "qr_code", "https://example.com/selftest", False, 20)
        check(found["ok"] and len(found["value"]) == 2, "found again by its link", failures)
        check(vote_color(db_path, "#3366cc", 1)["value"] == 1 and board(db_path, "mixer")["value"]["order"][0] == "#3366cc",
              "a Good vote moves the color to the top", failures)
        local = make_qr(db_path, "https://example.com/later", "#006633", "M", os.path.join(folder, "s.png"), 4,
                        short_request(shortlinks.new_code(LINKS["id_digits"]), "local"))
        public = make_qr(db_path, "https://example.com/later", "#006633", "M", os.path.join(folder, "t.png"), 4,
                         short_request(shortlinks.new_code(LINKS["id_digits"]), "nonlocal"))
        check(local["ok"] and public["ok"] and local["value"]["link"].startswith(LINKS["local"]["base"]) and
              public["value"]["link"].startswith(LINKS["nonlocal"]["base"]) and
              public["value"]["target"] == "https://example.com/later",
              "local and nonlocal short links are printed in the code, each with its destination", failures)
        exported = export_redirects(db_path, os.path.join(folder, "site"), "local")
        check(exported["ok"] and exported["value"]["written"] == 1 and len(exported["value"]["skipped"]) == 1,
              "the local section's redirect page is exported, and only that one", failures)
        code = local["value"]["short_code"]
        retarget_link(db_path, code, "https://example.com/later-still")
        schedule_link_change(db_path, code, "https://example.com/next-year", "2099-01-01")
        tagged = fresh_code(db_path, 7)
        key = localkey.read_key(localkey.key_path(db_path))
        check(shortlinks.is_valid_code(tagged) and shortlinks.has_valid_tag(tagged, key) and
              tamper_verdict(db_path, local["value"]["link"])["warning"] is False and
              tamper_verdict(db_path, "https://go.exampie.com/1")["warning"],
              "new IDs carry a tag under the local key, and an address that only looks like yours is called out", failures)
        undone = undo_link_change(db_path, code)
        known = link_history(db_path, code)
        check(undone["ok"] and undone["value"] == "https://example.com/later" and known["ok"] and
              len(known["value"]["changes"]) == 2 and len(known["value"]["coming"]) == 1,
              "a short link keeps its history, undoes a change and schedules another", failures)
        outbox = os.path.join(folder, "synced")
        planned = publish.plan_pages(outbox, "folder", [{"code": code, "url": "HTTPS://GO.EXAMPLE.SHOP/" + code,
                                                         "target": "https://example.com/a", "hex": "#006633"}],
                                     "HTTPS://GO.EXAMPLE.SHOP/", {})
        check(planned["ok"] and code + "/index.html" in planned["value"]["added"] and not os.path.exists(outbox),
              "publishing says what would change first, with nothing touched", failures)
        report = os.path.join(folder, "report.csv")
        handle = open(report, "w", encoding="utf-8")
        handle.write("date,utm_content,count\n2026-10-28," + code + "-006633,5\n")
        handle.close()
        import_scan_file(db_path, report)
        imported = import_scan_file(db_path, report)
        shown = search(db_path, "qr_code", code, False, 20, "2026-10-29")
        check(imported["ok"] and shown["ok"] and shown["value"][0]["scans"] == {"total": 5, "recent": 5},
              "scans are imported per short link, and importing again changes nothing", failures)

        print("ecp and mcp")
        engine = ecp.new_engine(db_path, "http://127.0.0.1:1", 1.0, __version__)
        asked = ecp.query(engine, "blue", "", ecp.new_call("selftest", {}, None))
        check(not asked["ok"] and asked["kind"] == "args_invalid", "no query before a local model is chosen", failures)
        check(not local_inference.parse_endpoint("http://example.com:11434")["ok"], "inference must be on loopback",
              failures)
        snapshot = ecp.read_environment(engine)
        asked_local = ecp.ground(dict(ecp.empty_plan(), section="local"), "my local codes")[0]
        ran = None
        if snapshot["ok"]:
            ran = ecp.run_plan(snapshot["value"], asked_local, swatch.DEFAULT_PRESET, LINKS)
        check(ran is not None and len(ran["records"]) == 1 and ran["records"][0]["section"] == "local" and
              ecp.ground(dict(ecp.empty_plan(), section="local"), "every code")[0]["section"] == "",
              "ECP finds the local short links only when the question names the section", failures)
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
    from tkinter import ttk, filedialog, messagebox, simpledialog

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

    state = {"job": None, "job_label": "", "job_number": 0, "finished": [], "queue": [], "picked": "", "order": [],
             "votes": {},
             "places": {}, "make_after": None, "matrix": None, "photos": {}, "swatches": {}, "picture": None,
             "picture_path": "", "picture_source": "", "results": [], "folder": folder, "models": [],
             "engine": engine, "model_id": "", "inference": "checking",
             "remembered_model": values["inference"]["model"], "short_candidate": "", "export_folders": {},
             "server": None, "serve_index": None, "preview_text": "", "preview_caption": "", "preview_logo": None,
             "logo": None, "level_before_logo": ""}

    window = tk.Tk()
    window.title("Generic Company Inc. — QR Palette " + __version__)
    window.geometry("1100x" + str(min(800, window.winfo_screenheight() - 80)))
    window.minsize(940, 640)
    icon_set = set_icon(window)
    status = tk.StringVar(value="Ready")
    footer = tk.StringVar(value="")

    # --- Jobs: one slow task at a time, off the window's thread; the rest wait their turn ----------
    def poll_job():
        while len(state["finished"]) > 0:
            number, done, outcome = state["finished"].pop(0)
            if number == state["job_number"] and state["job"] is not None:
                state["job"] = None
                done(outcome)
                start_next()
                return
        if state["job"] is not None:
            window.after(100, poll_job)

    def start_job(label, work, done):
        """Run work() off the window's thread and then done(outcome) on it. Jobs run one at a time, first
        come, first served: one asked for while another runs (Save while a model loads, say) waits for
        its turn instead of being refused."""
        state["queue"].append((label, work, done))
        if state["job"] is not None:
            status.set(state["job_label"] + "…  then " + label.lower() + " (" + str(len(state["queue"])) +
                       " waiting)")
            return
        start_next()

    def start_next():
        if state["job"] is not None or len(state["queue"]) == 0:
            return
        label, work, done = state["queue"].pop(0)
        state["job_number"] = state["job_number"] + 1
        number = state["job_number"]
        state["job_label"] = label

        def runner():
            try:
                outcome = work()
            except Exception as error:
                outcome = fail(label + " failed: " + str(error))
            state["finished"].append((number, done, outcome))

        waiting = ""
        if len(state["queue"]) > 0:
            waiting = "  (" + str(len(state["queue"])) + " more waiting)"
        status.set(label + "…" + waiting)
        state["job"] = threading.Thread(target=runner, daemon=True)
        state["job"].start()
        window.after(100, poll_job)

    def cancel_job():
        """Stop waiting for the running job (its answer is ignored); the jobs waiting behind it go on."""
        if state["job"] is not None:
            state["job"] = None
            state["job_number"] = state["job_number"] + 1
            status.set("Cancelled " + state["job_label"].lower())
            start_next()

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
        serving = ""
        if state["server"] is not None:
            serving = "  ·  serving local pages at " + state["server"]["base"]
        footer.set(str(records) + " QR code(s)  ·  local inference: " + state["inference"] + serving +
                   "  ·  registry: " + db_path)

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

    def export_pages(section):
        start = state["export_folders"].get(section) or LINKS[section]["export_folder"] or os.path.expanduser("~")
        folder = filedialog.askdirectory(title="Export the " + section + " redirect pages to", initialdir=start,
                                         mustexist=False)
        if not folder:
            return
        folder = registry.display_path(folder)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Export redirect pages", outcome["error"])
                return
            state["export_folders"][section] = folder
            message = "Wrote " + str(outcome["value"]["written"]) + " " + section + " redirect page(s) to " + folder
            if len(outcome["value"]["skipped"]) > 0:
                message = (message + "; " + str(len(outcome["value"]["skipped"])) +
                           " short link(s) on other addresses were left out")
            if section == "local":
                message = message + ". Serve the folder from this computer to try them (README.md shows how)."
            else:
                message = message + ". Publish the folder at " + shortlinks.host_of(LINKS[section]["base"]) + "."
            status.set(message)

        start_job("Exporting redirect pages", lambda: export_redirects(db_path, folder, section), done)

    def serve_pages():
        """Start or stop serving the local pages from this computer, so local short links work now."""
        if state["server"] is not None:
            shortlinks.stop_server(state["server"])
            state["server"] = None
            file_menu.entryconfig(state["serve_index"], label="Serve local pages")
            status.set("Stopped serving the local pages")
            refresh_footer()
            return
        base = LINKS["local"]["base"]
        network = False
        where = shortlinks.serve_address(base, False)
        if not where["ok"]:
            if "network" not in where["error"]:
                messagebox.showerror("Serve local pages", where["error"])
                return
            if not messagebox.askyesno("Serve local pages", "The local base " + base + " is an address on your "
                                       "network. While the pages are served, phones and computers on your network can "
                                       "open them (Windows may ask to let Python through its firewall). Serve them?"):
                return
            network = True
        folder = local_pages_folder()

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Serve local pages", outcome["error"])
                return
            started = shortlinks.start_server(folder, base, network)
            if not started["ok"]:
                messagebox.showerror("Serve local pages", started["error"])
                return
            state["server"] = started["value"]
            file_menu.entryconfig(state["serve_index"], label="Stop serving local pages")
            status.set("Serving " + str(outcome["value"]["written"]) + " local page(s) at " + base + " from " + folder +
                       "; they follow your changes until you stop")
            refresh_footer()

        start_job("Exporting the local pages", lambda: export_redirects(db_path, folder, "local"), done)

    def refresh_served():
        """While the local pages are served, write them again after a change, so they stay current."""
        if state["server"] is None:
            return
        folder = state["server"]["folder"]
        start_job("Updating the local pages", lambda: export_redirects(db_path, folder, "local"), lambda outcome: None)

    def back_up():
        suggested = default_backup_path()
        try:
            os.makedirs(os.path.dirname(suggested), exist_ok=True)
        except OSError:
            pass
        target = filedialog.asksaveasfilename(title="Back up the registry", initialdir=os.path.dirname(suggested),
                                              initialfile=os.path.basename(suggested), defaultextension=".db",
                                              filetypes=[("Registry backup", "*.db")])
        if not target:
            return
        target = registry.display_path(target)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Back up the registry", outcome["error"])
                return
            note = ""
            if os.path.isfile(localkey.key_path(db_path)):
                note = "  ·  qr_palette.key is not in it: keep a copy of that too, away from the backup"
            status.set("Backed up the registry to " + outcome["value"] + " (checked)" + note)

        start_job("Backing up the registry", lambda: registry.backup(db_path, target), done)

    def export_table():
        path = filedialog.asksaveasfilename(title="Export the registry", initialfile="qr-palette.csv",
                                            defaultextension=".csv",
                                            filetypes=[("CSV, one row per code (spreadsheets)", "*.csv"),
                                                       ("JSON, everything", "*.json")])
        if not path:
            return
        path = registry.display_path(path)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Export the registry", outcome["error"])
                return
            status.set("Exported " + str(outcome["value"]["codes"]) + " code(s) and " +
                       str(outcome["value"]["short_links"]) + " short link(s) to " + outcome["value"]["path"])

        start_job("Exporting the registry", lambda: export_registry(db_path, path), done)

    def show_audit():
        """The audit log, newest first: any line in full, the chain checked, and its fingerprint to keep
        somewhere else (so lines cut off the end would show even if the anchor beside it went too)."""
        path = state["engine"]["audit_file"]
        dialog = tk.Toplevel(window)
        dialog.title("Audit log")
        dialog.geometry("940x600")
        dialog.transient(window)
        top = ttk.Frame(dialog, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=path, foreground="#555555").pack(anchor="w")
        bar = ttk.Frame(top)
        bar.pack(anchor="w", pady=(6, 0))
        outcome_text = tk.StringVar(value="")
        ttk.Label(top, textvariable=outcome_text, wraplength=900, justify="left").pack(anchor="w", pady=(6, 0))
        table = ttk.Treeview(dialog, columns=("time", "tool", "result", "model", "rows", "ms"), show="tree headings",
                             height=14)
        table.heading("#0", text="Line")
        table.column("#0", width=60, stretch=False)
        for name, title, width in (("time", "Time (UTC)", 180), ("tool", "Tool", 180), ("result", "Result", 140),
                                   ("model", "Model", 170), ("rows", "Rows", 50), ("ms", "ms", 70)):
            table.heading(name, text=title)
            table.column(name, width=width, stretch=name == "model")
        table.pack(fill="both", expand=True, padx=8)
        detail = tk.Text(dialog, height=10, wrap="word")
        detail.pack(fill="x", padx=8, pady=8)
        records = []

        def alive():
            return dialog.winfo_exists()

        def load():
            records.clear()
            records.extend(audit.read_records(path, 500))
            for item in table.get_children():
                table.delete(item)
            for index in range(len(records) - 1, -1, -1):
                record = records[index]
                table.insert("", "end", iid=str(index), text=str(record.get("audit_id", "?")),
                             values=(record.get("ts", ""), record.get("tool", ""), record.get("result_kind", ""),
                                     str(record.get("model_id", "")).split("@")[0], record.get("row_count", ""),
                                     record.get("elapsed_ms", "")))
            if len(records) == 0:
                outcome_text.set("The audit log is empty.")
            else:
                outcome_text.set("The last " + str(len(records)) + " line(s), newest first. Click one to read it.")

        def show_line(event=None):
            chosen = table.selection()
            if len(chosen) == 0:
                return
            detail.config(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", json.dumps(records[int(chosen[0])], indent=2, ensure_ascii=False))
            detail.config(state="disabled")

        def check():
            def done(outcome):
                if not alive():
                    return
                if outcome["ok"]:
                    outcome_text.set("The chain is whole: " + str(outcome["value"]) + " line(s), and it still reaches "
                                     "its anchor.")
                else:
                    outcome_text.set("Problem: " + outcome["error"])

            start_job("Checking the audit log", lambda: audit.verify(path), done)

        def copy_fingerprint():
            found = audit.fingerprint(path)
            if not found["ok"]:
                outcome_text.set(found["error"])
                return
            text = audit.fingerprint_text(found["value"])
            window.clipboard_clear()
            window.clipboard_append(text)
            outcome_text.set("Copied fingerprint " + text[:20] + "…  Keep it somewhere else (a note, an email to "
                             "yourself); Check a kept fingerprint… compares the log with it later.")

        def check_kept():
            text = simpledialog.askstring("Check a kept fingerprint", "Paste a fingerprint you kept (a line number, "
                                          "a colon and 64 hex digits):", parent=dialog)
            if not text:
                return

            def done(outcome):
                if not alive():
                    return
                if outcome["ok"]:
                    outcome_text.set("It matches: line " + text.strip().split(":")[0] + " is as it was written, and "
                                     "the chain is whole (" + str(outcome["value"]) + " lines).")
                else:
                    outcome_text.set("Problem: " + outcome["error"])

            start_job("Checking the fingerprint", lambda: audit.check_fingerprint(path, text), done)

        ttk.Button(bar, text="Check the chain", command=check).pack(side="left")
        ttk.Button(bar, text="Copy fingerprint", command=copy_fingerprint).pack(side="left", padx=6)
        ttk.Button(bar, text="Check a kept fingerprint…", command=check_kept).pack(side="left")
        ttk.Button(bar, text="Refresh", command=load).pack(side="left", padx=6)
        table.bind("<<TreeviewSelect>>", show_line)
        load()

    def print_size():
        """Advice on how big to print the code in the preview, for a scanning distance."""
        text = state["preview_text"]
        if text == "":
            status.set("Type a link first: the advice is for the code in the preview")
            return
        caption = state["preview_caption"]
        logo_version = 0
        if state["preview_logo"] is not None:
            logo_version = state["matrix"]["version"]
        dialog = tk.Toplevel(window)
        dialog.title("Print size")
        dialog.transient(window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="For the code holding " + textsafe.clean(payloads.one_line(payloads.stored_form(text)[0]),
                                                                      80)).grid(row=0, column=0, columnspan=2, sticky="w")
        width_text = tk.StringVar(value="3")
        distance_text = tk.StringVar(value="0.3")
        ttk.Label(body, text="Printed width of the picture (cm)").grid(row=1, column=0, sticky="w", pady=(8, 2))
        width_entry = ttk.Entry(body, textvariable=width_text, width=8)
        width_entry.grid(row=1, column=1, sticky="w", pady=(8, 2))
        ttk.Label(body, text="Scanning distance (m)").grid(row=2, column=0, sticky="w")
        distance_entry = ttk.Entry(body, textvariable=distance_text, width=8)
        distance_entry.grid(row=2, column=1, sticky="w")
        answer = tk.StringVar(value="")
        ttk.Label(body, textvariable=answer, justify="left", wraplength=620).grid(row=3, column=0, columnspan=2,
                                                                                 sticky="w", pady=8)

        def update(event=None):
            try:
                width = float(width_text.get().replace(",", "."))
                distance = float(distance_text.get().replace(",", "."))
            except ValueError:
                answer.set("Type two numbers, such as 3 and 0.3.")
                return
            advice = print_advice(text, width, distance, caption, logo_version)
            if not advice["ok"]:
                answer.set(advice["error"] + ".")
                return
            lines = ["Modules need " + str(advice["value"]["need_mm"]) + " mm or more here (rules of thumb: at least " +
                     str(MIN_MODULE_MM) + " mm to print well, and the code at least a tenth as wide as the distance)."]
            for row in advice["value"]["levels"]:
                line = "Level " + row["level"]
                if row["level"] == chosen_level():
                    line = line + " (chosen)"
                line = line + ": version " + str(row["version"]) + ", modules " + str(row["module_mm"]) + " mm, "
                if row["fits"]:
                    line = line + "fits"
                else:
                    line = line + "too small: print it at least " + str(row["min_width_cm"]) + " cm wide"
                if row["caption_mm"] is not None:
                    line = line + "; address letters " + str(row["caption_mm"]) + " mm"
                    if row["caption_mm"] < MIN_CAPTION_MM:
                        line = line + " (too small to read)"
                lines.append(line)
            answer.set("\n".join(lines))

        width_entry.bind("<KeyRelease>", update)
        distance_entry.bind("<KeyRelease>", update)
        ttk.Button(body, text="Close", command=dialog.destroy).grid(row=4, column=1, sticky="e")
        update()

    def make_from_list():
        """A whole print run from a CSV: the rows are counted first, then made as one job, with a report."""
        dialog = tk.Toplevel(window)
        dialog.title("Make from a list")
        dialog.transient(window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        source_text = tk.StringVar(value="")
        folder_text = tk.StringVar(value=state["folder"])
        kind_choice = tk.StringVar(value="png")
        short_on = tk.BooleanVar(value=False)
        section_on = tk.StringVar(value=section_choice.get())
        snap_on = tk.BooleanVar(value=False)
        summary = tk.StringVar(value="Choose a CSV whose first row names its columns: link and color, and optionally "
                                     "label and file.")
        rows = []
        progress = {"done": 0, "total": 0, "stop": False, "running": False}

        def alive():
            return dialog.winfo_exists()

        def choose_source():
            path = filedialog.askopenfilename(title="A list of codes", parent=dialog,
                                              filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
            if not path:
                return
            path = registry.display_path(path)

            def done(outcome):
                status.set("Ready")
                if not alive():
                    return
                del rows[:]
                make_button.config(state="disabled")
                if not outcome["ok"]:
                    summary.set(outcome["error"] + ".")
                    return
                source_text.set(path)
                rows.extend(outcome["value"])
                problems = []
                for row in rows:
                    if row["problem"] != "":
                        problems.append(row)
                said = str(len(rows)) + " row(s): " + str(len(rows) - len(problems)) + " ready"
                if len(problems) > 0:
                    said = (said + ", " + str(len(problems)) + " with a problem (the first, row " +
                            str(problems[0]["row"]) + ": " + problems[0]["problem"] + ")")
                summary.set(said + ".")
                if len(problems) < len(rows):
                    make_button.config(state="normal")

            start_job("Reading the list", lambda: read_batch_csv(path), done)

        def choose_folder():
            chosen = filedialog.askdirectory(title="Save the pictures in", parent=dialog, mustexist=False,
                                             initialdir=folder_text.get())
            if chosen:
                folder_text.set(registry.display_path(chosen))

        def watch(done_rows, total):
            progress["done"] = done_rows
            progress["total"] = total
            return progress["stop"]

        def tick():
            if progress["running"] and alive():
                summary.set("Making code " + str(progress["done"] + 1) + " of " + str(progress["total"]) + "…")
                dialog.after(200, tick)

        def make():
            target = folder_text.get().strip()
            if target == "":
                summary.set("Choose a folder for the pictures.")
                return
            section = ""
            if short_on.get():
                section = section_on.get()
            chosen_rows = list(rows)
            kind = kind_choice.get()
            level = chosen_level()
            snap = snap_on.get()
            progress["stop"] = False
            progress["running"] = True
            make_button.config(state="disabled")
            stop_button.config(state="normal")

            def done(outcome):
                progress["running"] = False
                if alive():
                    stop_button.config(state="disabled")
                    make_button.config(state="normal")
                if not outcome["ok"]:
                    status.set("Nothing made")
                    messagebox.showerror("Make from a list", outcome["error"])
                    return
                value = outcome["value"]
                state["folder"] = target
                said = "Made " + str(value["made"]) + " code(s), skipped " + str(value["skipped"])
                if value["stopped"]:
                    said = said + " (stopped)"
                said = said + ". Report: " + value["report"]
                status.set(said)
                if alive():
                    summary.set(said)
                refresh_footer()
                refresh_used()
                if section == "local":
                    refresh_served()
                if messagebox.askyesno("Make from a list", said + "\n\nOpen the folder?"):
                    try:
                        os.startfile(target)
                    except (AttributeError, OSError) as error:
                        status.set(str(error))

            start_job("Making codes", lambda: make_batch(db_path, chosen_rows, target, kind, level, DEFAULT_SCALE, section,
                                                         snap, watch), done)
            tick()

        def stop():
            progress["stop"] = True
            summary.set("Stopping after this code…")

        ttk.Label(body, text="List").grid(row=0, column=0, sticky="w")
        ttk.Entry(body, textvariable=source_text, width=56, state="readonly").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Choose…", command=choose_source).grid(row=0, column=2)
        ttk.Label(body, textvariable=summary, wraplength=560, justify="left").grid(row=1, column=0, columnspan=3,
                                                                                   sticky="w", pady=6)
        ttk.Label(body, text="Folder").grid(row=2, column=0, sticky="w")
        ttk.Entry(body, textvariable=folder_text, width=56).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Choose…", command=choose_folder).grid(row=2, column=2)
        kinds = ttk.Frame(body)
        kinds.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(kinds, text="Pictures").pack(side="left")
        ttk.Radiobutton(kinds, text="PNG", variable=kind_choice, value="png").pack(side="left", padx=6)
        ttk.Radiobutton(kinds, text="SVG", variable=kind_choice, value="svg").pack(side="left")
        ttk.Label(kinds, text="Error correction " + chosen_level() + ", as in the Make tab.",
                  foreground="#555555").pack(side="left", padx=12)
        shorts = ttk.Frame(body)
        shorts.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(shorts, text="Short links, printed as", variable=short_on).pack(side="left")
        for name in shortlinks.SECTIONS:
            ttk.Radiobutton(shorts, text=name, value=name, variable=section_on).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(body, text="A color too light to scan: use the nearest that scans (otherwise the row is skipped)",
                        variable=snap_on).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(10, 0))
        make_button = ttk.Button(buttons, text="Make the codes", command=make, state="disabled")
        make_button.pack(side="left")
        stop_button = ttk.Button(buttons, text="Stop", command=stop, state="disabled")
        stop_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left")

    def publish_pages():
        """Publish the nonlocal pages: first what would change, with nothing touched; then, if the person
        says so, write them, and for a Git folder commit and push."""
        target = LINKS["nonlocal"]["publish"]
        if target["kind"] == "":
            messagebox.showinfo("Publish nonlocal pages", "Say where to publish first: nonlocal.publish in links.json. "
                                "Its kind is git (a folder in a Git repository, such as one GitHub Pages serves) or "
                                "folder (a folder something else syncs), and its folder is where. README.md shows how.")
            return

        def planned(outcome):
            if not outcome["ok"]:
                status.set("Nothing published")
                messagebox.showerror("Publish nonlocal pages", outcome["error"])
                return
            value = outcome["value"]
            total = len(value["added"]) + len(value["changed"]) + len(value["removed"])
            if total == 0:
                status.set("Nothing to publish: " + target["folder"] + " already has these pages")
                return
            lines = [str(len(value["added"])) + " page(s) to add, " + str(len(value["changed"])) + " to change, " +
                     str(len(value["removed"])) + " to remove, in\n" + target["folder"]]
            for word, paths in (("add", value["added"]), ("change", value["changed"]), ("remove", value["removed"])):
                for path in paths[:5]:
                    lines.append(word + "  " + path)
            if total > 15:
                lines.append("…")
            if len(value["skipped"]) > 0:
                lines.append(str(len(value["skipped"])) + " short link(s) on other addresses are left out.")
            ask = "Write these pages there?"
            if target["kind"] == "git":
                ask = "Commit them and push the branch? (Never forced.)"
            if not messagebox.askyesno("Publish nonlocal pages", "\n".join(lines) + "\n\n" + ask):
                status.set("Nothing published")
                return
            start_job("Publishing the pages", lambda: publish_now(db_path), published)

        def published(outcome):
            if not outcome["ok"]:
                status.set("Not published")
                messagebox.showerror("Publish nonlocal pages", outcome["error"])
                return
            value = outcome["value"]
            changes = value["changes"]
            message = (str(len(changes["added"])) + " page(s) added, " + str(len(changes["changed"])) + " changed, " +
                       str(len(changes["removed"])) + " removed in " + target["folder"])
            if target["kind"] == "git":
                if value["commit"] == "":
                    message = message + "; Git saw nothing new to commit"
                elif value["pushed"]:
                    message = message + "; committed " + value["commit"] + " and pushed"
                else:
                    message = message + "; committed " + value["commit"] + " but not pushed"
                    messagebox.showerror("Publish nonlocal pages", "The pages are committed (" + value["commit"] +
                                         ") but the push failed:\n\n" + value["push_error"] +
                                         "\n\nPush that folder with your Git client.")
            status.set(message)

        start_job("Checking what would change", lambda: publish_plan(db_path), planned)

    def import_scans_file():
        """Scan counts from an analytics report or a server log. Only counts are kept."""
        path = filedialog.askopenfilename(title="An analytics report or a server log",
                                          filetypes=[("Reports and logs", "*.csv *.log *.txt *.gz"), ("All files", "*.*")])
        if not path:
            return
        path = registry.display_path(path)

        def done(outcome):
            if not outcome["ok"]:
                status.set("No scans imported")
                messagebox.showerror("Import scans", outcome["error"])
                return
            value = outcome["value"]
            message = ("Imported " + str(value["scans"]) + " scan(s) on " + str(value["days"]) + " code-day(s) from " +
                       os.path.basename(path) + " (" + value["source"] + ")")
            if value["ignored"] > 0:
                message = message + "; " + str(value["ignored"]) + " other line(s) ignored"
            if len(value["unknown"]) > 0:
                message = message + "; " + str(len(value["unknown"])) + " ID(s) are not short links here"
            if len(state["results"]) > 0:
                run_search(message)
            else:
                status.set(message)

        start_job("Importing scans", lambda: import_scan_file(db_path, path), done)

    file_menu.add_command(label="Make from a list…", command=make_from_list)
    file_menu.add_command(label="Import scans…", command=import_scans_file)
    file_menu.add_command(label="Import votes from Color Voats…", command=import_votes)
    file_menu.add_command(label="Export local redirect pages…", command=lambda: export_pages("local"))
    file_menu.add_command(label="Export nonlocal redirect pages…", command=lambda: export_pages("nonlocal"))
    file_menu.add_command(label="Publish nonlocal pages…", command=publish_pages)
    file_menu.add_command(label="Serve local pages", command=serve_pages)
    state["serve_index"] = file_menu.index("end")
    file_menu.add_separator()
    file_menu.add_command(label="Back up the registry…", command=back_up)
    file_menu.add_command(label="Export the registry (CSV or JSON)…", command=export_table)
    file_menu.add_command(label="Audit log…", command=lambda: show_audit())
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
    ttk.Label(make_bar, text="Kind").pack(side="left")
    kind_names = {}
    for name in payloads.KINDS:
        kind_names[payloads.TITLES[name]] = name
    kind_box = ttk.Combobox(make_bar, values=list(kind_names), width=14, state="readonly")
    kind_box.set(payloads.TITLES["link"])
    kind_box.pack(side="left", padx=(6, 12))
    ttk.Label(make_bar, text="Link").pack(side="left")
    link_text = tk.StringVar(value="")
    link_entry = ttk.Entry(make_bar, textvariable=link_text, width=40)
    link_entry.pack(side="left", padx=6)
    kind_form = ttk.Frame(make_tab)
    kind_fields = {}
    ttk.Label(make_bar, text="Preset").pack(side="left", padx=(12, 0))
    preset_box = ttk.Combobox(make_bar, values=swatch.presets(), width=10, state="readonly")
    preset_box.set(preset)
    preset_box.pack(side="left", padx=6)
    ttk.Label(make_bar, text="Error correction").pack(side="left", padx=(12, 0))
    level_names = {"L": "L (7%)", "M": "M (15%)", "Q": "Q (25%)", "H": "H (30%)"}
    level_box = ttk.Combobox(make_bar, values=["L (7%)", "M (15%)", "Q (25%)", "H (30%)"], width=8, state="readonly")
    level_box.set(level_names[values["pictures"]["error_correction"]])
    level_box.pack(side="left", padx=6)
    short_bar = ttk.Frame(make_tab)
    short_bar.pack(fill="x", pady=(6, 0))
    short_choice = tk.BooleanVar(value=LINKS["short_by_default"])
    section_choice = tk.StringVar(value=LINK_SECTION)
    link_only = []  # what applies only to web links: a Kind other than Web link turns these off
    link_only.append(ttk.Checkbutton(short_bar, text="Short link, printed as", variable=short_choice,
                                     command=lambda: schedule_preview()))
    link_only[0].pack(side="left")
    for section in shortlinks.SECTIONS:
        link_only.append(ttk.Radiobutton(short_bar, text=section + "  " + LINKS[section]["base"] + "…", value=section,
                                         variable=section_choice, command=lambda: change_section()))
        link_only[len(link_only) - 1].pack(side="left", padx=(10, 0))
    if len(LINKS["templates"]) > 0:
        link_only.append(ttk.Button(short_bar, text="From template…", command=lambda: from_template()))
        link_only[len(link_only) - 1].pack(side="left", padx=16)
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
    save_bar = ttk.Frame(preview_side)  # right under the preview, so a long note below never hides it
    save_bar.pack(anchor="w", pady=(6, 0))
    logo_bar = ttk.Frame(preview_side)
    logo_bar.pack(anchor="w", pady=(6, 0))
    logo_text = tk.StringVar(value="No logo")
    make_info = tk.StringVar(value="Type a link and pick a color.")
    ttk.Label(preview_side, textvariable=make_info, wraplength=560, justify="left").pack(anchor="w", pady=4)

    def chosen_level():
        return level_box.get()[:1] or "M"

    def chosen_kind():
        return kind_names[kind_box.get()]

    def form_values():
        values_now = {}
        for key in kind_fields:
            values_now[key] = kind_fields[key].get()
        return values_now

    def change_kind(event=None):
        """A small form for the kind of code chosen, in place of the Link box; a web link has none."""
        kind = chosen_kind()
        for child in kind_form.winfo_children():
            child.destroy()
        kind_fields.clear()
        fields = payloads.FIELDS[kind]
        for index in range(len(fields)):
            key, label, hidden, choices = fields[index]
            row = index // 3
            column = 2 * (index % 3)
            ttk.Label(kind_form, text=label).grid(row=row, column=column, sticky="w", padx=(0 if column == 0 else 16, 6),
                                                  pady=2)
            if choices is not None:
                field = ttk.Combobox(kind_form, values=list(choices), state="readonly", width=12)
                field.set(choices[0])
                field.bind("<<ComboboxSelected>>", schedule_preview)
                field.grid(row=row, column=column + 1, sticky="w", pady=2)
            else:
                field = ttk.Entry(kind_form, width=26, show="*" if hidden else "")
                field.bind("<KeyRelease>", schedule_preview)
                field.grid(row=row, column=column + 1, sticky="w", pady=2)
            kind_fields[key] = field
        if kind == "link":
            kind_form.pack_forget()
            link_entry.config(state="normal")
            for widget in link_only:
                widget.config(state="normal")
        else:
            kind_form.pack(fill="x", pady=(6, 0), after=make_bar)
            link_entry.config(state="disabled")
            for widget in link_only:
                widget.config(state="disabled")
        refresh_preview()

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
        state["preview_text"] = ""
        state["preview_logo"] = None
        kind = chosen_kind()
        lead = ""
        if kind == "link":
            text = textsafe.clean(link_text.get(), None).strip()
            if text == "":
                make_info.set("Type a link and pick a color.")
                return
        else:
            built = payloads.build(kind, form_values())
            if not built["ok"]:
                make_info.set(built["error"].capitalize() + ".")
                return
            text = built["value"]["text"]
            lead = "Holds: " + textsafe.clean(payloads.one_line(built["value"]["stored"]), 240) + "\n"
            if built["value"]["masked"]:
                lead = lead + "The password goes in the code and its picture; the registry keeps it masked.\n"
        color = state["picked"] or qr_codec.INK
        caption = ""
        if kind == "link" and short_choice.get():
            checked = shortlinks.check_target(text)
            if not checked["ok"]:
                make_info.set(checked["error"] + ".")
                return
            if state["short_candidate"] == "":
                state["short_candidate"] = fresh_code(db_path, LINKS["id_digits"])
            section = section_choice.get()
            planned = plan_short_link(db_path, checked["value"], color, short_request(state["short_candidate"], section))
            if not planned["ok"]:
                make_info.set(planned["error"] + ".")
                return
            if not planned["value"]["made"]:
                state["short_candidate"] = planned["value"]["code"]
            text = planned["value"]["url"]
            caption = shortlinks.caption(text)
            lead = "Prints " + text + " (" + section + "), which sends people to " + checked["value"] + ".\n"
            if planned["value"]["made"]:
                lead = lead + "Made before for this link in this color. "
            if section == "local":
                lead = lead + "Local: works only where you serve the local pages.\n"
            elif shortlinks.is_placeholder(LINKS["nonlocal"]["base"]):
                lead = lead + "Set your own nonlocal address in links.json before printing.\n"
            elif planned["value"]["made"]:
                lead = lead + "\n"
        placed_logo = None
        if state["logo"] is not None:
            placed = qr_codec.place_logo(text, state["logo"])
            if not placed["ok"]:
                make_info.set(placed["error"] + ".")
                return
            matrix = placed["value"]["matrix"]
            placed_logo = placed["value"]["logo"]
            size = matrix["size"]
            lead = lead + ("The logo's square covers " + str(100 * placed_logo["box"][2] * placed_logo["box"][2] //
                                                             (size * size)) + "% of the modules.\n")
        else:
            made = qr_codec.encode_text(text, chosen_level(), 1, -1)
            if not made["ok"]:
                make_info.set(made["error"] + ".")
                return
            matrix = made["value"]
        state["matrix"] = matrix
        state["preview_text"] = text
        state["preview_caption"] = caption
        state["preview_logo"] = placed_logo
        photo = photo_from_png(fitted_png(matrix, color, caption, PREVIEW, placed_logo))
        state["photos"]["preview"] = photo
        preview.create_image((PREVIEW + 20) // 2, (PREVIEW + 20) // 2, image=photo)
        width, height = struct.unpack(">II", qr_codec.matrix_to_color_png(matrix, DEFAULT_SCALE, 4, color, caption)[16:24])
        hint = ""
        if state["picked"] == "":
            hint = " Pick a color to save it."
        make_info.set(lead + "Version " + str(matrix["version"]) + ", level " + matrix["level"] +
                      ". PNG will be " + str(width) + " × " + str(height) + " px." + hint)

    def test_robustness():
        """How much wear the code in the preview survives, as a job: decoding is slow in pure Python."""
        if state["matrix"] is None:
            status.set("Type a link first: the test is for the code in the preview")
            return
        matrix = state["matrix"]
        text = state["preview_text"]
        color = state["picked"] or qr_codec.INK
        caption = state["preview_caption"]
        logo = state["preview_logo"]

        def done(outcome):
            if not outcome["ok"]:
                status.set("Robustness: " + outcome["error"])
                return
            status.set("Robustness of the code in the preview: " + qr_codec.describe_score(outcome["value"]))

        start_job("Testing robustness", lambda: robustness_score(matrix, text, color, caption, logo), done)

    def choose_logo():
        path = filedialog.askopenfilename(title="A small picture for the middle of the code",
                                          filetypes=[("PNG pictures", "*.png"), ("All files", "*.*")])
        if not path:
            return
        path = registry.display_path(path)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Logo", outcome["error"])
                status.set("No logo chosen")
                return
            image = outcome["value"]
            if image["width"] > qr_codec.MAX_LOGO_SIDE or image["height"] > qr_codec.MAX_LOGO_SIDE:
                messagebox.showerror("Logo", "Pick a picture at most " + str(qr_codec.MAX_LOGO_SIDE) + " pixels a side.")
                status.set("No logo chosen")
                return
            if state["logo"] is None:
                state["level_before_logo"] = level_box.get()
            state["logo"] = image
            logo_text.set(os.path.basename(path) + "  (level H)")
            level_box.set(level_names["H"])
            level_box.config(state="disabled")
            status.set("Logo: " + os.path.basename(path))
            refresh_preview()

        start_job("Reading the logo", lambda: qr_codec.load_image_file(path), done)

    def clear_logo():
        if state["logo"] is None:
            return
        state["logo"] = None
        logo_text.set("No logo")
        status.set("No logo")
        level_box.config(state="readonly")
        level_box.set(state["level_before_logo"])
        refresh_preview()

    def schedule_preview(event=None):
        if state["make_after"] is not None:
            window.after_cancel(state["make_after"])
        state["make_after"] = window.after(250, refresh_preview)

    def change_section():
        """Local or nonlocal: picking one ticks Short link, and the choice is remembered."""
        save_setting("links", "use", section_choice.get())
        short_choice.set(True)
        schedule_preview()

    def save_as(kind):
        code_kind = chosen_kind()
        name = ""
        if code_kind == "link":
            text = textsafe.clean(link_text.get(), None).strip()
        else:
            built = payloads.build(code_kind, form_values())
            if not built["ok"]:
                make_info.set(built["error"].capitalize() + ".")
                return
            text = built["value"]["text"]
            name = built["value"]["name"]
        if text == "" or state["picked"] == "":
            make_info.set("Type a link and pick a color first.")
            return
        try:
            os.makedirs(state["folder"], exist_ok=True)
        except OSError:
            state["folder"] = os.path.expanduser("~")
        label = {"png": "PNG picture", "svg": "SVG drawing"}[kind]
        initial = suggested_name(text, state["picked"], kind)
        if name != "":
            initial = slug(name) + "-" + state["picked"][1:] + "." + kind
        path = filedialog.asksaveasfilename(title="Save QR code", initialdir=state["folder"], initialfile=initial,
                                            defaultextension="." + kind, filetypes=[(label, "*." + kind)])
        if not path:
            return
        color = state["picked"]
        level = chosen_level()
        short = None
        if code_kind == "link" and short_choice.get():
            if state["short_candidate"] == "":
                state["short_candidate"] = fresh_code(db_path, LINKS["id_digits"])
            short = short_request(state["short_candidate"], section_choice.get())
        logo = state["logo"]

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Save QR code", outcome["error"])
                status.set("Not saved")
                return
            state["folder"] = os.path.dirname(outcome["value"]["path"])
            if os.path.normcase(state["folder"]) != os.path.normcase(default_qr_folder()):
                save_setting("pictures", "folder", state["folder"])
            message = "Saved and registered: " + outcome["value"]["path"]
            if outcome["value"]["short_code"] != "":
                if outcome["value"]["short_code"] == state["short_candidate"]:
                    state["short_candidate"] = ""  # used: the next new short link gets a new ID
                message = (message + "  ·  " + short["section"] + " short link " + outcome["value"]["short_code"] +
                           " sends people to " + outcome["value"]["target"] + " (File → Export " + short["section"] +
                           " redirect pages… publishes it)")
                refresh_served()
            if payloads.is_masked(outcome["value"]["link"]):
                message = message + "  ·  the password is in the picture only, not in the registry"
            status.set(message)
            refresh_footer()
            refresh_used()

        start_job("Saving", lambda: make_qr(db_path, text, color, level, path, DEFAULT_SCALE, short, logo,
                                            code_kind != "link"), done)

    def from_template():
        """A small dialog that builds the link from one of links.json's templates."""
        names = sorted(LINKS["templates"])
        dialog = tk.Toplevel(window)
        dialog.title("Link from a template")
        dialog.transient(window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Template").grid(row=0, column=0, sticky="w")
        chooser = ttk.Combobox(body, values=names, state="readonly", width=24)
        chooser.grid(row=0, column=1, sticky="w", pady=4)
        pattern_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=pattern_text, foreground="#555555").grid(row=1, column=0, columnspan=2, sticky="w")
        fields = ttk.Frame(body)
        fields.grid(row=2, column=0, columnspan=2, sticky="we", pady=6)
        result_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=result_text, wraplength=440, justify="left").grid(row=3, column=0, columnspan=2,
                                                                                       sticky="w")
        entries = {}

        def filled():
            typed = {}
            for name in entries:
                typed[name] = entries[name].get()
            return shortlinks.fill_template(LINKS["templates"][chooser.get()], typed)

        def update(event=None):
            outcome = filled()
            result_text.set(outcome["value"] if outcome["ok"] else outcome["error"])

        def choose(event=None):
            for child in fields.winfo_children():
                child.destroy()
            entries.clear()
            pattern = LINKS["templates"][chooser.get()]
            pattern_text.set(pattern)
            names_in_order = shortlinks.template_fields(pattern)
            for row in range(len(names_in_order)):
                ttk.Label(fields, text=names_in_order[row]).grid(row=row, column=0, sticky="w", padx=(0, 8))
                entry = ttk.Entry(fields, width=40)
                entry.grid(row=row, column=1, pady=2)
                entry.bind("<KeyRelease>", update)
                entries[names_in_order[row]] = entry
            update()

        def use():
            outcome = filled()
            if not outcome["ok"]:
                result_text.set(outcome["error"])
                return
            link_text.set(outcome["value"])
            dialog.destroy()
            refresh_preview()

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Use this link", command=use).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", choose)
        chooser.set(names[0])
        choose()
        dialog.grab_set()

    def change_preset(event=None):
        save_setting("colors", "preset", preset_box.get())
        state["engine"]["preset"] = preset_box.get()
        redraw_board()

    tiles.bind("<Button-1>", pick_tile)
    kind_box.bind("<<ComboboxSelected>>", change_kind)
    link_entry.bind("<KeyRelease>", schedule_preview)
    level_box.bind("<<ComboboxSelected>>", schedule_preview)
    preset_box.bind("<<ComboboxSelected>>", change_preset)
    good_button.config(command=lambda: cast_vote(1))
    bad_button.config(command=lambda: cast_vote(-1))
    ttk.Button(save_bar, text="Save PNG…", command=lambda: save_as("png")).pack(side="left")
    ttk.Button(save_bar, text="Save SVG…", command=lambda: save_as("svg")).pack(side="left", padx=6)
    ttk.Button(save_bar, text="Print size…", command=print_size).pack(side="left", padx=(12, 0))
    ttk.Button(save_bar, text="Test robustness", command=test_robustness).pack(side="left", padx=6)
    ttk.Button(logo_bar, text="Logo…", command=choose_logo).pack(side="left")
    ttk.Button(logo_bar, text="No logo", command=clear_logo).pack(side="left", padx=6)
    ttk.Label(logo_bar, textvariable=logo_text, foreground="#555555").pack(side="left", padx=6)

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
    verdict_text = tk.StringVar(value="")
    verdict_label = ttk.Label(read_side, textvariable=verdict_text, wraplength=520, justify="left")
    verdict_label.pack(anchor="w", pady=(4, 0))
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
        verdict_text.set("")
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
        kind = payloads.kind_of(reading["text"])
        read_details.set("Read: " + qr_codec.describe(reading) + "." +
                         (" Kind: " + payloads.TITLES[kind] + "." if kind not in ("", "link") else ""))
        detected_swatch.create_rectangle(0, 0, 24, 24, fill=picture["color"], outline="")
        detected_text.set("detected ≈ " + picture["color"] + " (" + swatch.color_name(picture["color"]) + ")")
        verdict_text.set(outcome["value"]["verdict"]["line"])
        verdict_label.config(foreground="#b00020" if outcome["value"]["verdict"]["warning"] else "")
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
            return ok_result({"picture": picture["value"], "matches": matches["value"],
                              "verdict": tamper_verdict(db_path, picture["value"]["reading"]["text"])})

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
    question_entry = ttk.Entry(ask_row, textvariable=question, width=26)
    question_entry.pack(side="left", padx=6, fill="x", expand=True)  # narrow windows keep the buttons whole
    plan_text = tk.StringVar(value="Pick a local model to ask in plain English, e.g. \"blue codes that link to the shop\".")
    results = ttk.Treeview(find_tab, columns=("hex", "link", "scans", "path", "exists"), show="tree headings", height=8)
    results.heading("#0", text="Color")
    results.heading("hex", text="Hex")
    results.heading("link", text="Link")
    results.heading("scans", text="Scans (30 d)")
    results.heading("path", text="Path")
    results.heading("exists", text="File")
    results.column("#0", width=140, stretch=False)
    results.column("hex", width=74, stretch=False)
    results.column("link", width=290)
    results.column("scans", width=104, stretch=False)
    results.column("path", width=300)
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
            link = payloads.one_line(destination(shown))
            if shown["short_code"] != "":
                section = shortlinks.section_of(LINKS, shown["link"])
                link = link + "   (" + (section + " " if section != "" else "") + "short " + shown["short_code"] + ")"
            scanned = ""
            if shown["scans"] is not None:
                scanned = str(shown["scans"]["total"]) + " (" + str(shown["scans"]["recent"]) + ")"
            results.insert("", "end", iid=str(index), text=" " + shown["name"], image=swatch_image(shown["hex"]),
                           values=(shown["hex"], link, scanned, shown["path"], exists))
        detail_preview.delete("all")
        detail_text.set("Select a result to see it here.")
        status.set(note)

    def run_search(note=""):
        """Find by QR code or color. `note`, when given, is shown instead of the count, so a change
        that searches again to show its result keeps its own message."""
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
            show_results(outcome["value"], note or str(len(outcome["value"])) + " QR code(s) found")

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
        caption = ""
        if shown["short_code"] != "":
            caption = shortlinks.caption(shown["link"])
        photo = None
        masked = payloads.is_masked(shown["link"])
        if not masked:  # a masked code cannot be drawn from what the registry keeps
            photo = photo_from_png(preview_png(shown["link"], shown["hex"], shown["ec_level"], shown["version"], caption))
        state["photos"]["detail"] = photo
        if photo is not None:
            factor = 1
            while photo.width() // factor > 168:
                factor = factor + 1
            if factor > 1:
                photo = photo.subsample(factor, factor)
                state["photos"]["detail"] = photo
            detail_preview.create_image(86, 86, image=photo)
        logo_note = ""
        if shown["has_logo"]:
            logo_note = "\nIts picture has a logo the registry does not keep: this preview shows the code without it."
        more = logo_note
        if len(results.selection()) > 1:
            more = (logo_note + "\n…and " + str(len(results.selection()) - 1) + " more selected: Change destination…, "
                    "Redraw…, Forget record and Print sheet… act on them all.")
        if shown["short_code"] != "":
            detail_text.set(shown["name"] + "  " + shown["hex"] + "\nLink: " + textsafe.clean(shown["target"], 300) +
                            "\nPrinted as: " + shown["link"] + short_note(shown) +
                            "\nPath: " + shown["path"] + history_note(shown) + more)
        else:
            note = ""
            if masked:
                note = "\nThe registry keeps this code without its password: open the picture to see it."
            detail_text.set(shown["name"] + "  " + shown["hex"] + "\nHolds: " +
                            textsafe.clean(payloads.one_line(shown["link"]), 300) + "\nPath: " + shown["path"] + note + more)

    def history_note(shown):
        """A short link's scans, last change and next scheduled change, as lines for the detail."""
        lines = ""
        if shown["scans"] is not None:
            lines = ("\nScans: " + str(shown["scans"]["total"]) + " in all, " + str(shown["scans"]["recent"]) +
                     " in the last " + str(registry.RECENT_DAYS) + " days")
        known = link_history(db_path, shown["short_code"])
        if known["ok"]:
            if len(known["value"]["changes"]) > 0:
                last = known["value"]["changes"][0]
                lines = (lines + "\nChanged " + last["changed"][:10] + ", from " + textsafe.clean(last["old_target"], 120) +
                         " (History… has them all)")
            if len(known["value"]["coming"]) > 0:
                next_one = known["value"]["coming"][0]
                lines = lines + "\nGoes to " + textsafe.clean(next_one["target"], 120) + " from " + next_one["from_day"]
        return lines

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
        if key == "link":
            window.clipboard_append(destination(shown))
        else:
            window.clipboard_append(shown[key])
        status.set("Copied the " + key)

    def open_shown_link():
        shown = selected_shown()
        if shown is None:
            return
        link = destination(shown)
        if not qr_codec.is_link(link):
            status.set("Only http:// and https:// links can be opened")
            return
        if messagebox.askyesno("Open link", "Open this link in your browser?\n\n" + link):
            webbrowser.open(link.strip())

    def selected_all():
        """Every selected result (Ctrl+click or Shift+click picks several)."""
        chosen = []
        for item in results.selection():
            chosen.append(state["results"][int(item)])
        return chosen

    def change_destination():
        """Send the selected short links somewhere else (all of them to the same place)."""
        codes = []
        first = None
        for shown in selected_all():
            if shown["short_code"] != "" and shown["short_code"] not in codes:
                codes.append(shown["short_code"])
                if first is None:
                    first = shown
        if first is None:
            status.set("Pick a code with a short link: a code that holds its link itself cannot be sent elsewhere")
            return
        question = "Where should " + first["link"] + " send people?"
        if len(codes) > 1:
            question = "Where should these " + str(len(codes)) + " short links send people?"
        link = simpledialog.askstring("Change destination", question + "\nPrinted codes keep working; export the "
                                      "redirect pages again to publish it.", initialvalue=first["target"],
                                      parent=window)
        if link is None:
            return

        def work():
            for code in codes:
                changed = retarget_link(db_path, code, link)
                if not changed["ok"]:
                    return changed
            return ok_result(len(codes))

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Change destination", outcome["error"])
                return
            run_search(str(outcome["value"]) + " short link(s) now send people to " + link.strip() +
                       "  ·  export the redirect pages again to publish it")
            refresh_served()

        start_job("Changing the destination", work, done)

    def redraw_shown():
        """Draw the selected codes again, in another color or size, over their own files."""
        chosen = selected_all()
        if len(chosen) == 0:
            return
        color = simpledialog.askstring("Redraw", "Redraw " + str(len(chosen)) + " picture(s) in which color?\n"
                                       "#rrggbb, or leave it empty to keep each code's own color.",
                                       initialvalue=state["picked"], parent=window)
        if color is None:
            return
        scale = simpledialog.askinteger("Redraw", "Pixels per module for PNG pictures (1-40):",
                                        initialvalue=DEFAULT_SCALE, minvalue=1, maxvalue=40, parent=window)
        if scale is None:
            return
        jobs = []
        for shown in chosen:
            jobs.append((shown["id"], color.strip() or shown["hex"]))

        def work():
            redrawn = 0
            problems = []
            for number, hex_value in jobs:
                outcome = redraw_record(db_path, number, hex_value, scale)
                if outcome["ok"]:
                    redrawn = redrawn + 1
                else:
                    problems.append(outcome["error"])
            return ok_result({"redrawn": redrawn, "problems": problems})

        def done(outcome):
            message = "Redrew " + str(outcome["value"]["redrawn"]) + " picture(s), each read back first"
            if len(outcome["value"]["problems"]) > 0:
                message = message + "; " + str(len(outcome["value"]["problems"])) + " not: " + outcome["value"]["problems"][0]
            run_search(message)
            refresh_used()

        start_job("Redrawing", work, done)

    def forget_shown():
        chosen = selected_all()
        if len(chosen) == 0:
            return
        question = "Remove this record from the registry? The picture file stays where it is.\n\n" + chosen[0]["path"]
        if len(chosen) > 1:
            question = ("Remove these " + str(len(chosen)) + " records from the registry? The picture files stay where "
                        "they are.")
        if not messagebox.askyesno("Forget record", question):
            return
        numbers = []
        for shown in chosen:
            numbers.append(shown["id"])

        def work():
            removed = 0
            for number in numbers:
                outcome = forget_record(db_path, number)
                if not outcome["ok"]:
                    return outcome
                if outcome["value"]:
                    removed = removed + 1
            return ok_result(removed)

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Forget record", outcome["error"])
                return
            remaining = []
            for other in state["results"]:
                if other["id"] not in numbers:
                    remaining.append(other)
            show_results(remaining, str(outcome["value"]) + " record(s) removed; the files were not touched")
            refresh_footer()
            refresh_used()

        start_job("Forgetting", work, done)

    def show_history():
        """A short link's history, with Undo last change, and its changes to come, with Schedule a change."""
        shown = selected_shown()
        if shown is None or shown["short_code"] == "":
            status.set("Pick a code with a short link: a code that holds its link itself has no history")
            return
        code = shown["short_code"]
        dialog = tk.Toplevel(window)
        dialog.title("Short link history")
        dialog.geometry("760x470")
        dialog.transient(window)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Printed as " + shown["link"] + short_note(shown)).pack(anchor="w")
        now_text = tk.StringVar(value="")
        ttk.Label(body, textvariable=now_text, wraplength=730, justify="left").pack(anchor="w", pady=(2, 8))
        ttk.Label(body, text="Changes to come").pack(anchor="w")
        coming = ttk.Treeview(body, columns=("day", "target"), show="headings", height=3, selectmode="browse")
        coming.heading("day", text="From")
        coming.heading("target", text="Goes to")
        coming.column("day", width=100, stretch=False)
        coming.column("target", width=620)
        coming.pack(fill="x")
        ttk.Label(body, text="Where it has gone, newest first").pack(anchor="w", pady=(8, 0))
        past = ttk.Treeview(body, columns=("when", "old", "new"), show="headings", height=7)
        past.heading("when", text="Changed (UTC)")
        past.heading("old", text="From")
        past.heading("new", text="To")
        past.column("when", width=170, stretch=False)
        past.column("old", width=275)
        past.column("new", width=275)
        past.pack(fill="both", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(8, 0))
        record = {"target": shown["target"], "changes": []}

        def alive():
            return dialog.winfo_exists()

        def fill(outcome):
            status.set("Ready")
            if not alive():
                return
            if not outcome["ok"]:
                now_text.set(outcome["error"])
                return
            record["changes"] = outcome["value"]["changes"]
            for table in (coming, past):
                for item in table.get_children():
                    table.delete(item)
            for change in outcome["value"]["coming"]:
                coming.insert("", "end", iid=str(change["id"]), values=(change["from_day"], change["target"]))
            for change in record["changes"]:
                past.insert("", "end", values=(change["changed"], change["old_target"], change["new_target"]))
            if len(record["changes"]) > 0:
                record["target"] = record["changes"][0]["new_target"]
            now_text.set("Sends people to " + record["target"])

        def load():
            start_job("Reading the history", lambda: link_history(db_path, code), fill)

        def changed(outcome, message):
            if not outcome["ok"]:
                messagebox.showerror("Short link history", outcome["error"], parent=dialog if alive() else window)
                status.set("Nothing changed")
                return
            status.set(message)
            refresh_served()
            if len(state["results"]) > 0:
                run_search(message)
            if alive():
                load()

        def undo():
            if len(record["changes"]) == 0:
                status.set("This short link has not been changed yet")
                return
            back = record["changes"][0]["old_target"]
            if not messagebox.askyesno("Undo last change", "Send " + shown["link"] + " back to\n\n" + back + " ?",
                                       parent=dialog):
                return
            start_job("Undoing the change", lambda: undo_link_change(db_path, code),
                      lambda outcome: changed(outcome, "Sent back to " + back +
                                              "  ·  export the redirect pages again to publish it"))

        def schedule():
            day = simpledialog.askstring("Schedule a change", "From which day? (YYYY-MM-DD)", parent=dialog)
            if day is None:
                return
            day = day.strip()
            if not registry.is_day(day):
                messagebox.showerror("Schedule a change", "A day is written YYYY-MM-DD, such as 2026-12-01.", parent=dialog)
                return
            link = simpledialog.askstring("Schedule a change", "Where should it send people from " + day + "?",
                                          initialvalue=record["target"], parent=dialog)
            if link is None:
                return
            start_job("Scheduling the change", lambda: schedule_link_change(db_path, code, link, day),
                      lambda outcome: changed(outcome, "From " + day + " it sends people to " + link.strip() +
                                              "  ·  exports from that day on use it"))

        def cancel():
            chosen = coming.selection()
            if len(chosen) == 0:
                status.set("Pick the change to cancel first")
                return
            number = int(chosen[0])
            start_job("Cancelling the change", lambda: cancel_link_change(db_path, number),
                      lambda outcome: changed(outcome, "The scheduled change was cancelled"))

        ttk.Button(buttons, text="Undo last change", command=undo).pack(side="left")
        ttk.Button(buttons, text="Schedule a change…", command=schedule).pack(side="left", padx=6)
        ttk.Button(buttons, text="Cancel the scheduled change", command=cancel).pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=6)
        load()

    def offer_due_changes():
        """On start: changes scheduled for a day that has come are offered, never made unasked."""
        today = registry.today_text()
        due = due_link_changes(db_path, today)
        if not due["ok"] or len(due["value"]) == 0:
            return
        lines = []
        for change in due["value"][:8]:
            lines.append(change["from_day"] + "  " + change["code"] + " goes to " + textsafe.clean(change["target"], 80))
        if not messagebox.askyesno("Scheduled changes", str(len(due["value"])) + " scheduled change(s) of destination are "
                                   "due:\n\n" + "\n".join(lines) + "\n\nApply them now? Exports already use them; "
                                   "applying writes them into the registry and each link's history."):
            return

        def done(outcome):
            if not outcome["ok"]:
                messagebox.showerror("Scheduled changes", outcome["error"])
                return
            status.set("Applied " + str(outcome["value"]) + " scheduled change(s)  ·  export the redirect pages again to "
                       "publish them")
            refresh_served()

        start_job("Applying the scheduled changes", lambda: apply_due_changes(db_path, today), done)

    def print_shown():
        """The selected codes on a sheet of labels or as posters (sheets.json), as a PDF or SVG."""
        chosen = selected_all()
        if len(chosen) == 0:
            status.set("Select the codes to print first (Ctrl+click or Shift+click picks several)")
            return
        loaded = sheets.load_sheets(os.path.join(HERE, "sheets.json"))
        layouts = loaded["sheets"]["layouts"]
        names = sorted(layouts)
        dialog = tk.Toplevel(window)
        dialog.title("Print sheet")
        dialog.transient(window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=str(len(chosen)) + " code(s) selected. Layout (sheets.json):").grid(row=0, column=0, sticky="w")
        chooser = ttk.Combobox(body, values=names, state="readonly", width=40)
        chooser.set(names[0])
        chooser.grid(row=1, column=0, sticky="w", pady=4)
        about = tk.StringVar(value="")
        ttk.Label(body, textvariable=about, wraplength=420, justify="left", foreground="#555555").grid(row=2, column=0,
                                                                                                       sticky="w")

        def show_about_layout(event=None):
            layout = layouts[chooser.get()]
            per_page = layout["columns"] * layout["rows"]
            pages = sheets.page_count(layout, len(chosen))
            about.set(layout["about"] + " " + str(per_page) + " per page: " + str(pages) + " page(s).")

        def make():
            layout = layouts[chooser.get()]
            path = filedialog.asksaveasfilename(title="Save the sheet", initialfile="qr-sheet.pdf",
                                                defaultextension=".pdf", parent=dialog,
                                                filetypes=[("PDF", "*.pdf"), ("SVG drawing, one per page", "*.svg")])
            if not path:
                return
            path = registry.display_path(path)
            dialog.destroy()
            numbers = []
            for shown in chosen:
                numbers.append(shown["id"])

            def done(outcome):
                if not outcome["ok"]:
                    messagebox.showerror("Print sheet", outcome["error"])
                    return
                value = outcome["value"]
                message = ("Printed " + str(value["codes"]) + " code(s) on " + str(value["pages"]) + " page(s): " +
                           value["files"][0])
                if len(value["skipped"]) > 0:
                    message = message + "; left out " + str(len(value["skipped"])) + ": " + value["skipped"][0]
                if value["without_logo"] > 0:
                    message = message + "; " + str(value["without_logo"]) + " drawn without their logos"
                if value["smallest_module_mm"] < MIN_MODULE_MM:
                    message = (message + "; modules come out as small as " + str(value["smallest_module_mm"]) +
                               " mm, under the " + str(MIN_MODULE_MM) + " mm most printers and cameras handle well")
                status.set(message)
                try:
                    os.startfile(value["files"][0])
                except (AttributeError, OSError) as error:
                    status.set(message + " (cannot open it: " + str(error) + ")")

            start_job("Printing the sheet", lambda: sheets.print_sheet(db_path, numbers, layout, path), done)

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Make the sheet…", command=make).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", show_about_layout)
        show_about_layout()
        if len(loaded["warnings"]) > 0:
            status.set(loaded["warnings"][0])

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
    detail_changes = ttk.Frame(detail_side)  # these act on every selected result
    detail_changes.pack(anchor="w")
    ttk.Button(detail_changes, text="Change destination…", command=change_destination).pack(side="left")
    ttk.Button(detail_changes, text="Redraw…", command=redraw_shown).pack(side="left", padx=6)
    ttk.Button(detail_changes, text="Forget record", command=forget_shown).pack(side="left")
    ttk.Button(detail_changes, text="Print sheet…", command=print_shown).pack(side="left", padx=6)
    ttk.Button(detail_changes, text="History…", command=show_history).pack(side="left")
    ttk.Label(detail_changes, text="Ctrl+click picks several.", foreground="#555555").pack(side="left", padx=6)
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
        window.after(600, offer_due_changes)
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
    if state["server"] is not None:
        shortlinks.stop_server(state["server"])
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
    for name in ("--db", "--inference", "--inference-timeout", "--model", "--smoke", "--settings", "--export-redirects",
                 "--section"):
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
    if values["--export-redirects"] != "":
        for warning in warnings:
            sys.stderr.write("warning: " + warning + "\n")
        section = values["--section"] or LINK_SECTION
        if section not in shortlinks.SECTIONS:
            print("--section is local or nonlocal")
            return 2
        exported = export_redirects(db_path, os.path.abspath(values["--export-redirects"]), section)
        if not exported["ok"]:
            print(exported["error"])
            return 1
        print("wrote " + str(exported["value"]["written"]) + " " + section + " redirect page(s) to " +
              exported["value"]["folder"])
        if len(exported["value"]["skipped"]) > 0:
            print("skipped (another address or no longer a valid link): " + ", ".join(exported["value"]["skipped"]))
        return 0
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

# ==== stamp v1 | author=kjFriday | hmac-sha256=f8bf3ab391d52c743f3144c47e74e29708a3cc4f711aadf3d554b4f607709c5f ====
