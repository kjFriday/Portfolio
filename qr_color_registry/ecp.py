# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/ecp.py
# About: Environment Context Protocol (ECP) 1.0: QR Palette's registry, asked in plain English...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Environment Context Protocol (ECP) 1.0: QR Palette's registry, asked in plain English through a
local model, served to MCP clients as three tools.

This follows the ECP research spec (research/ecp_dual_rail_runtime_spec.md). ECP is an MCP server
(mcp_server.py) with three tools: ecp_list_models, ecp_select_model and ecp_query. This module is
what the tools do. Nothing is kept between calls: a query names its local model by model_id
("name@digest", as ecp_list_models and ecp_select_model give it) or falls back to the default model
in settings.json, and the digest is checked again before every plan.

The model only turns a question into a QueryPlan. The plan is checked against the question's own
words ("grounded") and run on the read-only rail. The model never writes SQL, never sees what is
stored, and never makes a file be opened. A failure is a named outcome (one of KINDS), which the MCP
server returns as an isError result; there are no ECP error codes. Every call is written to the
hash-chained audit log. ECP.md is the paper.

Records
  Engine     {"db", "endpoint", "endpoint_error", "timeout", "app_version", "default_model", "preset",
              "audit_file", "ollama_version"}
  Call       {"tool": str, "client_info": {} as the client says, "request_id": the JSON-RPC id or None}
  Outcome    {"ok": bool, "kind": "ok" | one of KINDS, "detail": str, "value": any}
  QueryPlan  {"intent": "find" | "recommend", "color", "near", "family", "link", "link_exact", "path",
              "limit"}                                                               "" means "any"
  Record     {"id", "hex", "color_name", "color_family", "rank", "payload_url", "target_url", "file_path",
              "net_votes", "created_at", "exists"}      payload_url is what the code holds; target_url is
              where its short link sends people, "" when the code holds its destination itself
  ColorPick  {"hex", "name", "family", "rank", "uses"}
