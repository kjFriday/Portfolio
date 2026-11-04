# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: ecp.py
# About: ECP 1.0: QR Palette's registry asked in plain English through a local model.
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""ECP 1.0: QR Palette's registry asked in plain English through a local model.

The Environment Context Protocol (ECP) 1.0 serves the registry to MCP clients as three tools.

This follows the ECP research spec (docs/research/ecp_dual_rail_runtime_spec.md). ECP is an MCP server
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
              "audit_file", "ollama_version", "links": links.json as shortlinks.load_links gives it,
              "scans_vote": whether scans feed the ranking (settings.json: colors.scans_vote)}
  Call       {"tool": str, "client_info": {} as the client says, "request_id": the JSON-RPC id or None}
  Outcome    {"ok": bool, "kind": "ok" | one of KINDS, "detail": str, "value": any}
  QueryPlan  {"intent": "find" | "recommend", "color", "near", "family", "link", "link_exact", "path",
              "section": "" | "local" | "nonlocal", "short": bool, "limit"}         "" means "any"
  Record     {"id", "hex", "color_name", "color_family", "rank", "payload_url", "target_url", "section",
              "file_path", "net_votes", "created_at", "exists"}      payload_url is what the code holds;
              target_url is where its short link sends people, "" when the code holds its destination
              itself; section is the short link's section ("local" or "nonlocal"), "" for no short link
  ColorPick  {"hex", "name", "family", "rank", "uses"}

Who calls it: mcp_server.py (the three tools, and the JSON-RPC framing at the end of this file),
the window's Ask row (gui/find_tab.py: list_models, select_model and query), finding.py (find_plan
and plan_filters, with no model) and app_settings.py (load_planner, configure_planner). It calls
local_inference.py for Ollama, registry.py for the rows, swatch.py for colors and rankings,
shortlinks.py for short-link sections and audit.py for the log.

Main flow of one ecp_query (query):
  1. Clean the question and refuse an empty one.
  2. Resolve the model: local, not a cloud model, and the digest it was pinned with.
  3. Plan: direct_plan answers a bare color code, link, path or family word with no model;
     otherwise the cloud check, then model_plan asks the model and ground() keeps only what the
     question's own words support.
  4. Read everything the answer needs in one visit on the read-only rail (read_environment).
  5. Run the plan in Python (run_plan): records that match, or colors to recommend.
  6. Cut the result to MAX_RESULT_CHARACTERS (fit_result), write the audit line (finish) and
     put its audit_id into the answer.

JSON-RPC 2.0, in short: a request is {"jsonrpc": "2.0", "id", "method", "params"}; a notification
is the same without an id and gets no answer; an answer carries the request's id and either a
"result" or an "error" {"code", "message", "data"}. The error codes -32700 to -32603 are the
standard's own. MCP's stdio transport sends one JSON message per line.

Start reading at query.
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
import shortlinks
import swatch
import textsafe

# VERSION and ENVIRONMENT name the protocol version and the environment served (no other module
# reads them). SOURCE and TRUST label every query answer: where its records came from (the read-only
# SQLite rail) and how far to trust them (stored text came from people and may hold anything, so a
# client treats it as data, never as instructions). KINDS are the named outcomes of a failed call.
VERSION = "1.0"
ENVIRONMENT = "QR Palette"
SOURCE = "ecp-sqlite-readonly"
TRUST = "untrusted-db-content"
INTERLOCK_STATE = "bypassed"  # QR Palette has no hardware interlock (ECP spec 8.5: --interlock none)
KINDS = ("interlock_fault", "interlock_disabled", "args_invalid", "rate_limited", "prompt_invalid",
         "inference_unavailable", "inference_timeout", "cloud_not_disabled", "model_not_local",
         "model_digest_mismatch", "egress_detected", "plan_unparseable", "plan_invalid", "plan_truncated",
         "db_unavailable", "db_timeout", "db_denied")

# Set from settings.json at start (these are the defaults). MAX_LINE: bytes in one JSON-RPC line;
# QUESTION_LIMIT: characters of a question; MAX_FIELD_CHARACTERS: characters of one stored string in
# a Record; MAX_RESULT_CHARACTERS: characters of a whole answer as JSON; REQUIRE_CLOUD_DISABLED: a
# model plan needs Ollama's cloud features off.
MAX_LINE = 1024 * 1024
QUESTION_LIMIT = 2000
MAX_FIELD_CHARACTERS = 256
MAX_RESULT_CHARACTERS = 40000
REQUIRE_CLOUD_DISABLED = True

