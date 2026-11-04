# ==== Generic Company Inc. portfolio ====================================
# Project: qr_palette | File: tests/test_ecp.py
# About: Tests for ECP's engine: choosing and pinning a local model, planning and grounding, the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's tools/stamp.py --check.
# Reused code, if any, is mapped in PROVENANCE.md.
# ========================================================================

"""Tests for ECP's engine: model choice, planning, grounding, refusals, audit and framing.

ECP (ECP.md) answers plain-English questions about the registry with a local model: the model only
proposes a QueryPlan, ecp.ground keeps what the question itself supports, and the plan runs read-only.
These tests cover choosing and pinning a local model, planning and grounding, the read-only answer with
its caps and labels, every refusal by kind, the audit log, planner.json and the JSON-RPC framing.

The model is FakeOllama from test_local_inference.py: tests queue the plans it answers with in
fake.plans and read what it was asked from fake.received. Each engine test gets a registry of the four
CODES in a temporary folder. LiveModelTests run only against a real local model, when
QR_PALETTE_LIVE_MODEL names one.

Start reading at EngineCase, then QueryTests and GroundingTests.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import audit
import ecp
import local_inference
import registry
import shortlinks
import swatch
from test_local_inference import FakeOllama, QWEN_DIGEST

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the program folder, above tests/

QWEN = "qwen2.5:7b-instruct@" + QWEN_DIGEST  # a model_id pinned to the fake's digest
# a link stored in the registry that must never show up in anything sent to the model
CANARY = "https://canary.example/CANARY-7f3a"
# the registry every engine test starts from: (picture file, link, color)
CODES = (("shop-blue.png", "https://shop.example.com/", "#3366cc"),
         ("menu-green.png", "https://example.com/menu", "#006633"),
         ("canary.png", CANARY, "#660099"),
         ("sale-red.png", "https://shop.example.com/sale", "#cc0000"))


def plan(**changes):
    """A QueryPlan with every field at its empty default, changed by `changes` (plan(family="blue"))."""
    value = {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "",
             "section": "", "short": False, "limit": 20}
    for key in changes:
        value[key] = changes[key]
    return value


def make_registry(folder):
    """A registry of the four CODES, their (empty) picture files, and one Good vote for #3366cc."""
    path = os.path.join(folder, "palette.db")
    opened = registry.connect(path, False)
    connection = opened["value"]
    for code in CODES:
        picture = os.path.join(folder, code[0])
        handle = open(picture, "wb")
        handle.close()
        registry.save_qr(connection, {"link": code[1], "color": code[2], "path": picture, "format": "png",
                                      "ec_level": "M", "version": 3, "origin": "made"})
    registry.vote(connection, "#3366cc", 1)
    registry.close(connection)
    return path


def plan_of(value):
    """The QueryPlan inside an answer's plan_used."""
    found = {}
    for key in ecp.PLAN_FIELDS:
        found[key] = value["plan_used"][key]
    return found


class EngineCase(unittest.TestCase):
    """An engine over a fresh registry of CODES, a FakeOllama, and an audit log in a temporary folder.

    The module caps a test may change (REQUIRE_CLOUD_DISABLED and the field and result caps) are saved
    in setUp and put back in tearDown, so no test leaks its settings into the next."""

    def setUp(self):
        """Make the registry and the fake, and an engine on it with a 5-second timeout and app version 0.1.0."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_ecp_")
        self.db = make_registry(self.folder)
        self.fake = FakeOllama()
        self.engine = ecp.new_engine(self.db, self.fake.url, 5.0, "0.1.0")
        self.engine["audit_file"] = os.path.join(self.folder, "audit.jsonl")
        self.saved = (ecp.REQUIRE_CLOUD_DISABLED, ecp.MAX_FIELD_CHARACTERS, ecp.MAX_RESULT_CHARACTERS)

    def tearDown(self):
        """Put the module caps back, stop the fake and remove the folder."""
        ecp.REQUIRE_CLOUD_DISABLED, ecp.MAX_FIELD_CHARACTERS, ecp.MAX_RESULT_CHARACTERS = self.saved
        self.fake.stop()
        shutil.rmtree(self.folder, ignore_errors=True)

    def call(self, tool):
        """A call record for `tool` from a client named "test", request id 1 (what the audit log keeps)."""
        return ecp.new_call(tool, {"name": "test"}, 1)

    def query(self, prompt, model_id=QWEN):
        """ecp_query with `prompt` on `model_id` (the pinned qwen by default) -> the raw Outcome."""
        return ecp.query(self.engine, prompt, model_id, self.call("ecp_query"))

    def answer(self, prompt, model_id=QWEN):
        """ecp_query that must succeed -> its value; a failure fails the test with its kind and detail."""
        result = self.query(prompt, model_id)
        self.assertTrue(result["ok"], result["kind"] + ": " + result["detail"])
        return result["value"]

    def links(self, value):
        """The payload links of an answer's records, in the order they came."""
        found = []
        for record in value["records"]:
            found.append(record["payload_url"])
        return found