"""

import hashlib
import json
import re
import sys
import time
import unicodedata

import audit
import local_inference
import registry
import swatch
import textsafe

VERSION = "1.0"
ENVIRONMENT = "QR Palette"
SOURCE = "ecp-sqlite-readonly"
TRUST = "untrusted-db-content"
INTERLOCK_STATE = "bypassed"  # QR Palette has no hardware interlock (ECP spec 8.5: --interlock none)
KINDS = ("interlock_fault", "interlock_disabled", "args_invalid", "rate_limited", "prompt_invalid",
         "inference_unavailable", "inference_timeout", "cloud_not_disabled", "model_not_local",
         "model_digest_mismatch", "egress_detected", "plan_unparseable", "plan_invalid", "plan_truncated",
         "db_unavailable", "db_timeout", "db_denied")

# Set from settings.json at start (these are the defaults).
MAX_LINE = 1024 * 1024
QUESTION_LIMIT = 2000
MAX_FIELD_CHARACTERS = 256
MAX_RESULT_CHARACTERS = 40000
REQUIRE_CLOUD_DISABLED = True

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

PLAN_FIELDS = ("intent", "color", "near", "family", "link", "link_exact", "path", "limit")
AUDIT_ID_ROOM = 20
ZERO_WIDTH = (0x061C, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF)  # and the marks LRM, RLM, ALM

# The planner's rules, examples and words. planner.json beside the program holds the same, as plain
# JSON for people to read and change; configure_planner() puts a loaded planner.json in place.
DEFAULT_PLANNER = {
    "about": "How ECP turns a question in plain English into a query plan. rules: what the selected local model "
             "is told, one line each; {families} stands for the list of color families. examples: questions "
             "with the plans they should give, added to the rules. family_words: more words for each color "
             "family. words_meaning_a_code: words that only say \"QR code\". words_to_skip and words_to_trim: "
             "filler words taken off the ends of links and paths. Edit, save and restart.",
    "rules": [
        "You turn one question about a registry of colored QR codes into a JSON query plan. Every QR code has a "
        "link (the text it holds), a color (#rrggbb, in a family such as blue or green) and the path of its "
        "picture file.",
        "Answer with one JSON object and nothing else, with exactly these fields:",
        '  intent: "find" to look QR codes up, "recommend" to suggest colors for a new QR code',
        '  color: a #rrggbb code written in the question, else ""',
        "  near: true when the question asks for colors close to that code",
        '  family: one of {families}, else ""',
        '  link: words the link should contain, copied from the question, else ""',
        '  link_exact: a whole link written in the question, else ""',
        '  path: words from a folder or file name in the question, else ""',
        "  limit: how many results the question wants, 20 when it does not say",
        "Copy text exactly from the question. Never invent a link, a path or a #rrggbb code: a color named in "
        "words (blue, dark green) is a family, not a code.",
    ],
    "examples": [
        {"question": "blue QR codes that link to the shop",
         "plan": {"intent": "find", "color": "", "near": False, "family": "blue", "link": "shop", "link_exact": "",
                  "path": "", "limit": 20}},
        {"question": "which code points to https://example.com/menu?",
         "plan": {"intent": "find", "color": "", "near": False, "family": "", "link": "",
                  "link_exact": "https://example.com/menu", "path": "", "limit": 20}},
        {"question": "suggest two colors for a new code",
         "plan": {"intent": "recommend", "color": "", "near": False, "family": "", "link": "", "link_exact": "",
                  "path": "", "limit": 2}},
        {"question": "codes close to #3366cc in the marketing folder",
         "plan": {"intent": "find", "color": "#3366cc", "near": True, "family": "", "link": "", "link_exact": "",
                  "path": "marketing", "limit": 20}},
    ],
    "family_words": swatch.FAMILY_WORDS,
    "words_meaning_a_code": ["qr", "qrs", "code", "codes", "one", "ones", "please"],
    "words_to_skip": ["the", "a", "an", "my", "our", "your", "this", "that", "these", "those", "to", "of", "page",
                      "site", "website", "url", "link", "links", "code", "codes", "qr", "one", "ones"],
    "words_to_trim": ["pages", "folder", "folders", "file", "files", "directory", "picture", "pictures", "image"],
}

# Set by configure_planner() (from DEFAULT_PLANNER until a planner.json is loaded).
PLANNER_RULES = ""
SYSTEM_PROMPT = ""
SYSTEM_PROMPT_SHA256 = ""
EXAMPLES = []
EDGE_WORDS = []
CODE_WORDS = []


# --- Records ---------------------------------------------------------------------------------------

def ok_result(value):
    return {"ok": True, "error": "", "value": value}


def fail(error):
    return {"ok": False, "error": error, "value": None}


def outcome(kind, detail, value):
    return {"ok": kind == "ok", "kind": kind, "detail": detail, "value": value}


def new_call(tool, client_info, request_id):
    """Who asked, for the audit log: the tool, the client's own (untrusted) description of itself, and
    the request's id."""
    if not isinstance(client_info, dict):
        client_info = {}
    return {"tool": tool, "client_info": client_info, "request_id": request_id}


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_plan():
    return {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "",
            "limit": registry.DEFAULT_LIMIT}


def plan_filters(plan):
    filters = registry.empty_filters()
    for key in ("color", "near", "family", "link", "link_exact", "path"):
        filters[key] = plan[key]
    return filters


def plan_schema():
    """The JSON schema a model's plan must follow: flat, every field required, "" for unset, no
    $ref and no keyword the grammar converter ignores (ECP spec 5.3-5.4). It is fixed by the program,
    never built from user text, and its hash goes into every audit record."""
    return {"type": "object",
            "properties": {"intent": {"type": "string", "enum": ["find", "recommend"]},
                           "color": {"type": "string", "maxLength": 7},
                           "near": {"type": "boolean"},
                           "family": {"type": "string", "enum": [""] + list(swatch.FAMILIES)},
                           "link": {"type": "string", "maxLength": 200},
                           "link_exact": {"type": "string", "maxLength": 2048},
                           "path": {"type": "string", "maxLength": 260},
                           "limit": {"type": "integer", "minimum": 1, "maximum": registry.MAX_LIMIT}},
            "required": list(PLAN_FIELDS), "additionalProperties": False}


def schema_sha256():
    return sha256_text(json.dumps(plan_schema(), sort_keys=True, separators=(",", ":")))


def new_engine(db_path, inference_url, timeout, app_version):
    parsed = local_inference.parse_endpoint(inference_url)
    endpoint = None
    if parsed["ok"]:
        endpoint = parsed["value"]
    return {"db": db_path, "endpoint": endpoint, "endpoint_error": parsed["error"], "timeout": timeout,
            "app_version": app_version, "default_model": "", "preset": swatch.DEFAULT_PRESET, "audit_file": "",
            "ollama_version": ""}


# --- The planner's configuration (planner.json) ----------------------------------------------------

def text_list(value):
    """True for a list of strings."""
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, str):
            return False
    return True


