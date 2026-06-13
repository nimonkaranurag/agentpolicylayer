# APL Wire Protocol Specification

**Protocol version:** `0.3.0`
**Status:** Stable for the `0.x` major line
**Source of truth:** `PROTOCOL_VERSION` in [`apl/types.py`](apl/types.py)

This document is the normative specification for the Agent Policy Layer (APL) wire
protocol: the frames, schemas, and rules a conforming policy **server** and **client**
exchange. It exists so that an independent implementation — in any language — can
interoperate with the reference implementation in this repository, and so that
cross-version compatibility can be reasoned about honestly rather than read out of the
code.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHOULD**, **SHOULD
NOT**, **MAY**, and **OPTIONAL** are to be interpreted as described in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

Where this document and the reference implementation disagree, that is a bug in one of
them; please file an issue. The reference implementation's types live in
[`apl/types.py`](apl/types.py) and its wire codec in
[`apl/serialization/`](apl/serialization/__init__.py).

---

## 1. Overview

APL wraps an AI agent in enforceable policies. At runtime the agent (the **client**)
emits a `PolicyEvent` at a lifecycle moment, sends it to one or more **policy servers**,
and each server returns zero or more `Verdict`s. The client **composes** the verdicts
into one decision and enforces it.

The protocol is:

- **JSON-based.** Every frame is a JSON object. Numbers, strings, booleans, arrays, and
  objects are standard JSON; timestamps are ISO 8601 strings (§4.3).
- **Transport-framed.** Two transports are defined: newline-delimited JSON over **stdio**
  (§6) and **HTTP** (§7). Both carry the same `PolicyEvent` and `Verdict` payloads.
- **Stateless per evaluation.** Each `evaluate` is self-contained; servers MUST NOT
  require prior evaluations to interpret a request. Session continuity, when needed,
  travels in `metadata` (§4.6).
- **Fail-closed.** A client that cannot obtain a well-formed verdict MUST treat the
  policy as *unavailable* and apply its configured fail mode (§8), which defaults to
  *deny*.

Policy **composition** (combining many verdicts into one) is a client-side concern and
is **not** part of the wire protocol; it is described informatively in §9 because the
reference HTTP server also returns an advisory composed verdict.

---

## 2. Versioning and compatibility

The protocol is versioned with a `MAJOR.MINOR.PATCH` string, single-sourced as
`PROTOCOL_VERSION`. It is **independent of the package version**: the PyPI package may
release many times without changing the protocol.

A server advertises its protocol version in the manifest (§5). On connect, a client
**MUST** compare it to its own using these rules (reference:
`_assert_protocol_compatible` in [`apl/layer/policy_client.py`](apl/layer/policy_client.py)):

| Server vs. client | Client behavior |
|---|---|
| Equal | Proceed. |
| Same `MAJOR`, different `MINOR`/`PATCH` | Proceed; SHOULD log a warning. |
| Different `MAJOR` | **Reject as unavailable** → fail closed (§8). |
| Either side unparseable | Proceed; SHOULD log a warning. |

The contract this encodes:

- A change that alters the meaning of an existing field, removes a field, or changes a
  frame's grammar is a **MAJOR** change.
- A backward-compatible addition (a new optional field, a new event type, a new
  enum member that older readers can ignore) is a **MINOR** change.
- Editorial or non-wire-affecting fixes are **PATCH** changes.

Because a differing major version fails closed, a client never silently trusts a server
whose wire semantics it cannot guarantee.

---

## 3. Encoding rules (the wire codec)

All payloads are encoded with the rules in [`apl/serialization/`](apl/serialization/__init__.py):

1. **`null` is omission.** A field whose value is `null`/`None` **MUST** be omitted from
   the serialized object rather than emitted as `null`. Readers **MUST** treat an absent
   field as its default.
2. **Empty collections are preserved.** An explicitly empty array or object (e.g.
   `llm_prompt: []`) **MUST** be transmitted as `[]`/`{}` and **MUST NOT** collapse to
   absent. The distinction between "no prompt field" and "an empty prompt" is semantic.