class ModelTests(EngineCase):
    """ecp_list_models and ecp_select_model: only local models, pinned by digest, loaded as NAME:local."""

    def test_only_local_models_are_listed_with_their_ids(self):
        """The list holds the four local text models by name, each with a name@digest id and the default
        marked, and says cloud features are off."""
        self.engine["default_model"] = "qwen2.5:7b-instruct"
        listed = ecp.list_models(self.engine, self.call("ecp_list_models"))
        self.assertTrue(listed["ok"], listed["detail"])
        names = []
        for model in listed["value"]["models"]:
            names.append(model["name"])
            self.assertEqual(model["is_default"], model["name"] == "qwen2.5:7b-instruct")
            self.assertEqual(model["model_id"], model["name"] + "@" + model["digest"])
        self.assertEqual(names, ["deepseek-coder:base", "deepseek-r1:7b", "old-model:latest", "qwen2.5:7b-instruct"])
        self.assertTrue(listed["value"]["cloud_disabled"])

    def test_selecting_pins_the_digest_and_loads_the_local_copy(self):
        """Selecting a bare name answers name@digest, loads NAME:local once, and reports whether it thinks."""
        selected = ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))
        self.assertTrue(selected["ok"], selected["detail"])
        self.assertEqual(selected["value"]["model_id"], QWEN)
        self.assertEqual((selected["value"]["loaded"], selected["value"]["supports_thinking"]), (True, False))
        self.assertEqual(self.fake.posted("/api/generate")[0]["model"], "qwen2.5:7b-instruct:local")
        thinking = ecp.select_model(self.engine, "deepseek-r1:7b", self.call("ecp_select_model"))
        self.assertTrue(thinking["value"]["supports_thinking"])

    def test_cloud_remote_embedding_and_unknown_models_are_refused(self):
        """Cloud, remote-only, embedding-only, unknown and ":local" names are "model_not_local", as is a
        model /api/show reports as remote; none of them is loaded."""
        for name in ("gpt-oss:120b-cloud", "remote-only:latest", "nomic-embed-text:latest", "nothing",
                     "qwen2.5:7b-instruct:local"):
            self.assertEqual(ecp.select_model(self.engine, name, self.call("ecp_select_model"))["kind"],
                             "model_not_local", name)
        self.fake.shown["qwen2.5:7b-instruct"] = {"remote_host": "https://ollama.com:443"}
        self.assertEqual(ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))["kind"],
                         "model_not_local")
        self.assertEqual(self.fake.posted("/api/generate"), [])  # nothing was loaded

    def test_an_answer_from_another_host_is_egress(self):
        """A load answer stamped with remote_host means the work left the computer: "egress_detected"."""
        self.fake.stamp = True
        self.assertEqual(ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))["kind"],
                         "egress_detected")

    def test_inference_down_or_not_on_loopback(self):
        """No server listening, and an address that is not loopback, are both "inference_unavailable"; the
        second says loopback is required."""
        self.fake.stop()
        self.assertEqual(ecp.list_models(self.engine, self.call("ecp_list_models"))["kind"], "inference_unavailable")
        self.fake = FakeOllama()
        engine = ecp.new_engine(self.db, "http://example.com:11434", 5.0, "0.1.0")
        listed = ecp.list_models(engine, self.call("ecp_list_models"))
        self.assertEqual(listed["kind"], "inference_unavailable")
        self.assertIn("loopback", listed["detail"])