# JSON-RPC 2.0's own error codes (section 5.1 of its specification)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# PLAN_FIELDS: a QueryPlan's fields, in order; PLAN_TEXT_FIELDS: those that are strings; SECTIONS:
# the short-link sections; AUDIT_ID_ROOM: characters kept free in an answer for its audit_id;
# ZERO_WIDTH: invisible characters neutral() takes out of stored text (zero-width space, non-joiner
# and joiner, word joiner, byte-order mark)
PLAN_FIELDS = ("intent", "color", "near", "family", "link", "link_exact", "path", "section", "short", "limit")
PLAN_TEXT_FIELDS = ("intent", "color", "family", "link", "link_exact", "path", "section")
SECTIONS = ("local", "nonlocal")
AUDIT_ID_ROOM = 20
ZERO_WIDTH = (0x061C, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF)  # and the marks LRM, RLM, ALM

# The planner's rules, examples and words. planner.json beside the program holds the same, as plain
# JSON for people to read and change; configure_planner() puts a loaded planner.json in place.
DEFAULT_PLANNER = {
    "about": "How ECP turns a question in plain English into a query plan. rules: what the selected local model "
             "is told, one line each; {families} stands for the list of color families. examples: questions "
             "with the plans they should give, added to the rules. family_words: more words for each color "
             "family. section_words: the words that name each section of short links (\"non local\" counts as "
             "nonlocal). short_words: words that ask for codes with a short link. words_meaning_a_code: words "
             "that only say \"QR code\". words_to_skip and words_to_trim: filler words taken off the ends of "
             "links and paths. Edit, save and restart.",
    "rules": [
        "You turn one question about a registry of colored QR codes into a JSON query plan. Every QR code has a "
        "link (the text it holds), a color (#rrggbb, in a family such as blue or green) and the path of its "
        "picture file. A code may hold a short link instead: a short address in the local section (for this "
        "computer) or the nonlocal section (on the internet) that forwards people to its destination.",
        "Answer with one JSON object and nothing else, with exactly these fields:",
        '  intent: "find" to look QR codes up, "recommend" to suggest colors for a new QR code',
        '  color: a #rrggbb code written in the question, else ""',
        "  near: true when the question asks for colors close to that code",
        '  family: one of {families}, else ""',
        '  link: words the link or the destination should contain, copied from the question, else ""',
        '  link_exact: a whole link written in the question, else ""',
        '  path: words from a folder or file name in the question, else ""',
        '  section: "local" or "nonlocal" when the question asks for that section\'s short links, else ""',
        "  short: true when the question asks only for codes with a short link, else false",
        "  limit: how many results the question wants, 20 when it does not say",
        "Copy text exactly from the question. Never invent a link, a path or a #rrggbb code: a color named in "
        "words (blue, dark green) is a family, not a code.",
    ],
    "examples": [
        {"question": "blue QR codes that link to the shop",
         "plan": {"intent": "find", "color": "", "near": False, "family": "blue", "link": "shop", "link_exact": "",
                  "path": "", "section": "", "short": False, "limit": 20}},
        {"question": "which code points to https://example.com/menu?",
         "plan": {"intent": "find", "color": "", "near": False, "family": "", "link": "",
                  "link_exact": "https://example.com/menu", "path": "", "section": "", "short": False, "limit": 20}},
        {"question": "suggest two colors for a new code",
         "plan": {"intent": "recommend", "color": "", "near": False, "family": "", "link": "", "link_exact": "",
                  "path": "", "section": "", "short": False, "limit": 2}},
        {"question": "codes close to #3366cc in the marketing folder",
         "plan": {"intent": "find", "color": "#3366cc", "near": True, "family": "", "link": "", "link_exact": "",
                  "path": "marketing", "section": "", "short": False, "limit": 20}},
        {"question": "my local codes",
         "plan": {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "",
                  "path": "", "section": "local", "short": False, "limit": 20}},
        {"question": "codes with a short link that still point to the menu",
         "plan": {"intent": "find", "color": "", "near": False, "family": "", "link": "menu", "link_exact": "",
                  "path": "", "section": "", "short": True, "limit": 20}},
        {"question": "blue codes on the nonlocal short links",
         "plan": {"intent": "find", "color": "", "near": False, "family": "blue", "link": "", "link_exact": "",
                  "path": "", "section": "nonlocal", "short": True, "limit": 20}},
    ],
    "family_words": swatch.FAMILY_WORDS,
    "section_words": {"local": ["local", "localhost"], "nonlocal": ["nonlocal", "public", "internet"]},
    "short_words": ["short", "shortlink", "shortlinks", "shortened", "redirect", "redirects", "redirected"],
    "words_meaning_a_code": ["qr", "qrs", "code", "codes", "one", "ones", "please"],
    "words_to_skip": ["the", "a", "an", "my", "our", "your", "this", "that", "these", "those", "to", "of", "page",
                      "site", "website", "url", "link", "links", "code", "codes", "qr", "one", "ones"],
    "words_to_trim": ["pages", "folder", "folders", "file", "files", "directory", "picture", "pictures", "image"],
}

