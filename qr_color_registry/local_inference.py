# ==== Generic Company Inc. portfolio ====================================
# Project: portfolio | File: qr_color_registry/local_inference.py
# About: QR Palette local inference: a client for an Ollama server on this computer, and nothing...
# Copyright (c) 2026 kjFriday | SPDX-License-Identifier: AGPL-3.0-only
# You may change this file under the AGPL-3.0. The stamp at the end marks
# the version kjFriday wrote. Verify with the portfolio's stamp.py --check.
# ========================================================================

"""QR Palette local inference: a client for an Ollama server on this computer, and nothing else.

Local only, by construction (the rules of the ECP research spec, section 5):
  * The endpoint must be http on a loopback IP address (127.0.0.0/8 or ::1), or the exact name
    "localhost", which is sent to 127.0.0.1. Names are never looked up, so DNS cannot point it away.
  * Requests go straight to that address with http.client: no proxy (from the environment or the
    system settings), and a redirect is a failure, never followed. Answers over 1 MiB are refused.
  * A loopback daemon can still send work off the computer. So: cloud and remote models are never
    listed or used (names ending in ":cloud" or "-cloud", or carrying remote_host / remote_model);
    plans are asked of NAME:local, which a remote manifest cannot serve; /api/status must say cloud
    is disabled (OLLAMA_NO_CLOUD=1); and any answer stamped with remote_host or remote_model is
    refused as egress. Only /api/version, /api/status, /api/tags, /api/show and /api/generate are
    ever called; nothing that pulls, pushes, creates, copies or deletes models.
A tunnel or another program listening on 127.0.0.1 cannot be told apart from Ollama; ECP.md says so.

Records
  Result      {"ok": bool, "error": str, "value": any, "kind": str}   kind names the failure for ECP
  Endpoint    {"host": "127.0.0.1" | "::1" | ..., "port": int, "url": str}
  LocalModel  {"model_id": "name@digest", "name", "digest", "family", "parameter_size",
               "quantization_level", "size_bytes", "capabilities": [str], "note": str,
               "is_default": bool}
  Planned     {"text": str, "done_reason": str, "inference_ns": {"total", "load", "eval_count"}}
"""

import http.client
import ipaddress
import json
import socket
import time
import urllib.parse

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_PORT = 11434
MAX_ANSWER_BYTES = 1024 * 1024
CLOUD_SUFFIXES = (":cloud", "-cloud")

# Set from settings.json at start (these are the defaults).
LIST_TIMEOUT = 3.0
PING_TIMEOUT = 2.0
KEEP_ALIVE = "10m"
PLAN_OPTIONS = {"temperature": 0, "seed": 7, "top_k": 1, "num_predict": 256, "num_ctx": 4096}
RETRY_ANSWER_TOKENS = 512


def ok_result(value):
    return {"ok": True, "error": "", "value": value, "kind": "ok"}


def fail(error):
    return {"ok": False, "error": error, "value": None, "kind": "inference_unavailable"}


def fail_kind(kind, error):
    return {"ok": False, "error": error, "value": None, "kind": kind}


def parse_endpoint(url):
    """An inference URL -> Result Endpoint, or a failure when it is not plain http on loopback."""
    if not isinstance(url, str) or url.strip() == "":
        return fail("no inference address")
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return fail("not a valid inference address: " + url)
    if parts.scheme.lower() != "http":
        return fail("local inference is plain http on this computer, not " + (parts.scheme or "no scheme"))
    if parts.username is not None or parts.password is not None:
        return fail("an inference address may not carry a user name or password")
    if parts.query != "" or parts.fragment != "" or parts.path not in ("", "/"):
        return fail("an inference address is only http://host:port")
    host = parts.hostname or ""
    if port is None:
        port = DEFAULT_PORT
    if host == "localhost":
        host = "127.0.0.1"
    if "%" in host:
        return fail("an inference address may not name a network zone")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return fail("local inference must be on a loopback address (127.0.0.1, ::1 or localhost); "
                    "names are not looked up: " + host)
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_loopback:
        return fail("local inference only: " + str(address) + " is not this computer")
    host = str(address)
    shown = host
    if address.version == 6:
        shown = "[" + host + "]"
    return ok_result({"host": host, "port": port, "url": "http://" + shown + ":" + str(port)})