class QueryTests(EngineCase):
    """ecp_query: model choice, direct questions, model plans and their grounding, refusals by kind."""

    def test_a_local_model_is_chosen_first(self):
        """With no model and no default, the query is "args_invalid" and points at ecp_list_models; a
        default model then answers."""
        refused = self.query("blue", "")
        self.assertEqual(refused["kind"], "args_invalid")
        self.assertIn("ecp_list_models", refused["detail"])
        self.engine["default_model"] = "qwen2.5:7b-instruct"
        self.assertEqual(self.answer("blue", "")["model_id"], QWEN)

    def test_the_pinned_digest_must_still_match(self):
        """A name@digest whose model has changed on disk is "model_digest_mismatch"; a bare name takes the
        model as it is now, and a removed or cloud model is "model_not_local"."""
        self.assertTrue(self.query("blue")["ok"])
        self.fake.models[0]["digest"] = "9" * 64
        self.assertEqual(self.query("blue")["kind"], "model_digest_mismatch")
        self.assertTrue(self.query("blue", "qwen2.5:7b-instruct")["ok"])  # a bare name takes the model as it is now
        self.fake.models.pop(0)
        self.assertEqual(self.query("blue", "qwen2.5:7b-instruct")["kind"], "model_not_local")
        self.assertEqual(self.query("blue", "gpt-oss:120b-cloud")["kind"], "model_not_local")

    def test_direct_questions_need_no_model(self):
        """A color code, a family word, a link or a picture path is answered without asking the model."""
        self.assertEqual(self.links(self.answer("#006633")), ["https://example.com/menu"])
        self.assertEqual(self.answer("blue QR codes")["plan_used"]["planner"], "direct")
        self.assertEqual(self.links(self.answer("https://example.com/menu")), ["https://example.com/menu"])
        self.assertEqual(self.answer(os.path.join(self.folder, "sale-red.png"))["row_count"], 1)
        self.assertEqual(self.fake.plans_asked(), [])

    def test_records_hold_the_color_the_link_and_the_path(self):
        """A record carries the color with its name and family, the link, the file and whether it exists,
        the rank and net votes; the answer carries its source, trust and interlock labels."""
        value = self.answer("#3366cc")
        record = value["records"][0]
        self.assertEqual((record["hex"], record["color_name"], record["color_family"]),
                         ("#3366cc", swatch.color_name("#3366cc"), "blue"))
        self.assertEqual(record["payload_url"], "https://shop.example.com/")
        self.assertEqual(record["file_path"], os.path.join(self.folder, "shop-blue.png"))
        self.assertTrue(record["exists"])
        self.assertIsInstance(record["rank"], int)
        self.assertEqual(record["net_votes"], 1)
        self.assertEqual((value["source"], value["trust"], value["interlock_state"]),
                         ("ecp-sqlite-readonly", "untrusted-db-content", "bypassed"))
        self.assertEqual((value["row_count"], value["truncated"]), (1, False))

    def test_the_model_plans_and_its_inventions_are_dropped(self):
        """The model's color and path, which the question never wrote, are dropped and listed as clamped;
        the family and link it named are kept. The model is asked with the system prompt, the question,
        the plan schema as format, and NAME:local."""
        self.fake.plans.append(plan(color="#0000ff", family="blue", link="shop", path="archive"))
        value = self.answer("which blue QR codes link to the shop?")
        self.assertEqual(value["plan_used"]["planner"], "model")
        self.assertEqual(plan_of(value), plan(family="blue", link="shop"))
        self.assertEqual(self.links(value), ["https://shop.example.com/"])
        self.assertEqual(len(value["plan_used"]["clamped"]), 2)
        self.assertIn("color: dropped", value["plan_used"]["clamped"][0])
        asked = self.fake.plans_asked()[0]
        self.assertEqual((asked["system"], asked["prompt"]), (ecp.SYSTEM_PROMPT, "which blue QR codes link to the shop?"))
        self.assertEqual(asked["format"], ecp.plan_schema())
        self.assertEqual(asked["model"], "qwen2.5:7b-instruct:local")

    def test_a_color_written_in_the_question_wins(self):
        """A color code written in the question replaces the one the model proposed, and says so."""
        self.fake.plans.append(plan(color="#44aacc", near=True))
        value = self.answer("show codes close to #3366cc please")
        self.assertEqual((value["plan_used"]["color"], value["plan_used"]["near"]), ("#3366cc", True))
        self.assertIn("replaced", value["plan_used"]["clamped"][0])

    def test_bad_plans_are_refused_by_kind(self):
        """Text that is not JSON is "plan_unparseable"; a partial plan, an extra field or a list is
        "plan_invalid"."""
        for answer, kind in (("not json", "plan_unparseable"), ({"intent": "find"}, "plan_invalid"),
                             (dict(plan(), notes="extra"), "plan_invalid"), ([1, 2], "plan_invalid")):
            self.fake.plans.append(answer)
            self.assertEqual(self.query("anything green in the menu?")["kind"], kind, answer)

    def test_a_cut_off_plan_is_asked_once_more_with_more_room(self):
        """A plan cut off at the token limit is asked once more with RETRY_ANSWER_TOKENS; cut off twice, it
        is "plan_truncated"."""
        self.fake.plans.extend(["CUT", plan(family="green")])
        self.assertEqual(self.links(self.answer("anything green?")), ["https://example.com/menu"])
        asked = self.fake.plans_asked()
        self.assertEqual((asked[0]["options"]["num_predict"], asked[1]["options"]["num_predict"]),
                         (local_inference.PLAN_OPTIONS["num_predict"], local_inference.RETRY_ANSWER_TOKENS))
        self.fake.plans.extend(["CUT", "CUT"])
        self.assertEqual(self.query("anything green?")["kind"], "plan_truncated")

    def test_planning_needs_the_cloud_features_off(self):
        """With Ollama's cloud features on, planning is refused before any model call and names
        OLLAMA_NO_CLOUD; direct questions still work, and turning the rule off lets planning run."""
        self.fake.cloud = {"disabled": False}
        refused = self.query("anything green?")
        self.assertEqual(refused["kind"], "cloud_not_disabled")
        self.assertIn("OLLAMA_NO_CLOUD", refused["detail"])
        self.assertEqual(self.fake.plans_asked(), [])
        self.assertTrue(self.query("#006633")["ok"])  # a direct question asks no model
        ecp.REQUIRE_CLOUD_DISABLED = False
        self.assertTrue(self.query("anything green?")["ok"])

    def test_a_plan_from_another_host_is_egress(self):
        """A planning answer stamped with remote_host is "egress_detected"."""
        self.fake.stamp = True
        self.assertEqual(self.query("anything green?")["kind"], "egress_detected")

    def test_slow_and_missing_inference_are_named(self):
        """A server slower than the engine's timeout is "inference_timeout"; no server is
        "inference_unavailable"."""
        self.engine["timeout"] = 0.3
        self.fake.delay = 1.0
        self.assertEqual(self.query("anything green?")["kind"], "inference_timeout")
        self.fake.delay = 0.0
        self.fake.stop()
        self.assertEqual(self.query("anything green?")["kind"], "inference_unavailable")
        self.fake = FakeOllama()

    def test_recommendations(self):
        """A recommend plan answers colors of the family, ranked by the mixer preset (the Good vote puts
        #3366cc first), and no records."""
        self.fake.plans.append(plan(intent="recommend", limit=3, family="blue"))
        value = self.answer("suggest 3 blue colors for a new code")
        self.assertEqual(len(value["colors"]), 3)
        for pick in value["colors"]:
            self.assertEqual(pick["family"], "blue")
            self.assertIsInstance(pick["rank"], int)
        self.assertEqual(value["colors"][0]["hex"], "#3366cc")  # its Good vote puts it first
        self.assertEqual(value["records"], [])
        self.assertIn("preset mixer", value["summary"])

    def test_stored_links_never_reach_the_model(self):
        """The canary link stored in the registry appears in no request the fake received: the model sees
        the question, never stored data."""
        for question in ("which codes link to the shop?", "anything purple?", "show me everything you have"):
            self.query(question)
        self.assertGreater(len(self.fake.plans_asked()), 0)
        for entry in self.fake.received:
            self.assertNotIn("CANARY-7f3a", entry[2])

    def test_an_empty_question_is_refused(self):
        """A question that is only control characters, a bidi override and spaces is "prompt_invalid"."""
        self.assertEqual(self.query("\x1b\u202e  ")["kind"], "prompt_invalid")