3. **Unknown fields are ignored (forward-compatibility).** A reader **MUST** accept and
   ignore object members it does not recognize. This is a deliberate forward-compat
   posture: a `MINOR`-newer peer can add fields without breaking an older reader. It is
   **not** a license to smuggle data — see the security note in §10. The one field that
   is **never** optional is verdict `confidence` (§4.8).

Implementations SHOULD encode UTF-8 JSON without insignificant whitespace.

---

## 4. Core schemas

The reference types are pydantic models in [`apl/types.py`](apl/types.py). The tables
below give field name, JSON type, and whether the field is REQUIRED on the wire (after
applying §3 rule 1). "default" is the value a reader assumes when the field is absent.

### 4.1 `EventType` (enum, string)

One of the 13 lifecycle events:

```
input.received   input.validated
plan.proposed    plan.approved
llm.pre_request  llm.post_response
tool.pre_invoke  tool.post_invoke
agent.pre_handoff agent.post_handoff
output.pre_send
session.start    session.end
```

A reader that receives an unrecognized event type **MUST** treat the event as
undecodable and fail closed (it cannot know which policies apply).

### 4.2 `Decision` (enum, string)

`allow` · `deny` · `modify` · `escalate` · `observe`.

### 4.3 Timestamps

Timestamps are ISO 8601 strings and **MUST** be timezone-aware. A naive timestamp
received on the wire is interpreted as UTC. (Reference: `_coerce_aware_utc`.)

### 4.4 `Message` (chat/completions shape)

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | string | yes | Conventionally `system`/`user`/`assistant`/`tool`; any string is accepted for provider pass-through. |
| `content` | string | no | |
| `name` | string | no | For tool messages. |
| `tool_calls` | array&lt;ToolCall&gt; | no | For assistant messages. |
| `tool_call_id` | string | no | For tool messages. |

`ToolCall` = `{ id: string, type: "function", function: { name: string, arguments:
string } }`. `arguments` is a JSON **string** (OpenAI convention). `function` is
REQUIRED within a `ToolCall`.

### 4.5 `EventPayload`

The per-event "delta". All fields OPTIONAL; different events populate different fields.

| Field | Type | Used by |
|---|---|---|
| `tool_name` | string | tool.* |
| `tool_args` | object | tool.* |
| `tool_result` | any | tool.post_invoke |
| `tool_error` | string | tool.post_invoke |
| `llm_model` | string | llm.* |
| `llm_prompt` | array&lt;Message&gt; | llm.pre_request |
| `llm_response` | Message | llm.post_response |
| `llm_tokens_used` | integer | llm.post_response |
| `output_text` | string | output.pre_send |
| `output_structured` | object | output.pre_send |
| `plan` | array&lt;string&gt; | plan.* |
| `target_agent` | string | agent.*_handoff |
| `source_agent` | string | agent.*_handoff |
| `handoff_payload` | object | agent.*_handoff |

### 4.6 `SessionMetadata`

| Field | Type | Default | Notes |
|---|---|---|---|
| `session_id` | string | random UUID | |
| `user_id` | string | absent | |
| `agent_id` | string | absent | |
| `token_count` | integer | `0` | |
| `token_budget` | integer | absent | |
| `cost_usd` | number | `0.0` | |
| `cost_budget_usd` | number | absent | |
| `user_roles` | array&lt;string&gt; | `[]` | |
| `user_region` | string | absent | GDPR / data residency. |
| `compliance_tags` | array&lt;string&gt; | `[]` | |
| `started_at` | timestamp | now (UTC) | Round-trips; aware. |
| `custom` | object | `{}` | Free-form extension point. |

### 4.7 `PolicyEvent` (the request payload)

| Field | Type | Default |
|---|---|---|
| `id` | string | random UUID |
| `type` | EventType | `input.received` |
| `timestamp` | timestamp | now (UTC) |
| `messages` | array&lt;Message&gt; | `[]` |
| `payload` | EventPayload | `{}` |
| `metadata` | SessionMetadata | defaults of §4.6 |

A server **MUST** echo the request `id` in its reply so the client can correlate
responses (load-bearing for stdio pipe integrity, §6.4).

### 4.8 `Verdict` (the response payload)

