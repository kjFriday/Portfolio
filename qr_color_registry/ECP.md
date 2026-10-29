# The Environment Context Protocol (ECP) 1.0

**Asking a local environment in plain English, through a local model the client picks, served as an MCP server**

Generic Company Inc. portfolio · QR Palette 0.1.0 · 29 October 2026 · AGPL-3.0

## Abstract

The Environment Context Protocol (ECP) lets a client ask an *environment* questions in plain English. Here the
environment is QR Palette's registry of colored QR codes. ECP is served as an MCP server with three tools:
`ecp_list_models`, `ecp_select_model` and `ecp_query`.

Tool protocols usually let the client's own model decide everything, and that model may run anywhere. ECP adds
one rule and one narrow job:
- The client must **pick a local model**, one that runs on the same computer as the environment. Its id
  (`name@digest`) travels with every query.
- The environment uses that model only to turn a question into a typed **query plan**, constrained by a fixed
  JSON schema.
- It then **grounds** the plan against the question's own words, runs it on a hardened **read-only rail**, labels
  the answer as untrusted data, and writes every call to a **hash-chained audit log**.

So the model never writes a query, never sees stored data, and never causes a file to be opened. Inference is
restricted to loopback addresses. Cloud and remote models are refused, and so, by default, is a local server
whose cloud features are switched on.

This paper specifies ECP as QR Palette implements it. It follows the ECP dual-rail runtime research spec
(`research/ecp_dual_rail_runtime_spec.md` in this repository, "the spec" below); §16 lists where QR Palette
differs and why. The paper also reports a measurement with two local models and describes the conformance tests.

## 1. Motivation

QR Palette makes QR codes in recommended colors and keeps a relational registry of them: for every picture file,
the link it encodes, its color and its path. The questions people ask of such a registry are simple but varied:

- "Which code points to the menu?"
- "Blue codes for the shop."
- "Where is the green one?"
- "Suggest a color for a new code."

Every answer must give back the color, the link and the path of the picture.

A plain MCP server would let any capable client model call lookup tools. That works, but it leaves three things
open that matter for a personal registry:
1. **Which model reads the question.** It is whatever the client runs, which is often a remote service.
2. **What the model is trusted to produce.** Free-form tool arguments, or free-form text built from results.
3. **Whether the answer can be checked later.** The same question can produce different calls, and nothing
   records how it was read.

ECP closes these by giving a local model a smaller role. The client names a local model. The environment asks that
model for a plan in a fixed shape, checks the plan against the question, and produces the answer itself. Every
call leaves a line in the audit log.

### 1.1 Design goals

| | Goal | How ECP meets it |
|---|---|---|
| G1 | Local inference only | The inference address must be a loopback IP literal or `localhost`. Names are never resolved; proxies and redirects are refused. Cloud and remote models are refused, plans are asked of `NAME:local`, the server must report its cloud features off, the model's digest is pinned, and an answer stamped by another host is refused (§9). |
| G2 | The model is chosen first | `ecp_query` needs a `model_id` from `ecp_list_models` or `ecp_select_model`, or the default model in `settings.json`. Nothing is remembered between calls (§6). |
| G3 | The model plans; the environment answers | The model's only output is a QueryPlan. The environment runs it as fixed filters over rows read on the rail, and writes the summary from a template (§8). |
| G4 | Grounded plans | Every literal in a plan (a color code, link text, path text) must appear in the question, and a family must be named in it. Everything else is dropped and reported (§8.2). |
| G5 | Read-only and hardened | The rail opens the registry read-only, behind an allow-list authorizer, limits and a time budget. No file is opened for a client, and network paths are never probed (§10, §13). |
| G6 | MCP-native and accountable | Three MCP tools in both MCP eras, failures as named kinds, every call in the audit log (§5, §11, §12). |

### 1.2 What changed since the first draft

The first draft of ECP 1.0, written earlier on 29 October 2026, was a JSON-RPC protocol of its own: eight methods
(`ecp.hello`, `model.select`, `env.ask`, …), a session state machine, error codes -32001 to -32009, and a
separate bridge for MCP clients. The research spec showed why that shape does not hold:
- MCP clients send `tools/call`; a custom top-level method is never offered to their model.
- MCP tells new implementations not to use -32000 to -32019; a failure inside a tool belongs in an `isError`
  result.
- MCP 2026-07-28 removed connection sessions, so a model selection cannot live in the connection.

ECP is therefore now a profile of MCP: the methods became three tools, the session became a `model_id` passed on
each call, the error codes became named kinds, and the bridge became the server.

## 2. Terminology

- **Client:** an MCP client (Claude Code, Claude Desktop or another) that starts `qr_palette.py --mcp`.
- **Environment:** the program that holds the data and answers: QR Palette.
- **Registry:** the environment's SQLite database of QR codes (§10).
- **Local model:** a model served by Ollama on the same computer. Its **model_id** is `name@digest`.
- **Plan:** a QueryPlan (§7.4), made by a **planner**: `direct` (no model) or `model`.
- **Grounding:** checking a model's plan against the question's own words.
- **Record:** one QR code in an answer: its color, link and path.
- **Kind:** the name of a failure (§11).
- **Rail:** the read-only database connection a call reads through (§10).

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174.

## 3. Architecture