class EnvironmentTests(EngineCase):
    """The registry and stored data around a query: missing or failing reads, hidden characters, short
    links and their sections, and the size caps."""

    def test_a_missing_registry_is_unavailable_and_not_made(self):
        """A registry path with no file is "db_unavailable", and the read-only rail does not create it."""
        self.engine["db"] = os.path.join(self.folder, "none.db")
        self.assertEqual(self.query("#006633")["kind"], "db_unavailable")
        self.assertFalse(os.path.exists(self.engine["db"]))

    def test_slow_and_refused_reads_are_named(self):
        """registry.all_rows is swapped for one that raises: an interrupted read is "db_timeout", an
        authorizer refusal "db_denied", and any other database error "db_unavailable"."""
        saved = registry.all_rows
        try:
            for error, kind in ((sqlite3.OperationalError("interrupted"), "db_timeout"),
                                (sqlite3.DatabaseError("not authorized"), "db_denied"),
                                (sqlite3.OperationalError("disk I/O error"), "db_unavailable")):
                def broken(connection, error=error):
                    """Raise this round's error (bound as a default, so each round keeps its own)."""
                    raise error

                registry.all_rows = broken
                self.assertEqual(self.query("#006633")["kind"], kind)
        finally:
            registry.all_rows = saved

    def test_stored_text_leaves_without_hidden_characters(self):
        """A stored link with a combining accent, a zero-width space, a tab, a bidi override and a bell
        comes out composed and clean, and that cleaning is not counted as truncation."""
        opened = registry.connect(self.db, False)
        registry.save_qr(opened["value"], {"link": "https://example.com/cafe\u0301\u200b\tmenu\u202e\x07",
                                           "color": "#996600", "path": os.path.join(self.folder, "odd.png"),
                                           "format": "png", "ec_level": "M", "version": 3, "origin": "made"})
        registry.close(opened["value"])
        value = self.answer("#996600")
        self.assertEqual(value["records"][0]["payload_url"], "https://example.com/caf\u00e9menu")
        self.assertFalse(value["truncated"])

    def test_short_links_answer_with_their_destination(self):
        """A short link is found by its destination, and its record carries both the printed address and
        target_url; a plain code's target_url is empty."""
        code = shortlinks.new_code(7)
        opened = registry.connect(self.db, False)
        registry.save_qr(opened["value"], {"link": "HTTPS://GO.EXAMPLE.COM/" + code, "color": "#996600",
                                           "path": os.path.join(self.folder, "short.png"), "format": "png",
                                           "ec_level": "M", "version": 2, "origin": "made",
                                           "short": {"code": code, "target": "https://example.com/opening-times"}})
        registry.close(opened["value"])
        value = self.answer("https://example.com/opening-times")
        self.assertEqual(len(value["records"]), 1)
        record = value["records"][0]
        self.assertEqual((record["payload_url"], record["target_url"]),
                         ("HTTPS://GO.EXAMPLE.COM/" + code, "https://example.com/opening-times"))
        self.assertEqual(self.answer("#006633")["records"][0]["target_url"], "")

    def test_short_links_by_section(self):
        """Plans for the local or the nonlocal section, or for short links to the menu, find just those
        codes; a plain code has no section, and neither has a short link whose base changed since."""
        local = shortlinks.new_code(7)
        public = shortlinks.new_code(7)
        opened = registry.connect(self.db, False)
        for code, base, color in ((local, "HTTP://LOCALHOST:8000/", "#996600"), (public, "HTTPS://GO.EXAMPLE.COM/",
                                                                                 "#336699")):
            registry.save_qr(opened["value"], {"link": base + code, "color": color,
                                               "path": os.path.join(self.folder, code + ".png"), "format": "png",
                                               "ec_level": "M", "version": 2, "origin": "made",
                                               "short": {"code": code, "target": "https://example.com/menu"}})
        registry.close(opened["value"])
        self.fake.plans.append(plan(section="local"))
        value = self.answer("my local codes")
        self.assertEqual(self.links(value), ["HTTP://LOCALHOST:8000/" + local])
        self.assertEqual(value["records"][0]["section"], "local")
        self.assertIn("local short links", value["summary"])
        self.fake.plans.append(plan(section="nonlocal", short=True))
        value = self.answer("codes on the non-local short links")
        self.assertEqual(self.links(value), ["HTTPS://GO.EXAMPLE.COM/" + public])
        self.assertEqual(value["records"][0]["section"], "nonlocal")
        self.fake.plans.append(plan(short=True, link="menu"))
        value = self.answer("short links that still point to the menu")
        self.assertEqual(sorted(self.links(value)), sorted(["HTTP://LOCALHOST:8000/" + local,
                                                            "HTTPS://GO.EXAMPLE.COM/" + public]))
        self.fake.plans.append(plan(link="menu"))
        self.assertEqual(self.answer("codes that point to the menu")["row_count"], 3)  # with the plain menu code
        self.assertEqual(self.answer("#006633")["records"][0]["section"], "")
        self.engine["links"] = shortlinks.copy_links(shortlinks.DEFAULT_LINKS)
        self.engine["links"]["local"]["base"] = "HTTP://192.168.1.20:8000/"  # the base was changed since
        self.assertEqual(self.answer("#996600")["records"][0]["section"], "")

    def test_long_fields_are_cut(self):
        """A field over MAX_FIELD_CHARACTERS (here 40) is cut to it and the answer marked truncated."""
        ecp.MAX_FIELD_CHARACTERS = 40
        value = self.answer("#006633")
        self.assertEqual(len(value["records"][0]["file_path"]), 40)
        self.assertTrue(value["truncated"])

    def test_big_results_lose_rows_from_the_end(self):
        """An answer over MAX_RESULT_CHARACTERS drops whole rows from the end until it fits, keeps
        row_count equal to the records, and is marked truncated."""
        everything = self.answer(self.folder)
        self.assertEqual(everything["row_count"], 4)
        ecp.MAX_RESULT_CHARACTERS = len(json.dumps(everything, ensure_ascii=False)) - 50
        value = self.answer(self.folder)
        self.assertTrue(value["truncated"])
        self.assertLess(value["row_count"], 4)
        self.assertEqual(value["row_count"], len(value["records"]))
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=False)), ecp.MAX_RESULT_CHARACTERS)
        self.assertEqual(self.links(value), self.links(everything)[:value["row_count"]])


