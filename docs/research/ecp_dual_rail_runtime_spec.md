# ECP dual rail runtime spec

Bottom line: the drafts' software shape survives with corrections (a
local model emits a schema-constrained plan, Rust compiles it into fixed
parameterized SQL, a read-only SQLite rail executes it, Claude Code sees
it as an MCP server over stdio), but their protocol framing (custom
JSON-RPC methods, sessions, UART as a peer transport, -3200x error
codes), their "zero dependency embedded MCU" claims, their DDL, their
no-egress argument and almost every hardware claim do not. The hardware
pair is respecified as an ISO 13849-1-style complementary two-channel
enable input with a discrepancy time, a latched hardware fault path and
an honest microsecond-to-millisecond software ladder; its side-channel,
host-isolation and area claims are withdrawn. "Immunity to injection"
becomes "SQL injection eliminated by construction; prompt injection
contained, not prevented", with the residual risks named.

Status: build specification, v1.0 draft, 2026-10-29. Primary reader:
Claude Code, implementing in a fresh repository. Secondary reader: the
author. Keywords MUST / SHOULD / MAY are normative. The tag `[D]` marks a
decision of this spec that no source dictates; everything else carries a
citation to the research notes' sources. Where the research flagged a gap
the text says "unverified" rather than filling it. Citations are
reference-style (`[label]`) and resolve in section 15.

## 1. Purpose and reading guide

ECP (Environment Context Protocol) is a read-only natural-language query
service for one SQLite database (tables `colors`, `links`, `qr_codes`,
`voats`) running on an edge Linux board. A host running Claude Code talks
to it as an MCP (Model Context Protocol) server. A prompt arrives as a
`tools/call`; the ECP Runtime asks a locally served Ollama model, reachable
only at the literal loopback address 127.0.0.1:11434, for a JSON
`ECPQueryPlan` constrained by a developer-owned schema; the plan is parsed
into a Rust struct, re-validated, compiled by exhaustive match into one of
three fixed parameterized `SELECT` templates, executed on a read-only,
authorizer-guarded connection, and the rows are returned to Claude Code as
typed, labelled, untrusted data. A complementary two-channel hardware input
(S, S-bar) from the host gates whether the runtime serves calls at all and
trips a latched hardware fault when the two channels agree for longer than
a discrepancy time. The model never writes SQL; the MCP process never
writes the database; the device never opens a network listener.

Relative to the two drafts, this spec makes the following corrections.
Each is argued, with sources, in the section named; Appendix B is the
ledger.

1. "MCP" is the Model Context Protocol, not "Master Control Process";
   the host-facing face of ECP is literally an MCP server (section 4).
2. `ecp.list_models`, `ecp.select_model`, `ecp.query` cannot be top-level
   JSON-RPC methods. They become three tools under `tools/list` /
   `tools/call`, with underscore names; model selection is stateless via a
   per-call `model_id`, because the 2026-07-28 revision removed sessions
   (section 4).
3. UART is not a transport Claude Code can open. The topology is Claude
   Code -> stdio -> host bridge -> UART -> device, where UART is an MCP
   custom transport that reuses stdio framing over a reliability layer
   (sections 3, 4).
4. The drafts' error codes -32000/-32001 sit in the range the current MCP
   policy tells new implementations not to use; domain failures become
   `isError: true` tool results (section 4).
5. `line.contains("ecp.query")` dispatch is replaced by a parsed JSON-RPC
   envelope with the mandated error codes, notification and batch rules
   (sections 4, 11).
6. "Zero dynamic dependencies", "standard library + bundled SQLite" and
   "embedded microcontroller core" are replaced by a statically linked
   musl Linux binary built offline from a vendored, locked crate set on an
   edge Linux board (sections 2, 10).
7. The `ECPQueryPlan` schema keeps its fields but drops `default` (the
   grammar converter ignores it), bounds `link_search` and `min_votes`,
   requires every key, and is emitted from the Rust struct rather than
   maintained by hand (sections 5, 6).
8. A loopback pin does not imply no egress: an Ollama daemon proxies
   `:cloud`-suffixed models, `remote_host` manifests and web search to
   ollama.com from the same port. The runtime implements client-side
   refusals and requires `OLLAMA_NO_CLOUD` (section 5).
9. The DDL is rewritten for `STRICT` tables: `BOOLEAN` and `DATETIME` are
   not legal STRICT type names; `==` becomes `=`; `AUTOINCREMENT` is kept
   only where id reuse would collide with file names; `PRAGMA
   foreign_keys` is set per connection outside a transaction; the read
   rail gets the sqlite.org untrusted-input hardening set (section 7).
10. The invariant "S + S-bar = 0" is wrong. Logic: S xor S-bar = 1.
    Voltage: V_S + V_S-bar = constant. Current: I_S + I_S-bar = 0 is what
    cancels far fields (section 8).
11. The drafts fuse differential signalling, WDDL/MDPL dual-rail precharge
    logic and two-channel safety inputs. Only the third is the lineage of
    "fault when S == S-bar". The DPA/DEMA, host-isolation and "2.0-2.3x
    area" claims are withdrawn; the interlock is specified in ISO 13849-1
    two-channel vocabulary with an honest timing ladder (section 8).
12. "Immunity to injection" becomes: SQL injection from model output is
    eliminated by construction; prompt injection is contained, not
    prevented; residual risks are enumerated (section 9).

## 2. Scope, non-goals and target platform

### 2.1 Target platform

The ECP Runtime targets an edge Linux board (Raspberry Pi, BeagleBone or
an industrial ARM64/x86-64 SBC), not a bare-metal microcontroller. The
reasons are structural, not preferences: rusqlite needs `std` and a
filesystem; the Ollama client needs TCP sockets; the interlock reader
uses the Linux GPIO character device, which is "Linux-only by
construction" ([gpiocdev README][gpiocdev]); and the bundled SQLite is
compiled with POSIX assumptions such as `-DHAVE_LOCALTIME_R` and
`SQLITE_THREADSAFE=1` ([libsqlite3-sys build.rs][sys-build]). If a true
MCU is ever required for the protective function, it is separate firmware
that owns the interlock and reports to this runtime; the Linux runtime
cannot meet sub-microsecond reaction times (section 8.6).

Build targets `[D]`: `aarch64-unknown-linux-musl` (device) and
`x86_64-unknown-linux-musl` (developer box, CI, and the host-side bridge).
Ollama runs on the same device as the runtime; "loopback" means the same
network namespace. The host-side bridge supports Linux hosts in v1; macOS
and Windows hosts are unverified.

### 2.2 What replaces "zero dynamic dependencies"

The honest claim is: a single statically linked musl executable with no
shared-library dependencies at runtime, built with `cargo build --locked
--offline` from a committed `Cargo.lock` and a committed `vendor/`
directory. A fully static binary requires a `*-unknown-linux-musl` target;
`+crt-static` against glibc "is not supported" by zig cc
([cargo-zigbuild README][zigbuild]). Even a pure-Rust binary is "aside
from libc ... statically linked" ([minreq README][minreq]). The dependency
set is roughly 25-40 crates once SQLite, serde, schemars, an HTTP client,
a QR encoder and GPIO are present (estimate from the direct-dependency
lists; exact count recorded at M0). For comparison, a minimal `rmcp`
stdio server locks 83 packages and a serde-only JSON-RPC server locks 11
([crates.io rmcp][rmcp], local measurement 2026-10-29). The only runtime
requirements are a Linux kernel with the GPIO chardev (uAPI v2), the
SQLite file, and a reachable Ollama daemon on loopback.

`#![forbid(unsafe_code)]` is asserted on every workspace crate's own
source; unsafe exists inside vetted dependencies (rusqlite/libsqlite3-sys
FFI and the C amalgamation). The lint is evaluated per crate
([rustc lint listing][lint]), and rusqlite itself contains `unsafe impl
Send for Connection {}` ([rusqlite src/lib.rs][rusq-lib]), so the claim
MUST be worded that way and never as "the binary is unsafe-free".

### 2.3 Non-goals for v1

- No write path reachable from MCP. Writes happen only through the CLI
  (section 7.6).
- No HTTP, WebSocket or TCP listener of any kind on the device or in the
  bridge. stdio and UART only.
- No support for cloud, remote-manifest or MLX-served models.
- No prompts, resources, sampling, roots, logging capability, or
  server-initiated requests. Tools only.
- No streaming of partial results; one `tools/call`, one result.
- No cryptographic material in the box; consequently no DPA/EMA target
  and no claim of side-channel resistance (section 8.5).
- No cross-circuit test pulses on the interlock in v1; the design claims
  the static-comparison diagnostic coverage figure, not the dynamic-test
  figure (section 8.3).
- No multi-tenant or per-user authorization; the stdio pipe is the access
  boundary ([MCP security best practices][mcp-sec]).

## 3. Architecture

### 3.1 Three domains

MCP Bridge (host). A relay process spawned by Claude Code. It speaks
newline-delimited JSON-RPC on stdin/stdout and the same lines, framed, on
a UART. It parses nothing and holds no state. On a single-box developer
setup it is omitted and Claude Code spawns the runtime directly.

Interlock (hardware, device side). Two single-ended inputs S and S-bar
with pull-ups, a hardware comparator (XNOR), an RC filter, a latch that
drives nRESET or a power-enable, and an external watchdog. The runtime
only observes it through GPIO and logs it.

ECP Runtime (device). One blocking, single-threaded-per-request Rust
binary: MCP server, planner client, plan validator, SQL compiler,
read-only SQLite rail, interlock reader, audit log.

```
  HOST                                    DEVICE (edge Linux board)
  +-------------+  stdio   +------------+  UART   +------------------+
  | Claude Code |<-------->| ecp-bridge |<=======>| ecp-runtime      |
  | MCP client  | JSON-RPC | (relay)    | framed  | MCP server       |
  +-------------+  lines   +------------+ lines   | plan -> SQL      |
                                                  +---+----------+---+
  +-------------+  S, S-bar (cable)                   | ro       | loopback
  | host GPIO   |=================+                   v          v
  | open drain  |                 |            +-----------+ +----------+
  +-------------+                 |            | ecp.sqlite| | ollama   |
                                  |            +-----------+ | 127.0.0.1|
                                  v                          | :11434   |
                      +-----------------------+              +----------+
                      | interlock HW:         |  FAULT, S, S-bar (GPIO in)
                      | XNOR -> RC -> latch   |------------> ecp-runtime
                      | -> nRESET / PWR_EN    |------------> SoC reset
                      +-----------------------+
```

### 3.2 One query, end to end

1. Claude Code calls `mcp__ecp__ecp_query` with `{"prompt": "...",
   "model_id": "..."}`; the bridge relays the line unchanged.
2. The runtime parses the JSON-RPC envelope, validates `_meta` (modern
   era) or the legacy session state, rate-limits, and reads the interlock
   snapshot. DISABLED or FAULT ends the call with an `isError` result.
3. If the prompt is exactly a hex colour (`^#[0-9A-Fa-f]{6}$`) the runtime
   SHOULD build the plan `{hex_code: ...}` without inference `[D]`.
   Otherwise it POSTs `/api/generate` to 127.0.0.1:11434 with the static
   system prompt, the user prompt, `format` = the ECPQueryPlan schema,
   `stream: false`, deterministic options, and checks the reply has
   `done_reason == "stop"` and no `remote_host` (section 5).
4. The reply body is parsed with `serde_json` into `EcpQueryPlan` under
   `deny_unknown_fields`, then `validate()` enforces the bounds the
   grammar cannot, producing a `ValidatedPlan` (section 6).
5. The compiler maps `sort_by` by exhaustive match to one of three
   `&'static str` templates and binds five parameters. The statement runs
   on the read rail (read-only flags, DEFENSIVE, query_only, authorizer,
   limits, progress handler), capped at 100 rows (section 7).
6. Rows are sanitized, size-capped, wrapped in `structuredContent` with
   `source` and `trust` labels and mirrored into a text block; the audit
   record is appended; the single response line is written and flushed.

### 3.3 Interlock state machine (replaces the drafts' session states)

The drafts' UNINITIALIZED / READY_IDLE / PLANNING_QUERY / EXECUTING_SQL
machine conflated per-call pipeline stages with device state and assumed
a session, which the current protocol forbids. The only persistent state
machine is the interlock's:

```
          both lines valid for >= t_disc
  INIT ------------------------------------> ENABLED (1,0)  serves calls
   |                                           ^   |
   | (0,0)/(1,1) >= t_disc                     |   | clean antivalent
   v                                           |   v transition
  FAULT (latched) <------------------------- DISABLED (0,1) refuses calls
   |      (0,0)/(1,1) >= t_disc from any state
   | functional test (DISABLED seen >= t_disc) + manual reset
   +----> INIT
```

`[D]` Code points: ENABLED = (S=1, S-bar=0); DISABLED = (S=0, S-bar=1).
The drafts labelled (0,1) "ECP Core Active"; here it is simply the host
having released the enable. Valid codewords are {(0,1),(1,0)}; fault
codewords are {(0,0),(1,1)} ([Rockwell DCS][rockwell],
[arXiv 1605.00681][survey]).

## 4. Protocol: ECP as an MCP server

### 4.1 Name and revisions

MCP is the Model Context Protocol. Every revision's text says so, e.g.
"changes made to the Model Context Protocol (MCP) specification since the
previous revision, 2025-11-25" ([MCP 2026-07-28 changelog][mcp-chg]). It
has been stewarded under the Linux Foundation's Agentic AI Foundation
since 2025-12-09 with Anthropic as original donor ([LF press
release][lf-aaif]). The drafts' "Master Control Process" expansion is
withdrawn; if a supervisor concept is ever needed it gets a different
abbreviation.

Dated revisions: 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25 and
2026-07-28; the TypeScript schema, "the source of truth for all protocol
messages", declares `LATEST_PROTOCOL_VERSION = "2026-07-28"`
([schema.ts][schema-ts], [MCP base protocol][mcp-base]). The 2026-07-28
revision moved MCP "from a bidirectional stateful protocol to a
request/response model" ([Claude blog][claude-blog]) and introduced a
twelve-month minimum deprecation window ([changelog][mcp-chg]).

Two eras therefore matter: legacy (2025-11-25 and earlier: `initialize`
handshake, connection-scoped session) and modern (2026-07-28: stateless,
`_meta` on every request, `server/discover`). The ECP Runtime MUST be a
dual-era server.

### 4.2 Why dual-era: Claude Code's negotiation

Claude Code has two client runtimes. "The v1 runtime is built on MCP
TypeScript SDK 1.x. The v2 runtime is the same code on MCP TypeScript SDK
2.0, which adds MCP protocol revision 2026-07-28." With feature flags it
uses v2 from Claude Code v2.1.232; without, by default from v2.1.274. On
v2 it "asks HTTP, stdio, and claude.ai connector servers whether they
support the newer revision and uses it with those that do" and connects
to every other server as v1 does; `MCP_SDK_GENERATION=v1|v2` and
`MCP_PROTOCOL_NEGOTIATION=auto|legacy` override this ([Claude Code MCP
docs][cc-mcp]).

The spec's probe matches: a dual-era client "SHOULD probe with
`server/discover` before sending any other request". If the server
returns a `DiscoverResult` or a recognized modern error such as
`UnsupportedProtocolVersionError`, it is modern; "any other error, or
does not respond within a reasonable timeout" means legacy, and the
fallback "MUST NOT be keyed to one specific error code"
([MCP stdio 2026-07-28][mcp-stdio]).

Branch rule (normative, from the versioning page): "A request carrying
modern per-request `_meta` is served statelessly according to this
revision. An `initialize` request selects legacy semantics, scoped to the
stdio process" ([MCP versioning][mcp-ver]). Concretely:

- `method == "initialize"` -> legacy mode for the life of the process.
- `params._meta["io.modelcontextprotocol/protocolVersion"]` present ->
  serve that request statelessly as 2026-07-28.
- Neither -> if legacy mode was already selected, serve it under legacy
  rules; otherwise it is malformed: `-32602`.

### 4.3 Modern-era requirements (2026-07-28)

Per request, `_meta` carries four fields under the
`io.modelcontextprotocol/` prefix: `protocolVersion` (string, required),
`clientInfo` (`Implementation`, optional), `clientCapabilities`
(`ClientCapabilities`, required), `logLevel` (optional). "A request
missing any required field is malformed; the server MUST reject it with
JSON-RPC error code `-32602`" ([MCP base protocol][mcp-base]). The
runtime MUST:

- Reject an unsupported `protocolVersion` with `-32022` and
  `data: {"supported": ["2026-07-28", "2025-11-25"], "requested": ...}`
  ([MCP versioning][mcp-ver]).
- Implement `server/discover`: "Servers MUST implement it." Result:
  `resultType: "complete"`, `supportedVersions: ["2026-07-28"]`,
  `capabilities: {"tools": {}}`, `instructions`, `ttlMs`, `cacheScope`,
  and `_meta["io.modelcontextprotocol/serverInfo"]`
  ([server/discover][mcp-disc]).
- Put `resultType: "complete"` in every result ([base][mcp-base]).
- Put `ttlMs` and `cacheScope` on `tools/list` results (`CacheableResult`)
  ([changelog][mcp-chg], [schema.ts][schema-ts]). `[D]` `ttlMs: 3600000`,
  `cacheScope: "public"`: the tool list is static.
- Include `_meta["io.modelcontextprotocol/serverInfo"]` in every result
  (SHOULD in the spec; MUST here) ([changelog][mcp-chg]).
- Never emit `ping`, `logging/setLevel` or the roots list-changed
  notification; they were removed ([changelog][mcp-chg]).
- Never write a JSON-RPC request to stdout: "The server MUST NOT write
  JSON-RPC requests to stdout" ([MCP stdio][mcp-stdio]). ECP issues no
  sampling, roots or elicitation; the MRTR `InputRequiredResult` pattern
  is unused.
- Treat every request as independent: "Servers MUST NOT rely on prior
  requests over the same connection to establish context"; cross-request
  state "MUST be referenced by an explicit identifier the client passes on
  each request" ([base][mcp-base]). This is why `model_id` is a per-call
  argument (section 4.6).
- Accept `notifications/cancelled`. `[D]` v1 processes requests
  sequentially, so a cancellation for a request whose response has
  already been written is a no-op; a cancellation read before a request
  is started suppresses it. The spec's "MUST NOT send any further
  messages for it" ([stdio][mcp-stdio]) is thereby met.
- Answer `prompts/list`, `resources/list` and any other undeclared method
  with `-32601` (Claude Code sends these discovery requests regardless of
  declared capabilities ([Claude Code MCP docs][cc-mcp])).

### 4.4 Legacy-era requirements (2025-11-25)

- `initialize` is "the first interaction". Respond with `protocolVersion`,
  `capabilities: {"tools": {}}`, `serverInfo {name, title, version}` and
  optional `instructions`. Version rule: echo the requested version if
  supported, else "respond with another protocol version it supports"
  ([MCP lifecycle 2025-11-25][mcp-life25]). `[D]` The runtime's legacy
  version is 2025-11-25; any other requested version receives
  `"2025-11-25"`.
- Accept `notifications/initialized`; before it, serve only `ping`
  ([lifecycle][mcp-life25]).
- Answer `ping` with an empty object result (the exact legacy `ping`
  result shape is from the schema, not quoted in the notes: unverified
  beyond "empty object").
- Serve `tools/list` and `tools/call` in the legacy shapes (no
  `resultType`, no `ttlMs`/`cacheScope`).

### 4.5 stdio framing and process rules

Both eras share the stdio rules: messages are newline-delimited JSON-RPC
2.0, "MUST NOT contain embedded newlines", UTF-8; "The server MUST NOT
write anything to its stdout that is not a valid MCP message"; stderr is
free for logs and clients "SHOULD NOT assume stderr output indicates
error conditions" ([MCP stdio][mcp-stdio], [MCP transports
2025-11-25][mcp-tr25]). Hence:

- Serialize compactly (no pretty printing); `\n` inside strings stays
  JSON-escaped; write each response with one `write_all` + flush.
- `[D]` Cap an input line at 1 MiB before parsing (the spec defines no
  maximum; rmcp bounds its line buffer, value unconfirmed). Over-long
  lines get `-32600` with `id: null` and the rest of the line is drained.