# Set by configure_planner() (from DEFAULT_PLANNER until a planner.json is loaded).
# SYSTEM_PROMPT is what the model is told: the rules, then every example as a question and its
# plan; its SHA-256 goes into each audit line, so a changed planner shows in the log. EDGE_WORDS
# are words_to_skip plus words_to_trim (trim_edges); CODE_WORDS are words_meaning_a_code
# (direct_plan); SECTION_WORDS and SHORT_WORDS are what ground() accepts as naming a section or
# asking for short links.
PLANNER_RULES = ""
SYSTEM_PROMPT = ""
SYSTEM_PROMPT_SHA256 = ""
EXAMPLES = []
EDGE_WORDS = []
CODE_WORDS = []
SECTION_WORDS = {}
SHORT_WORDS = []


# --- Records ---------------------------------------------------------------------------------------

def ok_result(value):
    """A successful Result holding `value` (for the window's lookups; the tools answer Outcomes)."""
    return {"ok": True, "error": "", "value": value}


def fail(error):
    """A failed Result with a short error phrase."""
    return {"ok": False, "error": error, "value": None}


def outcome(kind, detail, value):
    """An Outcome: `kind` is "ok" or one of KINDS, `detail` says what went wrong in words, and
    `value` is the answer (None for a failure). mcp_server turns a failure into an isError result."""
    return {"ok": kind == "ok", "kind": kind, "detail": detail, "value": value}


def new_call(tool, client_info, request_id):
    """Who asked, for the audit log: the tool, the client's own (untrusted) description of itself, and
    the request's id."""
    if not isinstance(client_info, dict):
        client_info = {}
    return {"tool": tool, "client_info": client_info, "request_id": request_id}