class AuditTests(EngineCase):
    """The audit log the engine writes: one chained line per call, holding hashes and counts only."""

    def lines(self):
        """The engine's audit log, one string per line."""
        handle = open(self.engine["audit_file"], "r", encoding="ascii")
        text = handle.read()
        handle.close()
        return text.splitlines()

    def test_every_call_is_one_line_of_a_chain(self):
        """Four calls make four chained lines with their tools, request ids and client info; the query's
        line holds the model, the hashes of the prompt, schema and system prompt, the Ollama version, the
        plan and timings, and never the prompt or any stored link."""
        ecp.list_models(self.engine, ecp.new_call("ecp_list_models", {"name": "test client"}, 7))
        ecp.select_model(self.engine, "qwen2.5:7b-instruct", ecp.new_call("ecp_select_model", {}, "eight"))
        self.fake.plans.append(plan(family="blue", link="shop"))
        value = self.answer("which blue QR codes link to the shop?")
        self.query("\x1b")
        self.assertEqual(audit.verify(self.engine["audit_file"])["value"], 4)
        self.assertEqual(value["audit_id"], 3)
        lines = self.lines()
        first = json.loads(lines[0])
        self.assertEqual((first["tool"], first["request_id"], first["client_info"]),
                         ("ecp_list_models", 7, {"name": "test client"}))
        self.assertEqual(json.loads(lines[1])["request_id"], "eight")
        asked = json.loads(lines[2])
        self.assertEqual((asked["result_kind"], asked["model_id"], asked["row_count"]), ("ok", QWEN, 1))
        self.assertEqual(asked["prompt_sha256"],
                         hashlib.sha256("which blue QR codes link to the shop?".encode("utf-8")).hexdigest())
        self.assertEqual(asked["schema_sha256"], ecp.schema_sha256())
        self.assertEqual(asked["system_prompt_sha256"], ecp.SYSTEM_PROMPT_SHA256)
        self.assertEqual(asked["ollama_version"], "0.40.10")
        self.assertEqual(asked["plan_used"]["family"], "blue")
        self.assertEqual(asked["inference_ns"]["eval_count"], 60)
        self.assertFalse(asked["progress_fired"])
        self.assertEqual(asked["interlock_state"], "bypassed")
        self.assertEqual(json.loads(lines[3])["result_kind"], "prompt_invalid")
        for line in lines:
            self.assertNotIn("which blue", line)  # the prompt itself is never written
            self.assertNotIn("shop.example.com", line)  # nor anything stored

    def test_a_log_that_cannot_be_written_does_not_hold_the_answer_back(self):
        """When the log cannot be written (its folder is a file) the answer still comes, with audit_id 0, and
        the failure goes to stderr."""
        self.engine["audit_file"] = os.path.join(self.db, "audit.jsonl")  # a "folder" that is a file
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            value = self.answer("#006633")
        self.assertEqual(value["audit_id"], 0)
        self.assertIn("audit:", said.getvalue())