- JSON-RPC rules the runtime MUST enforce: `jsonrpc` exactly `"2.0"`
  else `-32600`; unparseable line `-32700` with `id: null`; unknown
  method `-32601`; a `params` envelope (`name`, `arguments`, `_meta`)
  failing deserialisation `-32602` with the serde message in `data`
  (the contents of `arguments` are the tool's to validate and fail as
  `isError`, section 4.6); internal failure `-32603`. Request ids are
  strings or integers and "MUST NOT be `null`" in MCP; notifications have
  no id and get no reply; a batch array is answered per JSON-RPC 2.0
  (empty array -> one `-32600`; all-notification batch -> no output)
  ([JSON-RPC 2.0][jsonrpc], [MCP base][mcp-base]). The envelope holds
  `params` as `Option<Box<RawValue>>` (serde_json `raw_value` feature)
  and `id` as `Option<Option<Value>>`, the documented way to tell
  "absent" from `null` ([serde_json 1.0.154][sj],
  [serde issue #1042][serde-1042]).
- Exit promptly when stdin reaches EOF: "the primary graceful-shutdown
  signal and the only portable one" ([stdio][mcp-stdio]). Also handle
  `SIGINT` and `SIGTERM`: on macOS and Linux Claude Code "sends `SIGINT`,
  then `SIGTERM` if the process is still running 100 milliseconds later,
  then `SIGKILL` after a further 400 milliseconds"; on Windows it closes
  stdin and ends the process tree 300 ms later (v2.1.296+)
  ([Claude Code MCP docs][cc-mcp]). The runtime and bridge MUST flush the
  audit log and release the GPIO request / serial port inside that budget.
- Startup MUST answer the first request within the client's default
  30-second connection timeout (`MCP_TIMEOUT`) ([Claude Code
  quickstart][cc-qs]); model preloading therefore runs asynchronously.

### 4.6 The three tools

Only `server/discover`, `tools/*`, `prompts/*`, `resources/*`,
`completion/*`, `subscriptions/listen` and notifications exist as
server-side methods in the schema ([schema.ts][schema-ts]); Claude Code
issues discovery requests and then `tools/call` ([cc-mcp][cc-mcp]). No
MCP client calls a custom top-level method, so an `ecp.query` method
would never be surfaced to the model. The drafts' three methods are
therefore tools.

Naming. Dots are legal in tool names (`admin.tools.list` is a valid
example) ([MCP tools][mcp-tools]) but Claude Code replaces `.` in server
keys with `_` and surfaces tools as `mcp__<server>__<tool>`
([Agent SDK MCP docs][cc-sdk]). `[D]` On-wire names are
`ecp_list_models`, `ecp_select_model`, `ecp_query`; under server key
`ecp` they appear as `mcp__ecp__ecp_query` etc. The list is static, in
this fixed order, identical on every connection ("MUST NOT vary
per-connection or as a side effect of other requests") and `listChanged`
is not declared ([MCP tools][mcp-tools]).

Schema dialect: `inputSchema` "Defaults to 2020-12 if no `$schema` field
is present", root "MUST be `type: "object"`"; for no-argument tools use
`{"type": "object", "additionalProperties": false}` ([MCP
tools][mcp-tools]). The drafts' Draft-07 `$schema` line belongs to the
Ollama-facing plan schema (section 5), not to tool schemas.

Annotations are hints and "untrusted unless they come from trusted
servers"; defaults are `readOnlyHint: false`, `destructiveHint: true`,
`idempotentHint: false`, `openWorldHint: true` ([schema.ts][schema-ts]),
so omitting them makes every tool look dangerous and open-world.

Stateless model selection `[D]`: `model_id` is the string
`<name>@<digest>` where `digest` is the `/api/tags` SHA-256 digest field
([Ollama /api/tags][ol-tags]). `ecp_select_model` verifies a model is
local, pins its digest and warms it; it stores nothing. `ecp_query`
accepts `model_id` (optional; the configured default otherwise) and
re-checks the digest before every call. A handle "MUST NOT" be treated
as authentication ([MCP security best practices][mcp-sec]); here it is a
plain identifier and carries no authority.

Tool 1:

```json
{
  "name": "ecp_list_models",
  "title": "List local planner models",
  "description": "List Ollama models that are local to the ECP device.",
  "inputSchema": {"type": "object", "additionalProperties": false},
  "outputSchema": {
    "type": "object",
    "properties": {
      "models": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "model_id": {"type": "string"},
            "name": {"type": "string"},
            "digest": {"type": "string"},
            "family": {"type": "string"},
            "parameter_size": {"type": "string"},
            "quantization_level": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "is_default": {"type": "boolean"}
          },
          "required": ["model_id", "name", "digest", "is_default"]
        }
      },
      "cloud_disabled": {"type": "boolean"}
    },
    "required": ["models", "cloud_disabled"]
  },
  "annotations": {
    "readOnlyHint": true, "destructiveHint": false,
    "idempotentHint": true, "openWorldHint": false
  }
}
```

Tool 2:

```json
{
  "name": "ecp_select_model",
  "title": "Verify and warm a planner model",
  "description": "Verify a model is local, pin its digest, preload it.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "name": {"type": "string", "minLength": 1, "maxLength": 128}
    },
    "required": ["name"],
    "additionalProperties": false
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "model_id": {"type": "string"},
      "name": {"type": "string"},
      "digest": {"type": "string"},
      "supports_thinking": {"type": "boolean"},
      "loaded": {"type": "boolean"},
      "load_duration_ns": {"type": "integer"}
    },
    "required": ["model_id", "name", "digest", "loaded"]
  },
  "annotations": {
    "readOnlyHint": false, "destructiveHint": false,
    "idempotentHint": true, "openWorldHint": false
  }
}
```

`readOnlyHint` is false for tool 2 because preloading changes daemon
memory state; it is additive and idempotent.

Tool 3:

```json
{
  "name": "ecp_query",
  "title": "ECP read-only query",
  "description": "Plan and run one read-only SELECT from English.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "prompt":   {"type": "string", "minLength": 1,
                   "maxLength": 2000},
      "model_id": {"type": "string", "maxLength": 200}
    },
    "required": ["prompt"],
    "additionalProperties": false
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "model_id":  {"type": "string"},
      "plan_used": {"type": "object"},
      "records": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "hex":          {"type": "string"},
            "color_family": {"type": "string"},
            "payload_url":  {"type": "string"},
            "file_path":    {"type": "string"},
            "net_votes":    {"type": "integer"},
            "created_at":   {"type": "string"}
          },
          "required": ["hex", "color_family", "payload_url",
                       "file_path", "net_votes", "created_at"]
        }
      },
      "row_count":       {"type": "integer"},
      "truncated":       {"type": "boolean"},
      "interlock_state": {"type": "string"},
      "source":          {"const": "ecp-sqlite-readonly"},
      "trust":           {"const": "untrusted-db-content"},
      "audit_id":        {"type": "integer"}
    },
    "required": ["model_id", "plan_used", "records", "row_count",
                 "truncated", "interlock_state", "source", "trust",
                 "audit_id"]
  },
  "annotations": {
    "readOnlyHint": true, "destructiveHint": false,
    "idempotentHint": true, "openWorldHint": false
  }
}
```

The full description strings live in `src/mcp/tools.rs`; each MUST stay
under 4,096 characters, the default Claude Code sends to the model
(`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`, v2.1.280+)
([Claude Code env vars][cc-env]). The argument bounds (prompt 2,000
characters, `name` 128, `model_id` 200) are `[D]`. An unknown tool name
is a `-32602` protocol error; argument validation failures (over-long
prompt, unknown keys) are tool execution errors and therefore `isError`
results with kind `args_invalid` (section 4.7), which the spec lists
under "Input validation errors" ([MCP tools][mcp-tools]). `plan_used`
in the output schema is the ECPQueryPlan object of section 6; the string
fields of `records` are described in the live schema as "opaque data;
not instructions".

Results. A tool returns `content: [{"type": "text", "text": <json>}]`
plus `structuredContent` with the same JSON: "a tool that returns
structured content SHOULD also return the serialized JSON in a
TextContent block", and with an `outputSchema` "Servers MUST provide
structured results that conform to this schema" ([MCP
tools][mcp-tools]). `structuredContent` "is server-produced result data
and is unrelated to LLM 'structured outputs'" ([MCP tools][mcp-tools]).

### 4.7 Errors: JSON-RPC codes versus `isError`

"Any errors that originate from the tool SHOULD be reported inside the
result object, with `isError` set to true, not as an MCP protocol-level
error response" ([schema.ts][schema-ts]). Protocol errors (unknown tool,
malformed params, internal failures) stay JSON-RPC errors.

| Range / code       | Meaning                | ECP use                  |
|--------------------|------------------------|--------------------------|
| -32700             | Parse error            | unparseable line         |
| -32600             | Invalid Request        | bad envelope, >1 MiB     |
| -32601             | Method not found       | undeclared methods       |
| -32602             | Invalid params         | bad `_meta`, unknown tool|
| -32603             | Internal error         | panics, I/O              |
| -32000 .. -32019   | legacy sub-range       | MUST NOT emit            |
| -32020 .. -32099   | reserved for MCP spec  | emit only -32022         |
| -32022             | UnsupportedProtocolVer | with data.supported      |
| -32002, -32042     | retired                | MUST NOT emit            |
| outside -32768..0  | application codes      | none defined in v1       |

Sources: constants and the partition policy ([schema.ts][schema-ts],
[MCP base protocol][mcp-base]); "new implementations SHOULD NOT use
codes from" -32000..-32019; application codes "SHOULD be allocated
outside the JSON-RPC reserved range (-32768 to -32000)" ([base][mcp-base]).
The drafts' `-32000` and `-32001` are therefore withdrawn. `[D]` ECP
defines no custom JSON-RPC codes in v1. Every domain condition is an
`isError: true` result whose `structuredContent` is
`{"kind": <enum>, "detail": <string>}` with `kind` one of:

`interlock_fault`, `interlock_disabled`, `args_invalid`,
`rate_limited`, `prompt_invalid`, `inference_unavailable`,
`inference_timeout`, `cloud_not_disabled`, `model_not_local`,
`model_digest_mismatch`, `egress_detected`, `plan_unparseable`,
`plan_invalid`, `plan_truncated`, `db_unavailable`, `db_timeout`,
`db_denied`.

`detail` MUST NOT echo model output or database text verbatim; it names
the field or condition.

### 4.8 UART as a custom transport behind a host-side bridge

Claude Code registers a server as a subprocess command or a URL
(`stdio`, `http`, `sse`, `ws`); it cannot open a serial port
([cc-mcp][cc-mcp]). The standard transports are exactly stdio and
Streamable HTTP; HTTP+SSE is Deprecated ([changelog][mcp-chg],
[deprecated registry][mcp-dep]). Custom transports are permitted:
implementers "MUST preserve the JSON-RPC message format, the message
patterns, and the per-request metadata model", "SHOULD document their
connection establishment, message framing, and cancellation patterns",
and byte-stream transports "SHOULD reuse the stdio framing rather than
defining a new one" ([MCP transports 2026-07-28][mcp-tr]). That
recommendation is conditioned on "a reliable bidirectional byte stream";
raw UART is not one.

ECP UART binding `[D]`:

- Payload: exactly the stdio wire format (one newline-terminated JSON-RPC
  message per frame), so the bridge is a pure relay.
- Reliability layer beneath it: frame = 4-byte big-endian length +
  payload + 4-byte CRC-32 of the payload; a frame with a bad CRC or a
  length over 1 MiB is dropped and counted on stderr; no retransmission
  in v1 (a lost request is retried by the client at the MCP layer, as the
  spec already expects after a server restart ([stdio][mcp-stdio])).
- Line settings: 8N1, hardware flow control (RTS/CTS) required; baud
  rate is a deployment parameter.
- Establishment: the bridge opens the port, sends a zero-length frame
  and waits up to 2 s for a zero-length frame back before relaying;
  failure exits non-zero so Claude Code reports the server as failed.
- Cancellation: carried as the ordinary `notifications/cancelled`
  message inside a frame.
- Shutdown: stdin EOF, `SIGINT` or `SIGTERM` at the bridge closes the
  port within 100 ms; the runtime treats a closed port like stdin EOF.
- The bridge MUST NOT parse, log or modify payloads; its stderr carries
  only its own diagnostics. It holds the port with exclusive access.
- Serial I/O crate: not covered by the research. `[D]` v1 opens the tty
  as a plain file after the port is configured externally (a wrapper
  script runs `stty` before exec); a vetted serial crate is an open
  decision (section 12).

### 4.9 Registration with Claude Code

Register with `claude mcp add [options] <name> -- <command> [args...]`;
stdio is the default transport; everything after `--` "is passed to the
server untouched" ([cc-mcp][cc-mcp]). Server names "can contain only
letters, numbers, hyphens, and underscores" ([cc-mcp][cc-mcp]).

```sh
# single-box developer setup
claude mcp add --scope project ecp -- \
  /usr/local/bin/ecp-runtime serve --stdio --db /var/lib/ecp/ecp.sqlite

# deployed: host bridge to the device over UART
claude mcp add --scope project ecp -- \
  /usr/local/bin/ecp-bridge --port /dev/ttyUSB0 --baud 115200
```

Project scope writes `.mcp.json` in the project root, shared with
everyone who clones it; local scope lives under `~/.claude.json` for this
project; user scope under its top-level `mcpServers` ([Claude Code
quickstart][cc-qs]). `${VAR}` and `${VAR:-default}` expand in `command`,
`args`, `env`, `url` and `headers`; a missing variable with no default
is left as literal text with a warning ([cc-mcp][cc-mcp]):

```json
{
  "mcpServers": {
    "ecp": {
      "type": "stdio",
      "command": "ecp-bridge",
      "args": ["--port", "${ECP_PORT:-/dev/ttyUSB0}",
               "--baud", "${ECP_BAUD:-115200}"],
      "env": {"ECP_LOG": "info"},
      "timeout": 120000
    }
  }
}
```

The per-server `timeout` (ms, values below 1000 ignored) overrides
`MCP_TOOL_TIMEOUT`, whose default is about 28 hours; the stdio idle
timeout default is 30 minutes ([cc-mcp][cc-mcp], [cc-env][cc-env]).
Claude Code "prompts for approval in interactive sessions before using
project-scoped servers from `.mcp.json`" ([cc-mcp][cc-mcp]); it sets
`CLAUDE_PROJECT_DIR` in the server's environment, and
`CLAUDE_CODE_MCP_ALLOWLIST_ENV=1` spawns stdio servers "with only a safe
baseline environment plus the server's configured `env`" ([cc-mcp][cc-mcp],
[cc-env][cc-env]). Operators SHOULD set it; the runtime reads only
`ECP_*` variables and never `HTTP_PROXY` or `OLLAMA_HOST` (section 5).

After connecting, Claude Code "sends it capability discovery requests
such as `tools/list`, `prompts/list`, and `resources/list`" and retries
transient failures up to three times ([cc-mcp][cc-mcp]). In an
interactive session a server whose process exits is marked failed until
the user chooses Reconnect in `/mcp`; in `claude -p` and Agent SDK
sessions it is restarted on the next tool call ([cc-mcp][cc-mcp]).

### 4.10 Output size limits

"When a successful tool result with no image content is larger than
25,000 tokens, Claude Code saves the output to a file and replaces the
tool result with an error message that names the file path";
`MAX_MCP_OUTPUT_TOKENS` changes the limit; "a successful text result
longer than 50,000 characters is saved to a file regardless of the token
limit" unless the tool declares `anthropic/maxResultSizeChars` (placement
of that declaration unverified) ([Agent SDK MCP docs][cc-sdk]); a warning
appears above 10,000 tokens ([cc-mcp][cc-mcp]). A worst case of 100 rows
with 2,048-character URLs would exceed 50,000 characters, so `[D]`:
`payload_url` and `file_path` are truncated to 256 characters in results
with `truncated: true`; the serialized result is capped at 40,000
characters by dropping trailing rows and setting `truncated: true`; the
mirrored text block is the JSON only.

## 5. Inference boundary (Ollama on loopback)

### 5.1 Endpoint and connection rules

Ollama "binds 127.0.0.1 port 11434 by default" and has no authentication
on the local API: "Cloud requests need an API key. Local requests do
not." ([Ollama FAQ][ol-faq], [API introduction][ol-intro]). The router
installs only CORS and a `Host`-header check; against a loopback-bound
daemon a non-loopback `Host` value is rejected with HTTP 403
([server/routes.go][ol-routes]). `envconfig.Host()` special-cases
`OLLAMA_HOST=ollama.com` into `https://ollama.com:443`
([envconfig/config.go][ol-env]).

The runtime MUST:

- Connect to the literal `SocketAddr` `127.0.0.1:11434`; no hostname, no
  resolver, no `OLLAMA_HOST`. `[D]` The address is a compile-time
  constant; a build feature, not a config key, is required to change it
  (open decision (a)).
- Send `Host: 127.0.0.1:11434`, `Content-Type: application/json`,
  `Accept: application/json`.
- Disable HTTP proxy pickup. ureq "automatically reads proxy
  configuration from environment variables" (`ALL_PROXY`, `HTTPS_PROXY`,
  `HTTP_PROXY`) and has no implicit loopback bypass; the runtime MUST
  build its agent with `.proxy(None)` ([ureq README][ureq],
  [ureq src/proxy.rs][ureq-proxy]). If minreq is chosen instead, its
  `proxy` feature MUST stay off ([minreq][minreq]).
- Set `max_redirects(0)`, a response-body cap (`[D]` 1 MiB), and
  per-phase timeouts (`[D]` connect 500 ms; first byte 60 s to cover a
  cold load, for which no primary latency figure exists; total 90 s).
  Ollama's own load-stall limit is 5 minutes (`OLLAMA_LOAD_TIMEOUT`)
  ([envconfig][ol-env]).
- Decode both `Content-Length` and `Transfer-Encoding: chunked`; Go's
  `net/http` picks per response ([Go commit bef4cb47][go-chunk]); ureq
  supports both ([ureq README][ureq]).

### 5.2 Endpoints and fields used

`GET /api/version` -> `{"version": ...}` (recorded in the audit log)
([routes.go][ol-routes]).

`GET /api/status` -> `{"cloud": {"disabled": bool, "source":
"none"|"env"|"config"|"both"}}` ([routes.go][ol-routes],
[api/types.go][ol-types]).

`GET /api/tags` -> `{"models": [...]}`; each entry has `name`, `model`,
`modified_at`, `size`, `digest`, `details{parent_model, format, family,
families, parameter_size, quantization_level, ...}`, optional
`capabilities`, and optional `remote_model` / `remote_host` ("URL of the
upstream Ollama host, if the model is remote") ([/api/tags][ol-tags],
[api/types.go][ol-types]).

`POST /api/show` with `{"model": name}` -> `details`, `capabilities`,
`thinking{values, default}`, `modified_at`, and `remote_model` /
`remote_host` when the manifest is remote ([routes.go][ol-routes],
[Thinking docs][ol-think]).

`POST /api/generate` request fields used: `model`, `system`, `prompt`,
`format` (JSON Schema object), `stream: false`, `think` (only when the
model reports the capability), `keep_alive`, `options{temperature, seed,
top_k, num_predict, num_ctx}`. Response fields used: `response`, `done`,
`done_reason`, `remote_model`, `remote_host`, `total_duration`,
`load_duration`, `prompt_eval_count`, `eval_count` (durations in
nanoseconds) ([/api/generate][ol-gen], [api/types.go][ol-types]).
`done_reason` values are `"stop"`, `"length"`, `"load"`, `"unload"`
(from code; the docs do not enumerate them) ([llm/server.go][ol-srv],
[routes.go][ol-routes]). Any `done_reason` other than `"stop"` on a plan
request is a failed plan (`plan_truncated` for `"length"`).

