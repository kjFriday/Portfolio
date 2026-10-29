# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/test_local_inference.py
# About: Tests for the local inference client: the loopback rule, model listing, cloud checks and...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""Tests for the local inference client: the loopback rule, model listing, cloud checks and planning
calls. FakeOllama, a small Ollama stand-in on 127.0.0.1, is also used by the ECP, MCP and CLI tests."""

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import local_inference

PLAN = {"intent": "find", "color": "", "near": False, "family": "", "link": "", "link_exact": "", "path": "",
        "limit": 20}
QWEN_DIGEST = "a" * 64
R1_DIGEST = "b" * 64


def default_models():
    return [
        {"name": "qwen2.5:7b-instruct", "digest": QWEN_DIGEST, "size": 4683087332,
         "capabilities": ["completion", "tools"],
         "details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
        {"name": "deepseek-r1:7b", "digest": R1_DIGEST, "size": 4683075440,
         "capabilities": ["tools", "thinking", "completion"],
         "details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
        {"name": "deepseek-coder:base", "digest": "c" * 64, "size": 776080839, "capabilities": ["completion"],
         "details": {}},
        {"name": "nomic-embed-text:latest", "digest": "d" * 64, "size": 274302450, "capabilities": ["embedding"],
         "details": {}},
        {"name": "gpt-oss:120b-cloud", "digest": "e" * 64, "remote_host": "https://ollama.com:443",
         "remote_model": "gpt-oss:120b", "size": 384, "capabilities": ["completion", "tools"], "details": {}},
        {"name": "remote-only:latest", "digest": "f" * 64, "remote_model": "big-model", "size": 384,
         "capabilities": ["completion"], "details": {}},
        {"name": "old-model:latest", "digest": "1" * 64, "size": 1000, "details": {"family": "llama"}},
    ]


class FakeOllama:
    """An Ollama stand-in on 127.0.0.1 with a free port.
    mode     "normal", "redirect", "server-error", "not-json", "missing" (404 for /api/generate) or
             "no-status" (404 for /api/status)
    cloud    what /api/status says: {"disabled": True} unless changed
    stamp    True: every /api/generate answer says it came from another host
    plans    answers for the next planning calls: a dict (sent as JSON), a string as it is, or "CUT"
             for an answer cut off at the length limit
    shown    extra fields /api/show adds for a model name (remote_host, for instance)"""

    def __init__(self):
        self.models = default_models()
        self.plans = []
        self.mode = "normal"
        self.cloud = {"disabled": True}
        self.stamp = False
        self.shown = {}
        self.delay = 0.0
        self.received = []
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *arguments):
                pass

            def answer(self, status, value, raw):
                if fake.delay > 0:
                    time.sleep(fake.delay)
                data = raw
                if data is None:
                    data = json.dumps(value).encode("utf-8")
                try:
                    self.send_response(status)
                    if status in (301, 302, 307, 308):
                        self.send_header("Location", "http://example.com/api/tags")
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client gave up waiting (the slow-server test)

            def special(self):
                if fake.mode == "redirect":
                    self.answer(307, {}, b"{}")
                    return True
                if fake.mode == "server-error":
                    self.answer(500, {"error": "boom"}, None)
                    return True
                if fake.mode == "not-json":
                    self.answer(200, None, b"<html>hello</html>")
                    return True
                return False

            def do_GET(self):
                with fake.lock:
                    fake.received.append(("GET", self.path, ""))
                if self.special():
                    return
                if self.path == "/api/version":
                    self.answer(200, {"version": "0.40.10"}, None)
                elif self.path == "/api/status" and fake.mode != "no-status":
                    self.answer(200, {"cloud": fake.cloud}, None)
                elif self.path == "/api/tags":
                    self.answer(200, {"models": fake.models}, None)
                else:
                    self.answer(404, {"error": "not found"}, None)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                with fake.lock:
                    fake.received.append(("POST", self.path, body))
                if self.special():
                    return
                request = json.loads(body)
                if self.path == "/api/show":
                    shown = {"capabilities": ["completion"]}
                    for model in fake.models:
                        if model["name"] == request["model"] and isinstance(model.get("capabilities"), list):
                            shown["capabilities"] = model["capabilities"]
                    shown.update(fake.shown.get(request["model"], {}))
                    self.answer(200, shown, None)
                elif self.path == "/api/generate":
                    self.generate(request)
                else:
                    self.answer(404, {"error": "not found"}, None)

            def generate(self, request):
                if fake.mode == "missing":
                    self.answer(404, {"error": "model '" + request["model"] + "' not found"}, None)
                    return
                if "prompt" not in request:
                    answer = {"model": request["model"], "response": "", "done": True, "done_reason": "load",
                              "load_duration": 1234567}
                else:
                    content = json.dumps(PLAN)
                    reason = "stop"
                    with fake.lock:
                        if len(fake.plans) > 0:
                            content = fake.plans.pop(0)
                    if content == "CUT":
                        content = '{"intent": "fi'
                        reason = "length"
                    if not isinstance(content, str):
                        content = json.dumps(content)
                    answer = {"model": request["model"], "response": content, "done": True, "done_reason": reason,
                              "total_duration": 900000000, "load_duration": 1000000, "eval_count": 60}
                if fake.stamp:
                    answer["remote_host"] = "https://ollama.com:443"
                    answer["remote_model"] = "gpt-oss:120b"
                self.answer(200, answer, None)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def posted(self, path):
        found = []
        with self.lock:
            for entry in self.received:
                if entry[1] == path:
                    found.append(json.loads(entry[2]))
        return found

    def plans_asked(self):
        """The planning calls received: /api/generate bodies that carry a prompt."""
        found = []
        for body in self.posted("/api/generate"):
            if "prompt" in body:
                found.append(body)
        return found

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def endpoint_of(url):
    return local_inference.parse_endpoint(url)["value"]


class EndpointTests(unittest.TestCase):
    def test_loopback_addresses_are_accepted(self):
        cases = {"http://127.0.0.1:11434": ("127.0.0.1", 11434), "http://localhost:11434": ("127.0.0.1", 11434),
                 "http://LOCALHOST": ("127.0.0.1", 11434), "http://[::1]:8080/": ("::1", 8080),
                 "http://127.0.0.2:9": ("127.0.0.2", 9), "http://[::ffff:127.0.0.1]:11434": ("127.0.0.1", 11434)}
        for url in cases:
            parsed = local_inference.parse_endpoint(url)
            self.assertTrue(parsed["ok"], url + ": " + parsed["error"])
            self.assertEqual((parsed["value"]["host"], parsed["value"]["port"]), cases[url], url)
        self.assertEqual(endpoint_of("http://[::1]:8080")["url"], "http://[::1]:8080")

    def test_everything_else_is_refused_without_looking_names_up(self):
        for url in ("https://127.0.0.1:11434", "http://10.0.0.5:11434", "http://example.com:11434",
                    "http://localhost.example.com", "http://user:pw@127.0.0.1:11434", "http://127.0.0.1:11434/api",
                    "http://127.0.0.1:11434?x=1", "http://127.0.0.1:99999", "http://[fe80::1%25eth0]:11434",
                    "ftp://127.0.0.1", "", "http://0.0.0.0:11434", "http://127.1:11434", "127.0.0.1:11434",
                    "http://[::ffff:10.0.0.5]:11434", None):
            self.assertFalse(local_inference.parse_endpoint(url)["ok"], url)

    def test_nothing_listening_is_a_clear_failure(self):
        listed = local_inference.list_models(endpoint_of("http://127.0.0.1:1"), 1.0, "")
        self.assertFalse(listed["ok"])
        self.assertEqual(listed["kind"], "inference_unavailable")
        self.assertIn("cannot reach local inference", listed["error"])
        self.assertFalse(local_inference.reachable(None))

    def test_cloud_names(self):
        for name in ("gpt-oss:120b-cloud", "gpt-oss:120b:cloud", "qwen3:CLOUD", "qwen2.5:7b-instruct:local"):
            self.assertTrue(local_inference.is_cloud_name(name), name)
        for name in ("qwen2.5:7b-instruct", "deepseek-r1:7b", "cloudy:latest", "local-model:latest"):
            self.assertFalse(local_inference.is_cloud_name(name), name)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama()
        self.endpoint = endpoint_of(self.fake.url)

    def tearDown(self):
        self.fake.stop()

    def listed(self, default_name=""):
        listed = local_inference.list_models(self.endpoint, 3.0, default_name)
        self.assertTrue(listed["ok"], listed["error"])
        by_name = {}
        for model in listed["value"]:
            by_name[model["name"]] = model
        return listed["value"], by_name

    def test_only_local_models_that_complete_text_are_listed(self):
        models, by_name = self.listed("deepseek-r1:7b")
        names = []
        for model in models:
            names.append(model["name"])
        self.assertEqual(names, ["deepseek-coder:base", "deepseek-r1:7b", "old-model:latest", "qwen2.5:7b-instruct"])
        self.assertIn("base model", by_name["deepseek-coder:base"]["note"])
        self.assertIn("thinking", by_name["deepseek-r1:7b"]["note"])
        self.assertEqual(by_name["qwen2.5:7b-instruct"]["note"], "")
        self.assertEqual(by_name["qwen2.5:7b-instruct"]["model_id"], "qwen2.5:7b-instruct@" + QWEN_DIGEST)
        self.assertEqual(by_name["qwen2.5:7b-instruct"]["size_bytes"], 4683087332)
        self.assertTrue(by_name["deepseek-r1:7b"]["is_default"])
        self.assertFalse(by_name["qwen2.5:7b-instruct"]["is_default"])
        self.assertTrue(local_inference.reachable(self.endpoint))

    def test_capabilities_come_from_show_when_tags_lack_them(self):
        models, by_name = self.listed()
        self.assertEqual(by_name["old-model:latest"]["capabilities"], ["completion"])
        self.assertEqual(len(self.fake.posted("/api/show")), 1)

    def test_proxy_settings_are_ignored(self):
        saved = {}
        for key in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            saved[key] = os.environ.get(key)
            os.environ[key] = "http://10.255.255.1:9"
        try:
            models, by_name = self.listed()
            self.assertIn("qwen2.5:7b-instruct", by_name)
        finally:
            for key in saved:
                if saved[key] is None:
                    del os.environ[key]
                else:
                    os.environ[key] = saved[key]

    def test_redirects_and_bad_answers_fail(self):
        for mode, words in (("redirect", "redirect"), ("server-error", "HTTP 500"), ("not-json", "JSON")):
            self.fake.mode = mode
            listed = local_inference.list_models(self.endpoint, 3.0, "")
            self.assertFalse(listed["ok"], mode)
            self.assertIn(words, listed["error"], mode)
            self.assertEqual(listed["kind"], "inference_unavailable", mode)
        followed = 0
        for entry in self.fake.received:
            if entry[1] == "/api/tags":
                followed = followed + 1
        self.assertEqual(followed, 3)  # the redirect was not followed anywhere

    def test_a_slow_server_times_out(self):
        self.fake.delay = 1.5
        listed = local_inference.list_models(self.endpoint, 0.3, "")
        self.assertFalse(listed["ok"])
        self.assertEqual(listed["kind"], "inference_timeout")

    def test_version_and_cloud_status(self):
        self.assertEqual(local_inference.version(self.endpoint)["value"], "0.40.10")
        self.assertIs(local_inference.cloud_disabled(self.endpoint)["value"], True)
        for cloud in ({"disabled": False}, {}, None, {"disabled": "yes"}):
            self.fake.cloud = cloud
            self.assertIs(local_inference.cloud_disabled(self.endpoint)["value"], False, cloud)
        self.fake.mode = "no-status"
        self.assertIs(local_inference.cloud_disabled(self.endpoint)["value"], False)  # an older daemon cannot say
        self.fake.mode = "server-error"
        self.assertFalse(local_inference.cloud_disabled(self.endpoint)["ok"])

    def test_show_reports_remote_models(self):
        self.fake.shown["qwen2.5:7b-instruct"] = {"remote_host": "https://ollama.com:443"}
        shown = local_inference.show(self.endpoint, "qwen2.5:7b-instruct", 3.0)
        self.assertTrue(shown["value"]["remote"])
        shown = local_inference.show(self.endpoint, "deepseek-r1:7b", 3.0)
        self.assertEqual((shown["value"]["remote"], shown["value"]["thinking"]), (False, True))

    def test_warming_loads_the_local_copy(self):
        warmed = local_inference.warm(self.endpoint, "qwen2.5:7b-instruct", 3.0)
        self.assertEqual(warmed["value"], {"loaded": True, "load_duration_ns": 1234567})
        warmed = self.fake.posted("/api/generate")[0]
        self.assertEqual(warmed["model"], "qwen2.5:7b-instruct:local")
        self.assertEqual(warmed["options"], {"num_ctx": local_inference.PLAN_OPTIONS["num_ctx"]})
        self.fake.stamp = True
        self.assertEqual(local_inference.warm(self.endpoint, "qwen2.5:7b-instruct", 3.0)["kind"], "egress_detected")

    def test_plans_are_asked_deterministically_of_the_local_copy(self):
        models, by_name = self.listed()
        self.fake.plans.append({"intent": "find", "color": "", "near": False, "family": "blue", "link": "",
                                "link_exact": "", "path": "", "limit": 20})
        answered = local_inference.generate_json(self.endpoint, by_name["qwen2.5:7b-instruct"], "rules", "blue",
                                                 {"type": "object"}, 3.0, 256)
        self.assertTrue(answered["ok"], answered["error"])
        self.assertEqual(json.loads(answered["value"]["text"])["family"], "blue")
        self.assertEqual(answered["value"]["inference_ns"], {"total": 900000000, "load": 1000000, "eval_count": 60})
        local_inference.generate_json(self.endpoint, by_name["deepseek-r1:7b"], "rules", "x", {"type": "object"}, 3.0,
                                      512)
        asked = self.fake.plans_asked()
        self.assertEqual(asked[0]["model"], "qwen2.5:7b-instruct:local")
        self.assertEqual((asked[0]["system"], asked[0]["prompt"]), ("rules", "blue"))
        self.assertNotIn("think", asked[0])
        self.assertIs(asked[1]["think"], False)
        self.assertEqual(asked[0]["options"], {"temperature": 0, "seed": 7, "top_k": 1, "num_predict": 256,
                                               "num_ctx": 4096})
        self.assertEqual(asked[1]["options"]["num_predict"], 512)
        self.assertIs(asked[0]["stream"], False)
        self.assertEqual(asked[0]["format"], {"type": "object"})

    def test_cut_off_stamped_and_missing_answers_fail_by_kind(self):
        models, by_name = self.listed()
        model = by_name["qwen2.5:7b-instruct"]
        self.fake.plans.append("CUT")
        self.assertEqual(local_inference.generate_json(self.endpoint, model, "", "x", {}, 3.0, 256)["kind"],
                         "plan_truncated")
        self.fake.stamp = True
        self.assertEqual(local_inference.generate_json(self.endpoint, model, "", "x", {}, 3.0, 256)["kind"],
                         "egress_detected")
        self.fake.stamp = False
        self.fake.mode = "missing"
        answered = local_inference.generate_json(self.endpoint, model, "", "x", {}, 3.0, 256)
        self.assertEqual((answered["kind"], answered["value"]), ("model_not_local", 404))


if __name__ == "__main__":
    unittest.main()

# ==== stamp v1 | author=kjFriday | hmac-sha256=298f5e4822baa1ad940729de9fc5faa8933b3a63d4ba46e5c252e78e60a8794d ====