def load_planner(path):
    """planner.json -> {"planner": a whole planner configuration, "warnings": [str]}. Parts that are
    missing or not valid keep their defaults, and say so."""
    planner = {}
    for key in DEFAULT_PLANNER:
        planner[key] = DEFAULT_PLANNER[key]
    warnings = []
    try:
        handle = open(path, "r", encoding="utf-8-sig")
        try:
            text = handle.read()
        finally:
            handle.close()
        data = json.loads(text)
    except (OSError, ValueError) as error:
        return {"planner": planner, "warnings": ["cannot use " + path + " (" + str(error) + "); using the built-in "
                                                 "planner"]}
    if not isinstance(data, dict):
        return {"planner": planner, "warnings": [path + " must hold one JSON object; using the built-in planner"]}
    if "rules" in data:
        if text_list(data["rules"]) and len(data["rules"]) > 0:
            planner["rules"] = data["rules"]
        else:
            warnings.append("planner: rules must be a list of lines")
    if "examples" in data:
        examples = []
        if isinstance(data["examples"], list):
            for example in data["examples"]:
                if (isinstance(example, dict) and isinstance(example.get("question"), str) and
                        example["question"].strip() != "" and check_plan_shape(example.get("plan")) == "" and
                        example["plan"]["family"] in [""] + list(swatch.FAMILIES) and
                        example["plan"]["intent"] in ("find", "recommend")):
                    examples.append({"question": example["question"], "plan": example["plan"]})
                else:
                    warnings.append("planner: an example was left out; each needs a question and a whole plan")
        if len(examples) > 0:
            planner["examples"] = examples
        else:
            warnings.append("planner: no usable examples; using the built-in ones")
    if "family_words" in data:
        words = {}
        if isinstance(data["family_words"], dict):
            for word in data["family_words"]:
                meant = data["family_words"][word]
                if isinstance(meant, str) and meant in swatch.FAMILIES and word.strip() != "":
                    words[word.strip().lower()] = meant
                else:
                    warnings.append("planner: family_words: " + json.dumps(word) + " must name one of " +
                                    ", ".join(swatch.FAMILIES))
            planner["family_words"] = words
        else:
            warnings.append("planner: family_words must be an object of words and families")
    for key in ("words_meaning_a_code", "words_to_skip", "words_to_trim"):
        if key in data:
            if text_list(data[key]):
                lowered = []
                for item in data[key]:
                    lowered.append(item.lower())
                planner[key] = lowered
            else:
                warnings.append("planner: " + key + " must be a list of words")
    return {"planner": planner, "warnings": warnings}


def configure_planner(planner):
    """Put a planner configuration in place: the system prompt (rules, then the worked examples)
    and the word lists."""
    global PLANNER_RULES, SYSTEM_PROMPT, SYSTEM_PROMPT_SHA256, EXAMPLES, EDGE_WORDS, CODE_WORDS
    PLANNER_RULES = "\n".join(planner["rules"]).replace("{families}", ", ".join(swatch.FAMILIES))
    EXAMPLES = list(planner["examples"])
    lines = [PLANNER_RULES, "", "Examples, each a question and the plan to answer with:"]
    for example in EXAMPLES:
        lines.append("Question: " + example["question"])
        lines.append("Plan: " + json.dumps(example["plan"]))
    SYSTEM_PROMPT = "\n".join(lines)
    SYSTEM_PROMPT_SHA256 = sha256_text(SYSTEM_PROMPT)
    EDGE_WORDS = list(planner["words_to_skip"]) + list(planner["words_to_trim"])
    CODE_WORDS = list(planner["words_meaning_a_code"])
    swatch.FAMILY_WORDS = dict(planner["family_words"])


def planner_text(planner):
    """planner.json as people read it: indented, one setting per line."""
    return json.dumps(planner, indent=2, ensure_ascii=False) + "\n"


# --- Planning: direct, model, grounding ------------------------------------------------------------

def is_link_like(text):
    if text == "" or len(text.split()) != 1:
        return False
    lowered = text.lower()
    return "://" in lowered or lowered.startswith("mailto:") or lowered.startswith("tel:")


def is_path_like(text):
    if text == "" or "\n" in text:
        return False
    lowered = text.lower()
    if re.match(r"^[a-z]:[\\/]", lowered) or text.startswith("\\\\") or text.startswith("/"):
        return True
    return (lowered.endswith(".png") or lowered.endswith(".svg")) and len(text.split()) == 1