```
  MCP client ── stdio, one JSON-RPC message per line ──▶ ┌───────────────────────────────┐
  (Claude Code, Claude Desktop, …)                       │ qr_palette.py --mcp           │
                                                         │ MCP server · rate limit       │──▶ audit.jsonl
                                                         │ planner · grounding · answers │    (hash chain)
                                                         └──────┬─────────────────┬──────┘
                                   read-only rail (authorizer)  │                 │  HTTP, loopback only
                                                                ▼                 ▼
                                                     registry (SQLite)    local model (Ollama)
```

One `ecp_query`, end to end:
1. The envelope is parsed, the era's rules are applied (§5), and the rate limit is taken.
2. The arguments are checked against the tool's input schema.
3. The model is resolved on a fresh `/api/tags`: local, not cloud, and the digest it was pinned with.
4. The question is planned: directly when it needs no model, otherwise by the model, after `/api/status` says the
   server's cloud features are off.
5. A model plan is checked for shape and grounded.
6. One short visit on the rail reads what the answer needs; the plan runs over it.
7. The answer's strings are cleaned and capped, and the labels are added.
8. The call is appended to the audit log, and its `audit_id` goes into the answer.

The window's *Ask* box uses the same engine in-process, so it is planned, grounded and audited the same way (its
calls appear in the audit log as `window_ask` and friends). The window's own Find tab needs no model.

## 4. Transport and framing

The MCP stdio transport:

1. **Messages.** JSON-RPC 2.0, UTF-8, one per line. A line MUST NOT exceed 1 MiB (`protocol.max_message_bytes`).
   A longer line is skipped to its end and answered with -32600 and `id: null`.
2. **Server output.** Each response is compact ASCII JSON (non-ASCII characters escaped, so no raw line
   separators appear), followed by one line feed and a flush. Standard output carries protocol messages only;
   logs go to standard error.
3. **Envelope rules.**
   - A line that is not UTF-8 or not JSON gets -32700 with `id: null`.
   - `jsonrpc` MUST be `"2.0"`. An `id` MUST be a string or an integer, never null or a boolean (-32600).
   - `params`, when present, MUST be an object (-32602).
   - Notifications (no `id`) are never answered.
   - A batch (a JSON array) is answered as JSON-RPC 2.0 says: an empty array gets one -32600, and a batch of only
     notifications gets no output.
4. **Ending.** End of input, or a broken output pipe, ends the server cleanly. An unexpected failure is -32603;
   its details go to standard error only.

## 5. The two MCP eras

ECP serves both eras of MCP, so that clients of either kind can use it:

- **Legacy (2025-11-25).**
  - The client sends `initialize`. Whatever version it asks for, the answer is `2025-11-25`, with
    `capabilities: {"tools": {}}`, `serverInfo` and `instructions`.
  - Requests other than `ping` wait for `notifications/initialized` (-32600 before it). A second `initialize`
    gets -32600. `ping` answers `{}`.
  - Results carry no `resultType`, `ttlMs` or `cacheScope`.
- **Modern (2026-07-28).**
  - Every request names its version in `_meta["io.modelcontextprotocol/protocolVersion"]`, together with
    `io.modelcontextprotocol/clientCapabilities` (required) and `io.modelcontextprotocol/clientInfo`
    (optional). A missing required field gets -32602.
  - An unsupported version gets -32022 with `data: {"supported": ["2026-07-28", "2025-11-25"], "requested"}`.
  - `server/discover` returns `supportedVersions: ["2026-07-28"]`, the capabilities, the instructions,
    `ttlMs: 0` and `cacheScope: "private"`.
  - Every result carries `resultType: "complete"` and `_meta["io.modelcontextprotocol/serverInfo"]`.
    `tools/list` adds `ttlMs: 3600000` and `cacheScope: "public"`, because the tool list never changes.
  - `ping` was removed in this revision: -32601.
- **Choosing.** A request with modern `_meta` is served statelessly. `initialize` selects the legacy era for the
  rest of the process, even after a `server/discover` probe. A request with neither gets -32602, whose message
  names both ways to start.
- **Everything else.** Undeclared methods (`prompts/list`, `resources/list`, …) get -32601.
  `notifications/cancelled` is accepted; requests run one at a time, so it has nothing to stop.

## 6. The three tools

| Tool | Arguments | Result | Annotations |
|---|---|---|---|
| `ecp_list_models` | none | `{models: [LocalModel], cloud_disabled}` | read-only |
| `ecp_select_model` | `name` (1-128 characters) | Selected (§7.2) | not read-only: it loads the model into the server's memory |
| `ecp_query` | `prompt` (1-2000 characters), `model_id` (up to 200, optional) | QueryResult (§7.3) | read-only |

All three are non-destructive, idempotent and closed-world, have closed input schemas
(`additionalProperties: false`) and declare an `outputSchema`. The list is static and always in this order.

**Choosing a model without sessions.** A `model_id` is `name@digest`, where the digest is the one `/api/tags`
reports.
- `ecp_select_model` checks that the model is local (a fresh `/api/tags`, then `/api/show`), pins its digest into
  a `model_id`, and loads it with the planning context size, so the first question is quick. It stores nothing.
- `ecp_query` takes that `model_id`, a bare model name (which takes the model as it is now), or nothing, in which
  case the default model applies (`inference.model` in `settings.json`, or `--model`). With no model at all it
  fails with `args_invalid`, which names `ecp_list_models` as the next step.
- Before every plan, the digest is compared with a fresh `/api/tags`. A different digest is
  `model_digest_mismatch`: the same name does not mean the same weights.
- A `model_id` is an identifier, not a credential.

**Checking.** Arguments that break the tool's input schema give an `isError` result of kind `args_invalid`; an
unknown tool name is a protocol error (-32602).