class GroundingTests(unittest.TestCase):
    """ecp.ground and its helpers: a plan keeps only what the question itself supports."""

    def test_ground(self):
        """Values written in the question are kept ("navy" becomes family blue); an unknown intent, an
        unasked family and link, and an over-large limit are clamped; near needs a color."""
        kept, clamped = ecp.ground(plan(link="Shop", path="marketing", family="navy"),
                                   "navy codes for the SHOP in the Marketing folder")
        self.assertEqual(kept, plan(link="Shop", path="marketing", family="blue"))
        self.assertEqual(clamped, [])
        kept, clamped = ecp.ground(plan(intent="delete", family="pink", link_exact="https://example.net/x", limit=999),
                                   "what do I have?")
        self.assertEqual(kept, plan(limit=registry.MAX_LIMIT))
        self.assertEqual(len(clamped), 4)
        kept, clamped = ecp.ground(plan(near=True), "codes near nothing")
        self.assertFalse(kept["near"])

    def test_a_section_and_short_links_must_be_asked_for(self):
        """A section and short=True stay only when the question names them; "non-local", "non local",
        "nonlocal" and "public" name nonlocal and never local, "localhost" names local, and an unknown
        section is dropped."""
        kept, clamped = ecp.ground(plan(section="local", short=True), "my local codes with a short link")
        self.assertEqual((kept, clamped), (plan(section="local", short=True), []))
        kept, clamped = ecp.ground(plan(section="local", short=True), "every blue code")
        self.assertEqual(kept, plan())
        self.assertEqual(len(clamped), 2)
        self.assertIn("section: dropped", clamped[0])
        self.assertIn("short: dropped", clamped[1])
        for question in ("the non-local ones", "non local codes", "codes on the nonlocal links", "my public codes"):
            self.assertEqual(ecp.ground(plan(section="nonlocal"), question)[0]["section"], "nonlocal", question)
            self.assertEqual(ecp.ground(plan(section="local"), question)[0]["section"], "", question)
        self.assertEqual(ecp.ground(plan(section="local"), "codes on localhost")[0]["section"], "local")
        kept, clamped = ecp.ground(plan(section="elsewhere"), "local codes")
        self.assertEqual((kept["section"], len(clamped)), ("", 1))
        self.assertTrue(ecp.ground(plan(short=True), "which codes redirect?")[0]["short"])
        self.assertEqual(ecp.sections_in_question(ecp.words_of("local and non-local")), ["local", "nonlocal"])

    def test_filler_words_come_off_the_ends(self):
        """trim_edges takes words such as "the", "page" and "folder" off both ends of a link or path term."""
        self.assertEqual(ecp.trim_edges("the careers page"), "careers")
        self.assertEqual(ecp.trim_edges("Marketing folder"), "Marketing")
        self.assertEqual(ecp.trim_edges("store hours"), "store hours")
        self.assertEqual(ecp.trim_edges("the page"), "")
        kept, clamped = ecp.ground(plan(link="careers page"), "which code goes to the careers page?")
        self.assertEqual(kept["link"], "careers")

    def test_direct(self):
        """direct_plan reads a bare hex code, a plural family, a mailto link and a path; a sentence and a
        word made only of hex letters ("decade") are not direct."""
        self.assertEqual(ecp.direct_plan("3366CC"), plan(color="#3366cc"))
        self.assertEqual(ecp.direct_plan("Greys"), plan(family="grey"))
        self.assertEqual(ecp.direct_plan("mailto:shop@example.com"), plan(link_exact="mailto:shop@example.com"))
        self.assertEqual(ecp.direct_plan("C:\\Codes\\a b.png"), plan(path="C:\\Codes\\a b.png"))
        self.assertIsNone(ecp.direct_plan("blue codes for the shop"))
        self.assertIsNone(ecp.direct_plan("decade"))

    def test_plan_shapes(self):
        """check_plan_shape accepts a whole plan and refuses a missing or extra field and every wrong type
        (a bool for the limit included)."""
        self.assertEqual(ecp.check_plan_shape(plan()), "")
        missing = plan()
        del missing["path"]
        for value in (None, [], missing, dict(plan(), notes="extra"), dict(plan(), near="yes"),
                      dict(plan(), limit=True), dict(plan(), limit="5"), dict(plan(), color=None),
                      dict(plan(), short="yes"), dict(plan(), short=None), dict(plan(), section=None)):
            self.assertNotEqual(ecp.check_plan_shape(value), "", value)

    def test_the_plan_schema_is_flat_closed_and_fixed(self):
        """The JSON Schema sent as "format" requires every field, allows no others, uses no $ref, caps the
        limit at MAX_LIMIT, and hashes to the same 64 hex digits every time (the audit log records it)."""
        schema = ecp.plan_schema()
        self.assertEqual(schema["required"], list(ecp.PLAN_FIELDS))
        self.assertIs(schema["additionalProperties"], False)
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertEqual(schema["properties"]["limit"]["maximum"], registry.MAX_LIMIT)
        self.assertEqual(ecp.schema_sha256(), ecp.schema_sha256())
        self.assertEqual(len(ecp.schema_sha256()), 64)