def request(endpoint, method, path, body, timeout):
    """One JSON request to the endpoint -> Result parsed JSON answer. Redirects are failures; the
    Host header is the literal address. Not connecting in time is "inference_unavailable" (Windows
    retries a closed loopback port for about two seconds before refusing); connecting and then not
    being answered in time is "inference_timeout"."""
    connection = None
    try:
        connection = http.client.HTTPConnection(endpoint["host"], endpoint["port"], timeout=timeout)
        try:
            connection.connect()
        except socket.timeout:
            return fail("cannot reach local inference at " + endpoint["url"] + ": nothing answered")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        status = response.status
        answer = response.read(MAX_ANSWER_BYTES + 1)
    except socket.timeout:
        return fail_kind("inference_timeout", "local inference at " + endpoint["url"] + " did not answer in time")
    except (OSError, http.client.HTTPException) as error:
        return fail("cannot reach local inference at " + endpoint["url"] + ": " + (str(error) or type(error).__name__))
    finally:
        if connection is not None:
            connection.close()
    if 300 <= status < 400:
        return fail("the inference server answered with a redirect, which is refused (local only)")
    if len(answer) > MAX_ANSWER_BYTES:
        return fail("the inference server's answer is too big")
    try:
        parsed = json.loads(answer.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return fail("the inference server did not answer with JSON (HTTP " + str(status) + ")")
    if status >= 400:
        message = ""
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
            message = parsed["error"]
        kind = "inference_unavailable"
        if status == 404:
            kind = "model_not_local"
        return {"ok": False, "error": "HTTP " + str(status) + ": " + (message or "error"), "value": status,
                "kind": kind}
    return ok_result(parsed)


def reachable(endpoint):
    if endpoint is None:
        return False
    return request(endpoint, "GET", "/api/version", None, PING_TIMEOUT)["ok"]


def version(endpoint):
    """The daemon's version -> Result str (recorded in the audit log)."""
    answered = request(endpoint, "GET", "/api/version", None, PING_TIMEOUT)
    if not answered["ok"]:
        return answered
    if not isinstance(answered["value"], dict) or not isinstance(answered["value"].get("version"), str):
        return fail("the inference server did not say its version")
    return ok_result(answered["value"]["version"])


def cloud_disabled(endpoint):
    """Whether the daemon's cloud features are off (/api/status) -> Result bool. A daemon that
    cannot say counts as not disabled."""
    answered = request(endpoint, "GET", "/api/status", None, PING_TIMEOUT)
    if not answered["ok"]:
        if answered["kind"] == "model_not_local":
            return ok_result(False)  # no /api/status: an older daemon cannot promise it
        return answered
    cloud = None
    if isinstance(answered["value"], dict):
        cloud = answered["value"].get("cloud")
    if not isinstance(cloud, dict):
        return ok_result(False)
    return ok_result(cloud.get("disabled") is True)


def is_cloud_name(name):
    """True for names that route off the computer: a last ":"-part of "cloud" or "local" (which
    ECP adds itself), or a tag ending in "-cloud"."""
    lowered = name.lower()
    for suffix in CLOUD_SUFFIXES:
        if lowered.endswith(suffix):
            return True
    parts = lowered.split(":")
    return len(parts) > 1 and parts[len(parts) - 1] in ("cloud", "local")


def is_remote(row):
    """True for a model that a signed-in Ollama would run on someone else's computer."""
    for key in ("remote_host", "remote_model"):
        value = row.get(key)
        if isinstance(value, str) and value != "":
            return True
    name = row.get("name")
    return isinstance(name, str) and is_cloud_name(name)


def text_of(value):
    if isinstance(value, str):
        return value
    return ""


def local_model(row, capabilities, default_name):
    details = row.get("details")
    if not isinstance(details, dict):
        details = {}
    name = row["name"]
    digest = text_of(row.get("digest"))
    notes = []
    lowered = name.lower()
    if ":base" in lowered or "-base" in lowered:
        notes.append("base model: may not follow instructions")
    if "thinking" in capabilities:
        notes.append("thinking model: slower")
    if len(capabilities) == 0:
        notes.append("capabilities not reported")
    size = row.get("size")
    if isinstance(size, bool) or not isinstance(size, int):
        size = 0
    return {"model_id": name + "@" + digest, "name": name, "digest": digest,
            "family": text_of(details.get("family")), "parameter_size": text_of(details.get("parameter_size")),
            "quantization_level": text_of(details.get("quantization_level")), "size_bytes": size,
            "capabilities": capabilities, "note": "; ".join(notes), "is_default": name == default_name}


def capabilities_of(endpoint, row, timeout):
    """The model's capabilities: from /api/tags when the server lists them, else /api/show."""
    listed = row.get("capabilities")
    if isinstance(listed, list):
        return listed
    shown = request(endpoint, "POST", "/api/show", {"model": row["name"]}, timeout)
    if shown["ok"] and isinstance(shown["value"], dict) and isinstance(shown["value"].get("capabilities"), list):
        return shown["value"]["capabilities"]
    return []


def list_models(endpoint, timeout, default_name):
    """The models this computer can run -> Result [LocalModel], by name. Cloud, remote and
    embedding-only models are left out."""
    tags = request(endpoint, "GET", "/api/tags", None, timeout)
    if not tags["ok"]:
        return tags
    rows = []
    if isinstance(tags["value"], dict) and isinstance(tags["value"].get("models"), list):
        rows = tags["value"]["models"]
    models = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or row["name"] == "":
            continue
        if is_remote(row):
            continue
        capabilities = []
        for capability in capabilities_of(endpoint, row, timeout):
            if isinstance(capability, str):
                capabilities.append(capability)
        if len(capabilities) > 0 and "completion" not in capabilities:
            continue
        models.append(local_model(row, capabilities, default_name))
    models.sort(key=model_name)
    return ok_result(models)


def model_name(model):
    return model["name"]


def show(endpoint, name, timeout):
    """/api/show for one model -> Result {"capabilities": [str], "remote": bool, "thinking": bool}."""
    shown = request(endpoint, "POST", "/api/show", {"model": name}, timeout)
    if not shown["ok"]:
        return shown
    value = shown["value"]
    if not isinstance(value, dict):
        return fail("the inference server's answer about " + name + " is not an object")
    capabilities = []
    if isinstance(value.get("capabilities"), list):
        for capability in value["capabilities"]:
            if isinstance(capability, str):
                capabilities.append(capability)
    return ok_result({"capabilities": capabilities, "remote": is_remote({"remote_host": value.get("remote_host"),
                                                                          "remote_model": value.get("remote_model")}),
                      "thinking": "thinking" in capabilities})


def stamped_remote(answer):
    """True when an answer says it came from another host (the daemon stamps proxied answers)."""
    return isinstance(answer, dict) and is_remote({"remote_host": answer.get("remote_host"),
                                                   "remote_model": answer.get("remote_model")})


def warm(endpoint, name, timeout):
    """Load the model so the first question is quick -> Result {"loaded": bool, "load_duration_ns": int}.
    It is loaded with the planning context size, or the first plan would load it again. A daemon that
    does not say how long loading took is timed from here."""
    started = time.monotonic()
    answered = request(endpoint, "POST", "/api/generate", {"model": name + ":local", "keep_alive": KEEP_ALIVE,
                                                           "options": {"num_ctx": PLAN_OPTIONS["num_ctx"]}}, timeout)
    if not answered["ok"]:
        return answered
    answer = answered["value"]
    if stamped_remote(answer):
        return fail_kind("egress_detected", "the daemon answered for " + name + " from another host")
    loaded = isinstance(answer, dict) and answer.get("done_reason") == "load"
    duration = int((time.monotonic() - started) * 1000000000)
    reported = None
    if isinstance(answer, dict):
        reported = answer.get("load_duration")
    if isinstance(reported, int) and not isinstance(reported, bool) and reported > 0:
        duration = reported
    return ok_result({"loaded": loaded, "load_duration_ns": duration})


def generate_json(endpoint, model, system, prompt, schema, timeout, answer_tokens):
    """Ask a local model for one JSON object following `schema`, via /api/generate on NAME:local
    -> Result Planned. Deterministic settings; "think" is turned off only for models that think.
    A cut-off answer is a failure of kind "plan_truncated"; a stamped one is "egress_detected"."""
    options = {}
    for key in PLAN_OPTIONS:
        options[key] = PLAN_OPTIONS[key]
    options["num_predict"] = answer_tokens
    body = {"model": model["name"] + ":local", "system": system, "prompt": prompt, "format": schema,
            "stream": False, "options": options, "keep_alive": KEEP_ALIVE}
    if "thinking" in model["capabilities"]:
        body["think"] = False
    answered = request(endpoint, "POST", "/api/generate", body, timeout)
    if not answered["ok"]:
        return answered
    answer = answered["value"]
    if not isinstance(answer, dict):
        return fail_kind("plan_unparseable", "the model's answer is not an object")
    if stamped_remote(answer):
        return fail_kind("egress_detected", "the answer came from another host")
    reason = answer.get("done_reason")
    if reason == "length":
        return fail_kind("plan_truncated", "the model's answer was cut off")
    if reason != "stop" or not isinstance(answer.get("response"), str):
        return fail_kind("plan_unparseable", "the model did not finish an answer (" + str(reason) + ")")
    spent = {"total": 0, "load": 0, "eval_count": 0}
    for key, source in (("total", "total_duration"), ("load", "load_duration"), ("eval_count", "eval_count")):
        if isinstance(answer.get(source), int) and not isinstance(answer.get(source), bool):
            spent[key] = answer[source]
    return ok_result({"text": answer["response"], "done_reason": reason, "inference_ns": spent})

# ==== stamp v1 | author=kjFriday | hmac-sha256=df2f46fbb384003bbb7136dad2c3962d792810c8bff1f2a51065ae5f01239bdd ====