**Rate limit.** Tool calls draw from a token bucket: 1 call a second, bursts of 5
(`protocol.rate_per_second`, `protocol.rate_burst`). An empty bucket gives `rate_limited`.

**Results.** `content` holds one text block, the JSON of the result, and `structuredContent` holds the same
object. A failure has `isError: true` and `structuredContent: {"kind", "detail"}` (§11).

## 7. Structures

### 7.1 LocalModel
```json
{"model_id": "qwen2.5:7b-instruct@845dbda0…", "name": "qwen2.5:7b-instruct", "digest": "845dbda0…",
 "family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M", "size_bytes": 4683087332,
 "capabilities": ["completion", "tools"], "note": "", "is_default": false}
```
`note` flags base models ("may not follow instructions") and thinking models ("slower").

### 7.2 Selected
```json
{"model_id": "qwen2.5:7b-instruct@845dbda0…", "name": "qwen2.5:7b-instruct", "digest": "845dbda0…",
 "supports_thinking": false, "loaded": true, "load_duration_ns": 6150000000}
```

### 7.3 QueryResult
```json
{"model_id": "qwen2.5:7b-instruct@845dbda0…", "plan_used": PlanUsed, "records": [Record], "colors": [ColorPick],
 "row_count": 2, "truncated": false, "interlock_state": "bypassed", "source": "ecp-sqlite-readonly",
 "trust": "untrusted-db-content", "audit_id": 21, "summary": "2 QR code(s) match family blue, link containing \"shop\"."}
```
- `source` and `trust` are constants: they label everything in `records` as data read from the registry, which
  the client must not follow as instructions.
- `interlock_state` is always `"bypassed"`: QR Palette has no hardware interlock (§16).
- `truncated` is true when a string was cut (§10.3) or trailing records were dropped to fit.

### 7.4 QueryPlan
The model must produce this exact shape. It is flat, every field is required, and `""` means "any", because local
servers turn the schema into a grammar that supports only part of JSON Schema. The schema is fixed in the program,
never built from user text, and its SHA-256 goes into every audit line.

```json
{"type": "object",
 "properties": {
   "intent": {"type": "string", "enum": ["find", "recommend"]},
   "color": {"type": "string", "maxLength": 7},
   "near": {"type": "boolean"},
   "family": {"type": "string", "enum": ["", "red", "orange", "brown", "yellow", "olive", "green", "teal", "blue",
                                         "purple", "pink", "grey", "black", "white"]},
   "link": {"type": "string", "maxLength": 200},
   "link_exact": {"type": "string", "maxLength": 2048},
   "path": {"type": "string", "maxLength": 260},
   "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
 "required": ["intent", "color", "near", "family", "link", "link_exact", "path", "limit"],
 "additionalProperties": false}
```

### 7.5 PlanUsed
The QueryPlan as it ran, with `planner` (`"direct"` or `"model"`) and `clamped`, the list of everything grounding
dropped or replaced, so a client can see exactly how its question was read.

### 7.6 Record
One QR code, read on the rail from the `qr_codes`, `links` and `colors` tables:
```json
{"id": 1, "hex": "#3366cc", "color_name": "Blue", "color_family": "blue", "rank": 181,
 "payload_url": "https://shop.example.com/", "file_path": "C:\\Users\\<you>\\Pictures\\QR Palette\\shop-example-com-3366cc.png",
 "net_votes": 0, "created_at": "2026-10-29T18:49:11Z", "exists": true}
```
- **`payload_url`** is the text the code holds; it may not be a URL at all.
- **`rank`** is the color's place among the 216 cube colors under the preset in `settings.json` and the registry's
  votes. It is null for colors outside the cube.
- **`exists`** is checked only for files on the computer's own drives. For network paths it is null (§13).

### 7.7 ColorPick
A recommended color, for `intent: "recommend"`:
```json
{"hex": "#009900", "name": "Green", "family": "green", "rank": 4, "uses": 0}
```

### 7.8 Failure
```json
{"kind": "model_digest_mismatch", "detail": "qwen2.5:7b-instruct is not the model that was pinned"}
```
`detail` names the field or the condition. It never repeats the model's output or stored data.

## 8. Query planning and grounding

### 8.1 Planners
1. **direct.** These questions need no model and are planned deterministically:
   - a lone color code (`#3366cc`, or bare `3366cc` with at least one digit, so "decade" is not a color);
   - a whole link (with a scheme such as `https://`, `mailto:` or `tel:`), matched exactly;
   - path-like text (a drive letter, `\\`, `/`, or a `.png`/`.svg` name), compared as text and never opened;
   - a single family word, optionally with "QR codes".

   A direct question still needs a model to be named (G2), so that every query is made the same way.