def words_of(text):
    return re.findall(r"[a-z0-9]+", text.casefold())


def question_hexes(text):
    found = []
    for match in re.findall(r"#[0-9a-fA-F]{6}(?![0-9a-zA-Z])", text):
        found.append(match.lower())
    return found


def direct_plan(question):
    """Questions that need no model: a color code, a link, a picture's path, or a family word
    ("blue", "blue QR codes"). -> QueryPlan or None."""
    text = question.strip()
    plan = empty_plan()
    color = swatch.normalize_hex(text)
    if color != "" and (text.startswith("#") or re.search(r"[0-9]", text) is not None):
        plan["color"] = color  # a bare word made of hex letters ("decade") is not a color code
        return plan
    if is_link_like(text):
        plan["link_exact"] = text
        return plan
    if is_path_like(text):
        plan["path"] = text
        return plan
    words = []
    for word in words_of(text):
        if word not in CODE_WORDS:
            words.append(word)
    if len(words) == 1 and swatch.family_of_word(words[0]) != "":
        plan["family"] = swatch.family_of_word(words[0])
        return plan
    return None


def find_plan(by, text, near, limit):
    """The plan for a lookup by QR code or by color (the window's Find tab) -> Result QueryPlan.
    By QR code: a whole link matches exactly, a path matches its file, other text is words the
    link contains. By color: #rrggbb (or near it), or a family word."""
    plan = empty_plan()
    plan["limit"] = registry.clamp_limit(limit)
    if by == "qr_code":
        if is_link_like(text):
            plan["link_exact"] = text
        elif is_path_like(text):
            plan["path"] = text
        else:
            plan["link"] = text
        return ok_result(plan)
    color = swatch.normalize_hex(text)
    family = swatch.family_of_word(text)
    if color != "":
        plan["color"] = color
        plan["near"] = near
    elif family != "":
        plan["family"] = family
    else:
        return fail("a color is #rrggbb or one of: " + ", ".join(swatch.FAMILIES))
    return ok_result(plan)


def trim_edges(value):
    """Words such as "page", "the" or "folder" taken off both ends: "the careers page" -> "careers"."""
    words = value.split()
    while len(words) > 0 and re.sub(r"[^\w]", "", words[0].casefold()) in EDGE_WORDS:
        words = words[1:]
    while len(words) > 0 and re.sub(r"[^\w]", "", words[len(words) - 1].casefold()) in EDGE_WORDS:
        words = words[:len(words) - 1]
    return " ".join(words)


def check_plan_shape(value):
    """"" when a model's answer is a whole QueryPlan with the right types, else what is wrong."""
    if not isinstance(value, dict):
        return "the answer is not a JSON object"
    for key in value:
        if key not in PLAN_FIELDS:
            return "unknown field " + json.dumps(key)
    for key in ("intent", "color", "family", "link", "link_exact", "path"):
        if not isinstance(value.get(key), str):
            return key + " must be a string"
    if not isinstance(value.get("near"), bool):
        return "near must be true or false"
    limit = value.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int):
        return "limit must be a whole number"
    return ""


def family_in_question(family, words):
    for word in words:
        if swatch.family_of_word(word) == family:
            return True
    return False


def ground(proposed, question):
    """Keep only what the question supports -> (QueryPlan, clamped: [str]). Links, paths and color
    codes must be written in the question; a family must be named in it; a color code in the
    question always wins over the model's. Every change is listed."""
    clamped = []
    plan = empty_plan()
    lowered = question.casefold()
    words = words_of(question)
    if proposed["intent"] in ("find", "recommend"):
        plan["intent"] = proposed["intent"]
    else:
        clamped.append("intent: " + json.dumps(proposed["intent"]) + " read as find")
    written = question_hexes(question)
    color = swatch.normalize_hex(proposed["color"])
    if len(written) > 0:
        plan["color"] = written[0]
        if color != "" and color != written[0]:
            clamped.append("color: " + color + " replaced by " + written[0] + " from the question")
    elif color != "" and color[1:] in lowered:
        plan["color"] = color
    elif proposed["color"] != "":
        clamped.append("color: dropped " + json.dumps(proposed["color"]) + ", not written in the question")
    plan["near"] = proposed["near"] and plan["color"] != ""
    family = swatch.family_of_word(proposed["family"])
    if family != "" and family_in_question(family, words):
        plan["family"] = family
    elif proposed["family"] != "":
        clamped.append("family: dropped " + json.dumps(proposed["family"]) + ", not named in the question")
    for key in ("link", "link_exact", "path"):
        value = proposed[key].strip()
        if value == "":
            continue
        if value.casefold() in lowered:
            if key == "link_exact":
                plan[key] = value
            else:
                plan[key] = trim_edges(value)
        else:
            clamped.append(key + ": dropped " + json.dumps(value[:80]) + ", not in the question")
    if plan["link"] != "" and plan["link"] == plan["link_exact"]:
        plan["link"] = ""
    plan["limit"] = registry.clamp_limit(proposed["limit"])
    if plan["limit"] != proposed["limit"]:
        clamped.append("limit: " + str(proposed["limit"]) + " clamped to " + str(plan["limit"]))
    return plan, clamped