| Field | Type | Required | Notes |
|---|---|---|---|
| `decision` | Decision | yes | |
| `confidence` | number `[0,1]` | **yes (always)** | See below. |
| `reasoning` | string | no | |
| `modifications` | array&lt;Modification&gt; | conditionally | REQUIRED non-empty iff `decision == modify`. |
| `escalation` | Escalation | conditionally | REQUIRED iff `decision == escalate`. |
| `policy_name` | string | no | |
| `policy_version` | string | no | |
| `evaluation_ms` | number | no | |
| `trace` | object | no | |

**`confidence` is the one field that is REQUIRED even though §3 rule 1 omits `null`s.**
A reader **MUST** reject a verdict that omits `confidence` (rather than defaulting it to
`1.0`). Defaulting a missing confidence to full confidence would bias weighted
composition (§9) toward whatever the verdict decided — the wrong direction for a safety
system. A rejected verdict is treated as *unavailable* (§8). (Reference:
`verdict_from_wire`.)

**Decision invariants** (enforced on construction *and* deserialize):

- A `modify` verdict **MUST** carry at least one `Modification`.
- An `escalate` verdict **MUST** carry an `Escalation`.

`Modification` = `{ target, operation, value, path? }`:

- `target` ∈ `input` · `tool_args` · `llm_prompt` · `output` · `tool_result` · `plan` ·
  `handoff_payload`
- `operation` ∈ `replace` · `redact` · `append` · `prepend` · `patch`
- `path` is a JSON path, used only by `patch`.

`Escalation` = `{ type, prompt?, fallback_action?, timeout_ms?, options? }`:

- `type` ∈ `human_confirm` · `human_review` · `abort` · `fallback`

---

## 5. Manifest

A server describes itself with a `PolicyManifest`, returned on connect (§6.2, §7.2).

| Field | Type | Default | Notes |
|---|---|---|---|
| `server_name` | string | — | REQUIRED. |
| `server_version` | string | — | REQUIRED. Package/server version, not the protocol. |
| `protocol_version` | string | `0.3.0` | Drives §2 negotiation. |
| `policies` | array&lt;PolicyDefinition&gt; | `[]` | |
| `supports_batch` | boolean | `false` | Reserved; reference server evaluates one event per frame. |
| `supports_streaming` | boolean | `false` | Reserved. |
| `description` | string | absent | |
| `documentation_url` | string | absent | |

`PolicyDefinition`:

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string | — | REQUIRED. |
| `version` | string | — | REQUIRED. |
| `events` | array&lt;EventType&gt; | — | REQUIRED; the events this policy subscribes to. |
| `context_requirements` | array&lt;ContextRequirement&gt; | `[]` | Declared dot-paths the policy reads. |
| `blocking` | boolean | `true` | **Advisory.** See note below. |
| `timeout_ms` | integer | `1000` | Advisory per-policy evaluation bound. |
| `description` | string | absent | |
| `author` | string | absent | |
| `tags` | array&lt;string&gt; | `[]` | |

`ContextRequirement` = `{ path: string, required: boolean = true, description?:
string }`.

> **Note on `blocking`.** `blocking` is advertised in the manifest as an execution hint
> (a `false` value signals a policy whose verdict the agent need not await). The
> **reference enforcement path treats every policy as blocking** — it awaits all
> verdicts before composing — so today `blocking` is informational only: it is part of
> the published contract for clients that wish to implement fire-and-forget evaluation,
> but the reference client does not yet act on it. A conforming implementation MAY honor
> it; it MUST NOT assume the reference server does.

---

## 6. Transport: stdio

Reference: [`apl/transports/stdio.py`](apl/transports/stdio.py) (server),
[`apl/layer/client_transports/stdio_client_transport.py`](apl/layer/client_transports/stdio_client_transport.py)
(client).

### 6.1 Framing

Newline-delimited JSON (NDJSON): each frame is a single JSON **object** on one line,
terminated by `\n`. A frame **MUST NOT** contain a literal newline (encode it as `\n`
inside JSON strings). A frame **MUST NOT** exceed **16 MiB**; a larger frame fails
closed (the server logs and stops; the client raises *unavailable*).