2. **model.** Everything else goes to the named model through Ollama's `/api/generate`:
   - the model name with `:local` appended, so a model that lives on another host cannot answer;
   - `system`: the planning rules (the plan's fields in words, the family list, and "never invent a link, a path
     or a color code") followed by the worked examples, all from `planner.json` (§8.6);
   - `prompt`: the question, after control and direction characters are removed;
   - `format`: the QueryPlan schema; `stream: false`;
   - `options`: `temperature 0`, `seed 7`, `top_k 1`, `num_predict 256`, `num_ctx 4096`;
   - `think: false`, sent only to models that report the "thinking" capability.

   The answer must end with `done_reason: "stop"`. An answer cut off at the token limit is asked once more with
   room for 512 tokens, then fails as `plan_truncated`. An answer that is not JSON is `plan_unparseable`; one with
   a wrong type, a missing field or an extra field is `plan_invalid`. There is no keyword fallback: a plan that
   cannot be trusted is a named failure.

### 8.2 Grounding rules
Applied to every model plan before it runs:

1. A color code in the plan is kept only if its six hex digits appear in the question. A `#rrggbb` written in
   the question always wins over the model's.
2. `link`, `link_exact` and `path` are kept only if their text appears in the question (case-insensitively).
   Filler words at their ends ("the", "page", "folder", …) are removed, so "careers page" searches for "careers".
3. `family` is kept only if the question names it or one of its synonyms ("navy" is blue, "gray" is grey).
   `intent` must be `find` or `recommend`.
4. `near` only counts with a color. `limit` is clamped to 1-100.
5. Everything dropped or replaced is listed in `plan_used.clamped`.

A grounded plan can only narrow or widen the question's own words; it cannot add facts. Because the model never
receives stored data (§13), what it proposes cannot be shaped by what the registry holds.

### 8.3 Execution
- **Find.** A plan's filters combine with AND.
  - Link and path text match case-insensitively as typed, or when each of its words appears, ignoring
    punctuation. So "store hours" finds `…/store-hours`, and "shop sale" finds `https://shop.example.com/sale`.
    Matching runs in Python over the rows read on the rail, never with SQL `LIKE` wildcards.
  - Colors match exactly, or with `near` within OKLab distance 0.08; a family matches its colors.
  - A plan holds one family, so "red or blue" is read as red.
  - Results are newest first. The limit is 20 by default and 100 at most (`queries.default_limit`,
    `queries.max_limit`).
- **Recommend.** The usable colors (§8.4) come from the preset named in `settings.json`, best first, optionally
  of one family. Presets and their weights are JSON files too: a preset names the algos, and each algo's weights
  file holds its numbers.
- **Summary.** It is written from a template, never by the model.

### 8.4 Usable colors
QR codes are drawn in their color on white. ECP recommends, and the environment draws, only colors with a WCAG 2.x
contrast ratio of at least 3:1 against white, compared exactly: 118 of the 216 cube colors (`#0099ff`, at 2.9998,
is out). The conformance suite decodes a code in every one of the 118.

### 8.5 Measurement
On one desktop computer with Ollama 0.40.10 and the six mock codes of §15, both models starting unloaded:

| Model | `ecp_select_model` (loads it) | Planned questions | Plans changed by grounding |
|---|---|---|---|
| qwen2.5:7b-instruct | 6.3 s | six questions, 0.7-1.1 s each | none |
| deepseek-r1:7b (thinking; sent `think: false`) | 12.4 s | one question, 1.1 s | none |

All seven plans were right, including "suggest three colors" (a `recommend` plan with `limit: 3`) and "codes
close to #3366cc" (`near: true`). Three earlier observations shaped the design:
- When the warm-up did not send the planning context size, the first question paid for a second load (9.3 s).
  The warm-up now sends `num_ctx`.
- Without the worked examples, qwen2.5 invented `#0000ff` for "blue" and `#006400` for "dark green".
- Without a token cap, deepseek-r1 took 65-157 s a question and invented links and colors.

That is why grounding is part of the protocol rather than a property of a good model.

### 8.6 Configuration
Everything an operator may tune is plain, indented JSON with an `about` text in each part. The server reads these
files when it starts and never writes them.

| File | What it holds |
|---|---|
| `settings.json` | The inference address, default model, timeouts, token limits and the cloud check; the preset; contrast and "near"; result limits, question length, the rail's time budget; message size, rate limit and output caps; where the registry, pictures, rankings, planner and audit log are |
| `planner.json` | The planning rules, the worked examples, color-family words, and the filler words grounding trims |
| `presets/*.json`, `weights/*.json` | How the colors are ranked |

A value that is missing or of the wrong kind falls back to its default, and the fall-back is reported on standard
error. A file that is not valid JSON is never overwritten.

`inference.require_cloud_disabled` is the one safety check that can be turned off, because the person running the
server may decide their Ollama's cloud features are acceptable; it is on by default. These cannot be configured,
because they are the protocol: loopback-only inference, the model refusals of §9, the read-only rail, grounding,
the plan schema and the tool surface.

## 9. Local-inference policy

- **Address.**
  - The endpoint MUST be `http`, with no user information, query, fragment or path.
  - Its host MUST be an IP literal in 127.0.0.0/8 or `::1` (an IPv4-mapped address is unwrapped first), or
    exactly `localhost`, which is sent to 127.0.0.1.
  - Host names are never resolved, so DNS cannot send inference elsewhere.
- **Connection.**
  - Requests use a direct connection: no proxy from the environment or the system.
  - Any 3xx answer is a failure and is never followed. Answers larger than 1 MiB are refused.
  - Not connecting in time is `inference_unavailable`; connecting and then not being answered in time is
    `inference_timeout` (45 s for plans by default, `inference.timeout_seconds`).
- **Endpoints.** Only `/api/version` (for the audit log), `/api/status`, `/api/tags`, `/api/show` and
  `/api/generate` are called. Nothing pulls, pushes, creates, copies or deletes models, and nothing searches the
  web.
- **A loopback server can still reach the internet.** A signed-in Ollama runs models whose names end in `:cloud`
  or `-cloud`, or whose manifests carry `remote_host`/`remote_model`, on another computer, from the same port. So:
  1. Such models are never listed or accepted, and neither is any name whose last `:` part is `cloud` or `local`.
  2. Embedding-only models are left out: a planner needs "completion".
  3. `ecp_select_model` also asks `/api/show` and refuses a model the server says is remote.
  4. Plans are asked of `NAME:local`, which a remote manifest cannot serve.
  5. Before every plan, `/api/status` MUST report `cloud.disabled: true` (set `OLLAMA_NO_CLOUD=1` for the Ollama
     server), or the query fails with `cloud_not_disabled`. A server too old to say counts as not disabled.
  6. Any answer stamped with `remote_host` or `remote_model` is refused as `egress_detected`.
- **Limits of the policy.** A process listening on a loopback port cannot be told apart from Ollama, and a port
  forward or tunnel on 127.0.0.1 could relay requests elsewhere. ECP cannot detect that. Ollama's own other
  routes (web search, for one) are outside ECP's reach; operators who need that assurance should control what
  listens on the port and what the server may connect to.

## 10. The read-only rail

### 10.1 Opening
Every call opens its own connection, reads everything its answer needs in one short visit, and closes it before
any file is checked. In order:
1. Open the registry through a `file:` URI with `mode=ro`, so the file cannot be created or written. A missing
   file is `db_unavailable` ("no registry yet"), and nothing is created.
2. Check the header marks: `application_id` 0x51525041 and `user_version` 1. Any other file is refused.
3. `PRAGMA query_only=ON` and `PRAGMA trusted_schema=OFF`.
4. Where Python's `sqlite3` can set them (3.12 and later): `DEFENSIVE` on; trusted schema, triggers, views and
   double-quoted string literals off.
5. `PRAGMA quick_check` MUST return `ok`; a damaged registry is not served.
6. `PRAGMA hard_heap_limit` of 64 MiB.
7. Where Python can set them (3.11 and later), SQLite's limits: `LENGTH` 1,000,000, `SQL_LENGTH` 10,000, `COLUMN`
   100, `EXPR_DEPTH` 10, `COMPOUND_SELECT` 3, `VDBE_OP` 25,000, `FUNCTION_ARG` 8, `ATTACHED` 0,
   `LIKE_PATTERN_LENGTH` 50, `VARIABLE_NUMBER` 10, `TRIGGER_DEPTH` 10.
8. An allow-list authorizer: plain `SELECT`, reading the listed columns of `colors`, `links`, `qr_codes` and
   `votes`, and the function `count`. Everything else is denied (an error, never a silent null): other columns,
   other functions, `sqlite_master`, `PRAGMA`, `ATTACH`, writes and schema changes.
9. A progress handler that stops the visit once 2 s have passed (`queries.statement_seconds`): `db_timeout`.

The registry keeps SQLite's rollback journal, not WAL, so a read-only reader never needs to create files beside
it. The window is the only writer.

### 10.2 What is read
The rail reads a fixed set of statements: the registry's rows (a join of `qr_codes`, `links` and `colors`), the
counts, the votes and the colors in use. The plan is applied to those rows in Python. No SQL is built from a plan,
from a question or from the model.

### 10.3 What leaves
Every string read from the registry leaves without control characters (tab and newline included), zero-width
characters or direction controls, normalized to NFC, and cut to 256 characters (`protocol.max_field_characters`).
A whole result is kept under 40,000 characters (`protocol.max_result_characters`) by dropping records from the end.
Either sets `truncated`. Strings are plain values in `structuredContent`, never Markdown, and the text block holds
only the JSON.

## 11. Failures

Protocol errors are JSON-RPC errors, and only the standard ones:

| Code | When |
|---|---|
| -32700 | a line that is not UTF-8 or not JSON |
| -32600 | not JSON-RPC 2.0, a bad `id`, an empty batch, a line over 1 MiB, a request before `notifications/initialized`, a second `initialize` |
| -32601 | an undeclared method; `ping` in the modern era |
| -32602 | `params` not an object; missing modern `_meta` fields; neither era started; an unknown tool; `arguments` not an object |
| -32603 | an unexpected failure (details on standard error only) |
| -32022 | an unsupported MCP version, with `{supported, requested}` |

Everything that goes wrong inside a tool is a result with `isError: true` and one of these kinds:

| Kind | When |
|---|---|
| `args_invalid` | arguments break the input schema; no model named and no default |
| `rate_limited` | the token bucket is empty |
| `prompt_invalid` | nothing is left of the question after cleaning |
| `inference_unavailable` | the server cannot be reached, answers with an error, or the address breaks §9 |
| `inference_timeout` | the server did not answer in time |
| `cloud_not_disabled` | `/api/status` does not report the cloud features off |
| `model_not_local` | an unknown, cloud, remote or embedding model; the server no longer has it |
| `model_digest_mismatch` | the model's digest changed since it was pinned |
| `egress_detected` | an answer was stamped by another host |
| `plan_unparseable` | the model's answer is not JSON, or did not finish |
| `plan_invalid` | the plan has a wrong type, a missing field or an extra field |
| `plan_truncated` | the plan was cut off twice |
| `db_unavailable` | no registry, another file, a damaged registry, or a read error |
| `db_timeout` | the rail's time budget ran out |
| `db_denied` | the authorizer refused a statement |
| `interlock_fault`, `interlock_disabled` | defined by the spec for its hardware interlock; QR Palette never returns them |

## 12. Audit log

Every tool call, and every call from the window's *Ask* box, appends one JSON line to `audit.jsonl` in the
program's data folder (`audit.file` in `settings.json` moves it).
- **Fields:** `audit_id` (1, 2, 3, …), `ts` (UTC), `request_id`, `tool`, `client_info` (as the client describes
  itself, so untrusted), `result_kind`, `elapsed_ms`, `interlock_state`, `ollama_version`, and the `detail` of a
  failure. For queries also `prompt_sha256`, `model_id`, `schema_sha256`, `system_prompt_sha256`, `plan_used`,
  `clamped`, `plan_rejected_reason`, `inference_ns` (total, load, tokens), `progress_fired`, `row_count`,
  `bytes_returned` and `truncated`.
- **Never in it:** the prompt itself (only its SHA-256) or anything stored in the registry.
- **The chain:** each line holds `prev_sha256`, the SHA-256 of the line before (64 zeros for the first). Changing
  or deleting a line breaks the chain at the next line, and `audit.verify()` names it.
- **Sharing:** writers take a lock file while appending, so the window and a server can share one log. A lock
  left behind for more than 30 s is cleared.
- **Only the id leaves:** nothing in the log is sent to a client except `audit_id`. A log that cannot be written
  is reported on standard error, and the answer is not held back.
- **Limits:** cutting lines off the end leaves a valid chain, and anyone who can write the file can rewrite the
  whole chain. The log shows how questions were read and answered; it is evidence, not proof.

## 13. Security and privacy

### 13.1 Threat model
Inputs the environment does not trust:
- client questions and arguments, and the client's description of itself;
- the model's output;
- QR payloads stored in the registry, which may come from pictures registered from anywhere;
- anything reachable over the network.

The client process is trusted as much as the user who started it. Over stdio, it is that user.

### 13.2 What protects what
- **No query language from the model.** Plans are data with a fixed shape, checked and grounded, then applied as
  fixed filters. SQL injection from model output is ruled out by construction: no SQL is built from it.
- **The read-only rail** (§10). The conformance suite checks that the registry file's SHA-256 is unchanged after
  a full MCP session.
- **No file opened for a client.** Paths in questions are compared as text against the stored paths; nothing is
  decoded or read. `exists` is checked only for paths on the computer's own fixed or removable drives. Network
  paths and mapped network drives report null, so a query cannot make the computer contact a server, send its
  Windows sign-in to one, or hang on one. Decoding pictures is something only the window does, for a file the
  user chose.
- **Prompt isolation.** The model receives the planning rules, the worked examples and the question, nothing more.
  A QR payload cannot inject instructions into a model that never reads it. The suite stores a canary link and
  checks that no request to the model contains it.
- **Labelled, cleaned output** (§10.3, §7.3).
- **Bounded inputs.** Lines up to 1 MiB, questions up to 2,000 characters, model answers up to 1 MiB and 256 (or
  512) generated tokens, a rate limit, the rail's limits and time budget; in the window, pictures up to 20 MB and
  4096 px a side, with decompression capped before any pixel memory is taken.

### 13.3 Residual risks
Prompt injection is contained, not prevented. What remains, after the spec's list:
1. **Second-order injection.** Stored payloads are returned to the client, whose own model reads them. The labels
   help a careful client; stopping the client's model from obeying data is the client's job.
2. **Plan steering.** A question can be worded to steer the plan within the grounding rules. It shows only in
   `plan_used` and the audit log.
3. **Availability.** Bounded by the limits above, not eliminated.
4. **Disclosure.** Answers contain links and paths, and paths can contain folder and user names.
5. **The Ollama server and its models** are trusted to be what they say. A pinned digest detects a swapped model;
   it does not vouch for the model.
6. **Structured output.** A server that ignores parts of the schema degrades silently; the shape check and
   grounding are the real boundary.
7. **The schema must stay static.** A plan schema built from user text would become an attack surface.
8. **The wider MCP setup.** Other servers installed in the same client, and the client itself, are outside ECP.
9. **The registry file** is trusted as written by the window; the header marks and `quick_check` catch accidents,
   not a careful forgery.
10. **The audit log** has the limits of §12.
11. **Loopback is not authentication.** Any local process can talk to Ollama, and to this server's registry file.

### 13.4 Privacy
ECP keeps its own inference on the computer, but answers go to whoever asked. An MCP client sends what it
receives to the model it runs, which may be remote. Users choose which clients to connect.

### 13.5 Out of scope
Authentication (stdio inherits the user), multiple users, and writes: nothing in ECP writes the registry.

## 14. Conformance

The reference implementation's tests (`python -m unittest discover -p "test_*.py"`) are the conformance suite.
They run against a stand-in Ollama server on 127.0.0.1, which can also answer with errors, redirects, invalid
JSON, delays, cut-off plans, a server with its cloud features on, and answers stamped by another host.

- **`test_mcp_server.py`:** both MCP eras, the probe-then-legacy path, -32022, the tool schemas and annotations,
  `isError` results, argument checking, the rate limit, batches, null ids, and the audit line's client and
  request id.
- **`test_ecp.py`:** listing, pinning and warming models; every refusal of §9 and every kind of §11 that QR
  Palette can return; direct and model planning, the retry with more room, grounding, recommendations; the
  canary; the cleaning and caps of §10.3; the audit fields and what never enters the log; `planner.json`; and the
  framing (bad UTF-8, bad JSON, over-long lines, internal errors, one ASCII line per answer).
- **`test_local_inference.py`:** the loopback rule with no DNS involved, model filtering, capabilities from
  `/api/show`, ignored proxy settings, refused redirects, connect failures versus timeouts, `/api/status`, the
  warm-up, and the planning request's settings.
- **`test_registry.py`:** the rail: what it reads, everything it denies, its hardening, its time budget, and a
  damaged file refused.
- **`test_audit.py`:** the chain, what it shows and what it cannot, the lock, and one ASCII line per record.
- **`test_qr_palette.py`:** `--mcp` and `--ecp` run as real processes in both eras: standard output holds only
  JSON lines without carriage returns, the registry is unchanged afterwards, and the audit chain verifies. Also
  the default model and settings.
- **`test_settings.py`, `test_swatch.py`, `test_qr_codec.py`, `test_textsafe.py`:** the settings file, the color
  rules, the codec and the input guard that answers depend on.

## 15. Worked transcript

A real session against a scratch registry of six mock codes, with Ollama 0.40.10 on the same computer. The first
run used the default settings; the second used scratch settings with `require_cloud_disabled: false`, because this
computer's Ollama had its cloud features on. Results, schemas and paths are shortened, `<you>` stands for the
user's folder, and digests are cut to 8 characters. Client lines start with `→`, server lines with `←`.

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"live-demo"}}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{}},
   "serverInfo":{"name":"qr-palette-ecp","title":"QR Palette ECP","version":"0.1.0"},"instructions":"QR Palette's registry ..."}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