def model_plan(engine, model, question):
    """Ask the model for a plan (one retry with more room when its answer is cut off), then check and
    ground it -> Outcome {"plan", "clamped", "inference_ns"}."""
    answered = local_inference.generate_json(engine["endpoint"], model, SYSTEM_PROMPT, question, plan_schema(),
                                             engine["timeout"], local_inference.PLAN_OPTIONS["num_predict"])
    if not answered["ok"] and answered["kind"] == "plan_truncated":
        answered = local_inference.generate_json(engine["endpoint"], model, SYSTEM_PROMPT, question, plan_schema(),
                                                 engine["timeout"], local_inference.RETRY_ANSWER_TOKENS)
    if not answered["ok"]:
        return outcome(answered["kind"], answered["error"], None)
    try:
        proposed = json.loads(answered["value"]["text"])
    except ValueError:
        return outcome("plan_unparseable", "the model's plan is not JSON", None)
    problem = check_plan_shape(proposed)
    if problem != "":
        return outcome("plan_invalid", problem, None)
    plan, clamped = ground(proposed, question)
    return outcome("ok", "", {"plan": plan, "clamped": clamped, "inference_ns": answered["value"]["inference_ns"]})


# --- The environment (read-only) -------------------------------------------------------------------

def read_environment(engine):
    """Everything an answer needs, read in one short visit on the read-only rail -> Outcome
    {"rows", "counts", "votes", "vote_map", "used"}. The connection is closed before returning."""
    opened = registry.connect(engine["db"], True)
    if not opened["ok"]:
        return outcome("db_unavailable", opened["error"], None)
    connection = opened["value"]
    try:
        snapshot = {"rows": registry.all_rows(connection), "counts": registry.counts(connection),
                    "votes": registry.vote_log(connection), "vote_map": registry.vote_map(connection),
                    "used": registry.colors_in_use(connection)}
    except Exception as error:
        text = str(error)
        kind = "db_unavailable"
        if "interrupted" in text:
            kind = "db_timeout"
        elif "not authorized" in text or "prohibited" in text:
            kind = "db_denied"
        return outcome(kind, "cannot read the registry: " + text, None)
    finally:
        registry.close(connection)
    return outcome("ok", "", snapshot)


def capped(text, flags):
    """A string cut to MAX_FIELD_CHARACTERS, noting in flags["truncated"] when it was."""
    if len(text) > MAX_FIELD_CHARACTERS:
        flags["truncated"] = True
        return text[:MAX_FIELD_CHARACTERS]
    return text


def neutral(text, flags):
    """A string read from the registry, as it may leave (ECP spec 9.6): no control characters (tab
    and newline included), no zero-width or direction characters, NFC, and capped."""
    kept = []
    for character in textsafe.clean(str(text), None):
        if ord(character) >= 0x20 and ord(character) not in ZERO_WIDTH:
            kept.append(character)
    return capped(unicodedata.normalize("NFC", "".join(kept)), flags)


def describe_plan(plan):
    parts = []
    if plan["color"] != "":
        if plan["near"]:
            parts.append("colors near " + plan["color"])
        else:
            parts.append("color " + plan["color"])
    if plan["family"] != "":
        parts.append("family " + plan["family"])
    if plan["link_exact"] != "":
        parts.append('link "' + plan["link_exact"] + '"')
    if plan["link"] != "":
        parts.append('link containing "' + plan["link"] + '"')
    if plan["path"] != "":
        parts.append('path containing "' + plan["path"] + '"')
    return ", ".join(parts)