A reader **MUST** skip a malformed (non-JSON or non-object) frame rather than abort the
read loop — one bad byte must never silently stop enforcement. (The client is stricter:
a malformed *response* to a request it sent fails that evaluation closed.)

### 6.2 Handshake

On startup the server **MUST** emit exactly one manifest frame before serving requests:

```json
{"type": "manifest", "manifest": { /* PolicyManifest, §5 */ }}
```

### 6.3 Request/response frames

| Direction | Frame |
|---|---|
| client → server | `{"type": "evaluate", "event": { /* PolicyEvent */ }}` |
| server → client | `{"type": "verdicts", "event_id": "<echoed id>", "verdicts": [ /* Verdict, … */ ]}` |
| client → server | `{"type": "ping"}` |
| server → client | `{"type": "pong"}` |
| client → server | `{"type": "shutdown"}` |

An unrecognized `type` SHOULD be logged and ignored by the server.

### 6.4 Integrity requirements

- The server **MUST** set `event_id` in a `verdicts` frame to the `id` of the event it
  answered. A client **MUST** correlate replies to requests by `event_id`; on a mismatch
  it **MUST** consider the pipe desynchronized, tear the connection down, and fail
  closed.
- A client sharing one subprocess across concurrent evaluations **MUST** serialize each
  write→read round-trip, so two requests cannot interleave on the pipe and cross
  verdicts.
- A spawned server is a separate trust domain. A client **SHOULD** strip secret-looking
  environment variables (API keys, tokens, credentials) before handing the child its
  environment.

---

## 7. Transport: HTTP

Reference: [`apl/transports/http/`](apl/transports/http/). The reference server binds
`127.0.0.1` by default and applies a request-size limit.