class PlannerFileTests(unittest.TestCase):
    """planner.json: the rules, examples and word lists that make the system prompt."""

    def setUp(self):
        """A temporary folder for a planner.json of the test's own."""
        self.folder = tempfile.mkdtemp(prefix="qr_palette_planner_")
        self.path = os.path.join(self.folder, "planner.json")

    def tearDown(self):
        """Put the built-in planner back (configure_planner changes module state) and remove the folder."""
        ecp.configure_planner(ecp.DEFAULT_PLANNER)
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, data):
        """Write `data` as the test's planner.json."""
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(json.dumps(data))
        handle.close()

    def test_the_shipped_planner_file_shows_the_defaults(self):
        """The planner.json shipped beside the program is exactly planner_text(DEFAULT_PLANNER), and loads
        without warnings."""
        handle = open(os.path.join(HERE, "planner.json"), encoding="utf-8")
        shipped = handle.read()
        handle.close()
        self.assertEqual(shipped, ecp.planner_text(ecp.DEFAULT_PLANNER))
        self.assertEqual(ecp.load_planner(os.path.join(HERE, "planner.json"))["warnings"], [])

    def test_a_planner_file_changes_the_words_the_rules_and_the_examples(self):
        """A planner file's family words replace the built-in ones ("navy" is no longer known), its rules
        open the system prompt, its examples follow, and the prompt's hash follows the new text."""
        self.write({"family_words": {"sky": "blue"}, "examples": [{"question": "sky codes", "plan": plan(family="blue")}],
                    "rules": ["Plan it."]})
        loaded = self.load_and_use()
        self.assertEqual(loaded["warnings"], [])
        self.assertEqual(ecp.direct_plan("sky"), plan(family="blue"))
        self.assertEqual(swatch.family_of_word("navy"), "")
        self.assertTrue(ecp.SYSTEM_PROMPT.startswith("Plan it.\n"))
        self.assertIn("Question: sky codes", ecp.SYSTEM_PROMPT)
        self.assertEqual(ecp.SYSTEM_PROMPT_SHA256, hashlib.sha256(ecp.SYSTEM_PROMPT.encode("utf-8")).hexdigest())

    def load_and_use(self):
        """Load the test's planner.json and put it in place -> load_planner's result."""
        loaded = ecp.load_planner(self.path)
        ecp.configure_planner(loaded["planner"])
        return loaded

    def test_parts_that_cannot_be_used_keep_their_defaults(self):
        """Rules that are not a list, an example without a plan, a family word that is no family and a
        non-text skip word each warn and keep their defaults (five warnings in all)."""
        self.write({"rules": "plan it", "examples": [{"question": "x"}], "family_words": {"sky": "azure"},
                    "words_to_skip": [1]})
        loaded = ecp.load_planner(self.path)
        self.assertEqual(len(loaded["warnings"]), 5)
        self.assertEqual(loaded["planner"]["rules"], ecp.DEFAULT_PLANNER["rules"])
        self.assertEqual(loaded["planner"]["examples"], ecp.DEFAULT_PLANNER["examples"])
        self.assertEqual(loaded["planner"]["words_to_skip"], ecp.DEFAULT_PLANNER["words_to_skip"])

    def test_an_older_planner_file_keeps_its_examples(self):
        """Examples written before section and short existed get those fields filled in; section_words
        must name both sections; custom section and short words replace the built-in ones; an example
        with an unknown section is dropped."""
        older = plan(family="blue")
        del older["section"]
        del older["short"]
        self.write({"examples": [{"question": "blue codes", "plan": older}], "section_words": {"local": ["nearby"]}})
        loaded = ecp.load_planner(self.path)
        self.assertEqual(loaded["planner"]["examples"], [{"question": "blue codes", "plan": plan(family="blue")}])
        self.assertEqual(len(loaded["warnings"]), 1)  # section_words needs both sections
        self.assertEqual(loaded["planner"]["section_words"], ecp.DEFAULT_PLANNER["section_words"])
        self.write({"section_words": {"local": ["Nearby"], "nonlocal": ["online"]}, "short_words": ["brief"],
                    "examples": [{"question": "x", "plan": plan(section="far")}]})
        loaded = self.load_and_use()
        self.assertEqual(len(loaded["warnings"]), 2)  # the example's section, then "no usable examples"
        self.assertEqual(ecp.sections_in_question(ecp.words_of("nearby codes")), ["local"])
        self.assertEqual(ecp.sections_in_question(ecp.words_of("local codes")), [])
        self.assertTrue(ecp.ground(plan(short=True), "brief ones")[0]["short"])
        self.assertFalse(ecp.ground(plan(short=True), "short ones")[0]["short"])

    def test_a_missing_or_broken_file_means_the_built_in_planner(self):
        """A missing file and a file that is not JSON each give one warning and the built-in planner."""
        loaded = ecp.load_planner(os.path.join(self.folder, "missing.json"))
        self.assertEqual(loaded["planner"]["rules"], ecp.DEFAULT_PLANNER["rules"])
        self.assertEqual(len(loaded["warnings"]), 1)
        handle = open(self.path, "w", encoding="utf-8")
        handle.write("[1, 2")
        handle.close()
        self.assertEqual(len(ecp.load_planner(self.path)["warnings"]), 1)


def echo(state, message):
    """A handler for the framing tests: "echo" answers with its params, "boom" fails.

    It has the shape ecp.serve expects of a handler: (state, parsed message) -> a response message,
    or None for a notification, which JSON-RPC never answers."""
    number, method, params, problem, notification = ecp.request_parts(message)
    if notification:
        return None
    if problem is not None:
        return problem
    if method == "boom":
        raise ValueError("boom")
    if method != "echo":
        return ecp.error_message(number, ecp.METHOD_NOT_FOUND, "no method " + method, None)
    return ecp.result_message(number, params)