def run_plan(snapshot, plan, preset):
    """A checked plan against a snapshot -> {"records", "colors", "summary", "truncated"}."""
    flags = {"truncated": False}
    ranked = swatch.rank_colors(preset, snapshot["votes"])
    order = []
    places = {}
    if ranked["ok"]:
        order = ranked["value"]
        places = swatch.rank_places(order)
    records = []
    colors = []
    if plan["intent"] == "recommend":
        uses = {}
        for used in snapshot["used"]:
            uses[used["hex"]] = used["uses"]
        for color in swatch.usable_board(order):
            if len(colors) >= plan["limit"]:
                break
            if plan["family"] != "" and swatch.family(color) != plan["family"]:
                continue
            colors.append({"hex": color, "name": swatch.color_name(color), "family": swatch.family(color),
                           "rank": places.get(color), "uses": uses.get(color, 0)})
        names = []
        for pick in colors:
            names.append(pick["hex"] + " " + pick["name"])
        summary = ("Top " + str(len(colors)) + " color(s) for a new QR code (preset " + preset +
                   (", family " + plan["family"] if plan["family"] != "" else "") + "): " + ", ".join(names) + ".")
        return {"records": records, "colors": colors, "summary": summary, "truncated": False}
    for row in registry.find_rows(snapshot["rows"], plan_filters(plan), plan["limit"]):
        records.append({"id": row["id"], "hex": neutral(row["hex"], flags), "color_name": neutral(row["name"], flags),
                        "color_family": neutral(row["family"], flags), "rank": places.get(row["hex"]),
                        "payload_url": neutral(row["link"], flags), "target_url": neutral(row["target"], flags),
                        "file_path": neutral(row["path"], flags),
                        "net_votes": snapshot["vote_map"].get(row["hex"], 0),
                        "created_at": neutral(row["created"], flags), "exists": registry.file_state(row["path"], True)})
    wanted = describe_plan(plan)
    if wanted == "":
        summary = "The " + str(len(records)) + " newest QR code(s)."
    elif len(records) == 0:
        summary = "No QR codes match " + wanted + "."
    else:
        summary = str(len(records)) + " QR code(s) match " + wanted + "."
    return {"records": records, "colors": colors, "summary": summary, "truncated": flags["truncated"]}


def fit_result(value):
    """Drop trailing records until the result fits MAX_RESULT_CHARACTERS (ECP spec 4.10), keeping
    AUDIT_ID_ROOM characters free for the audit_id, which is only known once the call is logged."""
    while (len(value["records"]) > 0 and
           len(json.dumps(value, ensure_ascii=False)) + AUDIT_ID_ROOM > MAX_RESULT_CHARACTERS):
        value["records"] = value["records"][:len(value["records"]) - 1]
        value["truncated"] = True
    value["row_count"] = len(value["records"])
    return value


# --- The three tools ------------------------------------------------------------------------------

def ollama_version(engine):
    if engine["ollama_version"] == "" and engine["endpoint"] is not None:
        found = local_inference.version(engine["endpoint"])
        if found["ok"]:
            engine["ollama_version"] = found["value"]
    return engine["ollama_version"]


def write_audit(engine, fields):
    """One audit line for a call -> its audit_id, or 0 when there is no log (or it cannot be written,
    which is said on stderr: the answer is not held back)."""
    if engine["audit_file"] == "":
        return 0
    fields["ollama_version"] = ollama_version(engine)
    written = audit.append(engine["audit_file"], fields)
    if not written["ok"]:
        sys.stderr.write("audit: " + written["error"] + "\n")
        return 0
    return written["value"]


def finish(engine, call, started, result, extra):
    """Audit a finished call and return its Outcome (the audit_id goes into a successful value)."""
    fields = {"request_id": call["request_id"], "tool": call["tool"], "client_info": call["client_info"],
              "result_kind": result["kind"], "elapsed_ms": int((time.time() - started) * 1000),
              "interlock_state": INTERLOCK_STATE}
    for key in extra:
        fields[key] = extra[key]
    if not result["ok"]:
        fields["detail"] = result["detail"][:200]
    number = write_audit(engine, fields)
    if result["ok"] and isinstance(result["value"], dict) and "audit_id" in result["value"]:
        result["value"]["audit_id"] = number
    return result


def endpoint_or_error(engine):
    if engine["endpoint"] is None:
        return outcome("inference_unavailable", engine["endpoint_error"], None)
    return None