def sha256_text(text):
    """The SHA-256 of `text`'s UTF-8 bytes, as 64 lowercase hex digits."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_plan():
    """A QueryPlan that asks for nothing in particular: find, no filters, the default limit (the
    newest codes)."""
    return {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "",
            "section": "", "short": False, "limit": registry.DEFAULT_LIMIT}


def plan_filters(plan):
    """A QueryPlan's filter fields as registry.find_rows's filters (intent and limit are not filters)."""
    filters = registry.empty_filters()
    for key in ("color", "near", "family", "link", "link_exact", "path", "section", "short"):
        filters[key] = plan[key]
    return filters


def plan_schema():
    """The JSON schema a model's plan must follow: flat, every field required, "" for unset, no
    $ref and no keyword the grammar converter ignores (ECP spec 5.3-5.4). It is fixed by the program,
    never built from user text, and its hash goes into every audit record.

    Ollama turns this schema into a grammar that limits which tokens the model may produce
    (structured output), so the answer is shaped like a plan before it is parsed. The schema only
    shapes; check_plan_shape and ground still check the plan itself."""
    return {"type": "object",
            "properties": {"intent": {"type": "string", "enum": ["find", "recommend"]},
                           "color": {"type": "string", "maxLength": 7},
                           "near": {"type": "boolean"},
                           "family": {"type": "string", "enum": [""] + list(swatch.FAMILIES)},
                           "link": {"type": "string", "maxLength": 200},
                           "link_exact": {"type": "string", "maxLength": 2048},
                           "path": {"type": "string", "maxLength": 260},
                           "section": {"type": "string", "enum": [""] + list(SECTIONS)},
                           "short": {"type": "boolean"},
                           "limit": {"type": "integer", "minimum": 1, "maximum": registry.MAX_LIMIT}},
            "required": list(PLAN_FIELDS), "additionalProperties": False}


def schema_sha256():
    """The plan schema's SHA-256, over its canonical JSON (sorted keys, no spaces), so the same
    schema always hashes the same."""
    return sha256_text(json.dumps(plan_schema(), sort_keys=True, separators=(",", ":")))


def new_engine(db_path, inference_url, timeout, app_version):
    """A new Engine for the registry at `db_path`, with Ollama at `inference_url`.

    `timeout` is the seconds a model may take to plan (app_settings.PROTOCOL_TIMEOUT or
    WINDOW_TIMEOUT); `app_version` goes into the MCP server's serverInfo. An address that is not a
    local endpoint leaves "endpoint" None and its reason in "endpoint_error", which every call that
    needs the model then reports. qr_palette.py fills in the default model, preset, audit file,
    links and scans vote afterwards."""
    parsed = local_inference.parse_endpoint(inference_url)
    endpoint = None
    if parsed["ok"]:
        endpoint = parsed["value"]
    return {"db": db_path, "endpoint": endpoint, "endpoint_error": parsed["error"], "timeout": timeout,
            "app_version": app_version, "default_model": "", "preset": swatch.DEFAULT_PRESET, "audit_file": "",
            "ollama_version": "", "links": shortlinks.copy_links(shortlinks.DEFAULT_LINKS), "scans_vote": False}


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
    missing or not valid keep their defaults, and say so.

    Never fails: a file that cannot be read or is not one JSON object gives the built-in planner
    with one warning. Each part is checked on its own:
      - rules: a non-empty list of lines.
      - examples: each needs a question and a whole, well-typed plan with a known intent, family
        and section (with_new_fields fills section and short for an older file); bad ones are left
        out, and with none left the built-in examples stay.
      - family_words: each word must name one of swatch.FAMILIES; bad entries are dropped.
      - section_words: lists of words for exactly local and nonlocal.
      - the four word lists: lists of strings, lowercased.
    """
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
                plan = None
                if isinstance(example, dict):
                    plan = with_new_fields(example.get("plan"))
                if (plan is not None and isinstance(example.get("question"), str) and
                        example["question"].strip() != "" and check_plan_shape(plan) == "" and
                        plan["family"] in [""] + list(swatch.FAMILIES) and plan["section"] in [""] + list(SECTIONS)
                        and plan["intent"] in ("find", "recommend")):
                    examples.append({"question": example["question"], "plan": plan})
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
    if "section_words" in data:
        named = data["section_words"]
        if (isinstance(named, dict) and sorted(named) == sorted(SECTIONS) and text_list(named["local"]) and
                text_list(named["nonlocal"])):
            planner["section_words"] = {"local": lowered_words(named["local"]),
                                        "nonlocal": lowered_words(named["nonlocal"])}
        else:
            warnings.append("planner: section_words must give a list of words for local and for nonlocal")
    for key in ("short_words", "words_meaning_a_code", "words_to_skip", "words_to_trim"):
        if key in data:
            if text_list(data[key]):
                planner[key] = lowered_words(data[key])
            else:
                warnings.append("planner: " + key + " must be a list of words")
    return {"planner": planner, "warnings": warnings}


def lowered_words(words):
    """A list of words in lowercase, in the same order."""
    lowered = []
    for item in words:
        lowered.append(item.lower())
    return lowered


def with_new_fields(plan):
    """An example's plan with the fields added after a planner.json was written (section, short) at
    their defaults, so an older planner.json keeps its examples -> QueryPlan-shaped dict, or None."""
    if not isinstance(plan, dict):
        return None
    filled = dict(plan)
    if "section" not in filled:
        filled["section"] = ""
    if "short" not in filled:
        filled["short"] = False
    return filled


def configure_planner(planner):
    """Put a planner configuration in place: the system prompt (rules, then the worked examples)
    and the word lists.

    `planner` is a whole configuration, as load_planner gives it. Side effects: sets this module's
    planner globals and replaces swatch.FAMILY_WORDS, so the window's family words and the
    planner's agree. "{families}" in the rules becomes the list of color families. Runs once at
    import with DEFAULT_PLANNER (the last line of this file), and again from apply_settings."""
    global PLANNER_RULES, SYSTEM_PROMPT, SYSTEM_PROMPT_SHA256, EXAMPLES, EDGE_WORDS, CODE_WORDS
    global SECTION_WORDS, SHORT_WORDS
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
    SECTION_WORDS = {"local": list(planner["section_words"]["local"]),
                     "nonlocal": list(planner["section_words"]["nonlocal"])}
    SHORT_WORDS = list(planner["short_words"])
    swatch.FAMILY_WORDS = dict(planner["family_words"])


def planner_text(planner):
    """planner.json as people read it: indented, one setting per line."""
    return json.dumps(planner, indent=2, ensure_ascii=False) + "\n"


# --- Planning: direct, model, grounding ------------------------------------------------------------

