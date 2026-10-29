# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_ecp.py
# About: Tests for ECP's engine: choosing and pinning a local model, planning and grounding, the...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for ECP's engine: choosing and pinning a local model, planning and grounding, the read-only
answer with its caps and labels, every refusal by kind, the audit log, planner.json and the framing."""

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
import swatch
from test_local_inference import FakeOllama, QWEN_DIGEST

HERE = os.path.dirname(os.path.abspath(__file__))

QWEN = "qwen2.5:7b-instruct@" + QWEN_DIGEST
CANARY = "https://canary.example/CANARY-7f3a"
CODES = (("shop-blue.png", "https://shop.example.com/", "#3366cc"),
         ("menu-green.png", "https://example.com/menu", "#006633"),
         ("canary.png", CANARY, "#660099"),
         ("sale-red.png", "https://shop.example.com/sale", "#cc0000"))


def plan(**changes):
    value = {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "",
             "limit": 20}
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
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_ecp_")
        self.db = make_registry(self.folder)
        self.fake = FakeOllama()
        self.engine = ecp.new_engine(self.db, self.fake.url, 5.0, "0.1.0")
        self.engine["audit_file"] = os.path.join(self.folder, "audit.jsonl")
        self.saved = (ecp.REQUIRE_CLOUD_DISABLED, ecp.MAX_FIELD_CHARACTERS, ecp.MAX_RESULT_CHARACTERS)

    def tearDown(self):
        ecp.REQUIRE_CLOUD_DISABLED, ecp.MAX_FIELD_CHARACTERS, ecp.MAX_RESULT_CHARACTERS = self.saved
        self.fake.stop()
        shutil.rmtree(self.folder, ignore_errors=True)

    def call(self, tool):
        return ecp.new_call(tool, {"name": "test"}, 1)

    def query(self, prompt, model_id=QWEN):
        return ecp.query(self.engine, prompt, model_id, self.call("ecp_query"))

    def answer(self, prompt, model_id=QWEN):
        result = self.query(prompt, model_id)
        self.assertTrue(result["ok"], result["kind"] + ": " + result["detail"])
        return result["value"]

    def links(self, value):
        found = []
        for record in value["records"]:
            found.append(record["payload_url"])
        return found


class ModelTests(EngineCase):
    def test_only_local_models_are_listed_with_their_ids(self):
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
        selected = ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))
        self.assertTrue(selected["ok"], selected["detail"])
        self.assertEqual(selected["value"]["model_id"], QWEN)
        self.assertEqual((selected["value"]["loaded"], selected["value"]["supports_thinking"]), (True, False))
        self.assertEqual(self.fake.posted("/api/generate")[0]["model"], "qwen2.5:7b-instruct:local")
        thinking = ecp.select_model(self.engine, "deepseek-r1:7b", self.call("ecp_select_model"))
        self.assertTrue(thinking["value"]["supports_thinking"])

    def test_cloud_remote_embedding_and_unknown_models_are_refused(self):
        for name in ("gpt-oss:120b-cloud", "remote-only:latest", "nomic-embed-text:latest", "nothing",
                     "qwen2.5:7b-instruct:local"):
            self.assertEqual(ecp.select_model(self.engine, name, self.call("ecp_select_model"))["kind"],
                             "model_not_local", name)
        self.fake.shown["qwen2.5:7b-instruct"] = {"remote_host": "https://ollama.com:443"}
        self.assertEqual(ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))["kind"],
                         "model_not_local")
        self.assertEqual(self.fake.posted("/api/generate"), [])  # nothing was loaded

    def test_an_answer_from_another_host_is_egress(self):
        self.fake.stamp = True
        self.assertEqual(ecp.select_model(self.engine, "qwen2.5:7b-instruct", self.call("ecp_select_model"))["kind"],
                         "egress_detected")

    def test_inference_down_or_not_on_loopback(self):
        self.fake.stop()
        self.assertEqual(ecp.list_models(self.engine, self.call("ecp_list_models"))["kind"], "inference_unavailable")
        self.fake = FakeOllama()
        engine = ecp.new_engine(self.db, "http://example.com:11434", 5.0, "0.1.0")
        listed = ecp.list_models(engine, self.call("ecp_list_models"))
        self.assertEqual(listed["kind"], "inference_unavailable")
        self.assertIn("loopback", listed["detail"])


class QueryTests(EngineCase):
    def test_a_local_model_is_chosen_first(self):
        refused = self.query("blue", "")
        self.assertEqual(refused["kind"], "args_invalid")
        self.assertIn("ecp_list_models", refused["detail"])
        self.engine["default_model"] = "qwen2.5:7b-instruct"
        self.assertEqual(self.answer("blue", "")["model_id"], QWEN)

    def test_the_pinned_digest_must_still_match(self):
        self.assertTrue(self.query("blue")["ok"])
        self.fake.models[0]["digest"] = "9" * 64
        self.assertEqual(self.query("blue")["kind"], "model_digest_mismatch")
        self.assertTrue(self.query("blue", "qwen2.5:7b-instruct")["ok"])  # a bare name takes the model as it is now
        self.fake.models.pop(0)
        self.assertEqual(self.query("blue", "qwen2.5:7b-instruct")["kind"], "model_not_local")
        self.assertEqual(self.query("blue", "gpt-oss:120b-cloud")["kind"], "model_not_local")

    def test_direct_questions_need_no_model(self):
        self.assertEqual(self.links(self.answer("#006633")), ["https://example.com/menu"])
        self.assertEqual(self.answer("blue QR codes")["plan_used"]["planner"], "direct")
        self.assertEqual(self.links(self.answer("https://example.com/menu")), ["https://example.com/menu"])
        self.assertEqual(self.answer(os.path.join(self.folder, "sale-red.png"))["row_count"], 1)
        self.assertEqual(self.fake.plans_asked(), [])

    def test_records_hold_the_color_the_link_and_the_path(self):
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
        self.fake.plans.append(plan(color="#44aacc", near=True))
        value = self.answer("show codes close to #3366cc please")
        self.assertEqual((value["plan_used"]["color"], value["plan_used"]["near"]), ("#3366cc", True))
        self.assertIn("replaced", value["plan_used"]["clamped"][0])

    def test_bad_plans_are_refused_by_kind(self):
        for answer, kind in (("not json", "plan_unparseable"), ({"intent": "find"}, "plan_invalid"),
                             (dict(plan(), notes="extra"), "plan_invalid"), ([1, 2], "plan_invalid")):
            self.fake.plans.append(answer)
            self.assertEqual(self.query("anything green in the menu?")["kind"], kind, answer)

    def test_a_cut_off_plan_is_asked_once_more_with_more_room(self):
        self.fake.plans.extend(["CUT", plan(family="green")])
        self.assertEqual(self.links(self.answer("anything green?")), ["https://example.com/menu"])
        asked = self.fake.plans_asked()
        self.assertEqual((asked[0]["options"]["num_predict"], asked[1]["options"]["num_predict"]),
                         (local_inference.PLAN_OPTIONS["num_predict"], local_inference.RETRY_ANSWER_TOKENS))
        self.fake.plans.extend(["CUT", "CUT"])
        self.assertEqual(self.query("anything green?")["kind"], "plan_truncated")

    def test_planning_needs_the_cloud_features_off(self):
        self.fake.cloud = {"disabled": False}
        refused = self.query("anything green?")
        self.assertEqual(refused["kind"], "cloud_not_disabled")
        self.assertIn("OLLAMA_NO_CLOUD", refused["detail"])
        self.assertEqual(self.fake.plans_asked(), [])
        self.assertTrue(self.query("#006633")["ok"])  # a direct question asks no model
        ecp.REQUIRE_CLOUD_DISABLED = False
        self.assertTrue(self.query("anything green?")["ok"])

    def test_a_plan_from_another_host_is_egress(self):
        self.fake.stamp = True
        self.assertEqual(self.query("anything green?")["kind"], "egress_detected")

    def test_slow_and_missing_inference_are_named(self):
        self.engine["timeout"] = 0.3
        self.fake.delay = 1.0
        self.assertEqual(self.query("anything green?")["kind"], "inference_timeout")
        self.fake.delay = 0.0
        self.fake.stop()
        self.assertEqual(self.query("anything green?")["kind"], "inference_unavailable")
        self.fake = FakeOllama()

    def test_recommendations(self):
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
        for question in ("which codes link to the shop?", "anything purple?", "show me everything you have"):
            self.query(question)
        self.assertGreater(len(self.fake.plans_asked()), 0)
        for entry in self.fake.received:
            self.assertNotIn("CANARY-7f3a", entry[2])

    def test_an_empty_question_is_refused(self):
        self.assertEqual(self.query("\x1b\u202e  ")["kind"], "prompt_invalid")


class EnvironmentTests(EngineCase):
    def test_a_missing_registry_is_unavailable_and_not_made(self):
        self.engine["db"] = os.path.join(self.folder, "none.db")
        self.assertEqual(self.query("#006633")["kind"], "db_unavailable")
        self.assertFalse(os.path.exists(self.engine["db"]))

    def test_slow_and_refused_reads_are_named(self):
        saved = registry.all_rows
        try:
            for error, kind in ((sqlite3.OperationalError("interrupted"), "db_timeout"),
                                (sqlite3.DatabaseError("not authorized"), "db_denied"),
                                (sqlite3.OperationalError("disk I/O error"), "db_unavailable")):
                def broken(connection, error=error):
                    raise error

                registry.all_rows = broken
                self.assertEqual(self.query("#006633")["kind"], kind)
        finally:
            registry.all_rows = saved

    def test_stored_text_leaves_without_hidden_characters(self):
        opened = registry.connect(self.db, False)
        registry.save_qr(opened["value"], {"link": "https://example.com/cafe\u0301\u200b\tmenu\u202e\x07",
                                           "color": "#996600", "path": os.path.join(self.folder, "odd.png"),
                                           "format": "png", "ec_level": "M", "version": 3, "origin": "made"})
        registry.close(opened["value"])
        value = self.answer("#996600")
        self.assertEqual(value["records"][0]["payload_url"], "https://example.com/caf\u00e9menu")
        self.assertFalse(value["truncated"])

    def test_long_fields_are_cut(self):
        ecp.MAX_FIELD_CHARACTERS = 40
        value = self.answer("#006633")
        self.assertEqual(len(value["records"][0]["file_path"]), 40)
        self.assertTrue(value["truncated"])

    def test_big_results_lose_rows_from_the_end(self):
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
    def lines(self):
        handle = open(self.engine["audit_file"], "r", encoding="ascii")
        text = handle.read()
        handle.close()
        return text.splitlines()

    def test_every_call_is_one_line_of_a_chain(self):
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
        self.engine["audit_file"] = os.path.join(self.db, "audit.jsonl")  # a "folder" that is a file
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            value = self.answer("#006633")
        self.assertEqual(value["audit_id"], 0)
        self.assertIn("audit:", said.getvalue())


class GroundingTests(unittest.TestCase):
    def test_ground(self):
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

    def test_filler_words_come_off_the_ends(self):
        self.assertEqual(ecp.trim_edges("the careers page"), "careers")
        self.assertEqual(ecp.trim_edges("Marketing folder"), "Marketing")
        self.assertEqual(ecp.trim_edges("store hours"), "store hours")
        self.assertEqual(ecp.trim_edges("the page"), "")
        kept, clamped = ecp.ground(plan(link="careers page"), "which code goes to the careers page?")
        self.assertEqual(kept["link"], "careers")

    def test_direct(self):
        self.assertEqual(ecp.direct_plan("3366CC"), plan(color="#3366cc"))
        self.assertEqual(ecp.direct_plan("Greys"), plan(family="grey"))
        self.assertEqual(ecp.direct_plan("mailto:shop@example.com"), plan(link_exact="mailto:shop@example.com"))
        self.assertEqual(ecp.direct_plan("C:\\Codes\\a b.png"), plan(path="C:\\Codes\\a b.png"))
        self.assertIsNone(ecp.direct_plan("blue codes for the shop"))
        self.assertIsNone(ecp.direct_plan("decade"))

    def test_plan_shapes(self):
        self.assertEqual(ecp.check_plan_shape(plan()), "")
        missing = plan()
        del missing["path"]
        for value in (None, [], missing, dict(plan(), notes="extra"), dict(plan(), near="yes"),
                      dict(plan(), limit=True), dict(plan(), limit="5"), dict(plan(), color=None)):
            self.assertNotEqual(ecp.check_plan_shape(value), "", value)

    def test_the_plan_schema_is_flat_closed_and_fixed(self):
        schema = ecp.plan_schema()
        self.assertEqual(schema["required"], list(ecp.PLAN_FIELDS))
        self.assertIs(schema["additionalProperties"], False)
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertEqual(schema["properties"]["limit"]["maximum"], registry.MAX_LIMIT)
        self.assertEqual(ecp.schema_sha256(), ecp.schema_sha256())
        self.assertEqual(len(ecp.schema_sha256()), 64)


class PlannerFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_planner_")
        self.path = os.path.join(self.folder, "planner.json")

    def tearDown(self):
        ecp.configure_planner(ecp.DEFAULT_PLANNER)
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, data):
        handle = open(self.path, "w", encoding="utf-8")
        handle.write(json.dumps(data))
        handle.close()

    def test_the_shipped_planner_file_shows_the_defaults(self):
        handle = open(os.path.join(HERE, "planner.json"), encoding="utf-8")
        shipped = handle.read()
        handle.close()
        self.assertEqual(shipped, ecp.planner_text(ecp.DEFAULT_PLANNER))
        self.assertEqual(ecp.load_planner(os.path.join(HERE, "planner.json"))["warnings"], [])

    def test_a_planner_file_changes_the_words_the_rules_and_the_examples(self):
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
        loaded = ecp.load_planner(self.path)
        ecp.configure_planner(loaded["planner"])
        return loaded

    def test_parts_that_cannot_be_used_keep_their_defaults(self):
        self.write({"rules": "plan it", "examples": [{"question": "x"}], "family_words": {"sky": "azure"},
                    "words_to_skip": [1]})
        loaded = ecp.load_planner(self.path)
        self.assertEqual(len(loaded["warnings"]), 5)
        self.assertEqual(loaded["planner"]["rules"], ecp.DEFAULT_PLANNER["rules"])
        self.assertEqual(loaded["planner"]["examples"], ecp.DEFAULT_PLANNER["examples"])
        self.assertEqual(loaded["planner"]["words_to_skip"], ecp.DEFAULT_PLANNER["words_to_skip"])

    def test_a_missing_or_broken_file_means_the_built_in_planner(self):
        loaded = ecp.load_planner(os.path.join(self.folder, "missing.json"))
        self.assertEqual(loaded["planner"]["rules"], ecp.DEFAULT_PLANNER["rules"])
        self.assertEqual(len(loaded["warnings"]), 1)
        handle = open(self.path, "w", encoding="utf-8")
        handle.write("[1, 2")
        handle.close()
        self.assertEqual(len(ecp.load_planner(self.path)["warnings"]), 1)


def echo(state, message):
    """A handler for the framing tests: "echo" answers with its params, "boom" fails."""
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
    def run_lines(self, data):
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
        responses = self.run_lines(b'{"jsonrpc":"2.0","id":1,"method":"echo","params":{"a":1}}\n'
                                   b"\n"
                                   b'{"jsonrpc":"2.0","method":"echo"}\n'
                                   b'{"jsonrpc":"2.0","id":"two","method":"echo"}\n')
        self.assertEqual(len(responses), 2)
        self.assertEqual((responses[0]["id"], responses[0]["result"]), (1, {"a": 1}))
        self.assertEqual(responses[1]["id"], "two")

    def test_broken_input(self):
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
        responses = self.run_lines(b"{" + b" " * (ecp.MAX_LINE + 10) + b"}\n" +
                                   b'{"jsonrpc":"2.0","id":9,"method":"nope"}\n')
        self.assertEqual((responses[0]["error"]["code"], responses[0]["id"]), (ecp.INVALID_REQUEST, None))
        self.assertEqual(responses[1]["id"], 9)

    def test_a_failing_handler_is_an_internal_error_not_a_traceback(self):
        responses = self.run_lines(b'{"jsonrpc":"2.0","id":6,"method":"boom"}\n'
                                   b'{"jsonrpc":"2.0","id":7,"method":"echo"}\n')
        self.assertEqual((responses[0]["id"], responses[0]["error"]["code"]), (6, ecp.INTERNAL_ERROR))
        self.assertEqual(responses[1]["id"], 7)

    def test_non_ascii_text_stays_one_line(self):
        responses = self.run_lines('{"jsonrpc":"2.0","id":"é\u2028","method":"nope"}\n'.encode("utf-8"))
        self.assertEqual(responses[0]["id"], "é\u2028")


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=9c294bc3cf2128c5f3c7fba62e0a0de1679a18b0fe282da49296d847927c9cff ====