`/api/chat` is not used: it adds nothing for a single-shot plan and its
chat-template path emits schema keys alphabetically because the schema is
decoded into a Go map (issue #18717, open, reported on 0.35.0)
([ollama#18717][ol-18717]).

Unknown `options` keys are logged and ignored by the daemon, not
rejected ([api/types.go][ol-types]); option names are validated
client-side.

Warm-up `[D]`: at startup and after `ecp_select_model`, send
`/api/generate` with `model` and `keep_alive: "-1"` and no prompt;
`done_reason: "load"` confirms residency ("Load a model: Send only
`model`"; negative keep_alive means forever) ([/api/generate][ol-gen],
[FAQ][ol-faq]). Startup does not block on this.

### 5.3 The `format` path and what the grammar converter honours

On current main "All GGUF models are served via the upstream llama-server
subprocess"; a schema in `format` is forwarded as llama-server's
`json_schema` field, so the honoured keyword set is exactly llama.cpp's
`common/json-schema-to-grammar.cpp` and the guarantee is GBNF
grammar-constrained sampling ([llm/server.go][ol-srv],
[llm/llama_server.go][ol-ls]). "The JSON schema is only used to
constrain the model output and is not injected into the prompt"
([llama.cpp grammars README][lc-readme]); the system prompt MUST
therefore describe the plan fields in words.

Honoured, per the converter source and README
([json-schema-to-grammar.cpp][lc-conv], [grammars README][lc-readme]):

- `enum`, `const`.
- `object`/`properties`/`required`: required properties first, in
  declaration order; optional ones as an ordered optional chain.
- `additionalProperties`: defaults to `false` in the converter.
- `integer` with `minimum`/`maximum` (digit-range rules); "only
  supported for `"type": "integer"` for now, not `number`".
- `string` `minLength`/`maxLength`; `format` only `date`, `time`,
  `date-time`, `uuid` (no `uri`, no `email`).
- `pattern` only if anchored: it "must start with `^` and end with `$`";
  inside, literals, `.`, `[...]` classes, groups, `|`, `* + ?`, `{m}`,
  `{m,}`, `{m,n}`, and a short escape list (`\x..`, `\u....`, `\t \r \n
  \\ \" \[ \] \-`). `\d`, `\w`, `\s`, lookarounds and named groups throw
  `unsupported_pattern`, after which the converter accepts any string
  with only a stderr warning. The drafts' `^#[0-9A-Fa-f]{6}$` is inside
  the supported subset.
- `anyOf`/`oneOf` as unions; `allOf` merged; local `$ref` resolved but
  "Nested `$ref`s are broken"; "Can't mix `properties` w/ `anyOf` /
  `oneOf` in the same type"; no `patternProperties`.

Silently ignored: `default`, `title`, `description`, `examples` (no
converter code path reads them), `number` bounds, `multipleOf`,
`uniqueItems`, `not`, conditionals: "Unsupported features are skipped
silently" ([lc-conv][lc-conv], [lc-readme][lc-readme]). The drafts'
`"default": 20` and `"default": "net_votes"` therefore never reached the
model; the runtime supplies defaults.

Conflict between notes: the security note could not confirm whether
`pattern` and integer bounds are enforced; the Ollama note read the
converter source and confirms anchored patterns and integer bounds are
compiled into the grammar. The primary-source reading wins. Re-validation
in Rust is still mandatory (section 5.7).

Thinking interaction: when a response begins with thinking, the schema
is first converted to GBNF by an extra call to llama-server and wrapped so
it applies only after the thinking close string
([llama_server.go][ol-ls]). `think=false` plus `format` was silently
ignored for gemma4 on 0.20.x (fixed in 0.21.1 for gemma4 only;
qwen3.5/3.6 tracked in #14645) ([ollama#15260][ol-15260]). `[D]` Prefer
a non-thinking instruct model; send `think: false` only when `/api/show`
reports the capability; the M3 live test covers the exact model and
daemon version.

### 5.4 The corrected ECPQueryPlan wire schema

Emitted from the Rust struct in section 6 with
`SchemaSettings::draft07()` ([schemars generate.rs][schemars-gen]), then
snapshot-tested. Normative properties of the emitted schema (the
mechanism, attribute or transform, is Claude Code's choice):

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EcpQueryPlan",
  "type": "object",
  "properties": {
    "target_family": {
      "anyOf": [
        {"type": "string",
         "enum": ["red", "green", "blue", "cyan",
                  "magenta", "yellow", "gray"]},
        {"type": "null"}
      ]
    },
    "hex_code": {
      "anyOf": [
        {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
        {"type": "null"}
      ]
    },
    "link_search": {
      "anyOf": [
        {"type": "string", "minLength": 1, "maxLength": 32},
        {"type": "null"}
      ]
    },
    "min_votes": {
      "anyOf": [
        {"type": "integer", "minimum": -100000, "maximum": 100000},
        {"type": "null"}
      ]
    },
    "sort_by": {
      "anyOf": [
        {"type": "string",
         "enum": ["net_votes", "created_at", "color_family"]},
        {"type": "null"}
      ]
    },
    "limit": {
      "anyOf": [
        {"type": "integer", "minimum": 1, "maximum": 100},
        {"type": "null"}
      ]
    }
  },
  "required": ["target_family", "hex_code", "link_search",
               "min_votes", "sort_by", "limit"],
  "additionalProperties": false
}
```

Changes against the drafts and why:

- All six keys are `required` so the model must emit each one (null
  where not applicable); the grammar emits required keys in declaration
  order, which fixes key order and removes the missing-versus-null
  ambiguity ([lc-conv][lc-conv]).
- Nullable fields use property-level `anyOf` rather than
  `"type": ["string", "null"]`; the converter's lowering of type arrays
  was not re-read this session (unverified), while `anyOf` is the
  documented union path. The object level has no `anyOf`, respecting the
  "can't mix" rule.
- `link_search` gains `minLength`/`maxLength` (32 `[D]`); `min_votes`
  gains integer bounds (`[D]` +-100000); `default` keys are removed.
- The emitted schema MUST contain no `$ref` (inline enums), no
  `description` text derived from user input, and no keyword outside the
  honoured list. The schema is a security artifact: it is static,
  developer-owned, hashed into every audit record, and never built from
  user text or tool descriptions, which is the premise of the
  constrained-decoding attacks (EnumAttack / DictAttack, 94.3-99.5% ASR
  on gpt-5, gemini-2.5-pro, deepseek-r1, gpt-oss-120b)
  ([arXiv 2503.24191v2][cda]).

### 5.5 Off-box paths inside a loopback daemon, and the refusals

A daemon on 127.0.0.1 can still send a request off the box
([routes.go][ol-routes], [modelref.go][ol-modelref]):

1. Name suffix: a trailing `:cloud` (case-insensitive) or a tag ending in
   `-cloud` routes to `proxyCloudJSONRequest` toward ollama.com, signed
   with the daemon's key; `:local` forces local; `foo:cloud:local` is an
   error. Cloud models "do not need to be downloaded" ([Cloud
   docs][ol-cloud], [Cloud blog][ol-blog-cloud]).
2. Remote manifest: a locally pulled model whose config has `remote_host`
   / `remote_model` is forwarded to that host (default allow-list
   `OLLAMA_REMOTES=ollama.com`) and every response chunk is stamped
   `remote_model` / `remote_host`; such manifests can be created via
   `/api/create` ([routes.go][ol-routes], [api/types.go][ol-types]).
3. `/api/web_search`, `/api/web_fetch`, usage, balance, whoami, signin.
4. A Codex desktop proxy path on the same listener.

"Ollama's cloud currently does not support structured outputs"
([Structured outputs docs][ol-so]); a plan request that went to the
cloud would also lose its grammar.

Daemon-side control: `OLLAMA_NO_CLOUD=1` or `"disable_ollama_cloud":
true` in `~/.ollama/server.json` disables "remote inference and web
search"; cloud proxies then return 403 ([FAQ][ol-faq],
[envconfig][ol-env], [routes.go][ol-routes]). Whether it also disables
the Codex proxy's upstream selection is unverified, so the deployment
MUST additionally firewall the `ollama` process from any non-loopback
destination (the only control covering paths 3-4).

Client-side refusals the runtime MUST implement:

1. At startup and before every plan: `GET /api/status`; if
   `cloud.disabled != true`, `ecp_query` returns `cloud_not_disabled`.
   `tools/list` still works so the operator sees the error.
2. Accept only model names that appear in `/api/tags` with empty
   `remote_host` and `remote_model`; reject any name whose last
   `:`-segment is `cloud` or `local` or whose tag ends in `-cloud`.
3. `[D]` Append `:local` to the pinned name on `/api/generate`; with the
   current parser a remote manifest then yields 404 instead of a proxy.
   A daemon too old to parse `:local` also yields 404, which fails
   closed with an operator-facing message (the introducing version is
   unverified).
4. At `ecp_select_model`: `POST /api/show`; require `remote_host == ""`,
   `remote_model == ""`, `capabilities` containing `"completion"`;
   record `details.family`, `details.quantization_level`,
   `thinking.values`, and the `/api/tags` digest into `model_id`.
5. Before every plan: re-read `/api/tags`; if the digest for the name
   differs from `model_id`, return `model_digest_mismatch`. "Same model
   name" does not imply same weights.
6. On every `/api/generate` response: `remote_host` and `remote_model`
   MUST be absent or empty; otherwise return `egress_detected`, discard
   the plan, and log at the highest severity (data left the box).
7. Never call `/api/pull`, `/api/push`, `/api/create`, `/api/copy`,
   `/api/delete`, `/api/web_search`, `/api/web_fetch`, `/v1/*`, or any
   path not listed in 5.2. Model installation is an operator action.
8. No DNS: the client never resolves a name; the `Host` header is a
   literal.

### 5.6 Determinism settings and model choice

`seed` "will make the model generate the same text for the same prompt"
and the structured-output guidance is temperature 0
([Modelfile docs][ol-mf], [Structured outputs][ol-so]). Request
defaults are `temperature 0.8`, `seed -1`, `top_k 40`, `top_p 0.9`,
`num_predict -1`; `cache_prompt: true` is passed to llama-server
([api/types.go][ol-types], [llama_server.go][ol-ls]). `[D]` The runtime
sends `options: {"temperature": 0, "seed": 7, "top_k": 1, "num_predict":
256, "num_ctx": 4096}` and retries once with `num_predict: 512` on
`done_reason: "length"`; the box runs `OLLAMA_NUM_PARALLEL=1` (default
1) ([FAQ][ol-faq]). Default `num_ctx` is VRAM-tiered: 4k under 24 GiB
VRAM ([Context length docs][ol-ctx], [envconfig][ol-env]); the FAQ says
4096 and the Modelfile page still says 2048 (stale); the code-level
description wins. Nothing promises bitwise reproducibility across
hardware, drivers, batch or prompt-cache state; determinism is an
operational property to test, never a security control.

Model recommendations. Primary Ollama sources do not rank models for
schema adherence; the docs' own 2026 examples use `gemma4` and `gpt-oss`
([/api/generate][ol-gen]). Secondary 2026 sources, weighted accordingly:
library download sizes checked September 2026: qwen3:4b 2.5 GB, qwen3:8b
5.2 GB, gemma3:4b 3.3 GB, gemma3:12b 8.1 GB, phi4-mini:3.8b 2.5 GB,
llama3.2:3b 2.0 GB, llama3.1:8b 4.9 GB, mistral:7b 4.4 GB; runtime memory
exceeds download size ([needtoknowit, 2026-09-14][n2k]). For an 8 GB
GPU, "Qwen 3.5 9B (Q4_K_M)" at 6.6 GB is one author's default pick and
"Phi-4-mini handles structured output better than expected for its
size"; that article contains at least two factual errors
([mayhemcode, 2026-06-16][mayhem]). `gpt-oss:20b` "worked correctly with
`think=false` and `format`" ([ollama#15260][ol-15260]) but does not fit
8 GB VRAM. `[D]` v1 default: a 4B-class non-thinking instruct GGUF model
pinned by digest; with the grammar enforcing syntax, what the size buys
is semantic accuracy, and the 3-4B class is the latency ceiling for a
CPU-only 16 GB box. The drafts' example list (`llama3:8b`, `phi3:mini`,
`mistral:7b`) is just whatever `/api/tags` returns and is not endorsed.

### 5.7 What constrained decoding guarantees, and what Rust re-checks

Guaranteed by the grammar on the GGUF path when conversion succeeded and
`done_reason == "stop"`: parseable JSON; only declared keys; all
required keys in order; enum/const values; integer bounds; string
lengths; anchored patterns; `null` only where the union allows it.
Not guaranteed: semantic correctness of any value; `number` bounds;
unsupported patterns (degrade to any string, no API-visible signal);
completeness under `num_predict` truncation; enforcement at all on MLX,
cloud or buggy thinking paths; key order on `/api/chat`
([lc-conv][lc-conv], [lc-readme][lc-readme], [ol-18567][ol-18567]).

The runtime MUST therefore treat the grammar as a filter and perform, in
Rust, after `serde_json::from_str` under `deny_unknown_fields`: hex
syntax and case normalisation; `link_search` length, control-character
and whitespace checks; `min_votes` range; `limit` clamp to 1..=100 with
`None -> 20`; `sort_by` `None -> net_votes`; integer overflow (a 40-digit
literal fails `i32` deserialization and is a `plan_invalid`, not a
panic). OWASP's LLM01 measure (2) is exactly this: "Define and validate
output formats ... check adherence with deterministic code"
([OWASP LLM Top 10 2025][owasp-pdf]).

## 6. Query planning and SQL compilation

### 6.1 The struct is the single source of truth

One Rust type defines the planner contract. Its schema is emitted by
schemars, sent to Ollama as `format`, and snapshot-tested; its
deserialization is serde under `deny_unknown_fields`, "the direct
equivalent of `additionalProperties: false`" ([serde container
attributes][serde-ca]); its bounds are checked by `validate()`. No
JSON-Schema validator runs in the binary: `jsonschema` 0.60.2 with
default features links reqwest and TLS for remote `$ref` resolution and
even without them brings about twenty crates ([crates.io
jsonschema][jsonschema]); the struct plus explicit checks gives zero
schema-runtime dependency.

```rust
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ColorFamily { Red, Green, Blue, Cyan, Magenta, Yellow, Gray }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum SortBy { NetVotes, CreatedAt, ColorFamily }

/// Planner contract. Field order is wire order (section 5.4).
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct EcpQueryPlan {
    pub target_family: Option<ColorFamily>,
    pub hex_code: Option<String>,     // ^#[0-9A-Fa-f]{6}$, upper-cased
    pub link_search: Option<String>,  // 1..=32 chars, no controls
    pub min_votes: Option<i32>,       // -100_000..=100_000
    pub sort_by: Option<SortBy>,      // None -> NetVotes
    pub limit: Option<u8>,            // None -> 20; 1..=100
}

/// Only constructible through `EcpQueryPlan::validate`.
pub struct ValidatedPlan { /* normalised, private fields */ }
```

Rules:

- A missing `Option<T>` field and an explicit `null` both deserialize
  to `None` ([serde src/private/de.rs][serde-de]); the spec assigns them
  the same meaning. `flatten` is never used (incompatible with
  `deny_unknown_fields`) ([serde-ca][serde-ca]).
- serde_json's 128-level recursion limit stays on; `unbounded_depth` is
  forbidden ([serde_json src/de.rs][sj-de]). Input is size-capped before
  `from_str` (section 5.1 body cap), and `from_str` rejects trailing
  garbage ([sj-de][sj-de]).
- `validate()` returns `Result<ValidatedPlan, PlanError>`; `PlanError`
  names the field and rule and becomes `plan_invalid`. `sql::compile`
  accepts only `ValidatedPlan` (type-state), so an unvalidated plan cannot
  reach SQLite.
- Hex check is hand-written (length 7, `#`, six ASCII hex digits); the
  `regex` crate is not a dependency `[D]`.
- `hex_code` is upper-cased before binding; the database stores
  upper-case hex (section 7.6).

### 6.2 Enum-to-SQL by exhaustive match; everything else bound

Parameter markers "represent data values, not table names, column names,
or SQL keywords such as ASC and DESC"; the sort direction must be mapped
"to the literal ASC or DESC, rather than appending the supplied text";
allow-list validation "does not make it safe to concatenate into SQL"
([OWASP SQLi cheat sheet][owasp-sqli]). Hence:

```rust
fn order_by(sort: SortBy) -> &'static str {
    match sort {
        SortBy::NetVotes    => "net_votes DESC, q.id ASC",
        SortBy::CreatedAt   => "q.created_at DESC, q.id ASC",
        SortBy::ColorFamily => "c.color_family ASC, q.id ASC",
    }
}
```

The three complete statements are `&'static str` constants assembled at
compile time (`concat!`), one per `SortBy` variant; the match selects a
constant. No `format!`, no runtime string building of SQL anywhere in
the crate; a test greps the `sql` module for `format!` and `+` on SQL
strings and fails if any appears (M2). Tie-breakers on `q.id` make
results deterministic `[D]`.

`target_family` is bound as its lower-case string (a value, compared
with `=`); it is never spliced as an identifier.

### 6.3 LIKE with ESCAPE

`link_search` is a substring search over `links.payload_url`. SQLite LIKE
treats `%` and `_` as wildcards; with `ESCAPE`, "The escape character
followed by a percent symbol, underscore or itself matches a literal
percent symbol, underscore or escape character"; LIKE is
case-insensitive for 7-bit Latin characters only ([SQLite LIKE
docs][sq-like]). Since 2020 "The ESCAPE clause on LIKE takes precedence
over wildcards" ([SQLite forum][sq-forum]); the bundled 3.54.1 includes
this. The runtime MUST build the pattern as: escape `\` -> `\\`, `%` ->
`\%`, `_` -> `\_`, then wrap in `%...%`, and bind it with `ESCAPE '\'`.
Maximum pattern length is 2 + 2 x 32 = 66, under the connection limit
`SQLITE_LIMIT_LIKE_PATTERN_LENGTH = 80` (section 7.4). A property test
asserts that a stored URL containing a literal `%` matches only when
searched literally.

### 6.4 The compiled SELECT

```sql
SELECT c.hex,
       c.color_family,
       l.payload_url,
       q.file_path,
       COALESCE(nv.net_votes, 0) AS net_votes,
       q.created_at
FROM qr_codes AS q
JOIN colors AS c ON c.id = q.color_id
JOIN links  AS l ON l.id = q.link_id
LEFT JOIN (SELECT color_id, SUM(vote_type) AS net_votes
           FROM voats
           GROUP BY color_id) AS nv
       ON nv.color_id = c.id
WHERE (?1 IS NULL OR c.color_family = ?1)
  AND (?2 IS NULL OR c.hex = ?2)
  AND (?3 IS NULL OR l.payload_url LIKE ?3 ESCAPE '\')
  AND (?4 IS NULL OR COALESCE(nv.net_votes, 0) >= ?4)
ORDER BY net_votes DESC, q.id ASC        -- variant: NetVotes
LIMIT ?5;
```

Bindings: `?1` family text or NULL; `?2` upper-case hex or NULL; `?3`
escaped LIKE pattern or NULL; `?4` `min_votes` or NULL; `?5` the clamped
limit (1..=100). Five variables, under `SQLITE_LIMIT_VARIABLE_NUMBER =
10`. The other two variants differ only in the `ORDER BY` line. The
statements are prepared with `prepare_cached` on the read rail with the
authorizer already installed (authorization happens at prepare time and
again on re-prepare after a schema change
([sqlite3_set_authorizer][sq-auth])).

### 6.5 Limits, echo, and labels

- `LIMIT` is both bound and re-checked: the row loop stops at the
  clamped limit regardless of what SQLite returns.
- `plan_used` echoes the `ValidatedPlan` (post-normalisation: upper-case
  hex, defaults filled, with a `clamped` list naming any field the
  runtime altered), never the raw model text.
- The result carries `source: "ecp-sqlite-readonly"` and `trust:
  "untrusted-db-content"` so a host policy layer can taint-track
  (section 9.6).
- The `payload_url`, `file_path`, `hex`, `color_family` strings are
  returned as plain strings in `structuredContent`, never as Markdown
  links or images.

### 6.6 Planner prompt (context minimisation)

The system prompt is static, versioned (`PLANNER_PROMPT_V1`), hashed into
each audit record, and contains: the six fields and their meanings, the
seven families, the three sort keys, the instruction to answer only with
the JSON object ("Add 'return as JSON' to the prompt" is Ollama's own
guidance) ([Structured outputs blog][ol-blog-so]). It never contains
database rows, prior results or prior prompts; the planner sees only the
current English prompt plus the static schema description. This is the
Plan-Then-Execute / Context-Minimization shape, which bounds *which*
actions run but not their content ([prompt-injection design
patterns][patterns]). The second-order path (rows -> Claude Code -> next
prompt) remains and is treated in section 9.

## 7. Database

### 7.1 Corrected DDL

STRICT tables exist since 3.37.0 (2021-11-27); the allowed type names are
INT, INTEGER, REAL, TEXT, BLOB, ANY and "No other datatype names are
allowed" ([SQLite STRICT tables][sq-strict]). The drafts' `BOOLEAN` and
`DATETIME` columns would be rejected; in non-STRICT tables they are
merely NUMERIC-affinity names ([SQLite datatypes][sq-dt]). SQLite has no
Boolean or date storage class; booleans are integers 0/1 and dates are
TEXT, REAL or INTEGER ([sq-dt][sq-dt]). `DEFAULT CURRENT_TIMESTAMP` is
"a text representation of the current UTC date and time" in
`YYYY-MM-DD HH:MM:SS` ([SQLite CREATE TABLE][sq-ct]). `==` is a legal
synonym for `=` ([SQLite expressions][sq-expr]); `=` is used.

```sql
PRAGMA user_version = 1;

CREATE TABLE colors (
    id           INTEGER PRIMARY KEY,
    hex          TEXT    NOT NULL UNIQUE
                 CHECK (length(hex) = 7 AND substr(hex, 1, 1) = '#'),
    r            INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g            INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b            INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
    cube_index   INTEGER NOT NULL UNIQUE
                 CHECK (cube_index BETWEEN 0 AND 215),
    color_family TEXT    NOT NULL
                 CHECK (color_family IN ('red', 'green', 'blue',
                        'cyan', 'magenta', 'yellow', 'gray'))
) STRICT;

CREATE TABLE links (
    id          INTEGER PRIMARY KEY,
    payload_url TEXT NOT NULL UNIQUE
                CHECK (length(payload_url) BETWEEN 1 AND 2048),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE qr_codes (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path              TEXT    NOT NULL UNIQUE,
    link_id                INTEGER NOT NULL
                           REFERENCES links(id)  ON DELETE CASCADE,
    color_id               INTEGER NOT NULL
                           REFERENCES colors(id) ON DELETE RESTRICT,
    format                 TEXT    NOT NULL
                           CHECK (format IN ('PNG', 'SVG')),
    error_correction_level TEXT    NOT NULL
                           CHECK (error_correction_level
                                  IN ('L', 'M', 'Q', 'H')),
    verified_scan          INTEGER NOT NULL DEFAULT 0
                           CHECK (verified_scan IN (0, 1)),
    created_at             TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE voats (
    id         INTEGER PRIMARY KEY,
    color_id   INTEGER NOT NULL
               REFERENCES colors(id) ON DELETE CASCADE,
    vote_type  INTEGER NOT NULL CHECK (vote_type IN (-1, 1)),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX qr_codes_color_id ON qr_codes(color_id);
CREATE INDEX qr_codes_link_id  ON qr_codes(link_id);
CREATE INDEX voats_color_id    ON voats(color_id);
CREATE INDEX colors_family     ON colors(color_family);
```

Notes on the DDL:

- `NOT NULL` is load-bearing on `hex`: `length(NULL)` is NULL and a NULL
  CHECK result "is not a violation" ([sq-ct][sq-ct]).
- CHECK expressions "may not contain a subquery" ([sq-ct][sq-ct]), so
  cross-table rules live in foreign keys or the writer. Only built-in
  functions appear in CHECKs and DEFAULTs; `CURRENT_TIMESTAMP` is a
  keyword, chosen over `strftime(...)` so that `trusted_schema=OFF`,
  which can block non-innocuous functions in schema contexts
  ([SQLite PRAGMA][sq-pragma]), never interferes `[D]`.
- `AUTOINCREMENT` "is usually not needed" and adds CPU, memory, disk and
  I/O overhead via `sqlite_sequence`; without it a deleted maximum rowid
  can be reused ([SQLite AUTOINCREMENT][sq-auto]). It is kept only on
  `qr_codes` because file names derive from the id and a reused id would
  collide with a leftover file `[D]`; the other tables use plain
  `INTEGER PRIMARY KEY` (the rowid alias; an `INT PRIMARY KEY` would not
  be) ([sq-strict][sq-strict]).
- `ON DELETE RESTRICT` fires "as soon as the field is updated", even for
  deferred constraints, whereas NO ACTION waits ([SQLite foreign
  keys][sq-fk]); RESTRICT on `colors` is intended.
- Indexes on the foreign-key child columns are a decision `[D]` for
  cascade and join performance. `cube_index` is UNIQUE because v1 seeds
  exactly the 216 cube colours (7.6) `[D]`.
- `error_correction_level` keeps the drafts' column name.
- `[D]` Journal mode stays the default rollback journal (DELETE) in v1.
  WAL would require the read-only rail to have readable `-shm`/`-wal`
  files or a writable directory, and `immutable=1` is unsafe on a live
  database ([SQLite WAL][sq-wal]).

### 7.2 Foreign keys: per connection, outside a transaction

"Foreign key constraints are disabled by default" and `PRAGMA
foreign_keys = ON` is per connection; inside a multi-statement
transaction the pragma "simply has no effect" ([sq-fk][sq-fk],
[sq-pragma][sq-pragma]). The surprise: libsqlite3-sys's bundled build
compiles with `-DSQLITE_DEFAULT_FOREIGN_KEYS=1`, so under rusqlite
`bundled` enforcement is already ON
([libsqlite3-sys build.rs][sys-build]). The writer MUST NOT rely on
that: every writer connection executes `PRAGMA foreign_keys = ON`
immediately after open, before any `BEGIN`, and asserts `PRAGMA
foreign_keys` returns 1 (a build lacking FK support returns no row
([sq-fk][sq-fk])). Unknown or misspelled pragmas are "simply ignored"
([sq-pragma][sq-pragma]), which is why the readback
is mandatory. After seeding, `PRAGMA foreign_key_check` MUST return no
rows; `PRAGMA integrity_check` "does not find FOREIGN KEY errors"
([sq-pragma][sq-pragma]).

### 7.3 Read rail bring-up (the MCP process)

Order matters: pragmas before the authorizer, since the authorizer would
otherwise deny them. All APIs below exist in rusqlite 0.41.1
([rusqlite src/lib.rs][rusq-lib], [src/config.rs][rusq-cfg],
[src/limits.rs][rusq-lim], [src/hooks/mod.rs][rusq-hooks]).

1. `Connection::open_with_flags(path, SQLITE_OPEN_READ_ONLY |
   SQLITE_OPEN_NO_MUTEX | SQLITE_OPEN_EXRESCODE | SQLITE_OPEN_NOFOLLOW)`.
   `SQLITE_OPEN_URI` is deliberately absent (the default flag set
   includes it); the path comes from config and is a regular file.
2. `set_db_config(SQLITE_DBCONFIG_DEFENSIVE, true)`: disables
   `writable_schema`, `journal_mode=OFF`, direct shadow-table writes
   ([SQLite dbconfig][sq-dbcfg]).
3. `set_db_config(SQLITE_DBCONFIG_TRUSTED_SCHEMA, false)`: "all
   applications are encouraged to switch this setting off on every
   database connection" ([sq-pragma][sq-pragma]).
4. `SQLITE_DBCONFIG_ENABLE_TRIGGER = false`, `ENABLE_VIEW = false` (the
   schema has neither), `ENABLE_ATTACH_CREATE = false`,
   `ENABLE_ATTACH_WRITE = false`, `DQS_DML = false`, `DQS_DDL = false`,
   `ENABLE_COMMENTS = false` ([sq-dbcfg][sq-dbcfg], [rusq-cfg][rusq-cfg]).
5. `pragma_update(None, "query_only", true)`: writes fail with
   `SQLITE_READONLY`; "the database is not truly read-only"
   ([sq-pragma][sq-pragma]), which is why step 1 opens read-only too.
6. `PRAGMA quick_check` at open; refuse to serve if it is not `ok`
   (sqlite.org: "Reject and refuse to process any database file
   containing errors") ([SQLite security][sq-sec]) `[D]`.
7. `PRAGMA hard_heap_limit = 67108864` (64 MiB `[D]`; it "can only lower
   the heap limit") ([sq-pragma][sq-pragma]).
8. `set_limit` per section 7.4.
9. `authorizer(Some(...))` per section 7.5.
10. `progress_handler(1000, Some(deadline))` with a 2 s wall-clock budget
    `[D]`; the handler returns true to interrupt
    ([rusq-hooks][rusq-hooks]). An `InterruptHandle` is kept for the
    supervisor.
11. Prepare the three templates with `prepare_cached`.

`Connection` is `Send` but not `Sync`; rusqlite says to use "one for
each thread" ([rusq-lib][rusq-lib]). v1 serves requests sequentially on
one thread with one read connection. The extension-loading C API is
compiled in (`-DSQLITE_ENABLE_LOAD_EXTENSION=1`)
([sys-build][sys-build]); the rusqlite `load_extension` feature stays
off and the API is never called.

### 7.4 `sqlite3_limit` values

Per-connection, "Attempts to increase a limit above its hard upper bound
are silently truncated" ([sqlite3_limit][sq-limit]). Values are the
sqlite.org high-security column ([sq-sec][sq-sec]) except where marked.

| Limit                 | Default       | sqlite.org | ECP read rail  |
|-----------------------|---------------|------------|----------------|
| LENGTH                | 1,000,000,000 | 1,000,000  | 1,000,000      |
| SQL_LENGTH            | 1,000,000,000 | 100,000    | 10,000 `[D]`   |
| COLUMN                | 2,000         | 100        | 100            |
| EXPR_DEPTH            | 1,000         | 10         | 10, see note   |
| PARSER_DEPTH          | 2,500         | 100        | 100            |
| COMPOUND_SELECT       | 500           | 3          | 3              |
| VDBE_OP               | 250,000,000   | 25,000     | 25,000         |
| FUNCTION_ARG          | 127           | 8          | 8              |
| ATTACHED              | 10            | 0          | 0              |
| LIKE_PATTERN_LENGTH   | 50,000        | 50         | 80 `[D]`       |
| VARIABLE_NUMBER       | 999           | 10         | 10             |
| TRIGGER_DEPTH         | 1,000         | 10         | 10             |
| SCHEMA                | 10,000,000    | 100        | 100            |

Notes: `LIKE_PATTERN_LENGTH` is 80 because escaping can double a
32-character search (section 6.3). `EXPR_DEPTH` starts at 10; if the
compiled WHERE fails to prepare at 10 in M1, raise it to the smallest
passing value and record that value in CLAUDE.md.

### 7.5 Authorizer: allow-list, `Deny` not `Ignore`

The authorizer runs during `sqlite3_prepare`; `SQLITE_DENY` fails the
statement, `SQLITE_IGNORE` on `SQLITE_READ` silently substitutes NULL
([sqlite3_set_authorizer][sq-auth]). Silent NULLs would turn a compiler
bug into wrong answers instead of an error, so the read rail returns
`Deny` for everything outside the allow-list. rusqlite exposes
`AuthContext { action, database_name, accessor }` and `Authorization::
{Allow, Ignore, Deny}` (`#[non_exhaustive]`) ([rusq-hooks][rusq-hooks]).

```rust
use rusqlite::hooks::{AuthAction, AuthContext, Authorization};

const TABLES: [&str; 4] = ["colors", "links", "qr_codes", "voats"];
const FUNCS: [&str; 3] = ["coalesce", "sum", "like"];

pub fn read_rail_authorizer(ctx: AuthContext<'_>) -> Authorization {
    match ctx.action {
        AuthAction::Select => Authorization::Allow,
        AuthAction::Read { table_name, column_name } => {
            if TABLES.contains(&table_name)
                && column_allowed(table_name, column_name)
            {
                Authorization::Allow
            } else {
                Authorization::Deny
            }
        }
        AuthAction::Function { function_name } => {
            if FUNCS.contains(&function_name.to_ascii_lowercase()
                .as_str())
            {
                Authorization::Allow
            } else {
                Authorization::Deny
            }
        }
        _ => Authorization::Deny,
    }
}
```

`column_allowed` is a static table of exactly the columns the three
templates read; it is the enumerated set of columns the agent can ever
see (section 9.5). The function list is derived in M1 by a test that
records authorizer callbacks while preparing the templates; if the
`LIKE` operator or `COALESCE` does not surface as `Function`, the list
shrinks accordingly. The authorizer stays installed for the connection's
lifetime because a statement may be re-prepared after a schema change
([sq-auth][sq-auth]).

### 7.6 Writer rail: CLI only, never reachable from MCP

The writer is a CLI mode of the same binary (`ecp seed`, `ecp link add`,
`ecp qr add`, `ecp vote`, `ecp qr verify`; open decision (d)). It opens
with `SQLITE_OPEN_READ_WRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_NO_MUTEX
| SQLITE_OPEN_EXRESCODE`, sets `PRAGMA foreign_keys = ON` and verifies it
(7.2), sets DEFENSIVE and `trusted_schema` off, runs migrations keyed by
`PRAGMA user_version` `[D]`, and wraps every seed in one transaction.
The `serve` mode constructs no writer connection; the writer module's
entry point requires a token type only the CLI module can construct
`[D]`.

Seeding `colors` `[D]`: exactly the 216 web-safe cube colours. Channel
levels are {0, 51, 102, 153, 204, 255}; `cube_index = 36*ri + 6*gi + bi`
for level indices ri, gi, bi in 0..=5; `hex` is upper-case `#RRGGBB`.
`color_family` is assigned deterministically: if r = g = b then `gray`;
otherwise by hue sector of the RGB hue angle, red [330, 30), yellow
[30, 90), green [90, 150), cyan [150, 210), blue [210, 270), magenta
[270, 330). The seeder is idempotent (`INSERT OR IGNORE` on `hex`).

Seeding `links`, `qr_codes`, `voats` `[D]`: from a JSON-lines file given
on the command line; `payload_url` MUST be an absolute `http` or `https`
URL of 1..=2048 characters and is stored verbatim; the server treats it
as untrusted regardless. Votes are rows of `color_id` and `-1`/`1`.

### 7.7 QR generation

`qrcodegen` 1.8.0 (2022-04-17) has no dependencies, "Supports encoding
all 40 versions (sizes) and all 4 error correction levels", and outputs
raw modules; SVG rendering is a short user function
([crates.io qrcodegen][qrcodegen]). Mapping `[D]`:

| DB `error_correction_level` | `qrcodegen::QrCodeEcc` |
|-----------------------------|------------------------|
| L                           | Low                    |
| M                           | Medium                 |
| Q                           | Quartile               |
| H                           | High                   |

`ecp qr add --link <id> --color <id> --ec M --format SVG`: encode
`payload_url` with `QrCode::encode_text`, render an SVG whose dark
modules are filled with the colour's `hex` on a white background with a
4-module quiet zone `[D]`, write `qr_<id>.svg` under the configured
storage directory, and store the relative path. Row insert and file
write happen in that order inside one transaction; a file-write failure
rolls back and removes any partial file `[D]`. PNG output is behind the
`png-output` feature using `png` 0.18.1 (bitflags, crc32fast, fdeflate,
flate2, miniz_oxide) with a two-entry palette `[D]`; the `image` crate is
avoided because its defaults pull `rayon` and a codec stack
([crates.io png][png], [crates.io image][image]). `verified_scan` is 0
at creation and set to 1 by `ecp qr verify <id>` after a manual scan
`[D]`. The MCP process never opens `file_path`; it returns the string.

## 8. Hardware interlock: S / S-bar as a complementary two-channel input

### 8.1 The invariant, corrected

Three statements, one per physical layer:

- Logic (antivalence): S xor S-bar = 1 at all times outside a transition
  window shorter than the skew; valid codewords {(0,1), (1,0)}; fault
  codewords {(0,0), (1,1)}; a fault is (S xor S-bar = 0) persisting
  longer than the discrepancy time t_disc. This is Rockwell's
  "Complementary" input type ("active state when Channel A is 1 and
  Channel B is 0", inconsistent states A=0/B=0 and A=1/B=1) and Siemens'
  "1oo2 evaluation, non-equivalent" ([Rockwell DCS][rockwell],
  [Siemens F-DI manual][siemens]).
- Voltage: V_S + V_S-bar = 2 x V_CM = constant. CAN is the standing
  counter-example to "sum = 0": recessive CANH = CANL = 2.5 V, dominant
  3.5 V / 1.5 V, so the sum is about 5 V in both states ([Microchip
  AN228][an228]).
- Current: I_S + I_S-bar = 0 along a balanced, terminated pair ("equal
  but opposite currents, called oddmode signals") is what cancels the
  far field ([Fairchild AN-5020][an5020]).

"S + S-bar = 0" is wrong for logic levels and for voltages; the drafts'
`validate_interlock` (fault when `line_a == line_b`) was already the xor
rule in code. Also note that a differential receiver is the wrong front
end for an equal-state detector: at zero differential input a conventional
receiver outputs "random output states" and a failsafe-biased one outputs
a confidently valid level by design ([TI SLLA272D failsafe][ti-fs]). The
interlock therefore uses two single-ended inputs and a comparator gate.

### 8.2 Three things the drafts conflated

1. Differential signalling (RS-422/485, LVDS, CAN): a physical-layer
   technique that buys common-mode noise rejection and reduced
   differential-mode radiation; the pair carries one bit and provides no
   galvanic isolation ([TI RS-485 design guide][ti-485], [TI SLLA272D
   grounding][ti-iso]).
2. Dual-rail precharge logic (WDDL, SABL, MDPL): a gate-level logic style
   inside the die where every signal is two rails, precharged every
   cycle, capacitance-matched, as a DPA countermeasure ([Tiri &
   Verbauwhede, DATE 2004][wddl04], [Popp & Mangard, CHES 2005][mdpl]).
3. Two-channel antivalent safety inputs with discrepancy monitoring: the
   ISO 13849-1 / IEC 62061 practice of comparing two channels and
   latching a fault when they disagree (equivalent) or agree (antivalent)
   for longer than a configured time ([Siemens][siemens],
   [Rockwell][rockwell], [IFA Report 2/2017e][ifa]).

Only (3) is the lineage of "fault when S == S-bar". The spec uses its
vocabulary and drops "dual-rail" and "balanced differential" except where
the transmission-line sense is meant.

### 8.3 Verdicts on the drafts' trade-off table

| # | Draft claim                           | Verdict      |
|---|---------------------------------------|--------------|
| 1 | E_net ~ 0 far-field cancellation      | Overstated   |
| 2 | Defeats DPA/DEMA like WDDL/DPL        | False        |
| 3 | Isolates a compromised host bridge    | False        |
| 4 | Unmaskable hardware reset within ns   | Conditional  |
| 5 | Invariant S + S-bar = 0               | Wrong        |
| 6 | ~2.0x to 2.3x silicon area            | Unsupported  |

1. Differential-mode field scales as f^2 x L x s x I / r and "the fields
   from the two conductors subtract, producing a small net radiated
   electric field", but common-mode current from imbalance "usually
   dominates"; differential-mode radiation "is rarely, if ever, the
   dominant source" ([MSU EMRG module 9][msu],
   [Clemson CVEL-13-052][clemson]). Vendor notes describe the
   cancellation only qualitatively ([TI SLLA422][slla422],
   [AN-5020][an5020]). A static enable line switching a few times a day
   has near-DC spectral content; the box's EM signature comes from the
   SoC, DRAM and regulators, which the pair does not touch.
2. WDDL/MDPL protect because every internal datapath node is dual-rail,
   precharged each cycle and load-matched; the prototype AES cost 245K
   versus 79K gates, 85.5 MHz versus 330 MHz, and still disclosed 11 of
   16 key bytes after a mean of 255,391 measurements, with 5 undisclosed
   at 1,500,000 ([Tiri et al., CHES 2005][wddl05]); early
   propagation leaks data-dependent timing ([Suzuki & Saeki, CHES
   2006][suzuki]). A complementary pair on two pins gives the CPU core,
   caches, DRAM and the SQLite/LLM arithmetic none of this. And a line
   that sits at (1,0) for hours has no switching activity to balance.
3. The pair carries one bit. A compromised host drives a valid (1,0)
   indefinitely; the pair cannot distinguish a healthy host from a
   malicious host asserting healthy. It offers no galvanic isolation;
   that needs digital isolators plus isolated DC/DC, which tolerate
   ground potential differences "up to several kilovolts"
   ([TI SLLA272D grounding][ti-iso]).
4. True only for the first rung of the ladder in 8.6: a discrete
   XOR/XNOR gate driving nRESET or a power-enable (8-25 ns), a static or
   filtered pair, and a latch. Any MCU path is 12-16 cycles plus handler
   code; any Linux path is microseconds to milliseconds; and any
   discrepancy window moves the honest figure into the 5 ms-3 s band
   used in safety practice ([SN74HC86][hc86], [ARM interrupt
   latency][arm-lat], [Rockwell][rockwell]).
5. Section 8.1.
6. The WDDL literature reports area factors "between a factor 3.2 and
   3.6" (Kasumi 7,304 to 26,549 gates; DES 1,493 to 4,810; AES 13,241 to
   44,827), 3.1x on the CHES 2005 die (0.79 to 2.45 mm^2), 6x on FPGA;
   MDPL 4.54x ([wddl04][wddl04], [wddl05][wddl05], [mdpl][mdpl]). No
   source gives 2.0-2.3x. For an I/O pair silicon area is the wrong unit:
   the cost is one extra wire, one gate package, two resistors, a latch
   and a supervisor.

What the pair honestly buys: detection of a stuck-at, wire-to-wire
short, or open interlock cable (with biasing), earning diagnostic
coverage 90% for cross-monitoring without a dynamic test and 99% with
test pulses that also expose shorts to supply and cross-circuits
([IRSST/Becker, ISO 13849-1 Annex E][irsst], [Lenze AKB][lenze]); a
hardware-enforced, latched reset path with a defined discrepancy time and
reset procedure; eligibility, with a diverse second evaluation channel
and at least 65 of 100 CCF points, for Cat 3 / Cat 4 architectures up to
PL e ([IFA][ifa], [Pilz PNOZ s3][pilz-s3], [Siemens][siemens]). v1 has no
test pulses and claims DC 90%, not 99%.

### 8.4 Vocabulary adopted (ISO 13849-1 lineage)

- Complementary / antivalent / non-equivalent two-channel input (1oo2).
- Discrepancy time t_disc: Siemens F-DI configurable 5 ms to 30 s;
  Rockwell DCS 5 to 3000 ms (examples use 250 ms); Dold UG6960 fixed 3 s
  for e-stop, gate and mat, 1 s for light curtains, 0.5 s for two-hand
  control; Pilz PNOZ s3 simultaneity infinite ([siemens][siemens],
  [rockwell][rockwell], [Dold UG6960][dold], [pilz-s3][pilz-s3]).
- Latched fault with functional test and manual reset: Rockwell fault
  codes 16#4000/16#4001 require "Check wiring, perform a functional test
  (put A and B in a safe state), reset the fault"; manual restart needs
  a reset OFF-to-ON transition and ISO 13849-1 requires reset on a
  falling edge ([rockwell][rockwell]); Pilz s6 stays off until both
  elements are released and re-operated ([Pilz PNOZ s6][pilz-s6]).
- Cross-circuit detection by test pulses: Siemens briefly "switches off
  the sensor supply"; Pilz applies "specific pulses ... via the test
  pulse outputs" ([siemens][siemens], [Pilz lexicon][pilz-lex]). Not in
  v1.
- Diagnostic coverage and CCF as in 8.3; CCF points: separation 15,
  diversity 20, design 15, well-tried 5, FMEA 5, competence 5, EMC 25,
  other 10 ([irsst][irsst]). Routing S and S-bar in one ribbon with a
  shared supply earns few separation points; the hardware spec should
  route them apart.

### 8.5 The circuit

Host side `[D]`:

- One host GPIO drives the ENABLE bit through two open-drain drivers: S
  directly, S-bar through an inverter. Skew between the two lines is then
  gate delay plus cable mismatch (nanoseconds), not software timing.
  Open-drain drivers mean an unpowered or disconnected host releases
  both lines; with device pull-ups that reads (1,1) and faults. The
  alternative, two independently driven channels, scores more CCF
  diversity points but reintroduces software skew and is open decision
  (f).

Device side `[D]`, with sourced figures where they exist:

1. Two single-ended inputs with pull-ups (external resistors; the SoC's
   internal bias is requested as well but its availability "when the
   controller does not support bias configuration" is unverified).
2. Comparator: SN74HC266 open-drain XNOR, typical tpd 8 ns at 5 V
   ([TI SN74HC266][hc266]), or SN74HC86 XOR, 12 ns typical / 20 ns max
   at 4.5 V and 25 C, 25 ns over temperature ([TI SN74HC86][hc86]). With
   the XNOR's open-drain output pulled up through an RC network, the
   node is held low while the lines differ and charges toward the
   threshold when they agree; the RC time constant t_filter (`[D]`
   100 us) swallows transition skew and EMI glitches and is the first
   deliberate delay in the ladder.
3. A Schmitt-trigger inverter squares the filtered node; an SR latch
   captures the fault; the latch output drives the SoC nRESET or a
   load-switch power-enable (open decision (b)). The latch clears only
   on a manual reset input; auto-release would let an intermittent fault
   flap the runtime.
4. The raw S, S-bar and the latched FAULT line also go to three GPIO
   inputs for observation.
5. External watchdog with its own clock: "if properly configured, it
   cannot be bypassed or disabled by runaway code", unlike internal
   watchdogs that "Almost all can be disabled by software"; its reset
   output can also reset other ICs and assert on under-voltage
   ([ADI, internal vs external watchdogs][adi-wdt]). The runtime kicks
   it from the main loop only while the interlock reader thread is
   alive `[D]`; its timeout is per the chosen part's datasheet
   (unspecified here).
6. No galvanic isolation in v1; if host and device grounds can differ
   beyond the receiver's range, add digital isolators and an isolated
   supply ([ti-iso][ti-iso]).

Linux-side reader `[D]`, using gpiocdev 0.8.0 (2025-11-19), the pure-Rust
GPIO character-device uAPI v2 library ("does not use the slower and
obsoleted sysfs GPIO API") ([crates.io gpiocdev][gpiocdev],
[gpiocdev 0.8.0][gpiocdev-meta]):

```rust
use std::time::Duration;
use gpiocdev::line::{Bias, EdgeDetection, EventClock};
use gpiocdev::request::Request;

let req = Request::builder()
    .on_chip("/dev/gpiochip0")
    .with_consumer("ecp-interlock")
    .with_lines(&[S_OFFSET, SBAR_OFFSET, FAULT_OFFSET])
    .as_input()
    .with_bias(Bias::PullUp)
    .with_edge_detection(EdgeDetection::BothEdges)
    .with_debounce_period(Duration::from_millis(5))
    .with_event_clock(EventClock::Monotonic)
    .request()?;
```

Builder names are from the crate source (`with_bias`,
`with_debounce_period`, `with_edge_detection`, `with_event_clock`,
`Request::values`, `edge_events`, `wait_edge_event`) ([gpiocdev
builder.rs][gpiocdev-src]). One request covering all lines lets
`req.values()` read them atomically in one ioctl. The reader thread:

- samples `values()` every 10 ms `[D]` and also drains edge events,
  recording `timestamp_ns`, `line_offset` and `seqno`;
- applies t_disc (`[D]` default 50 ms, configurable 5 ms-3 s, matching
  the safety-practice band): equal levels shorter than t_disc are
  ignored; equal levels at or beyond t_disc set the software FAULT latch;
- publishes an atomic snapshot {ENABLED, DISABLED, FAULT, INIT,
  BYPASSED} that the serving loop reads before each `tools/call`;
- clears FAULT only by the procedure in 3.3: observe DISABLED for at
  least t_disc, then `ecp interlock reset` from the CLI. The hardware
  latch has its own manual reset.

Behaviour of `tools/call` by state: ENABLED serves; DISABLED returns
`interlock_disabled`; FAULT and INIT return `interlock_fault`; BYPASSED
(`serve --interlock none`, developer boxes without GPIO) serves with
`interlock_state: "bypassed"` in every result and a stderr warning at
startup `[D]`; `serve --interlock sim` uses the scripted backend for
tests.

### 8.6 The honest timing ladder

| Rung                            | Figure                            |
|---------------------------------|-----------------------------------|
| Discrete XOR/XNOR gate          | 8-25 ns                           |
| RC filter (design choice)       | t_filter, 100 us `[D]`            |
| Cortex-M exception entry        | 12-16 cycles before first instr.  |
| Linux kernel GPIO IRQ handler   | ~3.8-8.7 us average (2013 boards) |
| Linux userspace wake-up         | tens of us (PREEMPT_RT) to        |
|                                 | 50-500 us stock, ms outliers      |
| Software discrepancy window     | t_disc, 50 ms `[D]` (5 ms-3 s)   |
| Safety PLC/relay for comparison | 10-20 ms de-energisation          |

Sources: gate delays ([hc86][hc86], [hc266][hc266]); Cortex-M0/M0+/M3/M4
at 16/15/12/12 cycles with zero-wait-state memory, and only the NMI and
HardFault have fixed priorities ([ARM][arm-lat], [NXP NVIC
training][nxp-nmi]); kernel-space loopback test 3,770 ns on a 700 MHz
Pi, 4,957 ns on a 1 GHz BeagleBone Black, 8,699 ns at 500 MHz
([gkaindl latency test][gkaindl]); userspace `poll()` on a BeagleBone
Black min 81 / avg 84 / max 118 us on a standard kernel
([lore.kernel.org thread][lore]); edge intervals varying "as much as 15
mSec" ([BeagleBoard forum][bbb]); stock kernel "typically 50-500 us",
"below 50 us" with PREEMPT_RT ([Obuda PREEMPT_RT tutorial][obuda]);
Pilz PNOZ s3 de-energisation typ 10 ms / max 20 ms ([pilz-s3][pilz-s3]).

Normative statement: the runtime records kernel edge timestamps and
reacts in userspace; it is an observer and logger. The protective element
is the hardware path (comparator, filter, latch, watchdog). "Unmaskable"
applies only to the external reset/power path and the external watchdog;
a Cortex-M NMI is unmaskable at run time but still software; a Linux
handler is neither ([nxp-nmi][nxp-nmi], [adi-wdt][adi-wdt]).

### 8.7 What the interlock does not protect against

- A compromised host (or a stuck host GPIO) presenting a valid (1,0)
  forever. The pair detects wiring and driver faults, not well-formed
  malice.
- Voltage or clock glitching, EMFI or laser faults on the SoC: those act
  on the silicon's own supply, clock and logic. Equipment under $500
  suffices; instruction skip is "the most popular" fault model; a $5
  glitcher in a 2.5 us window at power-on reopened a locked nRF52 debug
  port, with no I/O wiring involved ([Yuce et al.][yuce],
  [LimitedResults, Black Hat EU 2020][nrf52]).
- DPA / CPA / CEMA: statistical key recovery against cryptographic
  computation ([Kocher et al., JCEN 2011][kocher]). The box holds no
  cryptographic secrets unless a later version adds signing or TLS, and
  then the countermeasure lives in that crypto implementation, not on
  the I/O pair. EM extraction of neural-network structure and weights has
  been shown on a Cortex-M3 ([Batina et al., CSI NN][csinn]);
  extrapolation to an application processor running a multi-GB model is
  open.
- Debug ports, storage removal, cold-boot DRAM remanence (keys recovered
  from DRAM after seconds to minutes) ([Halderman et al.][coldboot]).

Realistic physical-threat list for this box, with the owning mitigation:
SWD/JTAG/UART console access (debug lock-out, console disabled in
production); SD card or eMMC removal (encrypted storage, keys off DRAM if
ever present); supply glitching (external brown-out supervisor; the
watchdog); cable tampering on the interlock (this section); theft of the
model weights or database (storage encryption, physical enclosure). None
of these is affected by the complementary pair except the fourth.

## 9. Security model

### 9.1 Verdict on "immunity"

The claim holds narrowly and fails broadly. Narrowly: with closed enums
mapped by exhaustive match, typed re-validation and parameter binding,
the model cannot author SQL syntax, so SQL injection (CWE-89) through the
plan is eliminated at construction time. OWASP LLM05 names
"LLM-generated SQL queries ... executed without proper parameterization"
as the canonical failure and prescribes "parameterized queries or
prepared statements for all database operations involving LLM output"
([OWASP LLM05:2025][owasp-05]); Pedro et al. found "Query checking is a
complete solution against RD.1 and RI.2 attacks when SELECT query
filters are used", and ECP is stronger than query checking because there
is no model-authored SQL to check ([Pedro et al., ICSE 2025][pedro]).
Every public text-to-SQL CVE has the same root cause of executing model
output verbatim: LangChain SQLDatabaseChain CVE-2023-36189 (CVSS 7.5),
LlamaIndex CVE-2024-23751 (CVSS 9.8, "Drop the Students table"),
Vanna.AI CVE-2024-5565 ([CIRCL CVE-2023-36189][cve-lc], [CIRCL
CVE-2024-23751][cve-li], [JFrog][vanna]).

Broadly: prompt injection is contained, not prevented. OWASP LLM01 says
"it is unclear if there are fool-proof methods of prevention"
([OWASP LLM Top 10 2025][owasp-pdf]); Greshake et al. that "it is
currently hard to imagine a foolproof solution" ([Greshake et al., full
text][greshake-full]); adaptive attacks bypassed 12 published defenses at
over 90% success ([Willison, 2025-11-02][rule2]). Vanna shows the shape
that survives a valid read-only `SELECT`: the payload rode inside a
string literal to the next interpreter ([vanna][vanna]). Required wording
everywhere in the repository: "eliminates SQL injection from model output
by construction; contains, but does not prevent, prompt injection;
residual risks are enumerated in section 9.4".

### 9.2 Threat register

Each entry: threat; where it lands; control; status.

T1 SQL injection via plan values or enums. Device. Exhaustive match,
bound parameters, `deny_unknown_fields`, type-state compiler (section
6); authorizer, limits, DEFENSIVE, `query_only` as containment for a
compiler bug (section 7). Eliminated by construction; containment
tested.

T2 Direct prompt injection steering the planner (Pedro RI.1: answer
manipulation, 60% success against an SQL agent) ([pedro][pedro]).
Device/host. Blast radius bounded to a legal read-only plan over four
tables with at most 100 rows; `plan_used` echoed and logged so steering
is visible. Residual: wrong, empty or selectively omitted answers.

T3 Second-order injection: database text (`payload_url`, file paths)
carrying instructions into Claude Code. Host. Typed `structuredContent`,
`trust` label, sanitisation, no link or image rendering, size caps
(section 9.6); Claude Code's own approval prompts. Residual: this is the
Supabase / GitHub MCP pattern (9.3) and cannot be removed by the device.

T4 Egress from the "loopback" inference path. Device. Section 5.5
refusals, `OLLAMA_NO_CLOUD`, process firewall. Residual: paths 3-4
need the firewall; the Codex proxy's behaviour under `OLLAMA_NO_CLOUD`
is unverified.

T5 Ollama as an unauthenticated local service with a CVE history:
Probllama CVE-2024-37032 (path traversal to RCE via `/api/pull`, fixed
0.1.34), CVE-2024-39719/39720/39721/39722 (file disclosure, segfault,
infinite loop via `/api/create` and `/api/push`), CVE-2025-15514
(unauthenticated runner crash via `/api/chat` image data, affecting
0.11.5-rc0 through 0.13.5, published 2026-01-12; details rest on an
AI-generated vendor page) ([Wiz][wiz], [Oligo][oligo],
[SentinelOne][s1]). "Binding to 127.0.0.1 is not an authentication
boundary" ([MCP local server security][mcp-local]). Controls: the
runtime never calls management endpoints; digest pinning; the daemon
version is recorded per call; patch tracking in the SBOM; a daemon
outage fails closed (`inference_unavailable`, never a fallback to raw
text-to-SQL).

T6 Schema as attack surface (constrained-decoding attacks). Device. The
plan schema is static and developer-owned, never derived from user text
or tool descriptions; hashed per call ([cda][cda]). Residual: none if
the invariant holds; a test asserts the schema bytes are a compile-time
constant.

T7 Availability: pathological `link_search`, repeated calls, large
results, slow models. Device. LIKE escaping and length caps, limits,
progress handler, heap limit, rate limit (`[D]` token bucket, 1 call/s
sustained, burst 5), result caps, timeouts. The MCP spec makes "Rate
limit tool invocations" a server MUST ([MCP tools][mcp-tools]).

T8 Sensitive-data exposure (LLM02). Device. The exposed column set is
exactly `column_allowed` (7.5): `colors.hex`, `colors.color_family`,
`colors.id`, `links.id`, `links.payload_url`, `qr_codes.id`,
`qr_codes.file_path`, `qr_codes.link_id`, `qr_codes.color_id`,
`qr_codes.created_at`, `voats.color_id`, `voats.vote_type`. Anything
added later must be added here consciously.

T9 Tool poisoning, rug pulls, cross-server shadowing. Host. The tool
list is static, short, deterministic and undeclared for `listChanged`;
descriptions contain no instructions; a hash of the tool definitions is
published in the README for pinning clients. Shadowing by other installed
servers cannot be defended from inside ECP ([Invariant Labs][invariant],
[CSA whitepaper][csa-tp], [mcp-local][mcp-local]).

T10 Host compromise through text reaching Claude Code: CVE-2025-66032 in
`claude-code-action` (an attacker's GitHub App issue carried a prompt
injection; `cat` ran without approval, read `/proc/self/environ`, and
exchanged OIDC variables for a privileged token; CVSS 4.0 7.8; disclosed
2026-06-01; fixed in `claude-code-action` v1.0.94 and
`@anthropic-ai/claude-code` v1.0.93) and forged-confirmation
"Lies-in-the-Loop" dialogs ([CSA research note][csa-cc], [The Hacker
News][thn]). Out of ECP's control; the recommendation from the CVE
write-up applies to the host: network egress filtering "removes one of
the more reliable exfiltration paths even when injection succeeds".

T11 Compiler or hardening regression. Device. Tests in M2 and M6 assert
every template is a constant with only `?N` markers, that the authorizer
denies PRAGMA/ATTACH/CREATE/INSERT, and that the read connection reports
`SQLITE_READONLY` on write attempts.

T12 Database file written by another domain. Device. Only the CLI writes,
as the same user; `quick_check` at open, `trusted_schema` off, triggers
and views disabled anyway ([sq-sec][sq-sec]).

### 9.3 Lethal trifecta and Rule of Two

Willison's trifecta: "Access to your private data", "Exposure to
untrusted content", "The ability to externally communicate"; combine all
three and "an attacker can easily trick it into accessing your private
data and sending it to that attacker" ([Willison, 2025-06-16][trifecta]).
Meta's Rule of Two: no more than two of untrustworthy inputs, access to
sensitive systems, changing state or communicating externally
([rule2][rule2]).

The ECP device alone has legs one and two (the database; the prompt and
the rows) and lacks the third: read-only rail, no listener, no egress.
It is a Rule-of-Two-compliant component. The system is not: results flow
into Claude Code, which has shell, files and network, so the trifecta is
reassembled at the host. The precedent is exact: with the Supabase MCP a
Cursor agent read a planted support ticket, pulled the private
`integration_tokens` table and wrote it where the attacker could read
it; "If you configure their MCP as read-only you remove one leg of the
trifecta", yet the residual risk was called "enormous" ([Willison,
2025-07-06][supabase]). GhostSplice (2026) split a refused request across
a tool description, a tool result and a logging call and raised
compliance from 42% to 82% across 11 API models, with Claude Code among
the clients tested; its authors' advice is to "treat server output as
data, not instructions, and never pass one tool's output unchanged into
another tool's arguments" ([GhostSplice summary][ghostsplice]). The
spec therefore states the remaining leg plainly: it is the host, and the
device can only weaken it.

### 9.4 Residual risks (normative list, kept in the README)

1. Second-order prompt injection through returned rows (T3): host layer.
2. Plan steering / answer manipulation (T2): integrity; detectable only
   through `plan_used` in the audit log.
3. Availability (T7): bounded, not eliminated.
4. Sensitive-data exposure of the enumerated columns (T8).
5. Ollama service and model supply chain (T5).
6. Structured-output enforcement gaps: unsupported patterns degrade
   silently; thinking/format bugs are model-and-version specific; Rust
   re-validation is the real boundary (section 5.7).
7. Schema-as-attack-surface if the static-schema invariant is ever
   broken (T6).
8. MCP ecosystem risks outside ECP: co-installed servers, host
   vulnerabilities (T9, T10). Keep the server roster small; prefer
   clients that pin tool definitions ([mcp-local][mcp-local]).
9. Compiler defects (T11).
10. Database file integrity (T12).
11. Audit gaps: without `plan_used`, model digest, schema hash and prompt
    hash per call, steering is undetectable after the fact (9.7).
12. Interlock limits: a compromised host, core glitching, debug ports,
    storage removal, cold boot (section 8.7).

### 9.5 MCP local-server rules applied

- stdio only: local servers "SHOULD ... Use the `stdio` transport to
  limit access to just the MCP client" ([mcp-sec][mcp-sec]); "The stdio
  transport is not a sandbox" and "the client and a stdio server share
  one trust domain" ([mcp-local][mcp-local]).
- Static tool list, deterministic order, honest annotations
  (`readOnlyHint: true` on the reads; it is documentation for the host,
  not a control).
- `outputSchema` plus `structuredContent` on every tool.
- Logs on stderr only; "Log to `stderr` for stdio transports" is the
  migration path for the deprecated logging capability
  ([deprecated registry][mcp-dep]).
- Servers MUST validate inputs, implement access controls, rate limit,
  sanitize outputs ([mcp-tools][mcp-tools]).
- Credentials come from the environment, never from the protocol:
  stdio servers "SHOULD NOT" follow the HTTP authorization spec
  ([mcp-base][mcp-base]). ECP needs none.
- `clientInfo` is self-reported and "SHOULD NOT" drive security
  decisions ([mcp-base][mcp-base]); it is logged, not trusted.
- Loopback is not authentication: the Ollama endpoint is reachable by
  any local process and, through a browser, by websites
  ([mcp-local][mcp-local]); Ollama's own `Host` check is its DNS-
  rebinding guard, not an auth layer ([ol-routes][ol-routes]).
- Deployment: run the runtime and the Ollama daemon in one network
  namespace with no external interface; for containers "this is one
  flag (`--network=none`)" ([mcp-local][mcp-local]); equivalent systemd
  directives are unverified here and are an operator task.

### 9.6 Returned text is untrusted data

Every string that originates in the database is labelled and
neutralised before it leaves the device (an inference from OWASP LLM01
measure (6) "Segregate and identify external content", the MCP
`structuredContent` design, and the incident record; no source
prescribes a delimiter syntax):

- Rows are returned only inside `structuredContent` whose schema
  describes each string as opaque data; the text block is the JSON
  serialisation only, with no prose that could read as a system message.
- Control characters (U+0000-U+001F, U+007F), zero-width characters and
  bidirectional override code points are stripped; text is normalised to
  NFC; strings are truncated per section 4.10.
- `payload_url` is a plain string field; never a Markdown link or an
  image. GrafanaGhost exfiltrated enterprise data through a rendered
  external image URL ([OWASP GenAI exploit round-up Q1 2026][owasp-q1]).
- Top-level `source` and `trust` fields are constants (section 6.5).
- README instruction to users: ECP output is data; never pipe it
  verbatim into another tool's arguments ([ghostsplice][ghostsplice]).
- Prompt-wrapping banners are not counted as a mitigation; they degrade
  rather than prevent injection ([owasp-pdf][owasp-pdf], [rule2][rule2]).

### 9.7 Audit log

Append-only JSON lines on the device (`[D]` path from config, one line
per `tools/call`, each line carrying the SHA-256 of the previous line so
the file is a hash chain), satisfying LLM08's "detailed immutable logs"
wording and the MCP guide's "which server, which tool, when"
reconstruction goal ([owasp-pdf][owasp-pdf], [mcp-local][mcp-local]).
Fields `[D]`:

`audit_id` (monotonic), `ts` (RFC 3339 UTC), `request_id`, `tool`,
`client_info` (self-reported, untrusted), `prompt_sha256` (the prompt
itself is not stored), `model_id`, `ollama_version`,
`schema_sha256`, `system_prompt_sha256`, `plan_used`, `clamped` (fields
altered by validation), `plan_rejected_reason`, `sql_template_id`,
`param_sha256` (per bound parameter), `row_count`, `bytes_returned`,
`truncated`, `elapsed_ms`, `inference_ns` (`total_duration`,
`load_duration`, `eval_count`), `progress_fired`, `interlock_state`,
`result_kind` (ok or the `isError` kind), `prev_sha256`.

Nothing from the audit log is ever returned through MCP except
`audit_id`. Logs never go to stdout.

## 10. Crate manifest and repository layout

### 10.1 Toolchain

Current stable Rust is 1.99.1 (2026-10-15); edition 2024 has been stable
since 1.85.0 (2025-02-20) ([Rust release index][rust-rel]). The workspace
pins `rust-toolchain.toml` to `channel = "1.99.1"` with both musl targets,
sets `edition = "2024"`, and `rust-version = "1.89"`, the ceiling set by
rusqlite 0.41.1 (MSRV 1.89.0) ([crates.io rusqlite][rusqlite]). Other
MSRVs are lower: libsqlite3-sys 1.88.0 ([sys-crate][sys-crate]), ureq
1.85 ([ureq-meta][ureq-meta]), schemars 1.74 ([schemars][schemars]),
serde_json 1.71 ([sj][sj]), png 1.73 ([png][png]), gpiocdev 1.68
([gpiocdev-meta][gpiocdev-meta]), minreq 1.63 ([minreq][minreq]).

### 10.2 Pinned manifest (versions and dates verified 2026-10-29)

```toml
[workspace]
members = ["ecp-runtime", "ecp-bridge"]

[workspace.package]
edition = "2024"
rust-version = "1.89"
license = "MIT OR Apache-2.0"

# ecp-runtime/Cargo.toml
[package]
name = "ecp-runtime"
version = "0.1.0"
edition.workspace = true
rust-version.workspace = true

[dependencies]
# SQLite 3.54.1 statically compiled; `hooks` for authorizer and
# progress_handler; `limits` for set_limit. Keep default `cache`.
rusqlite   = { version = "=0.41.1",
               features = ["bundled", "hooks", "limits"] }
serde      = { version = "=1.0.229", features = ["derive"] }
serde_json = { version = "=1.0.154", features = ["raw_value"] }
schemars   = { version = "=1.2.3" }
# Pure Rust, no TLS; the agent MUST be built with .proxy(None).
ureq       = { version = "=3.5.0", default-features = false }
qrcodegen  = { version = "=1.8.0" }
png        = { version = "=0.18.1", optional = true }
gpiocdev   = { version = "=0.8.0" }

[features]
default    = []
png-output = ["dep:png"]

[dev-dependencies]
insta      = "=1.49.0"
proptest   = "=1.12.0"
assert_cmd = "=2.2.2"
```

Version and date provenance: rusqlite 0.41.1 (2026-10-28) bundling
SQLite 3.54.1 via libsqlite3-sys 0.39.1 (2026-10-25) whose shipped
`sqlite3.h` defines `SQLITE_VERSION "3.54.1"` (the README still says
3.54.0; the header wins) ([rusqlite][rusqlite],
[libsqlite3-sys][sys-crate], [sqlite3.h][sys-h]); serde 1.0.229
(2026-07-18) and serde_json 1.0.154 (2026-10-11) ([serde][serde],
[serde_json][sj]); schemars 1.2.3 (2026-10-12) ([schemars][schemars]);
ureq 3.5.0 (2026-10-21), "forbids unsafe code", blocking I/O, chunked
and Content-Length bodies, per-phase timeouts ([ureq][ureq],
[ureq 3.5.0 metadata][ureq-meta]); qrcodegen 1.8.0 (2022-04-17)
([qrcodegen][qrcodegen]); png 0.18.1 (2026-02-14) ([png][png]);
gpiocdev 0.8.0 (2025-11-19) ([gpiocdev 0.8.0][gpiocdev-meta]); insta
1.49.0 (2026-10-03), proptest 1.12.0 (2026-10-10), assert_cmd 2.2.2
(2026-05-11) ([insta][insta], [proptest][proptest],
[assert_cmd][assert_cmd]).

Excluded on purpose: `rmcp` (official SDK, 3.8.0 on 2026-10-23, Apache-
2.0, MSRV 1.88; tokio is a non-optional dependency and a minimal stdio
server locks 83 packages) ([rmcp][rmcp]); `jsonrpc-core` (no release
since 2021-07-20) and `jsonrpsee` (async, HTTP/WebSocket centric)
([jsonrpc-core][jsonrpc-core], [jsonrpsee][jsonrpsee]); `jsonschema`
(section 6.1); `regex`; `image`; `fast_qr` with its `image` feature
(pulls `resvg`) ([crates.io fast_qr][fastqr]); `qrcode` 0.14.1 (last
release 2024-07-05; acceptable but not chosen) ([crates.io
qrcode][qrcode]); `gpio-cdev` (2023) and `rppal` (Pi-only); any
`tokio`/async runtime `[D]`; rusqlite `load_extension`, `bundled-full`,
`modern-full`, `vtab`, `functions`.

The bridge crate depends on nothing beyond `std` in v1 (section 4.8).
The exact transitive count is recorded at M0; the research estimate is
25-40 crates.

### 10.3 Repository layout

```
ecp/
  Cargo.toml  Cargo.lock  rust-toolchain.toml  deny.toml
  .cargo/config.toml         # [source.crates-io] replace-with vendored
  vendor/                    # cargo vendor --versioned-dirs (committed)
  SPEC.md                    # this document
  CLAUDE.md                  # Appendix A
  README.md                  # residual risks, tool-definition hash
  schema/ecp_query_plan.draft07.json   # snapshot of the wire schema
  ecp-runtime/src/
    main.rs                  # arg parsing: serve | seed | link | qr |
                             #   vote | interlock | check
    rpc/      envelope.rs codes.rs batch.rs io.rs
    mcp/      lifecycle.rs discover.rs meta.rs tools.rs call.rs
    plan/     model.rs schema.rs validate.rs prompt.rs
    sql/      compile.rs templates.rs like.rs
    db/       open_ro.rs open_rw.rs authorizer.rs limits.rs
              migrate.rs seed.rs
    infer/    client.rs egress.rs model_pin.rs
    interlock/ state.rs reader.rs gpio.rs sim.rs watchdog.rs
    qr/       encode.rs svg.rs png.rs
    cli/      seed.rs link.rs qr.rs vote.rs interlock.rs check.rs
    audit/    log.rs sanitize.rs
  ecp-runtime/tests/         # assert_cmd, proptest, insta snapshots
  ecp-bridge/src/main.rs     # stdio <-> UART relay
  hw/                        # schematic notes for section 8.5
  deploy/                    # unit files, stty wrapper, firewall notes
```

### 10.4 Build, vendor and verification commands

`cargo vendor` copies all dependencies into a directory and prints the
`.cargo/config.toml` stanza; `--locked` "Fails if the lock file is
missing or if dependency resolution would change it"; `--offline` stops
network use and "Running cargo fetch beforehand is recommended";
`--frozen` is both ([cargo-vendor man page][vendor]).

```sh
# once, online
cargo vendor --versioned-dirs vendor > .cargo/config.toml
git add vendor Cargo.lock .cargo/config.toml

# every build, offline
cargo build --release --locked --offline \
  --target x86_64-unknown-linux-musl
cargo zigbuild --release --locked --offline \
  --target aarch64-unknown-linux-musl
cargo test --locked --offline

# gates
cargo deny check          # licenses, bans, advisories, sources
cargo audit --no-fetch    # against a mirrored advisory DB
cargo vet                 # human audit records per crate version
```

Tool versions as of 2026-10-29: cargo-deny 0.20.2 (2026-07-09),
cargo-audit 0.22.2 (2026-06-05), cargo-vet 0.10.3 (2026-10-22),
cargo-zigbuild 0.24.0 (2026-10-21), cc 1.10.0 (2026-10-23)
([cargo-deny][deny], [cargo-audit][audit], [cargo-vet][vet],
[cargo-zigbuild][zigbuild], [cc][cc]). The `bundled` feature compiles
the SQLite amalgamation with the `cc` crate, so a C compiler for the
*target* triple is required; `cargo zigbuild` supplies one and honours
`CFLAGS`; `LIBSQLITE3_FLAGS` and `SQLITE_MAX_*` env vars are honoured by
the build script ([sys-build][sys-build], [zigbuild][zigbuild]). A test
build of `bundled` on `aarch64-unknown-linux-musl` with zigbuild was not
performed in the research (highly likely to work; unverified) and is an
M0 acceptance item. The `cargo audit` offline database workflow
(`--no-fetch`, mirrored DB) is unverified and is also M0.

## 11. Implementation plan for Claude Code

Milestones are ordered; each has acceptance tests that MUST pass before
the next begins. "Mock Ollama" is a `std::net::TcpListener` HTTP/1.1
server in the test tree that serves canned `/api/tags`, `/api/show`,
`/api/status`, `/api/version` and `/api/generate` bodies and records
every request, including the `Host` header and whether the body was
chunked.

### M0 Repository and vendoring

Do: workspace, toolchain pin, pinned manifest, `deny.toml`, vendoring,
`.cargo/config.toml`, CI script, `#![forbid(unsafe_code)]` on both
crates, `hw/` and `deploy/` stubs, README with the residual-risk list.

Accept: `cargo build --release --locked --offline` succeeds for
`x86_64-unknown-linux-musl` inside a container with no network;
`cargo zigbuild` succeeds for `aarch64-unknown-linux-musl` (or the
failure is documented as the first open issue); `file` reports the
binaries statically linked; `cargo deny check` passes; the transitive
crate count is written into README; `cargo audit --no-fetch` runs
against a mirrored database or the gap is recorded.

### M1 Database, CLI seeder, QR

Do: migrations, DDL of 7.1, writer bring-up (7.2, 7.6), read bring-up
(7.3-7.5), seeders, QR SVG (7.7), `ecp check` (runs `quick_check`,
`foreign_key_check`, prints limits and authorizer configuration).

Accept (in-memory and file databases): `PRAGMA foreign_keys` reads 1 on
the writer; inserting `'x'` into `colors.r` fails with
`SQLITE_CONSTRAINT_DATATYPE`; `BOOLEAN`/`DATETIME` never appear in the
DDL; deleting a referenced colour fails immediately (RESTRICT); deleting
a link cascades to its `qr_codes`; 216 colours with unique `hex` and
`cube_index`, 6 of them `gray`; `foreign_key_check` empty and
`integrity_check` `ok` after seeding; the read connection answers
`INSERT` with `SQLITE_READONLY`, and `PRAGMA writable_schema=ON`,
`ATTACH`, `CREATE TABLE`, `load_extension()` are denied by the
authorizer (`Deny`, an error, never a silent NULL); `quick_check`
failure refuses service; the three templates prepare under the 7.4
limits (record any `EXPR_DEPTH` adjustment); the authorizer callback
recording test fixes the function allow-list; a generated SVG has
`qr.size()` modules per side plus the quiet zone and well-formed XML.

### M2 Plan struct, schema, SQL compiler

Do: `plan/model.rs`, `plan/schema.rs` (draft07 emission + normalisation),
`plan/validate.rs`, `sql/templates.rs`, `sql/compile.rs`, `sql/like.rs`,
`plan/prompt.rs` (`PLANNER_PROMPT_V1`).

Accept: insta snapshot of the wire schema equals
`schema/ecp_query_plan.draft07.json`; assertions on the schema: no
`$ref`, all six keys `required`, `additionalProperties: false`, every
`pattern` anchored and within the supported subset, no `number` bounds,
no `default`; `deny_unknown_fields` rejects an extra key; a 40-digit
`min_votes` is `plan_invalid`, not a panic; proptest: for any
`EcpQueryPlan` (including invalid ones) either `validate()` fails with a
named field or the compiled statement prepares and runs on a seeded
in-memory database under the production authorizer and limits with
`row_count <= limit`; LIKE property of 6.3; a source test that no file
under `sql/` or `db/` contains `format!(` or string concatenation
producing SQL; insta snapshots of the three templates.

### M3 Ollama client with egress refusals

Do: `infer/client.rs` (ureq, `.proxy(None)`, literal `SocketAddr`,
timeouts, body cap), `infer/egress.rs`, `infer/model_pin.rs`, warm-up,
`ecp_list_models` and `ecp_select_model` logic.

Accept against mock Ollama: with `HTTP_PROXY`, `HTTPS_PROXY`,
`ALL_PROXY` and `OLLAMA_HOST=ollama.com` all set in the environment, the
request still arrives at the mock on 127.0.0.1 with `Host:
127.0.0.1:11434`; names `foo:cloud`, `foo:20b-cloud`, `foo:local:cloud`
are rejected before any request; a tags entry with `remote_host` is
excluded from `ecp_list_models`; `/api/status` with `cloud.disabled:
false` yields `cloud_not_disabled`; a generate response carrying
`remote_host` yields `egress_detected` and the plan is discarded;
`done_reason: "length"` yields one retry at `num_predict: 512` then
`plan_truncated`; a non-JSON `response` yields `plan_unparseable`; a
changed digest yields `model_digest_mismatch`; a chunked response body
decodes; a 2 MiB body is refused; `think` is sent only when
`capabilities` contains `thinking`; the request `model` ends in
`:local`; a mock that never answers trips the first-byte timeout as
`inference_timeout`. Live (opt-in, `ECP_LIVE_OLLAMA=1`, against the
pinned model and daemon version): the schema is accepted, null fields
come back as `null`, enum values are honoured, a negative `min_votes`
is accepted (negative integer bounds in the converter are unverified),
key order matches declaration order, `done_reason` is `stop`.

### M4 MCP stdio server, dual era

Do: `rpc/*`, `mcp/*`, `ecp_query` wired to M1-M3, output caps, rate
limit, signals, `serve --stdio`.

Accept with `assert_cmd` driving the real binary over stdin/stdout and
mock Ollama: a legacy script (`initialize` -> `notifications/initialized`
-> `ping` -> `tools/list` -> `tools/call` x3 -> stdin EOF) and a modern
script (`server/discover` -> `tools/list` -> `tools/call` with `_meta`)
both succeed and stdout contains only valid JSON lines; `server/discover`
sent first then `initialize` is answered per the branch rule; missing
`_meta.protocolVersion` -> `-32602`; version `1900-01-01` -> `-32022`
with `data.supported`; unknown method -> `-32601`; parse error ->
`-32700` with `id: null`; `jsonrpc: "1.0"` -> `-32600`; a 2 MiB line ->
`-32600`; a notification gets no reply; an empty batch -> one `-32600`;
`tools/list` is byte-identical across two runs and carries `ttlMs` and
`cacheScope` only in the modern script; every modern result has
`resultType: "complete"` and `serverInfo`; tool results carry both the
text block and `structuredContent` validating against `outputSchema`
(a test-only validator may be used in `dev-dependencies`); a 100-row
result with 2,048-character URLs is truncated under 40,000 characters
with `truncated: true`; the sixth call inside one second returns
`rate_limited`; `SIGINT` or `SIGTERM` exits within 100 ms with the
audit line flushed; the README documents the `claude mcp add` smoke test
and the expected `mcp__ecp__ecp_query` name.

### M5 Interlock reader and fault semantics

Do: `interlock/state.rs` (3.3), `interlock/sim.rs` (scripted
`LineSource`), `interlock/gpio.rs` (gpiocdev), `interlock/watchdog.rs`,
`ecp interlock reset`, `serve --interlock gpio|sim|none`.

Accept with the simulated backend: INIT -> ENABLED after valid levels for
t_disc; a (1,1) pulse shorter than t_disc is ignored; (0,0) or (1,1) for
t_disc or longer latches FAULT; valid levels afterwards do not clear it;
DISABLED for t_disc followed by `ecp interlock reset` returns to INIT;
`tools/call` returns `interlock_disabled` / `interlock_fault` with
protocol traffic still served; `--interlock none` stamps
`interlock_state: "bypassed"` and warns on stderr; watchdog kicks stop
within one period when the reader thread is killed; every edge is logged
with `timestamp_ns` and `seqno`. The gpiocdev backend compiles for both
targets and is exercised manually on hardware (checklist in `hw/`).

### M6 Hardening, audit log, supply-chain gates

Do: `audit/log.rs` (hash chain), `audit/sanitize.rs`, tool-definition
hash in README, deployment notes (network namespace, `stty` wrapper,
`OLLAMA_NO_CLOUD=1`, firewall), `cargo vet` records, adversarial pass.

Accept: the audit chain verifies end to end; a tampered line breaks it;
sanitisation strips control, zero-width and bidi characters and
normalises to NFC (table-driven tests); the adversarial suite (OWASP
LLM01 measure 7) covers steering prompts, wildcard abuse, integer
extremes, and payload URLs containing instruction text, and every case
yields either a bounded legal plan or a named `isError` kind; `cargo
deny`, `cargo vet`, `cargo audit --no-fetch` pass; the bridge relays a
10,000-line script bit-exactly over a pty pair.

### Things Claude Code MUST NOT do

- Build SQL with `format!`, `concat` at runtime, `+`, `push_str`, or any
  string interpolation of plan values. Templates are `&'static str`.
- Enable or read HTTP proxies; read `HTTP_PROXY`, `HTTPS_PROXY`,
  `ALL_PROXY`, `NO_PROXY` or `OLLAMA_HOST`; use a hostname for the
  inference endpoint.
- Use `line.contains(...)`, `starts_with`, or regexes to dispatch
  JSON-RPC; parse the envelope.
- Add any network listener (HTTP, WebSocket, TCP, Unix socket) to the
  runtime or the bridge.
- Change tool names, descriptions, schemas or order at runtime, or
  declare `listChanged`.
- Open a writable database connection from `serve`; call writer code
  from `serve`.
- Call `/api/pull`, `/api/push`, `/api/create`, `/api/copy`,
  `/api/delete`, `/api/web_search`, `/api/web_fetch`, `/v1/*`.
- Write anything but JSON-RPC messages to stdout; put logs on stdout.
- Enable `unbounded_depth`, rusqlite `load_extension`, `bundled-full`,
  `modern-full`, `vtab`, `functions`; add `tokio` or any async runtime;
  add `regex` for hex validation.
- Return `Authorization::Ignore` from the read-rail authorizer.
- Render URLs or file paths as Markdown links, images or HTML.
- Allocate JSON-RPC error codes in -32768..-32000.
- Spawn shells or commands from tool arguments; open `file_path`.
- Use `immutable=1` or any `file:` URI on the live database; rely on
  `SQLITE_DEFAULT_FOREIGN_KEYS` instead of the pragma readback.
- Fall back to raw text-to-SQL, a different endpoint, or a cloud model
  when the pinned local model is unavailable.
- Claim "immune to injection", "zero dependencies", "unmaskable
  nanosecond reset" or "DPA resistant" anywhere in the repository.

## 12. Open decisions

Each item names the options and the default this spec builds with until
the author rules.

(a) Inference endpoint pin. Default: the literal `127.0.0.1:11434`
Ollama endpoint, compile-time constant, no hostname, no proxy, no TLS,
with the section 5.5 refusals. Alternative: the author elsewhere runs
local inference behind an authenticated LiteLLM proxy rather than Ollama
directly. Implications of the proxy path: the endpoint becomes a
host:port or hostname with a bearer token and probably TLS (pulling a
TLS stack and a resolver into the binary and a secret into the device);
the API becomes OpenAI-compatible, where `response_format: json_schema`
is copied verbatim into `format` but `temperature` and `top_p` default to
1.0, `num_ctx` cannot be set, and the chat-template path has the
alphabetical key-order bug ([Ollama OpenAI compatibility][ol-openai],
[openai.go][ol-openai-go], [ol-18717][ol-18717]); and the no-egress
argument changes shape, because the runtime can no longer observe
`remote_host` stamps or `/api/status` and must trust the proxy's routing
policy and allow-list. If chosen: a build feature `infer-proxy`, an IP
literal only (no DNS), token from an `ECP_*` environment variable, the
proxy's upstream allow-list documented as the egress boundary, and the
`cloud_not_disabled` check replaced by a documented proxy-side control.

(b) Hardware fault action. Default: the latch asserts the SoC nRESET
(fail-safe; nothing runs on a faulted interlock), with a board jumper
to select "latch-only" for bench work. Alternative: software-visible
latch only (the runtime keeps serving protocol traffic and refuses tool
calls). Note that in the default the Linux reader's FAULT state is
reached only in latch-only mode or if the reset path fails; the audit
log must therefore also record the FAULT GPIO level at every startup.

(c) `link_search` representation. Default: free text, LIKE with ESCAPE,
1..=32 characters, `LIKE_PATTERN_LENGTH` 80. Alternative 1: replace by
an enum of host names derived from the seeded `links` at build time
(removes wildcards and scans; narrows expressiveness). Alternative 2:
`instr(lower(payload_url), lower(?3)) > 0` (no wildcard semantics at
all; same ASCII-only case folding as LIKE). The security note's
preference order is enum, then instr, then LIKE-with-ESCAPE.

(d) Writer CLI location. Default: same binary, subcommands, writer
module gated by a token type the `serve` path cannot construct, and the
`serve` mode never opening read-write. Alternative: a separate
`ecp-admin` binary behind a Cargo feature so the deployed `serve`
binary contains no writer code at all (stronger, two artifacts to ship).

(e) The `voats` spelling. Default: keep `voats` as the table name and
project term (it is the author's vocabulary), with a README line that it
means votes. Alternative: rename to `votes` now, before any data exists;
a compatibility view is not an option because views are disabled on the
read rail.

(f) Host-side S-bar derivation. Default: one host GPIO, S direct and
S-bar through an inverter, both open-drain (nanosecond skew; fewer CCF
diversity points). Alternative: two independent host GPIOs (more
diversity; software skew that forces a longer `t_filter`).

(g) UART reliability layer and serial crate. Default: the section 4.8
frame (length, payload, CRC-32), port configured by `stty` in a wrapper,
opened as a file. Alternative: a vetted serial crate added to the
vendored set after `cargo vet`; not covered by the research.

(h) Timing constants. Default: `t_filter` 100 us (hardware RC),
`t_disc` 50 ms, reader sample period 10 ms, statement budget 2 s,
inference first-byte 60 s / total 90 s, rate limit 1/s burst 5. All are
`[D]` and configurable except `t_filter`.

(i) Hex fast path. Default: a prompt that is exactly `#RRGGBB` bypasses
inference. Alternative: always plan through the model for uniform audit
records.

## 13. Appendix A: CLAUDE.md seed

```markdown
# ECP dual rail runtime

Read SPEC.md before touching code. SPEC.md wins over this file.

## Build and test
- Toolchain: rust-toolchain.toml (1.99.1), edition 2024, MSRV 1.89.
- Offline only: `cargo build --release --locked --offline`
  (targets: x86_64-unknown-linux-musl, aarch64-unknown-linux-musl via
  `cargo zigbuild`). Never run `cargo update` or add crates without
  re-vendoring and `cargo deny check` + `cargo vet`.
- Tests: `cargo test --locked --offline`. Live Ollama tests only with
  `ECP_LIVE_OLLAMA=1`. Mock Ollama lives in tests/mock_ollama.rs.
- Snapshots: `schema/ecp_query_plan.draft07.json` and the SQL templates
  are insta snapshots; a diff is a reviewed change, not a nuisance.

## Invariants (tests enforce them)
- The model never writes SQL. Plans deserialize into `EcpQueryPlan`
  under `deny_unknown_fields`, pass `validate()`, and compile by
  exhaustive match into one of three `&'static str` templates.
- Every value is a bound parameter; `link_search` is LIKE ... ESCAPE '\'.
- `serve` opens SQLite read-only with DEFENSIVE, trusted_schema off,
  query_only, sqlite3_limit set, and an allow-list authorizer that
  returns Deny (never Ignore) outside colors/links/qr_codes/voats.
- Inference goes to the literal SocketAddr 127.0.0.1:11434 with
  `.proxy(None)`, `:local` suffix, digest pin, `/api/status`
  cloud.disabled check, and `remote_host` refusal on every response.
- MCP: dual era (initialize or `_meta` + server/discover), static tool
  list (ecp_list_models, ecp_select_model, ecp_query), stdout carries
  only JSON-RPC lines, logs on stderr, domain failures are isError.
- Interlock: S xor S-bar = 1; (0,0)/(1,1) >= t_disc latches FAULT;
  the Linux reader observes, hardware protects.

## Forbidden
- format!/concat of SQL; line.contains dispatch; any network listener;
  HTTP proxies or OLLAMA_HOST; tokio; regex; unbounded_depth;
  load_extension; writer code reachable from `serve`; stdout logging;
  JSON-RPC codes in -32768..-32000; Markdown links in results;
  calling /api/pull, /api/create, /api/push, /api/delete, /v1/*.
- The words "immune", "zero dependencies", "unmaskable", "DPA" in
  docs or code comments unless quoting SPEC.md's corrections.

## Where things live
- rpc/ envelope+codes; mcp/ lifecycle+tools; plan/ struct+schema+
  validate; sql/ templates+compile; db/ open_ro+open_rw+authorizer;
  infer/ ollama client+egress; interlock/ state+gpio+sim; qr/; cli/;
  audit/. Bridge: ecp-bridge/ (stdio <-> UART relay, parses nothing).

## Commit discipline
- One milestone per PR (SPEC.md section 11). Acceptance tests first.
- Record any limit you had to raise (e.g. EXPR_DEPTH) here with why.
```

## 14. Appendix B: Corrections ledger

Format: draft claim -> verdict -> where corrected -> source.

1. "Master Control Process (MCP)" -> wrong; Model Context Protocol ->
   4.1 -> [mcp-chg], [lf-aaif].
2. `ecp.list_models` / `ecp.select_model` / `ecp.query` as JSON-RPC
   methods -> not surfaced by any MCP client; tools instead -> 4.6 ->
   [schema-ts], [cc-mcp].
3. Session-bound "active model" (`select_model` then `query`) ->
   forbidden by 2026-07-28 statelessness; per-call `model_id` -> 4.3,
   4.6 -> [mcp-base].
4. Dotted tool names -> legal but normalised by Claude Code; underscore
   names -> 4.6 -> [mcp-tools], [cc-sdk].
5. Error codes -32000, -32001 -> legacy sub-range, do not use; isError
   results -> 4.7 -> [mcp-base].
6. "JSON-RPC over stdio or UART" as peers -> UART is a custom transport
   behind a host bridge; Claude Code cannot open serial -> 4.8 ->
   [mcp-tr], [cc-mcp].
7. Single-era `initialize`-style lifecycle -> dual era with
   `server/discover` probe -> 4.2-4.4 -> [mcp-stdio], [mcp-ver],
   [cc-mcp].
8. Prompt-style stdin loop with `ECP Ready >` prompt and `exit` command
   -> stdout must carry only MCP messages -> 4.5 -> [mcp-stdio].
9. `line.contains("ecp.query")` dispatch; hard-coded response ids ->
   parsed envelope, echoed ids, batch/notification rules -> 4.5 ->
   [jsonrpc].
10. "Zero dynamic dependencies" / "standard library + bundled SQLite"
    -> statically linked musl binary with 25-40 vendored crates -> 2.2,
    10 -> [zigbuild], [minreq], [rusqlite].
11. "Isolated embedded microcontroller core" -> edge Linux board; MCU
    would be separate firmware -> 2.1 -> [gpiocdev], [sys-build].
12. `verify_endpoint` accepting `"localhost"` -> literal SocketAddr, no
    names -> 5.1 -> [ureq-proxy], [ol-env].
13. "Hard-coding 127.0.0.1:11434 prevents network egress" -> daemon
    proxies cloud models, remote manifests, web search from that port;
    client-side refusals plus `OLLAMA_NO_CLOUD` -> 5.5 -> [ol-routes],
    [ol-modelref], [ol-faq].
14. Schema `default` values -> ignored by the grammar converter; runtime
    defaults -> 5.3-5.4 -> [lc-conv].
15. Unbounded `link_search` and `min_votes` -> bounded; LIKE escaping
    -> 5.4, 6.3 -> [sq-like], [sq-sec].
16. "Regex structural verification prevents escape-character attacks"
    -> pattern is honoured only when anchored and simple, and degrades
    silently otherwise; Rust re-validates -> 5.3, 5.7 -> [lc-conv],
    [lc-readme].
17. "additionalProperties: false causes the deserializer to reject" ->
    true only with `deny_unknown_fields`; both are required -> 6.1 ->
    [serde-ca].
18. Hand-maintained JSON Schema -> emitted from the Rust struct and
    snapshot-tested -> 6.1 -> [schemars-gen].
19. `BOOLEAN`, `DATETIME` columns with "strict column checks" ->
    illegal in STRICT tables; INTEGER CHECK(0,1), TEXT -> 7.1 ->
    [sq-strict], [sq-dt].
20. `length(hex) == 7` -> legal but `=` used -> 7.1 -> [sq-expr].
21. `AUTOINCREMENT` everywhere -> only on `qr_codes` -> 7.1 ->
    [sq-auto].
22. FK clauses assumed enforced -> per-connection pragma outside a
    transaction, readback required; bundled default is ON -> 7.2 ->
    [sq-fk], [sq-pragma], [sys-build].
23. No connection hardening -> read-only flags, DEFENSIVE,
    trusted_schema off, query_only, limits, authorizer, progress
    handler, heap limit -> 7.3-7.5 -> [sq-sec], [sq-auth], [sq-dbcfg].
24. No write path specified -> CLI writer, 6x6x6 seeding, qrcodegen SVG
    -> 7.6-7.7 -> [qrcodegen], [png].
25. "S + S-bar = 0" -> S xor S-bar = 1; V sum constant; I sum zero ->
    8.1 -> [rockwell], [an228], [an5020].
26. "Dual-Rail Balanced Differential Logic" as one thing -> three
    distinct artifacts -> 8.2 -> [ti-485], [wddl04], [siemens].
27. "E_net ~ 0 renders RF sniffing ineffective" -> overstated; CM
    dominates; irrelevant to SoC emissions -> 8.3 -> [msu], [clemson].
28. "Dual-rail methodologies such as WDDL ... remove data-dependent
    switching signatures" applied to an I/O pair -> category error ->
    8.3 -> [wddl04], [wddl05], [mdpl], [suzuki].
29. "Software breach in the host-facing bridge cannot access the ECP
    runtime without violating the invariant" -> false; valid (1,0)
    forever -> 8.3, 8.7 -> [ti-iso], [lenze].
30. "Unmaskable hardware reset interrupt within nanoseconds" ->
    conditional on a discrete latch path; Linux is us-ms -> 8.5-8.6 ->
    [hc86], [hc266], [arm-lat], [gkaindl], [obuda], [adi-wdt].
31. "~2.0x to 2.3x silicon area" -> unsupported; 3.1-3.6x, 4.5x, 6x
    FPGA in the literature; wrong metric for an I/O pair -> 8.3 ->
    [wddl04], [wddl05], [mdpl].
32. "Converts fault injection attempts into deterministic halts" ->
    covers wiring faults only; core glitching unaffected -> 8.7 ->
    [yuce], [nrf52].
33. "Prevents ... extracting ... cryptographic states via oscilloscope
    power traces" -> no cryptographic secrets in the box; DPA not
    addressed by the pair -> 8.7 -> [kocher].
34. Session state machine UNINITIALIZED/READY_IDLE/... -> per-call
    pipeline plus interlock state machine -> 3.2-3.3 -> [mcp-base].
35. "Immunity via strongly typed JSON Schema translation" -> SQLi
    eliminated; prompt injection contained; residual list -> 9.1, 9.4
    -> [owasp-05], [pedro], [owasp-pdf], [rule2], [vanna].
36. "Restricts context processing to edge hardware, eliminating remote
    data exposure" -> results re-enter Claude Code; trifecta reassembled
    at the host -> 9.3 -> [trifecta], [supabase], [csa-cc].
37. No audit, rate limit or output labelling -> required -> 9.5-9.7 ->
    [mcp-tools], [owasp-pdf], [mcp-local].
38. "Draft-07" assumed for everything -> MCP tool schemas default to
    2020-12; Draft-07 only for the Ollama-facing plan schema -> 4.6,
    5.4 -> [mcp-tools], [schemars-gen].
39. Example model list (`llama3:8b`, `phi3:mini`, `mistral:7b`) ->
    illustrative only; pinned 4B-class non-thinking model by digest ->
    5.6 -> [n2k], [mayhem], [ol-15260].
40. "Streams the results back" -> single result per call; size caps ->
    2.3, 4.10 -> [cc-sdk].

## 15. Sources

All sources were read by the research team on 2026-10-29 unless the
entry says otherwise. "Primary" means a specification, standard body,
vendor datasheet, official documentation, crate tarball or paper;
"secondary" means a summary, blog or aggregator and is weighted
accordingly in the text. The URL list at the end holds each address
once; URL lines are the only lines in this file allowed to exceed 80
columns, because an address cannot be broken without breaking the link.

### MCP and Claude Code (primary unless noted)

- mcp-chg: [MCP 2026-07-28 changelog][mcp-chg]
- mcp-base: [MCP 2026-07-28 base protocol][mcp-base]
- mcp-stdio: [MCP 2026-07-28 stdio transport][mcp-stdio]
- mcp-tr: [MCP 2026-07-28 transports overview][mcp-tr]
- mcp-ver: [MCP 2026-07-28 versioning][mcp-ver]
- mcp-disc: [MCP 2026-07-28 server/discover][mcp-disc]
- mcp-tools: [MCP 2026-07-28 tools][mcp-tools]
- mcp-dep: [MCP 2026-07-28 deprecated features registry][mcp-dep]
- mcp-life25: [MCP 2025-11-25 lifecycle][mcp-life25]
- mcp-tr25: [MCP 2025-11-25 transports][mcp-tr25]
- schema-ts: [MCP schema.ts 2026-07-28 (normative)][schema-ts]
- mcp-sec: [MCP security best practices (2026-07-28 docs)][mcp-sec]
- mcp-local: [MCP local server security guide][mcp-local]
- lf-aaif: [Linux Foundation press release, 2025-12-09][lf-aaif]
- claude-blog: [Claude blog on MCP 2026-07-28][claude-blog]
- cc-mcp: [Claude Code MCP documentation][cc-mcp]
- cc-qs: [Claude Code MCP quickstart][cc-qs]
- cc-sdk: [Claude Code Agent SDK MCP documentation][cc-sdk]
- cc-env: [Claude Code environment variables][cc-env]
- jsonrpc: [JSON-RPC 2.0 specification][jsonrpc]
- rmcp: [crates.io rmcp (official Rust SDK)][rmcp]
- invariant: [Invariant Labs, tool poisoning notification][invariant]
- csa-tp: [CSA whitepaper, MCP tool poisoning, 2026-05-06][csa-tp]

### Ollama and llama.cpp (primary: docs and main-branch source)

- ol-faq: [Ollama FAQ][ol-faq]
- ol-intro: [Ollama API introduction][ol-intro]
- ol-tags: [Ollama /api/tags][ol-tags]
- ol-gen: [Ollama /api/generate][ol-gen]
- ol-so: [Ollama structured outputs][ol-so]
- ol-think: [Ollama thinking][ol-think]
- ol-cloud: [Ollama cloud models][ol-cloud]
- ol-ctx: [Ollama context length][ol-ctx]
- ol-mf: [Ollama Modelfile][ol-mf]
- ol-openai: [Ollama OpenAI compatibility][ol-openai]
- ol-env: [ollama envconfig/config.go][ol-env]
- ol-routes: [ollama server/routes.go][ol-routes]
- ol-types: [ollama api/types.go][ol-types]
- ol-ls: [ollama llm/llama_server.go][ol-ls]
- ol-srv: [ollama llm/server.go][ol-srv]
- ol-modelref: [ollama internal/modelref/modelref.go][ol-modelref]
- ol-openai-go: [ollama openai/openai.go][ol-openai-go]
- ol-blog-so: [Ollama blog, structured outputs, 2024-12-06][ol-blog-so]
- ol-blog-cloud: [Ollama blog, cloud models, 2025-09-19][ol-blog-cloud]
- ol-18717: [ollama issue #18717, key order on chat path][ol-18717]
- ol-15260: [ollama issue #15260, think=false and format][ol-15260]
- ol-18567: [ollama issue #18567, MLX structured output][ol-18567]
- lc-readme: [llama.cpp grammars README][lc-readme]
- lc-conv: [llama.cpp common/json-schema-to-grammar.cpp][lc-conv]
- go-chunk: [Go net/http chunking commit (mirror)][go-chunk]
- n2k: [needtoknowit, Ollama model sizes, 2026-09-14 (secondary)][n2k]
- mayhem: [mayhemcode, local LLMs by VRAM, 2026-06-16 (secondary)][mayhem]

### Rust crates and toolchain (primary: crates.io metadata, tarballs)

- rust-rel: [Rust release blog index][rust-rel]
- lint: [rustc lint listing, allowed-by-default][lint]
- rusqlite: [crates.io rusqlite][rusqlite]
- rusq-lib: [rusqlite 0.41.1 src/lib.rs][rusq-lib]
- rusq-hooks: [rusqlite 0.41.1 src/hooks/mod.rs][rusq-hooks]
- rusq-lim: [rusqlite 0.41.1 src/limits.rs][rusq-lim]
- rusq-cfg: [rusqlite 0.41.1 src/config.rs][rusq-cfg]
- sys-crate: [crates.io libsqlite3-sys][sys-crate]
- sys-build: [libsqlite3-sys 0.39.1 build.rs][sys-build]
- sys-h: [libsqlite3-sys 0.39.1 sqlite3/sqlite3.h][sys-h]
- serde: [crates.io serde][serde]
- serde-ca: [serde container attributes][serde-ca]
- serde-de: [serde 1.0.229 src/private/de.rs][serde-de]
- serde-1042: [serde issue #1042, absent versus null][serde-1042]
- sj: [crates.io serde_json 1.0.154][sj]
- sj-de: [serde_json 1.0.154 src/de.rs][sj-de]
- schemars: [crates.io schemars 1.2.3][schemars]
- schemars-gen: [schemars 1.2.3 src/generate.rs][schemars-gen]
- jsonschema: [crates.io jsonschema][jsonschema]
- jsonrpc-core: [crates.io jsonrpc-core][jsonrpc-core]
- jsonrpsee: [crates.io jsonrpsee][jsonrpsee]
- ureq: [crates.io ureq README][ureq]
- ureq-meta: [crates.io ureq 3.5.0 metadata][ureq-meta]
- ureq-proxy: [ureq 3.5.0 src/proxy.rs][ureq-proxy]
- minreq: [crates.io minreq][minreq]
- qrcodegen: [crates.io qrcodegen][qrcodegen]
- qrcode: [crates.io qrcode][qrcode]
- fastqr: [crates.io fast_qr][fastqr]
- png: [crates.io png 0.18.1][png]
- image: [crates.io image 0.25.10][image]
- gpiocdev: [crates.io gpiocdev README][gpiocdev]
- gpiocdev-meta: [crates.io gpiocdev 0.8.0][gpiocdev-meta]
- gpiocdev-src: [gpiocdev 0.8.0 src/request/builder.rs][gpiocdev-src]
- vendor: [cargo-vendor(1) man page][vendor]
- zigbuild: [crates.io cargo-zigbuild README][zigbuild]
- deny: [crates.io cargo-deny][deny]
- audit: [crates.io cargo-audit][audit]
- vet: [crates.io cargo-vet][vet]
- cc: [crates.io cc][cc]
- insta: [crates.io insta][insta]
- proptest: [crates.io proptest][proptest]
- assert_cmd: [crates.io assert_cmd][assert_cmd]

### SQLite (primary: sqlite.org and its official mirror)

- sq-fk: [SQLite foreign keys][sq-fk]
- sq-pragma: [SQLite PRAGMA statements][sq-pragma]
- sq-strict: [SQLite STRICT tables][sq-strict]
- sq-dt: [SQLite datatypes][sq-dt]
- sq-ct: [SQLite CREATE TABLE][sq-ct]
- sq-expr: [SQLite expressions][sq-expr]
- sq-auto: [SQLite AUTOINCREMENT][sq-auto]
- sq-sec: [SQLite, Defense Against The Dark Arts][sq-sec]
- sq-limit: [SQLite sqlite3_limit][sq-limit]
- sq-auth: [SQLite sqlite3_set_authorizer][sq-auth]
- sq-dbcfg: [SQLite database connection configuration][sq-dbcfg]
- sq-wal: [SQLite write-ahead logging][sq-wal]
- sq-like: [SQLite LIKE documentation text (docsrc)][sq-like]
- sq-forum: [SQLite forum, LIKE ESCAPE precedence, 2020][sq-forum]

### Security literature and incidents

- owasp-pdf: [OWASP Top 10 for LLM Applications 2025 (PDF mirror)][owasp-pdf]
- owasp-05: [OWASP LLM05:2025 improper output handling][owasp-05]
- owasp-sqli: [OWASP SQL injection prevention cheat sheet][owasp-sqli]
- owasp-q1: [OWASP GenAI exploit round-up Q1 2026][owasp-q1]
- greshake-full: [Greshake et al. 2023, full text (ar5iv)][greshake-full]
- trifecta: [Willison, the lethal trifecta, 2025-06-16][trifecta]
- supabase: [Willison, Supabase MCP, 2025-07-06][supabase]
- rule2: [Willison, new prompt-injection papers, 2025-11-02][rule2]
- patterns: [Willison on Beurer-Kellner et al., 2025-06-13][patterns]
- pedro: [Pedro et al., P2SQL injections, ICSE 2025][pedro]
- cve-lc: [CIRCL vulnerability-lookup, CVE-2023-36189][cve-lc]
- cve-li: [CIRCL vulnerability-lookup, CVE-2024-23751][cve-li]
- vanna: [JFrog, Vanna.AI CVE-2024-5565][vanna]
- cda: [Zhang et al., constrained decoding attacks, arXiv 2503.24191][cda]
- csa-cc: [CSA research note, Claude Code action CVE-2025-66032][csa-cc]
- thn: [The Hacker News, Reprompt, 2026-01-15 (secondary)][thn]
- ghostsplice: [GhostSplice vendor summary, 2026-08-11 (secondary)][ghostsplice]
- wiz: [Wiz, Probllama CVE-2024-37032][wiz]
- oligo: [Oligo, More Models More ProbLLMs][oligo]
- s1: [SentinelOne, CVE-2025-15514 (AI-generated page, secondary)][s1]

### Hardware, EMC, side channels and functional safety

- ti-485: [TI, RS-485 design guide SLLA272B][ti-485]
- ti-fs: [TI SLLA272D, failsafe section][ti-fs]
- ti-iso: [TI SLLA272D, grounding and isolation][ti-iso]
- an5020: [Fairchild AN-5020, LVDS fundamentals][an5020]
- slla422: [TI SLLA422, LVDS SerDes in industrial systems][slla422]
- msu: [MSU EMRG, module 9 radiated emissions][msu]
- clemson: [Clemson CVEL-13-052][clemson]
- an228: [Microchip AN228, CAN physical layer][an228]
- wddl04: [Tiri and Verbauwhede, WDDL, DATE 2004][wddl04]
- wddl05: [Tiri et al., WDDL prototype IC, CHES 2005][wddl05]
- mdpl: [Popp and Mangard, MDPL, CHES 2005][mdpl]
- suzuki: [Suzuki and Saeki, early propagation, CHES 2006][suzuki]
- survey: [Power side channels in security ICs, arXiv 1605.00681][survey]
- kocher: [Kocher et al., introduction to DPA, JCEN 2011][kocher]
- csinn: [Batina et al., CSI NN, USENIX Security 2019][csinn]
- yuce: [Yuce, Schaumont, Witteman, fault attacks survey][yuce]
- nrf52: [LimitedResults, nRF52 debug resurrection, Black Hat EU 2020][nrf52]
- coldboot: [Halderman et al., Lest We Remember, USENIX 2008][coldboot]
- ifa: [IFA Report 2/2017e, functional safety of machine controls][ifa]
- irsst: [IRSST / Becker, ISO 13849-1 presentation][irsst]
- lenze: [Lenze AKB 201014347, monitoring passive sensors][lenze]
- siemens: [Siemens ET 200SP F-DI 8x24VDC HF manual][siemens]
- rockwell: [Rockwell, Dual Channel Input Stop (DCS)][rockwell]
- pilz-s3: [Pilz PNOZ s3 datasheet][pilz-s3]
- pilz-lex: [Pilz lexicon, test pulses][pilz-lex]
- pilz-s6: [Pilz PNOZ s6 operating manual][pilz-s6]
- dold: [Dold UG6960 safety relay datasheet][dold]
- hc86: [TI SN74HC86 datasheet, switching characteristics][hc86]
- hc266: [TI SN74HC266 product page][hc266]
- arm-lat: [ARM, interrupt latency of Cortex-M processors][arm-lat]
- nxp-nmi: [NXP, NVIC training][nxp-nmi]
- gkaindl: [gkaindl, Linux GPIO IRQ latency test][gkaindl]
- lore: [lore.kernel.org, BeagleBone GPIO latency thread, 2015][lore]
- bbb: [BeagleBoard forum, poll() edge-detection latency][bbb]
- obuda: [Obuda University, PREEMPT_RT latency tutorial][obuda]
- adi-wdt: [Analog Devices, internal vs external watchdogs][adi-wdt]

### Reference URLs

[mcp-chg]: https://modelcontextprotocol.io/specification/2026-07-28/changelog
[mcp-base]: https://modelcontextprotocol.io/specification/2026-07-28/basic
[mcp-stdio]: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
[mcp-tr]: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports
[mcp-ver]: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
[mcp-disc]: https://modelcontextprotocol.io/specification/2026-07-28/server/discover
[mcp-tools]: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
[mcp-dep]: https://modelcontextprotocol.io/specification/2026-07-28/deprecated
[mcp-life25]: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
[mcp-tr25]: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
[schema-ts]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts
[mcp-sec]: https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices
[mcp-local]: https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/local-server-security.md
[lf-aaif]: https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation
[claude-blog]: https://claude.com/blog/bringing-mcp-2026-07-28-to-claude
[cc-mcp]: https://code.claude.com/docs/en/mcp
[cc-qs]: https://code.claude.com/docs/en/mcp-quickstart
[cc-sdk]: https://code.claude.com/docs/en/agent-sdk/mcp
[cc-env]: https://code.claude.com/docs/en/env-vars
[jsonrpc]: https://www.jsonrpc.org/specification
[rmcp]: https://crates.io/crates/rmcp
[invariant]: https://invariantlabs.ai/blog/mcp-security-notification
[csa-tp]: https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/
[ol-faq]: https://docs.ollama.com/faq.md
[ol-intro]: https://docs.ollama.com/api/introduction.md
[ol-tags]: https://docs.ollama.com/api/tags.md
[ol-gen]: https://docs.ollama.com/api/generate.md
[ol-so]: https://docs.ollama.com/capabilities/structured-outputs.md
[ol-think]: https://docs.ollama.com/capabilities/thinking.md
[ol-cloud]: https://docs.ollama.com/cloud.md
[ol-ctx]: https://docs.ollama.com/context-length.md
[ol-mf]: https://docs.ollama.com/modelfile.md
[ol-openai]: https://docs.ollama.com/openai.md
[ol-env]: https://github.com/ollama/ollama/blob/main/envconfig/config.go
[ol-routes]: https://github.com/ollama/ollama/blob/main/server/routes.go
[ol-types]: https://github.com/ollama/ollama/blob/main/api/types.go
[ol-ls]: https://github.com/ollama/ollama/blob/main/llm/llama_server.go
[ol-srv]: https://github.com/ollama/ollama/blob/main/llm/server.go
[ol-modelref]: https://github.com/ollama/ollama/blob/main/internal/modelref/modelref.go
[ol-openai-go]: https://github.com/ollama/ollama/blob/main/openai/openai.go
[ol-blog-so]: https://registry.ollama.ai/blog/structured-outputs
[ol-blog-cloud]: https://registry.ollama.ai/blog/cloud-models
[ol-18717]: https://github.com/ollama/ollama/issues/18717
[ol-15260]: https://github.com/ollama/ollama/issues/15260
[ol-18567]: https://github.com/ollama/ollama/issues/18567
[lc-readme]: https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
[lc-conv]: https://github.com/ggml-org/llama.cpp/blob/master/common/json-schema-to-grammar.cpp
[go-chunk]: https://lab.nexedi.cn/kirr/go/-/commit/bef4cb475c0638ab5193f75f2683b35a7c7f6547
[n2k]: https://needtoknowit.com.au/blog/best-ollama-models-to-download.md
[mayhem]: https://www.mayhemcode.com/2026/06/best-local-llms-for-4gb-6gb-and-8gb.html
[rust-rel]: https://blog.rust-lang.org/releases
[lint]: https://doc.rust-lang.org/nightly/rustc/lints/listing/allowed-by-default.html
[rusqlite]: https://crates.io/crates/rusqlite
[rusq-lib]: https://docs.rs/crate/rusqlite/0.41.1/source/src/lib.rs
[rusq-hooks]: https://docs.rs/crate/rusqlite/0.41.1/source/src/hooks/mod.rs
[rusq-lim]: https://docs.rs/crate/rusqlite/0.41.1/source/src/limits.rs
[rusq-cfg]: https://docs.rs/crate/rusqlite/0.41.1/source/src/config.rs
[sys-crate]: https://crates.io/crates/libsqlite3-sys
[sys-build]: https://docs.rs/crate/libsqlite3-sys/0.39.1/source/build.rs
[sys-h]: https://docs.rs/crate/libsqlite3-sys/0.39.1/source/sqlite3/sqlite3.h
[serde]: https://crates.io/crates/serde
[serde-ca]: https://serde.rs/container-attrs
[serde-de]: https://docs.rs/crate/serde/1.0.229/source/src/private/de.rs
[serde-1042]: https://github.com/serde-rs/serde/issues/1042
[sj]: https://crates.io/crates/serde_json/1.0.154
[sj-de]: https://docs.rs/crate/serde_json/1.0.154/source/src/de.rs
[schemars]: https://crates.io/crates/schemars/1.2.3
[schemars-gen]: https://docs.rs/crate/schemars/1.2.3/source/src/generate.rs
[jsonschema]: https://crates.io/crates/jsonschema
[jsonrpc-core]: https://crates.io/crates/jsonrpc-core
[jsonrpsee]: https://crates.io/crates/jsonrpsee
[ureq]: https://crates.io/crates/ureq
[ureq-meta]: https://crates.io/crates/ureq/3.5.0
[ureq-proxy]: https://docs.rs/crate/ureq/3.5.0/source/src/proxy.rs
[minreq]: https://crates.io/crates/minreq
[qrcodegen]: https://crates.io/crates/qrcodegen
[qrcode]: https://crates.io/crates/qrcode
[fastqr]: https://crates.io/crates/fast_qr
[png]: https://crates.io/crates/png/0.18.1
[image]: https://crates.io/crates/image/0.25.10
[gpiocdev]: https://crates.io/crates/gpiocdev
[gpiocdev-meta]: https://crates.io/crates/gpiocdev/0.8.0
[gpiocdev-src]: https://docs.rs/crate/gpiocdev/0.8.0/source/src/request/builder.rs
[vendor]: https://man.archlinux.org/man/cargo-vendor.1.en
[zigbuild]: https://crates.io/crates/cargo-zigbuild
[deny]: https://crates.io/crates/cargo-deny
[audit]: https://crates.io/crates/cargo-audit
[vet]: https://crates.io/crates/cargo-vet
[cc]: https://crates.io/crates/cc
[insta]: https://crates.io/crates/insta
[proptest]: https://crates.io/crates/proptest
[assert_cmd]: https://crates.io/crates/assert_cmd
[sq-fk]: https://www2.sqlite.org/foreignkeys.html
[sq-pragma]: https://www2.sqlite.org/pragma.html
[sq-strict]: https://www2.sqlite.org/stricttables.html
[sq-dt]: https://www2.sqlite.org/datatype3.html
[sq-ct]: https://www2.sqlite.org/lang_createtable.html
[sq-expr]: https://www2.sqlite.org/lang_expr.html
[sq-auto]: https://www2.sqlite.org/autoinc.html
[sq-sec]: https://www2.sqlite.org/security.html
[sq-limit]: https://www2.sqlite.org/c3ref/limit.html
[sq-auth]: https://www.sqlite.org/c3ref/set_authorizer.html
[sq-dbcfg]: https://www2.sqlite.org/c3ref/c_dbconfig_defensive.html
[sq-wal]: https://www2.sqlite.org/wal.html
[sq-like]: https://www.sqlite.org/docsrc/info/ec08a46c8b7cd374
[sq-forum]: https://sqlite.org/forum/forumpost/11e9ac5a80
[owasp-pdf]: https://www.mindtwo.de/storage/media/images/4525/owasp-top-10-for-llm-applications-2025.pdf
[owasp-05]: https://genai.owasp.org/llmrisk/llm052025-improper-output-handling/
[owasp-sqli]: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
[owasp-q1]: https://genai.owasp.org/2026/04/14/owasp-genai-exploit-round-up-report-q1-2026/
[greshake-full]: https://ar5iv.labs.arxiv.org/html/2302.12173
[trifecta]: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
[supabase]: https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/
[rule2]: https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/
[patterns]: https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/
[pedro]: https://syssec.dpss.inesc-id.pt/papers/pedro_icse25.pdf
[cve-lc]: https://cvepremium.circl.lu/vuln/cve-2023-36189
[cve-li]: https://vulnerability.circl.lu/vuln/CVE-2024-23751
[vanna]: https://jfrog.com/blog/prompt-injection-attack-code-execution-in-vanna-ai-cve-2024-5565
[cda]: https://arxiv.org/abs/2503.24191v2
[csa-cc]: https://labs.cloudsecurityalliance.org/research/csa-research-note-claude-code-github-action-prompt-injection/
[thn]: https://thehackernews.com/2026/01/researchers-reveal-reprompt-attack.html
[ghostsplice]: https://orcarouter.ai/blog/2026-08-11-ghostsplice-cross-channel-fragmentation
[wiz]: https://wiz.io/blog/probllama-ollama-vulnerability-cve-2024-37032
[oligo]: https://oligo.security/blog/more-models-more-probllms
[s1]: https://www.sentinelone.com/vulnerability-database/cve-2025-15514/
[ti-485]: https://erg.abdn.ac.uk/users/Gorry/eg3576/resources/RS485-intro-TI.pdf
[ti-fs]: https://www.ti.com/document-viewer/lit/html/SLLA272D/GUID-F745A16C-0BB2-4A1E-B69C-6928D1ABA951
[ti-iso]: https://www.ti.com/document-viewer/lit/html/SLLA272D/GUID-F2F5FEAF-3C1B-436A-A04A-871865637DBD
[an5020]: https://hallaweb.jlab.org/tech/Detectors/public_html/manuals/chip_specs/A-L/fairchild/lvds_fairchild/AN-5020.pdf
[slla422]: https://ti.com/lit/pdf/slla422
[msu]: https://www.egr.msu.edu/emrg/sites/default/files/content/module9_radiated_emissions.pdf
[clemson]: https://cecas.clemson.edu/cvel/Reports/CVEL-13-052.pdf
[an228]: https://www.cs.hs-rm.de/~kaiser/1313_canacademy/Microchip_AN228_A%20CAN%20Physical%20Layer%20Discussion.pdf
[wddl04]: https://mooney.gatech.edu/Courses/ECE3170/lectures/TiriVerbDATE04.pdf
[wddl05]: https://www.iacr.org/archive/ches2005/026.pdf
[mdpl]: https://iacr.org/archive/ches2005/013.pdf
[suzuki]: https://www.iacr.org/archive/ches2006/21/21.pdf
[survey]: https://arxiv.org/pdf/1605.00681
[kocher]: https://web.eecs.umich.edu/~genkin/teaching/fall2018/EECS598-12_files/Kocher2011_Article_IntroductionToDifferentialPowe.pdf
[csinn]: https://www.usenix.org/conference/usenixsecurity19/presentation/batina
[yuce]: https://ar5iv.arxiv.org/html/2003.10513
[nrf52]: https://i.blackhat.com/eu-20/Wednesday/eu-20-LimitedResults-Debug-Resurrection-On-nRF52-Series.pdf
[coldboot]: https://www.usenix.org/legacy/event/sec08/tech/full_papers/halderman/halderman_html/
[ifa]: https://publikationen.dguv.de/widgets/pdf/download/article/4150
[irsst]: https://medias.irsst.qc.ca/videos/1210_mp_co_HD_becker_en_pdf.pdf
[lenze]: https://www.lenze.com/en-de/go/akb/201014347/1
[siemens]: https://cache.industry.siemens.com/dl/files/499/78589499/att_878784/v1/et200sp_f-di_8x24vdc_hf_manual_en-US_en-US.pdf
[rockwell]: https://www.rockwellautomation.com/en-in/docs/studio-5000-logix-designer/37-00/contents-ditamap/instruction-set/safety-instructions/dual-channel-input-stop--dcs-.html
[pilz-s3]: https://www.farnell.com/datasheets/1679411.pdf
[pilz-lex]: https://www.pilz.com/en-DE/support/lexicon/articles/072903
[pilz-s6]: https://www.pilz.com/download/open/OM_PNOZ_s6_21398-EN-17.pdf
[dold]: https://cdn.automationdirect.com/static/specs/safetyrelay2chestopadjdelay.pdf
[hc86]: https://html.alldatasheet.jp/html-pdf/27948/TI/SN74HC86/103/4/SN74HC86.html
[hc266]: https://ti.com/product/SN74HC266
[arm-lat]: https://developer.arm.com/community/arm-community-blogs/b/architectures-and-processors-blog/posts/beginner-guide-on-interrupt-latency-and-interrupt-latency-of-the-arm-cortex-m-processors
[nxp-nmi]: https://nxp.com.cn/docs/en/supporting-information/Nested-Vector-Interrupt-Controller-Training.pdf
[gkaindl]: https://github.com/gkaindl/linux-gpio-irq-latency-test
[lore]: https://lore.kernel.org/all/54DA1929.5040206@gmail.com/
[bbb]: https://forum.beagleboard.org/t/bbb-poll-function-edge-detection-latency/14660
[obuda]: https://www.aut.uni-obuda.hu/es/Linux%20in%20Embedded%20Systems/Tutorials/preempt-rt-latency
[adi-wdt]: https://www.analog.com/en/resources/technical-articles/comparison-of-internal-and-external-watchdog-timers.html