def is_link_like(text):
    """True for text that is one whole link: a single word with "://", or a mailto: or tel: link."""
    if text == "" or len(text.split()) != 1:
        return False
    lowered = text.lower()
    return "://" in lowered or lowered.startswith("mailto:") or lowered.startswith("tel:")


def is_path_like(text):
    """True for text that is a picture's path: one line starting with a drive ("C:\\" or "C:/"), a
    network share (\\\\server) or "/", or a single word ending in .png or .svg."""
    if text == "" or "\n" in text:
        return False
    lowered = text.lower()
    if re.match(r"^[a-z]:[\\/]", lowered) or text.startswith("\\\\") or text.startswith("/"):
        return True
    return (lowered.endswith(".png") or lowered.endswith(".svg")) and len(text.split()) == 1


def words_of(text):
    """The question's words: runs of ASCII letters and digits, casefolded ("Non-local QR" ->
    ["non", "local", "qr"]). Other letters split words."""
    return re.findall(r"[a-z0-9]+", text.casefold())


def question_hexes(text):
    """Every #rrggbb written in the text, lowercased, in order. "#3366cc" counts; "#3366ccff" or
    "#3366cg" does not, since a letter or digit may not follow the six hex digits."""
    found = []
    for match in re.findall(r"#[0-9a-fA-F]{6}(?![0-9a-zA-Z])", text):
        found.append(match.lower())
    return found


def direct_plan(question):
    """Questions that need no model: a color code, a link, a picture's path, or a family word
    ("blue", "blue QR codes"). -> QueryPlan or None.

    None means the question needs the model. A direct plan never asks Ollama anything, so a
    question like "#3366cc" works even with no model loaded (query still checks the model first).

    Steps:
      1. The whole question is a color code: a #rrggbb, or six hex digits that hold a digit.
      2. The whole question is one link (is_link_like): link_exact.
      3. The whole question is a picture's path (is_path_like): path.
      4. Its words, less the CODE_WORDS ("qr", "codes", ...), are one family word: family.
    """
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
    link contains. By color: #rrggbb (or near it), or a family word.

    `by` is "qr_code" or, for anything else, color; `near` only matters for a color code; `limit`
    is clamped to 1..registry.MAX_LIMIT. Fails only for a color that is neither a code nor a
    family word. No model and no grounding: the person typed the text into the field themselves."""
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
    """Words such as "page", "the" or "folder" taken off both ends: "the careers page" -> "careers".

    The words are EDGE_WORDS; a word is compared without its punctuation and casefolded. Words in
    the middle stay: "the shop page of the menu" -> "shop page of the menu"."""
    words = value.split()
    while len(words) > 0 and re.sub(r"[^\w]", "", words[0].casefold()) in EDGE_WORDS:
        words = words[1:]
    while len(words) > 0 and re.sub(r"[^\w]", "", words[len(words) - 1].casefold()) in EDGE_WORDS:
        words = words[:len(words) - 1]
    return " ".join(words)


def check_plan_shape(value):
    """"" when a model's answer is a whole QueryPlan with the right types, else what is wrong.

    Only the shape: no unknown field, every text field a string, near and short true or false, and
    limit a whole number (JSON true is refused, though Python counts a bool as an int). A missing
    text or bool field fails its type check. Values are judged later, by ground()."""
    if not isinstance(value, dict):
        return "the answer is not a JSON object"
    for key in value:
        if key not in PLAN_FIELDS:
            return "unknown field " + json.dumps(key)
    for key in PLAN_TEXT_FIELDS:
        if not isinstance(value.get(key), str):
            return key + " must be a string"
    for key in ("near", "short"):
        if not isinstance(value.get(key), bool):
            return key + " must be true or false"
    limit = value.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int):
        return "limit must be a whole number"
    return ""


def family_in_question(family, words):
    """True when one of the question's words names `family` (by swatch.family_of_word: "blues",
    "navy" and the like count for blue)."""
    for word in words:
        if swatch.family_of_word(word) == family:
            return True
    return False


def sections_in_question(words):
    """The sections of short links a question names, by SECTION_WORDS: "my local codes" -> ["local"].
    "non local" and "non-local" name nonlocal, not local."""
    named = []
    for index in range(len(words)):
        word = words[index]
        # words_of splits "non-local" into "non" and "local": read the pair as one word, nonlocal
        if word == "non" and index + 1 < len(words) and words[index + 1] == "local":
            continue
        if word == "local" and index > 0 and words[index - 1] == "non":
            word = "nonlocal"
        for section in SECTIONS:
            if word in SECTION_WORDS.get(section, []) and section not in named:
                named.append(section)
    return named


def short_in_question(words):
    """True when one of the question's words asks for short links (SHORT_WORDS)."""
    for word in words:
        if word in SHORT_WORDS:
            return True
    return False