### 7.1 Endpoints

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/evaluate` | `PolicyEvent` (JSON) | `{ event_id, verdicts[], composed_verdict, evaluation_ms }` |
| `GET` | `/manifest` | — | `PolicyManifest` (§5) |
| `GET` | `/health` | — | `{ status, uptime_seconds?, requests_total? }` (liveness; intentionally low-disclosure) |
| `GET` | `/metrics` | — | Prometheus text exposition (`text/plain; version=0.0.4`) |
| `GET` | `/events` | — | Server-Sent Events keepalive stream (`text/event-stream`) |
| `GET` | `/` | — | `302` redirect to `/health` |

`POST /evaluate`:

- The request `Content-Type` **MUST** be `application/json`; otherwise the server
  returns `415`.
- `verdicts` are the authoritative per-policy results. `composed_verdict` is an
  **advisory** convenience the reference server computes with its default strategy
  (deny-overrides, §9); a client that composes its own verdicts (the reference client
  does) MAY ignore it.

### 7.2 Connect

A client connects by issuing `GET /manifest`. A non-`200` response, an unreachable host,
a timeout, or a malformed manifest body is an *availability failure* → fail closed (§8).
Redirects **MUST NOT** be followed (defends against SSRF and an `https→http` downgrade).
A client **SHOULD** cap the response body it will read (the reference caps at 16 MiB) so
a compromised server cannot exhaust client memory.

### 7.3 Authentication

Authentication is OPTIONAL and configured per server. When enabled, the server requires
`Authorization: Bearer <token>` on every non-public route and compares the token in
**constant time**. `/health` and `/` are public (liveness probes / orchestrators) even
when auth is enabled. A failed check returns `401` with the error envelope (§7.5). The
token MAY be supplied to the reference server via `--auth-token` or the `APL_AUTH_TOKEN`
environment variable.

### 7.4 CORS

CORS is **allow-list only**: the server reflects an `Origin` only when it is on the
configured list, and never emits a wildcard by default. Configuring a literal `*` in the
allow-list permits any origin and is reported with a startup warning. A preflight
`OPTIONS` for an allowed origin returns `204`; for a disallowed origin, `403`.

### 7.5 Error envelope

Error responses use a stable JSON envelope and **MUST NOT** echo the underlying
exception text:

```json
{"error": "<machine_code>", "message": "<fixed human string>", "request_id": "<id>"}
```

Defined codes: `invalid_json` (400), `invalid_request` (400),
`unsupported_media_type` (415), `payload_too_large` (413), `unauthorized` (401),
`internal_error` (500). Every response (including errors) carries an `X-Request-ID`
header.

---

## 8. Availability and fail modes

A policy is **unavailable** when it times out, raises, returns something that is not a
well-formed `Verdict` (including a verdict missing `confidence`, §4.8), or its server
cannot be reached.

A client **MUST** resolve an unavailable policy through its configured `FailMode`:

- **`closed`** (default, REQUIRED default): an unavailable policy **denies** the action.
- **`open`**: an unavailable policy **allows** the action. This disables enforcement on
  failure and **MUST** be an explicit opt-in; the reference implementation logs a warning
  when it is selected.

A layer-level timeout (bounding the *whole* evaluation across all servers) likewise
resolves to a single decision — `deny` by default. The unavailable verdict's `reasoning`
**SHOULD** record that this was an availability failure, distinct from a deliberate
policy decision.

---

## 9. Composition (informative)

Composition reduces many verdicts to one and is performed **by the client**; it is not
part of the wire protocol. It is documented here because the reference HTTP server also
returns an advisory `composed_verdict`, and because interoperable clients benefit from a
shared vocabulary. Reference: [`apl/composition/`](apl/composition/).

| Mode | Rule |
|---|---|
| `deny_overrides` (default) | any `deny` wins; else `escalate`; else apply all `modify`; else `allow`. |
| `allow_overrides` | any `allow` wins; else `modify`; else `escalate`; else `deny`. |
| `unanimous` | every non-`observe` verdict must be `allow`, else `deny`. |
| `first_applicable` | first non-`observe` verdict wins, in configured priority order. |
| `weighted` | `weight × confidence` vote; `escalate` short-circuits; `deny` wins ties. |

Two composition rules are load-bearing for safety and any reimplementation SHOULD match
them:

- **A server with no policy for an event abstains** (returns an empty verdict list) — it
  does **not** emit a full-confidence `allow`. An injected `allow` would out-vote a real
  `deny` from another server.
- **Modifications accumulate, ordered, and are not collapsed per target.** Two policies
  that both modify `output` (redact PII *and* append a disclaimer) both apply; only an
  exact-duplicate modification is dropped.

---

## 10. Security considerations

- **Fail closed (§8).** The single most important property: when in doubt, deny. Every
  ambiguous or failed path resolves to deny unless fail-open is explicitly selected.
- **`confidence` required (§4.8).** Prevents an under-specified verdict from silently
  scoring as fully confident.
- **Major-version gate (§2).** A client never trusts a server whose wire semantics it
  cannot guarantee.
- **Unknown fields are ignored, not trusted (§3 rule 3).** Ignoring unknown members
  buys forward-compatibility, but an implementation **MUST NOT** treat an unknown field
  as carrying privileged meaning, and **MUST NOT** reflect it back. Security-relevant
  semantics live only in the fields defined here. Unknown members are dropped on
  re-serialization (they are not round-tripped).
- **Transport hardening (HTTP).** Loopback bind by default, constant-time token compare,
  CORS allow-list, request-size limit, response-size cap, no redirect following, stable
  error envelope with no exception disclosure, suppressed server-identity headers.
- **Trust domains (stdio).** A spawned policy server does not inherit the agent's secret
  environment variables.

---

## 11. Conformance

A **conforming server** MUST: emit a valid manifest on connect; answer `evaluate` with a
`verdicts` frame echoing the request `id`; include `confidence` on every verdict; honor
the encoding rules of §3; and, over HTTP, implement the error envelope of §7.5.

A **conforming client** MUST: perform version negotiation per §2; reject a verdict
missing `confidence`; resolve unavailability through a fail mode defaulting to closed
(§8); and, over stdio, correlate replies by `event_id` (§6.4).

The reference implementation's behavior is pinned by the test suite in
[`tests/`](tests/); `tests/test_provider_patch_targets.py`,
`tests/test_serialization.py`, `tests/test_transports.py`, and `tests/test_layer.py` are
the closest executable companions to this document.

---

## Changelog

- **0.3.0** — Initial published specification of the existing `0.x` wire protocol. No
  wire change; this document makes the previously code-only contract explicit. See
  [`docs/adr/`](docs/adr/) for the decisions behind it.