→ {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"ecp_query","arguments":{"prompt":"blue QR codes that link to the shop"}}}
← {"jsonrpc":"2.0","id":4,"result":{"content":[...],"structuredContent":{"kind":"args_invalid",
   "detail":"choose a local model first: ecp_list_models, then pass its model_id"},"isError":true}}
→ {"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"ecp_query","arguments":{"prompt":"blue QR codes that link to the shop","model_id":"qwen2.5:7b-instruct"}}}
← {"jsonrpc":"2.0","id":7,"result":{"content":[...],"structuredContent":{"kind":"cloud_not_disabled",
   "detail":"Ollama's cloud features are on; set OLLAMA_NO_CLOUD=1 for the Ollama server (or allow it in settings.json)"},"isError":true}}

   (second run: the modern era, with the scratch settings)
→ {"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
   "io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"live-demo","version":"1"}}}}
← {"jsonrpc":"2.0","id":1,"result":{"supportedVersions":["2026-07-28"],"capabilities":{"tools":{}},"instructions":"...",
   "ttlMs":0,"cacheScope":"private","resultType":"complete","_meta":{"io.modelcontextprotocol/serverInfo":{...}}}}
→ {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ecp_select_model","arguments":{"name":"qwen2.5:7b-instruct"},"_meta":{...}}}
← {"jsonrpc":"2.0","id":2,"result":{...,"structuredContent":{"model_id":"qwen2.5:7b-instruct@845dbda0","name":"qwen2.5:7b-instruct",
   "digest":"845dbda0","supports_thinking":false,"loaded":true,...},"isError":false,"resultType":"complete",...}}      6.3 s
→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ecp_query","arguments":{"prompt":"blue QR codes that link to the shop",
   "model_id":"qwen2.5:7b-instruct@845dbda0"},"_meta":{...}}}