def ground(proposed, question):
    """Keep only what the question supports -> (QueryPlan, clamped: [str]). Links, paths and color
    codes must be written in the question; a family or a section must be named in it, and short
    links asked for in its words; a color code in the question always wins over the model's. Every
    change is listed.

    Grounding is the guard against a model that invents things. A small local model may answer
    "blue codes for the shop" with link "https://shop.example.com", or add a path it imagined; a
    plan that filters on invented text would quietly find nothing, or the wrong codes. So every
    value is accepted only when the question itself backs it, and each dropped or changed value
    is said in `clamped` (which goes into the answer's plan_used and the audit log).

    `proposed` has passed check_plan_shape. Steps:
      1. intent: find or recommend, anything else read as find.
      2. color: the first #rrggbb written in the question wins; else the model's color when its six
         digits appear in the question; else dropped. near only stands with a color.
      3. family: kept when a question word names that family.
      4. section: kept when the question names that section (sections_in_question).
      5. short: kept when a question word asks for short links.
      6. link, link_exact, path: kept when they appear in the question (casefolded); link and path
         lose filler words at their ends, and a link the same as link_exact is dropped as redundant.
      7. limit: clamped to 1..registry.MAX_LIMIT.
    """
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
        plan["color"] = color  # written without its # ("codes in 3366cc")
    elif proposed["color"] != "":
        clamped.append("color: dropped " + json.dumps(proposed["color"]) + ", not written in the question")
    plan["near"] = proposed["near"] and plan["color"] != ""
    family = swatch.family_of_word(proposed["family"])
    if family != "" and family_in_question(family, words):
        plan["family"] = family
    elif proposed["family"] != "":
        clamped.append("family: dropped " + json.dumps(proposed["family"]) + ", not named in the question")
    if proposed["section"] in SECTIONS and proposed["section"] in sections_in_question(words):
        plan["section"] = proposed["section"]
    elif proposed["section"] != "":
        clamped.append("section: dropped " + json.dumps(proposed["section"]) + ", not named in the question")
    if proposed["short"] and short_in_question(words):
        plan["short"] = True
    elif proposed["short"]:
        clamped.append("short: dropped, the question does not ask for short links")
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
    ground it -> Outcome {"plan", "clamped", "inference_ns"}.

    `model` is a LocalModel from resolve_model; the question goes to it with SYSTEM_PROMPT and the
    plan schema. A model that runs out of answer tokens mid-plan (plan_truncated) is asked once
    more with RETRY_ANSWER_TOKENS. Outcomes: local_inference's own failure kinds, plan_unparseable
    when the answer is not JSON, plan_invalid when it is not a well-typed plan. inference_ns is
    Ollama's own account of the call: {"total", "load"} in nanoseconds and "eval_count" tokens."""
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
    {"rows", "counts", "votes", "vote_map", "used", "scans"}. The connection is closed before returning.

    The read-only rail (registry.connect(path, True)) opens the file with mode=ro and query_only,
    lets only an allow-list of tables, columns and functions through its authorizer, and stops a
    visit that runs past registry.STATEMENT_SECONDS with a progress handler. The rail's refusals
    come back as sqlite3 errors, sorted here by their text: "interrupted" is the progress handler
    stopping the visit (db_timeout); "not authorized" or "prohibited" is a denial (db_denied);
    anything else is db_unavailable. "scans" is read only when scans feed the ranking."""
    opened = registry.connect(engine["db"], True)
    if not opened["ok"]:
        return outcome("db_unavailable", opened["error"], None)
    connection = opened["value"]
    try:
        snapshot = {"rows": registry.all_rows(connection), "counts": registry.counts(connection),
                    "votes": registry.vote_log(connection), "vote_map": registry.vote_map(connection),
                    "used": registry.colors_in_use(connection), "scans": None}
        if engine["scans_vote"]:
            snapshot["scans"] = registry.color_scans(connection)
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
    and newline included), no zero-width or direction characters, NFC, and capped.

    Why: stored text came from whoever made the codes and goes to a model's context. Invisible
    characters can hide words from a person reading the answer, direction controls can reorder what
    is shown, and control characters can break a terminal. textsafe.clean takes out C0 and C1
    controls, separators and direction controls; this also takes out tab and newline and the
    ZERO_WIDTH characters. NFC (Unicode normalization form C) gives each accented letter one form,
    so equal-looking text is equal. `flags` collects whether anything was cut."""
    kept = []
    for character in textsafe.clean(str(text), None):
        if ord(character) >= 0x20 and ord(character) not in ZERO_WIDTH:
            kept.append(character)
    return capped(unicodedata.normalize("NFC", "".join(kept)), flags)


