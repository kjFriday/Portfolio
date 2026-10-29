# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_qr_palette.py
# About: Tests for QR Palette's core and its command line: making, registering, finding, votes...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for QR Palette's core and its command line: making, registering, finding, votes, settings, and
the MCP server (--mcp, --ecp) run as a real process."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import audit
import ecp
import local_inference
import mcp_server
import qr_codec
import qr_palette
import registry
import settings
import shortlinks
import swatch
from test_local_inference import QWEN_DIGEST, FakeOllama

MODERN = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
          "io.modelcontextprotocol/clientCapabilities": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "qr_palette.py")


def child_environment(folder):
    environment = dict(os.environ)
    for key in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONSTARTUP"):
        environment.pop(key, None)
    environment["LOCALAPPDATA"] = folder
    return environment


def file_hash(path):
    handle = open(path, "rb")
    data = handle.read()
    handle.close()
    return hashlib.sha256(data).hexdigest()


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="qr_palette_core_")
        self.db = os.path.join(self.folder, "palette.db")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.folder, name)

    def make(self, name, link, color):
        made = qr_palette.make_qr(self.db, link, color, "M", self.path(name), 4)
        self.assertTrue(made["ok"], made["error"])
        return made["value"]


class MakeTests(CoreCase):
    def test_made_codes_are_files_and_records(self):
        made = self.make("shop.png", "https://shop.example.com/", "#3366cc")
        self.assertTrue(os.path.isfile(made["path"]))
        picture = qr_codec.read_qr_file(made["path"])
        self.assertEqual((picture["value"]["reading"]["text"], picture["value"]["color"]),
                         ("https://shop.example.com/", "#3366cc"))
        svg = self.make("menu.svg", "https://example.com/menu", "#006633")
        self.assertTrue(svg["path"].endswith("menu.svg"))
        found = qr_palette.search(self.db, "qr_code", "https://example.com/menu", False, 20)["value"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["hex"], found[0]["path"], found[0]["exists"]), ("#006633", svg["path"], True))

    def test_what_cannot_be_made(self):
        for link, color, problem in (("", "#3366cc", "type a link"), ("x", "", "pick a color"),
                                     ("x", "#ffff00", "too light"), ("x" * 4000, "#3366cc", "too long")):
            made = qr_palette.make_qr(self.db, link, color, "M", self.path("bad.png"), 4)
            self.assertFalse(made["ok"])
            self.assertIn(problem, made["error"])
        self.assertFalse(os.path.exists(self.path("bad.png")))

    def test_saving_over_a_code_replaces_its_record(self):
        self.make("same.png", "https://example.com/a", "#3366cc")
        self.make("same.png", "https://example.com/b", "#cc0000")
        rows = qr_palette.search(self.db, "color", "red", False, 20)["value"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(qr_palette.search(self.db, "qr_code", "example.com", False, 20)["value"][0]["link"],
                         "https://example.com/b")

    def test_control_characters_are_cleaned_before_encoding(self):
        made = self.make("clean.png", "https://example.com/\u202eabc\x07", "#3366cc")
        self.assertEqual(made["link"], "https://example.com/abc")

    def test_names(self):
        self.assertEqual(qr_palette.slug("https://www.Shop.example.com/sale?id=4"), "shop-example-com-sale-id-4")
        self.assertEqual(qr_palette.slug("::"), "qr-code")
        self.assertEqual(qr_palette.suggested_name("https://example.com/a", "#3366cc", "svg"), "example-com-a-3366cc.svg")


class RegisterTests(CoreCase):
    def test_pictures_made_elsewhere_are_registered_in_the_color_given(self):
        matrix = qr_codec.encode_text("https://example.com/elsewhere", "Q", 1, -1)["value"]
        qr_codec.save_matrix(matrix, self.path("elsewhere.png"), 4, "#3467cb")
        picture = qr_codec.read_qr_file(self.path("elsewhere.png"))
        self.assertEqual(picture["value"]["color"], "#3467cb")
        registered = qr_palette.register_picture(self.db, self.path("elsewhere.png"), "#3467CB")
        self.assertTrue(registered["ok"], registered["error"])
        found = qr_palette.search(self.db, "color", "#3366cc", True, 20)["value"]
        self.assertEqual(found[0]["link"], "https://example.com/elsewhere")
        self.assertEqual(found[0]["ec_level"], "Q")
        matches = qr_palette.matches_for_text(self.db, "https://example.com/elsewhere", "")["value"]
        self.assertEqual(len(matches), 1)

    def test_other_formats_and_bad_files_are_refused(self):
        matrix = qr_codec.encode_text("x", "M", 1, -1)["value"]
        image = qr_codec.matrix_to_image(matrix, 3, 4)
        ppm = b"P5 " + str(image["width"]).encode() + b" " + str(image["height"]).encode() + b" 255\n" + bytes(image["gray"])
        handle = open(self.path("code.ppm"), "wb")
        handle.write(ppm)
        handle.close()
        refused = qr_palette.register_picture(self.db, self.path("code.ppm"), "#000000")
        self.assertIn("only PNG and SVG", refused["error"])
        self.assertFalse(qr_palette.register_picture(self.db, self.path("missing.png"), "#000000")["ok"])
        self.assertFalse(qr_palette.register_picture(self.db, self.path("code.ppm"), "black")["ok"])

    def test_forgetting_leaves_the_file(self):
        made = self.make("keep.png", "https://example.com/keep", "#3366cc")
        self.assertTrue(qr_palette.forget_record(self.db, made["id"])["value"])
        self.assertTrue(os.path.isfile(made["path"]))
        self.assertEqual(qr_palette.search(self.db, "qr_code", "keep", False, 20)["value"], [])


class VoteTests(CoreCase):
    def test_votes_reorder_the_board(self):
        first = qr_palette.board(self.db, "mixer")["value"]
        self.assertEqual(len(first["order"]), 118)
        self.assertEqual(qr_palette.vote_color(self.db, "#009966", 1)["value"], 1)
        self.assertEqual(qr_palette.board(self.db, "mixer")["value"]["order"][0], "#009966")
        self.assertEqual(qr_palette.vote_color(self.db, "#009966", 1)["value"], 0)
        self.assertEqual(qr_palette.board(self.db, "mixer")["value"]["order"], first["order"])

    def test_color_voats_votes_are_imported_once(self):
        social = {"posts": [], "votes": {"#3366cc": {"voat": 1, "when": 1793188800.0},
                                         "#cc0000": {"voat": -1, "when": 1793188900.0}},
                  "comments": {}, "saved": {}}
        handle = open(self.path("social.json"), "w", encoding="utf-8")
        json.dump(social, handle)
        handle.close()
        self.assertEqual(qr_palette.import_color_voats(self.db, self.path("social.json"))["value"], 2)
        self.assertEqual(qr_palette.import_color_voats(self.db, self.path("social.json"))["value"], 0)
        self.assertEqual(qr_palette.board(self.db, "popular")["value"]["votes"], {"#3366cc": 1, "#cc0000": -1})
        handle = open(self.path("bad.json"), "w", encoding="utf-8")
        handle.write("[]")
        handle.close()
        self.assertFalse(qr_palette.import_color_voats(self.db, self.path("bad.json"))["ok"])


class ShortLinkTests(CoreCase):
    TARGET = "https://shop.example.com/hours"

    def make_short(self, name, color, target=TARGET, section="nonlocal"):
        return qr_palette.make_qr(self.db, target, color, "M", self.path(name), 4,
                                  qr_palette.short_request(shortlinks.new_code(7), section))

    def test_local_and_nonlocal_short_links_are_separate(self):
        public = self.make_short("hours.png", "#3366cc")["value"]
        local = self.make_short("hours-local.png", "#3366cc", section="local")["value"]
        self.assertNotEqual(local["short_code"], public["short_code"])
        self.assertEqual(local["link"], "HTTP://LOCALHOST:8000/" + local["short_code"])
        self.assertEqual(local["target"], public["target"])
        self.assertEqual(qr_codec.read_qr_file(local["path"])["value"]["reading"]["text"], local["link"])
        again = self.make_short("hours-local.svg", "#3366cc", section="local")["value"]
        self.assertEqual(again["short_code"], local["short_code"])
        notes = []
        for shown in qr_palette.search(self.db, "qr_code", "hours", False, 20)["value"]:
            notes.append(qr_palette.short_note(shown))
        self.assertEqual(sorted(notes), [" (local)", " (local)", " (nonlocal)"])

    def test_a_short_link_is_printed_and_its_destination_registered(self):
        made = self.make_short("hours.png", "#3366cc")
        self.assertTrue(made["ok"], made["error"])
        code = made["value"]["short_code"]
        self.assertTrue(shortlinks.is_valid_code(code))
        self.assertEqual(made["value"]["link"], "HTTPS://GO.EXAMPLE.COM/" + code)
        self.assertEqual(made["value"]["target"], self.TARGET)
        self.assertEqual(made["value"]["version"], 2)
        picture = qr_codec.read_qr_file(made["value"]["path"])
        self.assertEqual(picture["value"]["reading"]["text"], made["value"]["link"])
        for value in ("hours", self.TARGET, code):
            found = qr_palette.search(self.db, "qr_code", value, False, 20)["value"]
            self.assertEqual(len(found), 1, value)
            self.assertEqual((found[0]["short_code"], found[0]["target"]), (code, self.TARGET))

    def test_the_same_destination_and_color_reuse_the_id(self):
        first = self.make_short("hours.png", "#3366cc")["value"]
        again = self.make_short("hours.svg", "#3366cc")["value"]
        other = self.make_short("hours-green.png", "#006633")["value"]
        self.assertEqual(again["short_code"], first["short_code"])
        self.assertNotEqual(other["short_code"], first["short_code"])
        self.assertEqual(len(qr_palette.search(self.db, "qr_code", "hours", False, 20)["value"]), 3)

    def test_only_web_links_get_short_links(self):
        refused = self.make_short("x.png", "#3366cc", "just some text")
        self.assertFalse(refused["ok"])
        self.assertIn("http", refused["error"])
        self.assertFalse(os.path.exists(self.path("x.png")))

    def test_destinations_change_without_a_new_picture(self):
        made = self.make_short("hours.png", "#3366cc")["value"]
        before = file_hash(made["path"])
        self.assertTrue(qr_palette.retarget_link(self.db, made["short_code"], "https://shop.example.com/holidays")["ok"])
        found = qr_palette.search(self.db, "qr_code", "holidays", False, 20)["value"]
        self.assertEqual(found[0]["target"], "https://shop.example.com/holidays")
        self.assertEqual(file_hash(made["path"]), before)
        self.assertFalse(qr_palette.retarget_link(self.db, made["short_code"], "not a link")["ok"])
        self.assertFalse(qr_palette.retarget_link(self.db, shortlinks.new_code(7), self.TARGET)["ok"])

    def export(self, arguments):
        return subprocess.run([sys.executable, PROGRAM, "--db", self.db] + arguments, capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)

    def test_redirect_pages_are_exported_from_the_command_line_one_section_at_a_time(self):
        first = self.make_short("hours.png", "#3366cc")["value"]
        second = self.make_short("menu.png", "#006633", "https://example.com/menu")["value"]
        local = self.make_short("try.png", "#006633", "https://example.com/try", "local")["value"]
        site = self.path("site")
        done = self.export(["--export-redirects", site, "--section", "nonlocal"])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(b"wrote 2 nonlocal redirect page(s)", done.stdout)
        handle = open(os.path.join(site, first["short_code"], "index.html"), encoding="utf-8")
        page = handle.read()
        handle.close()
        self.assertIn("url=https://shop.example.com/hours?utm_source=qr", page)
        self.assertTrue(os.path.isfile(os.path.join(site, second["short_code"], "index.html")))
        self.assertFalse(os.path.exists(os.path.join(site, local["short_code"])))
        lan = self.path("lan")
        done = self.export(["--export-redirects", lan])  # settings.json's links.use: local by default
        self.assertIn(b"wrote 1 local redirect page(s)", done.stdout)
        self.assertTrue(os.path.isfile(os.path.join(lan, local["short_code"], "index.html")))
        self.assertEqual(self.export(["--export-redirects", lan, "--section", "elsewhere"]).returncode, 2)
        self.assertFalse(qr_palette.export_redirects(self.path("none.db"), site, "local")["ok"])


class ApplySettingsTests(unittest.TestCase):
    def tearDown(self):
        qr_palette.apply_settings(settings.load("no-such-settings.json")["values"])

    def test_settings_reach_every_module(self):
        values = settings.load("no-such-settings.json")["values"]
        values["colors"]["minimum_contrast"] = 4.5
        values["queries"]["max_limit"] = 50
        values["queries"]["statement_seconds"] = 0.5
        values["inference"]["max_answer_tokens"] = 128
        values["inference"]["retry_answer_tokens"] = 300
        values["inference"]["require_cloud_disabled"] = False
        values["protocol"]["max_field_characters"] = 80
        values["protocol"]["rate_burst"] = 9
        values["colors"]["preset"] = "nothing_like_it"
        warnings = qr_palette.apply_settings(values)
        self.assertEqual(len(swatch.usable_colors()), 77)
        self.assertEqual(registry.MAX_LIMIT, 50)
        self.assertEqual(registry.STATEMENT_SECONDS, 0.5)
        self.assertEqual(local_inference.PLAN_OPTIONS["num_predict"], 128)
        self.assertEqual(local_inference.RETRY_ANSWER_TOKENS, 300)
        self.assertIs(ecp.REQUIRE_CLOUD_DISABLED, False)
        self.assertEqual(ecp.MAX_FIELD_CHARACTERS, 80)
        self.assertEqual(mcp_server.RATE_BURST, 9)
        self.assertEqual(values["colors"]["preset"], "mixer")
        self.assertEqual(len(warnings), 1)

    def test_the_engine_follows_the_settings(self):
        values = settings.load("no-such-settings.json")["values"]
        values["colors"]["preset"] = "popular"
        engine = qr_palette.make_engine("x.db", "http://127.0.0.1:11434", 9.0, values, "qwen2.5:7b-instruct")
        self.assertEqual((engine["preset"], engine["default_model"], engine["timeout"]),
                         ("popular", "qwen2.5:7b-instruct", 9.0))
        self.assertEqual(engine["audit_file"], qr_palette.default_audit_path())
        values["audit"]["file"] = os.path.abspath("elsewhere.jsonl")
        self.assertEqual(qr_palette.make_engine("x.db", "", 9.0, values, "")["audit_file"],
                         os.path.abspath("elsewhere.jsonl"))

    def test_ecp_records_become_result_rows(self):
        record = {"id": 3, "hex": "#3366cc", "color_name": "Blue", "color_family": "blue", "rank": 1,
                  "payload_url": "https://example.com/a", "target_url": "", "file_path": "C:\\Codes\\a.png",
                  "net_votes": 0, "created_at": "2026-10-29T10:00:00Z", "exists": None}
        self.assertEqual(qr_palette.shown_from_record(record),
                         {"id": 3, "link": "https://example.com/a", "hex": "#3366cc", "name": "Blue", "family": "blue",
                          "path": "C:\\Codes\\a.png", "exists": None, "ec_level": "M", "version": 1,
                          "short_code": "", "target": ""})
        record["payload_url"] = "HTTPS://GO.EXAMPLE.COM/12345674"
        record["target_url"] = "https://example.com/a"
        shown = qr_palette.shown_from_record(record)
        self.assertEqual((shown["short_code"], qr_palette.destination(shown)), ("12345674", "https://example.com/a"))

    def test_links_json_comes_from_the_settings(self):
        folder = tempfile.mkdtemp(prefix="qr_palette_links_setting_")
        try:
            path = os.path.join(folder, "links.json")
            handle = open(path, "w", encoding="utf-8")
            handle.write(json.dumps({"nonlocal": {"base": "HTTPS://GO.SHOP.TEST/"}, "id_digits": 5}))
            handle.close()
            values = settings.load("no-such-settings.json")["values"]
            self.assertEqual(values["links"]["use"], "local")
            values["links"]["file"] = path
            values["links"]["use"] = "nonlocal"
            self.assertEqual(qr_palette.apply_settings(values), [])
            self.assertEqual((qr_palette.LINKS["nonlocal"]["base"], qr_palette.LINKS["id_digits"]),
                             ("HTTPS://GO.SHOP.TEST/", 5))
            self.assertEqual(qr_palette.LINK_SECTION, "nonlocal")
            self.assertEqual(qr_palette.short_request("1", qr_palette.LINK_SECTION)["base"], "HTTPS://GO.SHOP.TEST/")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class CommandLineTests(CoreCase):
    def setUp(self):
        CoreCase.setUp(self)
        self.fake = FakeOllama()
        self.make("shop.png", "https://shop.example.com/", "#3366cc")
        self.make("menu.png", "https://example.com/menu", "#006633")

    def tearDown(self):
        self.fake.stop()
        CoreCase.tearDown(self)

    def run_program(self, arguments, lines):
        data = b""
        for line in lines:
            data = data + json.dumps(line).encode("utf-8") + b"\n"
        done = subprocess.run([sys.executable, PROGRAM] + arguments, input=data, capture_output=True, timeout=120,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertNotIn(b"\r", done.stdout)
        answers = []
        for line in done.stdout.split(b"\n"):
            if line != b"":
                answers.append(json.loads(line.decode("ascii")))
        return done, answers

    def test_version_and_bad_options(self):
        done = subprocess.run([sys.executable, PROGRAM, "--version"], capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.stdout.decode("ascii").strip(), "Generic Company QR Palette 0.1.0")
        done = subprocess.run([sys.executable, PROGRAM, "--ecp", "--inference", "http://example.com:11434"],
                              capture_output=True, timeout=60, env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"local inference", done.stdout)
        done = subprocess.run([sys.executable, PROGRAM, "--db"], capture_output=True, timeout=60,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 2)

    def lines_of(self, number, prompt, model_id, meta):
        params = {"name": "ecp_query", "arguments": {"prompt": prompt}}
        if model_id != "":
            params["arguments"]["model_id"] = model_id
        if meta is not None:
            params["_meta"] = meta
        return {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": params}

    def legacy_start(self):
        return [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}]

    def audit_file(self):
        return os.path.join(self.folder, "Generic Company Inc", qr_palette.APP_ID, "audit.jsonl")

    def test_mcp_over_stdio_in_both_eras(self):
        before = file_hash(self.db)
        done, answers = self.run_program(["--mcp", "--db", self.db, "--inference", self.fake.url], self.legacy_start() + [
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self.lines_of(3, "#3366cc", "", None),
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "ecp_select_model", "arguments": {"name": "qwen2.5:7b-instruct"}}},
            self.lines_of(5, "#3366cc", "qwen2.5:7b-instruct@" + QWEN_DIGEST, None)])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(answers), 5)
        self.assertEqual(answers[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(len(answers[1]["result"]["tools"]), 3)
        self.assertEqual(answers[2]["result"]["structuredContent"]["kind"], "args_invalid")  # no model chosen yet
        self.assertEqual(answers[3]["result"]["structuredContent"]["model_id"], "qwen2.5:7b-instruct@" + QWEN_DIGEST)
        self.assertFalse(answers[4]["result"]["isError"])
        self.assertEqual(answers[4]["result"]["structuredContent"]["records"][0]["file_path"], self.path("shop.png"))
        done, answers = self.run_program(["--ecp", "--db", self.db, "--inference", self.fake.url], [
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN}},
            self.lines_of(2, "#006633", "qwen2.5:7b-instruct", MODERN)])
        self.assertEqual(answers[0]["result"]["supportedVersions"], ["2026-07-28"])
        self.assertEqual(answers[1]["result"]["resultType"], "complete")
        self.assertEqual(answers[1]["result"]["structuredContent"]["records"][0]["payload_url"],
                         "https://example.com/menu")
        self.assertEqual(file_hash(self.db), before)
        self.assertEqual(audit.verify(self.audit_file())["value"], 4)

    def test_the_default_model(self):
        done, answers = self.run_program(["--mcp", "--db", self.db, "--inference", self.fake.url, "--model",
                                          "qwen2.5:7b-instruct"], self.legacy_start() + [
            self.lines_of(2, "https://example.com/menu", "", None)])
        self.assertEqual(answers[1]["result"]["structuredContent"]["records"][0]["hex"], "#006633")

    def test_settings_change_what_the_server_does(self):
        custom = self.path("custom-settings.json")
        audit_path = os.path.join(self.folder, "logs", "ecp-audit.jsonl")
        handle = open(custom, "w", encoding="utf-8")
        handle.write(json.dumps({"queries": {"default_limit": 1}, "registry": self.db, "audit": {"file": audit_path},
                                 "inference": {"url": self.fake.url, "model": "qwen2.5:7b-instruct"}}))
        handle.close()
        done, answers = self.run_program(["--mcp", "--settings", custom], self.legacy_start() + [
            self.lines_of(2, self.folder, "", None)])
        self.assertEqual(done.returncode, 0, done.stderr)
        content = answers[1]["result"]["structuredContent"]
        self.assertEqual((content["row_count"], content["model_id"]), (1, "qwen2.5:7b-instruct@" + QWEN_DIGEST))
        self.assertEqual(audit.verify(audit_path)["value"], 1)

    def test_a_broken_settings_file_is_reported_not_fatal(self):
        broken = self.path("broken-settings.json")
        handle = open(broken, "w", encoding="utf-8")
        handle.write('{"colors": ')
        handle.close()
        before = file_hash(broken)
        done, answers = self.run_program(["--mcp", "--settings", broken, "--db", self.db, "--inference", self.fake.url],
                                         self.legacy_start() + [self.lines_of(2, "#3366cc", "qwen2.5:7b-instruct", None)])
        self.assertIn(b"not valid JSON", done.stderr)
        self.assertEqual(answers[1]["result"]["structuredContent"]["row_count"], 1)
        self.assertEqual(file_hash(broken), before)

    def test_selftest(self):
        done = subprocess.run([sys.executable, PROGRAM, "--selftest"], capture_output=True, timeout=120,
                              env=child_environment(self.folder), cwd=HERE)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=4eb405681a22f197e8ca2c4521796455a76f19e0d98d9a55e9162d152ef0cdb5 ====