← {"jsonrpc":"2.0","id":3,"result":{...,"structuredContent":{"model_id":"qwen2.5:7b-instruct@845dbda0",
   "plan_used":{"planner":"model","clamped":[],"intent":"find","color":"","near":false,"family":"blue","link":"shop",
                "link_exact":"","path":"","limit":20},
   "records":[{"id":5,"hex":"#0066cc","color_name":"Blue","color_family":"blue","rank":77,
               "payload_url":"https://shop.example.com/hours","file_path":"C:\\Users\\<you>\\...\\shop-example-com-hours-0066cc.svg",
               "net_votes":0,"created_at":"2026-10-29T18:49:12Z","exists":true},
              {"id":1,"hex":"#3366cc",...,"payload_url":"https://shop.example.com/",...}],
   "colors":[],"row_count":2,"truncated":false,"interlock_state":"bypassed","source":"ecp-sqlite-readonly",
   "trust":"untrusted-db-content","audit_id":21,"summary":"2 QR code(s) match family blue, link containing \"shop\"."},
   "isError":false,"resultType":"complete",...}}                                                                     1.05 s
→ ... "arguments":{"prompt":"suggest three colors for a new code",...}
← ... "plan_used":{"planner":"model",...,"intent":"recommend",...,"limit":3},"records":[],
      "colors":[{"hex":"#000000","name":"Black","family":"black","rank":1,"uses":0},
                {"hex":"#6600ff","name":"Purple","family":"purple","rank":3,"uses":0},
                {"hex":"#009900","name":"Green","family":"green","rank":4,"uses":0}],...                                0.74 s