def describe_plan(plan):
    """The plan's filters in words for the answer's summary ("family blue, link containing
    "shop""), or "" when it has none."""
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
    if plan["section"] != "":
        parts.append(plan["section"] + " short links")
    elif plan["short"]:
        parts.append("short links")
    return ", ".join(parts)


def with_sections(rows, links):
    """Rows with "section": their short link's section by links.json's bases ("local" or "nonlocal"),
    "" for a code without a short link (or one made on a base that is no longer either section's)."""
    marked = []
    for row in rows:
        row = dict(row)
        row["section"] = ""
        if row["short_code"] != "":
            row["section"] = shortlinks.section_of(links, row["link"])
        marked.append(row)
    return marked


def run_plan(snapshot, plan, preset, links):
    """A checked plan against a snapshot -> {"records", "colors", "summary", "truncated"}. `links`
    (links.json) gives the sections' bases.

    `snapshot` is read_environment's value; `preset` names the ranking preset. The rank of a color
    is its place on the board swatch.rank_colors builds from the preset, the votes and (when they
    count) the scans; a ranking that fails leaves every rank None, and nothing to recommend.

    recommend: the usable colors (enough contrast on white to scan), best first, of the plan's
    family if it names one, up to the limit, each with how many codes use it already. No records.

    find: the rows that pass the plan's filters (registry.find_rows, newest first, up to the
    limit), each as a Record whose stored strings go through neutral(). "exists" is only looked
    up for files on a local drive, so a query never reaches a network share. The summary says how
    many matched what."""
    flags = {"truncated": False}
    ranked = swatch.rank_colors(preset, snapshot["votes"], snapshot["scans"])
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
    for row in registry.find_rows(with_sections(snapshot["rows"], links), plan_filters(plan), plan["limit"]):
        records.append({"id": row["id"], "hex": neutral(row["hex"], flags), "color_name": neutral(row["name"], flags),
                        "color_family": neutral(row["family"], flags), "rank": places.get(row["hex"]),
                        "payload_url": neutral(row["link"], flags), "target_url": neutral(row["target"], flags),
                        "section": row["section"], "file_path": neutral(row["path"], flags),
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
    AUDIT_ID_ROOM characters free for the audit_id, which is only known once the call is logged.

    The size is measured as the JSON the client will get (ensure_ascii off, so a character counts
    once). Records go from the end, so the newest stay. Sets "truncated" when any went, and
    "row_count" to the records left. Changes `value` in place and returns it."""
    while (len(value["records"]) > 0 and
           len(json.dumps(value, ensure_ascii=False)) + AUDIT_ID_ROOM > MAX_RESULT_CHARACTERS):
        value["records"] = value["records"][:len(value["records"]) - 1]
        value["truncated"] = True
    value["row_count"] = len(value["records"])
    return value


# --- The three tools ------------------------------------------------------------------------------

def ollama_version(engine):
    """Ollama's version for the audit line, asked once and kept in the engine; "" when it cannot
    be had."""
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
    """Audit a finished call and return its Outcome (the audit_id goes into a successful value).

    `call` is new_call's record; `started` is time.time() when the call began; `extra` adds the
    call's own facts (hashes, model, plan, counts). The audit line has the request's id, the
    tool, the client's description, the outcome's kind, the elapsed milliseconds, the interlock
    state, the extra fields and, for a failure, its first 200 characters of detail. The audit_id
    is only set in a value that already has the key (query's answer)."""
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
    """None when the engine has an Ollama endpoint, else the inference_unavailable Outcome that
    says why its address was refused."""
    if engine["endpoint"] is None:
        return outcome("inference_unavailable", engine["endpoint_error"], None)
    return None


def list_models(engine, call):
    """ecp_list_models -> Outcome {"models": [LocalModel], "cloud_disabled": bool}.

    The models come from Ollama's /api/tags, without cloud, remote and embedding-only ones.
    cloud_disabled is False when Ollama cannot say. Every call is audited."""
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
    """The model by name on a fresh /api/tags -> Outcome LocalModel.

    A cloud name (":cloud", "-cloud" and the like) is refused before Ollama is asked; a name not
    in the local list is model_not_local. The list is read again each time, so a model removed
    since it was chosen is noticed."""
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
    -> Outcome {"model_id", "name", "digest", "supports_thinking", "loaded", "load_duration_ns"}.

    Steps:
      1. The endpoint must be there, and the name a local model (find_local).
      2. /api/show must not say the model is served from another host.
      3. warm loads it, so the first question does not wait for loading.
    The model_id ("name@digest") is what a client passes to ecp_query: the digest pins this exact
    model, and a model pulled again under the same name no longer matches. Nothing is kept in the
    engine; the audit line records the name asked for."""
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
    cloud, and the same digest it was pinned with -> Outcome LocalModel.

    `model_id` is "name@digest", a bare name (no digest to check), or "" for settings.json's
    default model; with neither, args_invalid. The name is everything before the last "@", since a
    model's name may hold one itself."""
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
    "trust", "audit_id", "summary"}.

    `prompt` is the question as the client sent it; `model_id` as resolve_model takes it; `call`
    is new_call's record. Every path, success or failure, ends in finish(), so every call leaves
    one audit line. The audit line holds the prompt's SHA-256, never the prompt.

    Steps:
      1. Clean the question (control characters out, at most QUESTION_LIMIT characters).
      2. Resolve and check the model, even when the plan will be direct.
      3. Plan: direct_plan, or with REQUIRE_CLOUD_DISABLED first make sure Ollama's cloud features
         are off, then model_plan (ask, check the shape, ground).
      4. read_environment on the read-only rail.
      5. run_plan, then fit_result to MAX_RESULT_CHARACTERS.
      6. finish: write the audit line and put its audit_id into the answer.
    """
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
    extra["progress_fired"] = snapshot["kind"] == "db_timeout"  # the rail's time limit stopped the read
    if not snapshot["ok"]:
        return finish(engine, call, started, snapshot, extra)
    ran = run_plan(snapshot["value"], plan, engine["preset"], engine["links"])
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
    """A JSON-RPC answer to request `number` carrying `value` as its result."""
    return {"jsonrpc": "2.0", "id": number, "result": value}


def error_message(number, code, message, data):
    """A JSON-RPC error answer to request `number` (None when the request's id could not be read,
    as the standard asks) with `code`, `message` and, when not None, `data`."""
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": number, "error": error}


def request_parts(message):
    """A parsed message -> (id, method, params, error message or None, is notification).

    Checks, in order: the message is an object; a present id is a number or a string (null and
    true/false are refused, though JSON-RPC allows null, so every answer can be matched); jsonrpc
    is "2.0" and method a string; params, when given, is an object (by-name parameters only).
    A message without an "id" key is a notification."""
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
    """One line of bytes -> (message or batch, error response or None).

    A batch is a JSON array of messages; the caller's handler takes it apart. Bytes that are not
    UTF-8, and text that is not JSON, are parse errors (-32700) with a null id."""
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
    """One message (or batch answer) as one line: ASCII JSON, no raw newlines inside, one \\n.

    ensure_ascii writes every other character as a \\u escape, so no newline, U+2028 or stray
    byte can split the line on the client's side. -> False when the output is closed or broken
    (the client went away), which ends serve."""
    try:
        writer.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")
        writer.flush()
    except (OSError, ValueError):
        return False
    return True


def serve(handler, state, reader, writer):
    """Read one message per line until the input ends; answer each request on its own line.
    Unexpected errors become JSON-RPC internal errors, never a traceback on stdout.

    `handler(state, message)` answers one parsed line (a message, or a batch) with a response or
    None (for notifications); `reader` and `writer` are binary streams, normally stdin and stdout.
    stdout carries only protocol messages, so every diagnostic goes to stderr. -> 0 when the input
    ends, the output breaks or the user interrupts.

    Steps, for each line:
      1. Read at most MAX_LINE + 1 bytes. A line longer than MAX_LINE is read to its end and
         thrown away, and answered with an invalid request error.
      2. Skip blank lines.
      3. Parse it (parse_line); a parse error is answered at once.
      4. Hand it to the handler; an exception becomes an internal error, with the request's id
         when it can be read.
      5. Write the response, if any, as one line.
    """
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


# the built-in planner is in force from import on, so the tests and --selftest need no planner.json
configure_planner(DEFAULT_PLANNER)

# ==== stamp v1 | author=kjFriday | hmac-sha256=d7f6a51585e65341f9007223514930ae39c0e2b9450c8a8ae88ea97669c41219 ====