def list_models(engine, call):
    """ecp_list_models -> Outcome {"models": [LocalModel], "cloud_disabled": bool}."""
    started = time.time()
    problem = endpoint_or_error(engine)
    if problem is None:
        listed = local_inference.list_models(engine["endpoint"], local_inference.LIST_TIMEOUT, engine["default_model"])
        if not listed["ok"]:
            problem = outcome(listed["kind"], listed["error"], None)
    if problem is not None:
        return finish(engine, call, started, problem, {})
    disabled = local_inference.cloud_disabled(engine["endpoint"])
    value = {"models": listed["value"], "cloud_disabled": disabled["ok"] and disabled["value"]}
    return finish(engine, call, started, outcome("ok", "", value), {})


def find_local(engine, name):
    """The model by name on a fresh /api/tags -> Outcome LocalModel."""
    if local_inference.is_cloud_name(name):
        return outcome("model_not_local", name + " names a cloud model", None)
    listed = local_inference.list_models(engine["endpoint"], local_inference.LIST_TIMEOUT, engine["default_model"])
    if not listed["ok"]:
        return outcome(listed["kind"], listed["error"], None)
    for model in listed["value"]:
        if model["name"] == name:
            return outcome("ok", "", model)
    return outcome("model_not_local", name + " is not a local model here", None)


def select_model(engine, name, call):
    """ecp_select_model: check the model is local, pin its digest and load it; nothing is kept
    -> Outcome {"model_id", "name", "digest", "supports_thinking", "loaded", "load_duration_ns"}."""
    started = time.time()
    found = endpoint_or_error(engine)
    if found is None:
        found = find_local(engine, name)
    if found["ok"]:
        shown = local_inference.show(engine["endpoint"], name, local_inference.LIST_TIMEOUT)
        if not shown["ok"]:
            found = outcome(shown["kind"], shown["error"], None)
        elif shown["value"]["remote"]:
            found = outcome("model_not_local", name + " is served from another host", None)
    if found["ok"]:
        model = found["value"]
        warmed = local_inference.warm(engine["endpoint"], name, engine["timeout"])
        if not warmed["ok"]:
            found = outcome(warmed["kind"], warmed["error"], None)
        else:
            found = outcome("ok", "", {"model_id": model["model_id"], "name": name, "digest": model["digest"],
                                       "supports_thinking": "thinking" in model["capabilities"],
                                       "loaded": warmed["value"]["loaded"],
                                       "load_duration_ns": warmed["value"]["load_duration_ns"]})
    return finish(engine, call, started, found, {"model_id": name})


def resolve_model(engine, model_id):
    """The model a query names (or the default model), checked on a fresh /api/tags: local, not
    cloud, and the same digest it was pinned with -> Outcome LocalModel."""
    wanted = model_id or engine["default_model"]
    if wanted == "":
        return outcome("args_invalid", "choose a local model first: ecp_list_models, then pass its model_id", None)
    name = wanted
    digest = ""
    if "@" in wanted:
        name = wanted[:wanted.rindex("@")]
        digest = wanted[wanted.rindex("@") + 1:]
    problem = endpoint_or_error(engine)
    if problem is not None:
        return problem
    found = find_local(engine, name)
    if not found["ok"]:
        return found
    if digest != "" and digest != found["value"]["digest"]:
        return outcome("model_digest_mismatch", name + " is not the model that was pinned", None)
    return found


def query(engine, prompt, model_id, call):
    """ecp_query: plan and run one read-only lookup from plain English -> Outcome {"model_id",
    "plan_used", "records", "colors", "row_count", "truncated", "interlock_state", "source",
    "trust", "audit_id", "summary"}."""
    started = time.time()
    question = textsafe.clean(prompt, QUESTION_LIMIT).strip()
    extra = {"prompt_sha256": sha256_text(prompt), "model_id": model_id or engine["default_model"],
             "schema_sha256": schema_sha256(), "system_prompt_sha256": SYSTEM_PROMPT_SHA256}
    if question == "":
        return finish(engine, call, started, outcome("prompt_invalid", "the question is empty", None), extra)
    model = resolve_model(engine, model_id)
    if not model["ok"]:
        return finish(engine, call, started, model, extra)
    extra["model_id"] = model["value"]["model_id"]
    plan = direct_plan(question)
    planner = "direct"
    clamped = []
    if plan is None:
        planner = "model"
        if REQUIRE_CLOUD_DISABLED:
            disabled = local_inference.cloud_disabled(engine["endpoint"])
            if not disabled["ok"]:
                return finish(engine, call, started, outcome(disabled["kind"], disabled["error"], None), extra)
            if not disabled["value"]:
                return finish(engine, call, started,
                              outcome("cloud_not_disabled", "Ollama's cloud features are on; set OLLAMA_NO_CLOUD=1 "
                                      "for the Ollama server (or allow it in settings.json)", None), extra)
        planned = model_plan(engine, model["value"], question)
        if not planned["ok"]:
            extra["plan_rejected_reason"] = planned["kind"]
            return finish(engine, call, started, planned, extra)
        plan = planned["value"]["plan"]
        clamped = planned["value"]["clamped"]
        extra["inference_ns"] = planned["value"]["inference_ns"]
    snapshot = read_environment(engine)
    extra["progress_fired"] = snapshot["kind"] == "db_timeout"
    if not snapshot["ok"]:
        return finish(engine, call, started, snapshot, extra)
    ran = run_plan(snapshot["value"], plan, engine["preset"])
    plan_used = {"planner": planner, "clamped": clamped}
    for key in PLAN_FIELDS:
        plan_used[key] = plan[key]
    value = fit_result({"model_id": model["value"]["model_id"], "plan_used": plan_used, "records": ran["records"],
                        "colors": ran["colors"], "row_count": 0, "truncated": ran["truncated"],
                        "interlock_state": INTERLOCK_STATE, "source": SOURCE, "trust": TRUST, "audit_id": 0,
                        "summary": ran["summary"]})
    extra["plan_used"] = plan_used
    extra["clamped"] = clamped
    extra["row_count"] = value["row_count"]
    extra["truncated"] = value["truncated"]
    extra["bytes_returned"] = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    return finish(engine, call, started, outcome("ok", "", value), extra)