→ ... "arguments":{"prompt":"which code goes to the careers page?",...}
← ... "plan_used":{...,"link":"careers",...},"records":[{"id":4,"hex":"#663399","color_name":"Dark purple",...,
      "payload_url":"https://example.com/careers",...}],...                                                          0.82 s
```

Every planned answer names the plan it ran, and the audit log holds the same plan with the prompt's hash.

## 16. Deviations from the research spec

The spec describes a Rust runtime on an edge Linux board behind a hardware interlock. QR Palette is a desktop
program, so some parts are different, and some are absent:

| The spec | QR Palette | Why |
|---|---|---|
| A static Rust (musl) binary on an edge Linux board; a UART bridge to the host | A Python 3.10+ program using only the standard library, on Windows; stdio only | The portfolio's platform; there is no separate device |
| A two-channel hardware interlock gating every call | None. `interlock_state` is always `"bypassed"` (the spec's `--interlock none` mode), and the interlock kinds never occur | No interlock hardware |
| The inference address is a compile-time constant, 127.0.0.1:11434 | Any loopback IP literal or `localhost`, from `settings.json` or `--inference` | Every setting is meant to be editable JSON; names are still never resolved |
| `ECPQueryPlan` (`target_family`, `hex_code`, `link_search`, `min_votes`, `sort_by`, `limit`) compiled into three fixed SQL templates | QR Palette's QueryPlan (§7.4), applied in Python to rows read with fixed statements | The registry's questions are by link, color, path and recommendation; in both, no SQL comes from the model |
| Seven color families | Thirteen | The palette's own names, shared with Color Voats |
| Tables `colors`, `links`, `qr_codes`, `voats`, `STRICT` | `colors`, `links`, `qr_codes`, `votes`, not `STRICT` | The registry's existing schema (`user_version` 1) |
| The DDL sets only `user_version` | The registry also sets `application_id` 0x51525041 ("QRPA"), checked on every open | It tells a QR Palette registry apart from any other SQLite file, and other programs find the registry by it. It stays in any future schema. |
| Open with read-only flags and `NOFOLLOW`, no URI | A `file:` URI with `mode=ro` | The only read-only open in Python's `sqlite3`, which has no `NOFOLLOW` |
| Also `ENABLE_ATTACH_CREATE`, `ENABLE_ATTACH_WRITE`, `ENABLE_COMMENTS`; limits `PARSER_DEPTH`, `SCHEMA`, `LIKE_PATTERN_LENGTH` 80 | Not set; `LIKE_PATTERN_LENGTH` 50 | Python's `sqlite3` does not expose them; `ATTACHED` 0 and the authorizer cover attaching, and `LIKE` is never used |
| A 2 s budget per statement | 2 s per visit | A call reads in one short visit |
| Separate connect, first-byte and total timeouts | One timeout per request: 3 s to list models, 2 s for status, 45 s for plans | `http.client` has one timeout |
| Only an exact `#RRGGBB` prompt skips inference | Also whole links, path-like text and single family words (§8.1) | They need no model; the spec leaves this open (decision (i)) |
| Records: `hex`, `color_family`, `payload_url`, `file_path`, `net_votes`, `created_at` | The same, plus `id`, `color_name`, `rank`, `exists`; results add `colors` and `summary` | The window's needs and recommendations |
| Audit fields `sql_template_id` and `param_sha256` | Not recorded | There are no SQL templates; `plan_used` records what ran |

