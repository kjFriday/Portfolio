# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/settings.py
# About: QR Palette settings: one human-readable JSON file, settings.json, for everything a user...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette settings: one human-readable JSON file, settings.json, for everything a user may change.

The file lives in %LOCALAPPDATA%\\Generic Company Inc\\GenericCompany.QRPalette\\ (or wherever
--settings points). The window writes it with every setting and its default the first time it runs,
indented and with an "about" text in each section, so it reads like a form. Any setting left out, or
not valid, uses its default and is reported; a file that is not valid JSON is never overwritten.
--ecp and --mcp only read it. settings.example.json beside the program shows the defaults.

Records
  Result    {"ok": bool, "error": str, "value": any}
  Settings  {"path": str, "state": "missing" | "ok" | "broken", "raw": dict as read, "values": dict with
             every setting checked and paths expanded, "warnings": [str]}
"""

import json
import math
import os

DEFAULTS = {
    "about": "QR Palette settings. Edit with any text editor while the program is closed. A setting that is "
             "left out or not valid uses its default (see settings.example.json and README.md). registry: the "
             "SQLite file of QR codes; empty means the program's data folder.",
    "registry": "",
    "pictures": {
        "about": "Where new QR codes are saved and how they are drawn. folder: empty means Pictures\\QR Palette. "
                 "pixels_per_module: the PNG scale. error_correction: L, M, Q or H.",
        "folder": "",
        "pixels_per_module": 8,
        "error_correction": "M",
    },
    "colors": {
        "about": "preset: the ranking in presets/ (mixer, balanced, popular, discover, or your own). "
                 "minimum_contrast: the WCAG contrast against white a color needs to be offered (3.0 keeps 118 "
                 "of the 216). near_distance: how close in OKLab counts as near. rankings_folder: the folder that "
                 "holds presets/ and weights/; empty means beside the program.",
        "preset": "mixer",
        "minimum_contrast": 3.0,
        "near_distance": 0.08,
        "rankings_folder": "",
    },
    "inference": {
        "about": "The local model server: http on 127.0.0.1, ::1 or localhost only. model: the default model for "
                 "ecp_query when a client passes no model_id, and the one the window selects at start; empty "
                 "means a client must choose. require_cloud_disabled: refuse to plan unless the server reports its "
                 "cloud features off (set OLLAMA_NO_CLOUD=1 for Ollama); turning it off lets a signed-in server "
                 "reach the internet. Times are in seconds: timeout_seconds for --ecp and --mcp, "
                 "window_timeout_seconds for the window's Ask. max_answer_tokens and retry_answer_tokens: room for "
                 "a plan, and for one retry when it is cut off.",
        "url": "http://127.0.0.1:11434",
        "model": "",
        "require_cloud_disabled": True,
        "timeout_seconds": 45,
        "window_timeout_seconds": 300,
        "list_timeout_seconds": 3,
        "max_answer_tokens": 256,
        "retry_answer_tokens": 512,
        "context_tokens": 4096,
        "keep_alive": "10m",
    },
    "planner": {
        "about": "How plain-English questions become query plans: the model's rules, worked examples and color "
                 "words. file: empty means planner.json beside the program.",
        "file": "",
    },
    "links": {
        "about": "Short links: links.json holds their two sections (local and nonlocal), the ID length, the tags "
                 "added to destinations and the link templates. file: empty means links.json beside the program. "
                 "use: which section new short links use, local (this computer or your own network) or nonlocal "
                 "(your internet address); the Make tab switches it.",
        "file": "",
        "use": "local",
    },
    "queries": {
        "about": "How many results an answer holds, how long a question may be, and how long one read of the "
                 "registry may take before it is stopped.",
        "default_limit": 20,
        "max_limit": 100,
        "question_characters": 2000,
        "statement_seconds": 2,
    },
    "protocol": {
        "about": "Limits for ECP's MCP server: the longest message line; tool calls per second and the burst "
                 "allowed; the most characters of a link or path in a result, and of a whole result (rows are "
                 "dropped from the end to fit, and truncated is set).",
        "max_message_bytes": 1048576,
        "rate_per_second": 1,
        "rate_burst": 5,
        "max_field_characters": 256,
        "max_result_characters": 40000,
    },
    "audit": {
        "about": "The audit log: one JSON line per ECP call, each holding the SHA-256 of the line before, so any "
                 "change shows. file: empty means audit.jsonl in the program's data folder.",
        "file": "",
    },
}

# (section or "", key, kind, low, high or choices): what each setting may be
SPEC = (
    ("", "registry", "path", None, None),
    ("pictures", "folder", "path", None, None),
    ("pictures", "pixels_per_module", "int", 1, 40),
    ("pictures", "error_correction", "choice", ("L", "M", "Q", "H"), None),
    ("colors", "preset", "name", None, None),
    ("colors", "minimum_contrast", "number", 1.0, 21.0),
    ("colors", "near_distance", "number", 0.0, 1.0),
    ("colors", "rankings_folder", "path", None, None),
    ("inference", "url", "text", None, None),
    ("inference", "model", "text", None, None),
    ("inference", "require_cloud_disabled", "bool", None, None),
    ("inference", "timeout_seconds", "number", 1, 3600),
    ("inference", "window_timeout_seconds", "number", 1, 3600),
    ("inference", "list_timeout_seconds", "number", 0.5, 60),
    ("inference", "max_answer_tokens", "int", 32, 4096),
    ("inference", "retry_answer_tokens", "int", 32, 8192),
    ("inference", "context_tokens", "int", 512, 131072),
    ("inference", "keep_alive", "text", None, None),
    ("planner", "file", "path", None, None),
    ("links", "file", "path", None, None),
    ("links", "use", "choice", ("local", "nonlocal"), None),
    ("queries", "default_limit", "int", 1, 1000),
    ("queries", "max_limit", "int", 1, 1000),
    ("queries", "question_characters", "int", 20, 5000),
    ("queries", "statement_seconds", "number", 0.1, 60),
    ("protocol", "max_message_bytes", "int", 4096, 16777216),
    ("protocol", "rate_per_second", "number", 0.1, 1000),
    ("protocol", "rate_burst", "int", 1, 1000),
    ("protocol", "max_field_characters", "int", 32, 100000),
    ("protocol", "max_result_characters", "int", 1000, 10000000),
    ("audit", "file", "path", None, None),
)


def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def copy_tree(value):
    """A deep copy of plain JSON data."""
    if isinstance(value, dict):
        copied = {}
        for key in value:
            copied[key] = copy_tree(value[key])
        return copied
    if isinstance(value, list):
        copied_list = []
        for item in value:
            copied_list.append(copy_tree(item))
        return copied_list
    return value


def example_text():
    """settings.example.json: every setting with its default, as the window first writes it."""
    return json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n"


def read_text(path):
    """A UTF-8 text file (a byte-order mark is allowed), closed again even when reading fails."""
    handle = open(path, "r", encoding="utf-8-sig")
    try:
        return handle.read()
    finally:
        handle.close()


def expand(path):
    """%VARIABLES% and ~ in a path setting, so "%USERPROFILE%\\Pictures" works as typed."""
    if path == "":
        return ""
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


def describe(kind, low, high):
    if kind == "int":
        return "a whole number from " + str(low) + " to " + str(high)
    if kind == "number":
        return "a number from " + str(low) + " to " + str(high)
    if kind == "choice":
        return "one of " + ", ".join(low)
    if kind == "name":
        return "a preset name (lower-case letters, digits and _)"
    if kind == "bool":
        return "true or false"
    return "text"


def valid(value, kind, low, high):
    if kind in ("text", "path"):
        return isinstance(value, str)
    if kind == "name":
        if not isinstance(value, str) or value == "" or not value[0].isalpha():
            return False
        for character in value:
            if not (character.islower() or character.isdigit() or character == "_") or not character.isascii():
                return False
        return True
    if kind == "choice":
        return value in low
    if kind == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if kind == "int" and not isinstance(value, int):
        return False
    if kind == "number" and not (isinstance(value, (int, float)) and math.isfinite(value)):
        return False
    return low <= value <= high


def load(path):
    """settings.json -> Settings record. Never fails: what cannot be used is reported in "warnings"
    and replaced by its default."""
    state = {"path": path, "state": "missing", "raw": {}, "values": copy_tree(DEFAULTS), "warnings": []}
    if os.path.isfile(path):
        try:
            raw = json.loads(read_text(path))
        except ValueError as error:
            state["state"] = "broken"
            state["warnings"].append(path + " is not valid JSON (" + str(error) + "); using the defaults and "
                                     "leaving the file as it is")
            return state
        except OSError as error:
            state["state"] = "broken"
            state["warnings"].append("cannot read " + path + ": " + str(error) + "; using the defaults")
            return state
        if not isinstance(raw, dict):
            state["state"] = "broken"
            state["warnings"].append(path + " must hold one JSON object; using the defaults")
            return state
        state["state"] = "ok"
        state["raw"] = raw
    warned_sections = []
    for entry in SPEC:
        section, key, kind, low, high = entry
        source = state["raw"]
        target = state["values"]
        name = key
        if section != "":
            name = section + "." + key
            source = state["raw"].get(section, {})
            target = state["values"][section]
            if not isinstance(source, dict):
                if section not in warned_sections:
                    warned_sections.append(section)
                    state["warnings"].append("settings: " + section + " must be an object; using its defaults")
                source = {}
        if key not in source:
            value = target[key]
        elif valid(source[key], kind, low, high):
            value = source[key]
        else:
            value = target[key]
            state["warnings"].append("settings: " + name + " must be " + describe(kind, low, high) + "; using " +
                                     json.dumps(value))
        if kind == "path":
            value = expand(value)
        target[key] = value
    queries = state["values"]["queries"]
    if queries["default_limit"] > queries["max_limit"]:
        queries["default_limit"] = queries["max_limit"]
        state["warnings"].append("settings: queries.default_limit is above max_limit; using " +
                                 str(queries["max_limit"]))
    return state


def save(state, changes):
    """Write settings changed in the window -> Result path. `changes` is [(section, key, value)].
    The rest of the file, including anything added by hand, is kept as it was. A broken file is
    never overwritten. Written to a temporary file first, then moved into place."""
    if state["state"] == "broken":
        return fail(state["path"] + " is not valid JSON; fix it by hand first (nothing was saved)")
    raw = state["raw"]
    if state["state"] == "missing":
        raw = copy_tree(DEFAULTS)
    for change in changes:
        section, key, value = change
        if section == "":
            raw[key] = value
        else:
            if not isinstance(raw.get(section), dict):
                raw[section] = {}
            raw[section][key] = value
    folder = os.path.dirname(os.path.abspath(state["path"]))
    temporary = state["path"] + ".tmp"
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(temporary, "w", encoding="utf-8", newline="\n")
        handle.write(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        handle.close()
        os.replace(temporary, state["path"])
    except OSError as error:
        return fail("cannot save " + state["path"] + ": " + str(error))
    fresh = load(state["path"])
    state["state"] = fresh["state"]
    state["raw"] = fresh["raw"]
    state["values"] = fresh["values"]
    return ok_result(state["path"])


def write_defaults(state):
    """The first run: write every setting with its default, so the file can be read and edited."""
    if state["state"] != "missing":
        return ok_result(state["path"])
    return save(state, [])

# ==== stamp v1 | author=kjFriday | hmac-sha256=fff82d82f8778f8d0bb165802a57ee483a615b42e1508a415208b7e35941052f ====