class FramingTests(unittest.TestCase):
    """ecp.serve: newline-delimited JSON-RPC 2.0, one response line per request, never a traceback."""

    def run_lines(self, data):
        """Serve `data` (bytes, one message per line) through echo -> the parsed responses.

        Checks on the way that the output holds no carriage return and is ASCII (json.loads of an
        ascii decode). serve's stderr is swallowed."""
        writer = io.BytesIO()
        with contextlib.redirect_stderr(io.StringIO()):
            ecp.serve(echo, {}, io.BytesIO(data), writer)
        output = writer.getvalue()
        self.assertNotIn(b"\r", output)
        responses = []
        for line in output.split(b"\n"):
            if line != b"":
                responses.append(json.loads(line.decode("ascii")))
        return responses

    def test_one_answer_per_request_line(self):
        """Two requests get two answers with their ids; a blank line and a notification (no id) get none."""
        responses = self.run_lines(b'{"jsonrpc":"2.0","id":1,"method":"echo","params":{"a":1}}\n'
                                   b"\n"
                                   b'{"jsonrpc":"2.0","method":"echo"}\n'
                                   b'{"jsonrpc":"2.0","id":"two","method":"echo"}\n')
        self.assertEqual(len(responses), 2)
        self.assertEqual((responses[0]["id"], responses[0]["result"]), (1, {"a": 1}))
        self.assertEqual(responses[1]["id"], "two")

    def test_broken_input(self):
        """Each broken line gets its JSON-RPC error code: bytes that are not UTF-8 and text that is not JSON
        are parse errors; a non-object, a bool or null id, and version 1.0 are invalid requests; params
        as a list are invalid params; an unknown method is method not found."""
        responses = self.run_lines(b"\xff\xfe\n" + b"{not json\n" + b'"text"\n' +
                                   b'{"jsonrpc":"2.0","id":true,"method":"x"}\n' +
                                   b'{"jsonrpc":"2.0","id":null,"method":"echo"}\n' +
                                   b'{"jsonrpc":"1.0","id":3,"method":"x"}\n' +
                                   b'{"jsonrpc":"2.0","id":4,"method":"echo","params":[1]}\n' +
                                   b'{"jsonrpc":"2.0","id":5,"method":"nope"}\n')
        codes = []
        for response in responses:
            codes.append(response["error"]["code"])
        self.assertEqual(codes, [ecp.PARSE_ERROR, ecp.PARSE_ERROR, ecp.INVALID_REQUEST, ecp.INVALID_REQUEST,
                                 ecp.INVALID_REQUEST, ecp.INVALID_REQUEST, ecp.INVALID_PARAMS, ecp.METHOD_NOT_FOUND])
        self.assertIsNone(responses[0]["id"])

    def test_an_over_long_line_is_refused_and_skipped(self):
        """A line over MAX_LINE is refused with a null id, and the next line is read and answered normally."""
        responses = self.run_lines(b"{" + b" " * (ecp.MAX_LINE + 10) + b"}\n" +
                                   b'{"jsonrpc":"2.0","id":9,"method":"nope"}\n')
        self.assertEqual((responses[0]["error"]["code"], responses[0]["id"]), (ecp.INVALID_REQUEST, None))
        self.assertEqual(responses[1]["id"], 9)

    def test_a_failing_handler_is_an_internal_error_not_a_traceback(self):
        """A handler that raises gives an internal error for that id, and serving goes on."""
        responses = self.run_lines(b'{"jsonrpc":"2.0","id":6,"method":"boom"}\n'
                                   b'{"jsonrpc":"2.0","id":7,"method":"echo"}\n')
        self.assertEqual((responses[0]["id"], responses[0]["error"]["code"]), (6, ecp.INTERNAL_ERROR))
        self.assertEqual(responses[1]["id"], 7)

    def test_non_ascii_text_stays_one_line(self):
        """An id holding an accented letter and U+2028 comes back intact, escaped onto one ASCII line."""
        responses = self.run_lines('{"jsonrpc":"2.0","id":"é\u2028","method":"nope"}\n'.encode("utf-8"))
        self.assertEqual(responses[0]["id"], "é\u2028")


class LiveModelTests(unittest.TestCase):
    """Plans from a real local model for the questions about short links. They run only when
    QR_PALETTE_LIVE_MODEL names a model this computer's Ollama has (for example qwen2.5:7b-instruct), at
    QR_PALETTE_LIVE_URL (default http://127.0.0.1:11434). The cloud check is the fake server's to test:
    here the plan is still asked of NAME:local on loopback."""

    def setUp(self):
        """Skip unless QR_PALETTE_LIVE_MODEL is set; else build a registry with one local and one nonlocal
        short link and an engine on the live server, with the cloud rule off, and skip when the model
        cannot be used there."""
        self.model = os.environ.get("QR_PALETTE_LIVE_MODEL", "").strip()
        if self.model == "":
            self.skipTest("set QR_PALETTE_LIVE_MODEL to a local model, such as qwen2.5:7b-instruct, to run it")
        self.folder = tempfile.mkdtemp(prefix="qr_palette_live_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.db = make_registry(self.folder)
        opened = registry.connect(self.db, False)
        for base, color in (("HTTP://LOCALHOST:8000/", "#996600"), ("HTTPS://GO.EXAMPLE.COM/", "#336699")):
            code = shortlinks.new_code(7)
            registry.save_qr(opened["value"], {"link": base + code, "color": color,
                                               "path": os.path.join(self.folder, code + ".png"), "format": "png",
                                               "ec_level": "M", "version": 2, "origin": "made",
                                               "short": {"code": code, "target": "https://shop.example.com/hours"}})
        registry.close(opened["value"])
        self.engine = ecp.new_engine(self.db, os.environ.get("QR_PALETTE_LIVE_URL", "http://127.0.0.1:11434"), 120.0,
                                     "0.1.0")
        saved = ecp.REQUIRE_CLOUD_DISABLED
        ecp.REQUIRE_CLOUD_DISABLED = False
        self.addCleanup(setattr, ecp, "REQUIRE_CLOUD_DISABLED", saved)
        found = ecp.resolve_model(self.engine, self.model)
        if not found["ok"]:
            self.skipTest(self.model + " cannot be used here: " + found["kind"] + " " + found["detail"])

    def test_questions_about_short_links_are_planned(self):
        """A real model plans four short-link questions with the fields expected, and every record found
        is in the section asked for."""
        for question, wanted in (("my local codes", {"section": "local"}),
                                 ("which QR codes have a short link?", {"short": True, "section": ""}),
                                 ("blue codes on the nonlocal short links", {"family": "blue", "section": "nonlocal"}),
                                 ("codes that link to the shop", {"link": "shop", "section": "", "short": False})):
            result = ecp.query(self.engine, question, self.model, ecp.new_call("ecp_query", {}, 1))
            self.assertTrue(result["ok"], question + ": " + result["kind"] + " " + result["detail"])
            self.assertEqual(result["value"]["plan_used"]["planner"], "model", question)
            for key in wanted:
                self.assertEqual(result["value"]["plan_used"][key], wanted[key], question)
            for record in result["value"]["records"]:
                if wanted.get("section", "") != "":
                    self.assertEqual(record["section"], wanted["section"], question)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=5fbc5f425c9e64754e51f3110cfbc204af381853f63e9878155288f823053193 ====