## 17. ECP and plain MCP

| | A plain MCP tool server | ECP |
|---|---|---|
| Who reads the question | the client's model, wherever it runs | the client's model, and a local model the client picks to plan |
| What a model produces | tool arguments and final text | one QueryPlan, grounded before use |
| Who writes the answer | the client's model | the environment, from records and a template |
| Inference location | not specified | loopback only, with cloud and remote models refused |
| Model choice | none | stateless: a pinned `model_id` on every call |
| Failures | anything | named kinds |
| Record of use | none required | a hash-chained audit line per call |

ECP does not replace MCP. It is a narrower contract for one environment, written as an MCP server so that any MCP
client can use it without bypassing its rules.

## 18. A note on the name

"ECP" is also the common abbreviation of Roku's External Control Protocol, an HTTP interface for Roku devices. The
two are unrelated. In this portfolio, ECP means the Environment Context Protocol, and its tool names carry the
prefix `ecp_` so the two are not confused in logs.

## 19. Future work

- A `STRICT` registry schema (`user_version` 2), as the spec's DDL has it, keeping the `application_id` marker.
  Programs that read the registry check `user_version` too, so they have to accept the new version at the same
  time.
- Anchoring the audit chain outside the file, so that cutting off the end shows.
- Writes (making and registering codes) stay out of ECP; if they come, they come behind the window's own
  confirmation, never through MCP.
- More environments behind the same rules.

## References

1. *ECP dual rail runtime spec*, v1.0 draft, 29 October 2026. `research/ecp_dual_rail_runtime_spec.md`.
2. JSON-RPC Working Group. *JSON-RPC 2.0 Specification*, 2010. https://www.jsonrpc.org/specification
3. *Model Context Protocol Specification*, revisions 2025-11-25 and 2026-07-28.
   https://modelcontextprotocol.io/specification
4. Ollama. *API reference* (`/api/version`, `/api/status`, `/api/tags`, `/api/show`, `/api/generate`, structured
   outputs) and *FAQ* (`OLLAMA_NO_CLOUD`). https://docs.ollama.com/api
5. SQLite. *Defense Against The Dark Arts* (security guidance), the `sqlite3_db_config`, `sqlite3_limit` and
   authorizer documentation, and *PRAGMA statements*. https://sqlite.org/security.html
6. OWASP. *Top 10 for Large Language Model Applications*, LLM01 (prompt injection), 2025.
7. ISO/IEC 18004:2015. *Information technology: QR Code bar code symbology specification.*
8. W3C. *Web Content Accessibility Guidelines (WCAG) 2.2*, definitions of contrast ratio and relative luminance,
   2023.
9. B. Ottosson. *A perceptual color space for image processing* (OKLab), 2020.
   https://bottosson.github.io/posts/oklab/
10. N. Otsu. "A threshold selection method from gray-level histograms." *IEEE Transactions on Systems, Man, and
    Cybernetics* 9(1), 1979.
11. E. B. Wilson. "Probable inference, the law of succession, and statistical inference." *Journal of the
    American Statistical Association* 22(158), 1927.
12. S. Bradner. RFC 2119, 1997, and B. Leiba. RFC 8174, 2017: key words for use in RFCs.