# --- JSON-RPC (the framing the MCP server uses) ----------------------------------------------------

def result_message(number, value):
    return {"jsonrpc": "2.0", "id": number, "result": value}


def error_message(number, code, message, data):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": number, "error": error}


def request_parts(message):
    """A parsed message -> (id, method, params, error message or None, is notification)."""
    if not isinstance(message, dict):
        return None, "", {}, error_message(None, INVALID_REQUEST, "a message is one JSON object", None), False
    notification = "id" not in message
    number = message.get("id")
    if not notification and (number is None or isinstance(number, bool) or not isinstance(number, (int, str))):
        return None, "", {}, error_message(None, INVALID_REQUEST, "id must be a number or a string", None), False
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return number, "", {}, error_message(number, INVALID_REQUEST, "not a JSON-RPC 2.0 request", None), notification
    params = message.get("params", {})
    if not isinstance(params, dict):
        return number, "", {}, error_message(number, INVALID_PARAMS, "params must be an object", None), notification
    return number, message["method"], params, None, notification


def parse_line(line):
    """One line of bytes -> (message or batch, error response or None)."""
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None, error_message(None, PARSE_ERROR, "a message must be UTF-8", None)
    try:
        message = json.loads(text)
    except ValueError:
        return None, error_message(None, PARSE_ERROR, "not JSON", None)
    return message, None


def write_message(writer, message):
    """One message (or batch answer) as one line: ASCII JSON, no raw newlines inside, one \\n."""
    try:
        writer.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")
        writer.flush()
    except (OSError, ValueError):
        return False
    return True


def serve(handler, state, reader, writer):
    """Read one message per line until the input ends; answer each request on its own line.
    Unexpected errors become JSON-RPC internal errors, never a traceback on stdout."""
    while True:
        try:
            line = reader.readline(MAX_LINE + 1)
        except (OSError, ValueError, KeyboardInterrupt):
            return 0
        if line == b"":
            return 0
        if len(line) > MAX_LINE and not line.endswith(b"\n"):
            while True:
                rest = reader.readline(MAX_LINE + 1)
                if rest == b"" or rest.endswith(b"\n"):
                    break
            response = error_message(None, INVALID_REQUEST, "a message may be at most " + str(MAX_LINE) + " bytes",
                                     None)
        elif line.strip() == b"":
            continue
        else:
            message, response = parse_line(line.strip())
            if response is None:
                try:
                    response = handler(state, message)
                except KeyboardInterrupt:
                    return 0
                except Exception as error:
                    sys.stderr.write("internal error: " + repr(error) + "\n")
                    number = None
                    if isinstance(message, dict) and isinstance(message.get("id"), (int, str)):
                        number = message.get("id")
                    response = error_message(number, INTERNAL_ERROR, "internal error", None)
        if response is not None:
            if not write_message(writer, response):
                return 0


configure_planner(DEFAULT_PLANNER)

# ==== stamp v1 | author=kjFriday | hmac-sha256=252770f35ca4ac997d45aee59634bb12e0788dc345c3679c7eb6a858d730794d ====
