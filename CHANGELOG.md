# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), and from the next
release onward versions are cut automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional
Commits.

## [Unreleased]

## [0.5.1](https://github.com/nimonkaranurag/agentpolicylayer/compare/agent-policy-layer-v0.5.0...agent-policy-layer-v0.5.1) (2026-06-13)

### Added

- **Protocol specification.** A normative, versioned [`SPEC.md`](SPEC.md) — frame
  grammar, manifest/event/verdict schemas, version negotiation, fail modes, and a
  conformance section — plus a [`docs/`](docs/) tree and five
  [ADRs](docs/adr/). The previously code-only wire contract is now explicit enough for
  an independent implementation.
- **`APL_AUTH_TOKEN` environment variable** for the HTTP bearer token: `apl serve
  --auth-token` falls back to it, so the secret needn't sit in argv (visible to any
  local process via `ps`/`/proc`).
- **Python 3.14** is supported and tested — added to the classifiers and the CI test
  matrix, alongside a new macOS lane.
- Documented the optional-extras install (`[cli]` / `[http]` / `[langgraph]` /
  `[all]`) in the README, and linked the protocol spec.

### Security

- **A wildcard CORS allow-list is no longer silent.** Configuring a literal `*`
  (which reflects *any* `Origin`) now logs a warning when the HTTP app is built.
- **Unknown wire fields have an explicit forward-compat posture.** `PolicyEvent`,
  `Verdict`, and `PolicyManifest` now declare `extra="ignore"` deliberately — unknown
  fields are accepted and dropped, never trusted or round-tripped (SPEC §3/§10,
  ADR 0004) — instead of inheriting the behavior as an undocumented pydantic default.

### Fixed

- **Honest coverage measurement.** Coverage is measured against `apl` only with branch
  coverage on (`[tool.coverage]`; CI runs `--cov=apl`); the previous bare `--cov`
  counted `tests/` in the denominator and reported an inflated number with no branch
  coverage. The floor is now an apl-only branch-coverage ratchet (84%; currently
  85.82%).
- **Broken CHANGELOG compare link.** The 0.4.0 entry compared against a nonexistent
  `agent-policy-layer-v0.3.0` tag; corrected to the real `v0.3.0` tag.
- The pre-commit config no longer claims its hooks "can't drift" from CI — they run
  from a once-installed `.venv`, which can lag the dependency floors CI fresh-installs.

### Changed

- **Instrumentation patch targets are actually exercised.** Each provider's
  `patch_all_methods()` now runs against a module-shaped SDK stub
  (`openai`/`anthropic`/`litellm`/`watsonx`) installed into `sys.modules`, so the
  import paths and request/response shapes that break on an SDK release are executed in
  CI — not just the suite's own fake provider.
- **`uv.lock` is consumed instead of dead.** Local dev provisions from it via
  `uv sync` (`scripts/dev.sh`), CI verifies it stays current (`uv lock --check`), and
  the lock was refreshed (it had drifted to pre-0.5 dependencies).
- **`blocking` is documented as advisory.** The per-policy `blocking` manifest field
  is an advertised execution hint, not enforced by the reference layer (which awaits
  every policy before composing); see SPEC §5.
- **Endpoint and weak-test coverage.** The README-documented `/metrics`, `/manifest`,
  and `/events` HTTP endpoints are now tested, and four weak tests were hardened (an
  assertion-free logging test, a rule loop that passed vacuously on a `None`
  regression, annotation-source-string assertions, and fake-only message coverage).

## [0.5.0](https://github.com/nimonkaranurag/agentpolicylayer/compare/agent-policy-layer-v0.4.0...agent-policy-layer-v0.5.0) (2026-06-13)

### ⚠ BREAKING CHANGES

- **CLI and HTTP dependencies are now optional extras.** The base install carries
  only the core runtime (`pydantic`, `pyyaml`, and `rich` — the last used by the
  injection-safe log renderer). The `apl` command-line tool now requires
  `pip install 'agent-policy-layer[cli]'` (adds `click`) and the HTTP transport
  (server *and* client) requires `agent-policy-layer[http]` (adds `aiohttp`);
  `agent-policy-layer[all]` installs every runtime feature. An embedder doing
  in-process or stdio evaluation no longer drags CLI/HTTP dependencies in.
  Requesting an unavailable subsystem fails with an actionable install hint.

### Security

A sweep of *quiet* non-enforcement paths — cases where APL reported (or implied)
that it had enforced something it had not. All now fail closed.

- **Composition no longer fails open.** Two policies modifying the same target
  (e.g. redact PII **and** append a disclaimer on `output`) both apply instead of
  the last silently dropping the first; weighted ties resolve to **deny** (not
  allow); a server with no policy for an event **abstains** (empty verdict list)
  instead of emitting a full-confidence ALLOW that out-voted a real deny;
  `first_applicable` lets the first verdict actually win; `allow_overrides` no
  longer flips ALLOW→DENY when a monitoring-only OBSERVE verdict is present.
- **Streaming and modern entry points are enforced.** Anthropic streaming is read
  via its `content_block_delta` shape (previously every chunk extracted `""`, so
  the output policy never ran). The OpenAI Responses API, `beta.chat.completions.
  parse`, and LangChain `.stream()`/`.astream()` are now instrumented; Anthropic's
  bespoke `messages.stream()` helper is a documented exclusion.
- **Modifications fail closed.** The three modification appliers were unified into
  one shared, fail-closed function: a MODIFY targeting a slot the enforcement point
  can't apply now raises instead of being silently skipped while the action
  proceeds unmodified.
- **The declarative engine no longer silently never-fires.** `apl validate` checks
  each `when` dot-path against the event model (a typo like `payload.output_txt` is
  rejected), requires `then.decision`, and validates `in` arguments are lists (a
  string argument was substring matching — an allowlist bypass). Unmatched policies
  return OBSERVE-with-trace, not a bare ALLOW.
- **stdio transport integrity.** The client now correlates each reply to the
  request it sent (`event_id`) under a per-transport lock, tearing the subprocess
  down and failing closed on a mismatch or a cancelled read — fixing wrong-verdict
  delivery and post-timeout desync under concurrent `evaluate`. Oversize frames
  (>16 MiB) fail closed instead of crashing with an uncaught `LimitOverrunError`,
  and a spawned policy server no longer inherits the agent's secret env vars.
- **A misconfigured layer fails closed.** A `PolicyLayer` with no `add_server()`
  now denies (per `fail_mode`) with a warning instead of silently allowing
  everything; one unreachable server degrades to a deny in its own evaluation
  instead of wedging the whole layer.
- **HTTP client hardening.** Response bodies are read with a 16 MiB cap (a
  compromised server could otherwise OOM the agent), redirects are not followed
  (SSRF / https→http downgrade), and a bearer token can be supplied via
  `add_server(uri, token=...)`.
- **Verdict/type invariants & info disclosure.** `Verdict` is `validate_assignment`
  (mutating it re-checks invariants), `on_timeout` is constrained to allow/deny,
  naive datetimes are coerced to UTC, policy exception text is no longer echoed
  into `verdict.reasoning`, `GET /health` no longer discloses server
  name/version/policy-count to an unauthenticated caller, and the default aiohttp
  `Server` version header is suppressed.

### Added

- `PolicyLayer.add_server(uri, *, token=...)` — bearer-token auth for the HTTP
  client, so auth-protected "shared org policies" servers are reachable.
- Declarative policies accept a per-policy `default_decision` (`deny`/`allow`/
  `observe`) controlling what an unmatched policy returns — a default-deny
  allowlist is now expressible.
- Request-side MODIFY (`input`/`llm_prompt`) is converted back to each provider's
  native message shape and written to the slot the SDK actually reads.

### Fixed

- The decorator's MODIFY now writes `tool_args` back to the positional slot it came
  from, so the README's own `call_tool("name", {...})` call style no longer raises
  `TypeError: multiple values for argument 'tool_args'`.
- `auto_instrument` is refused (clear error) if APL is already instrumented, and
  `uninstrument` closes the policy layer's subprocesses/sessions before tearing
  down the background loop instead of leaking them.
- Fixed `examples/usage_demo.py` to be compatible with `v0.4.0` of APL.
- HTTP server: `GET /` now redirects to `/health` instead of erroring — the route
  handler was synchronous, which aiohttp 3.x rejects at request time.
- CI (was failing): Type-checking (`mypy`) reported errors have been fixed.

### Changed

- **Releases are gated on green CI.** The automated PyPI publish
  (`release-please.yml`) now runs lint + type-check + the full test matrix before
  shipping, so a release cut from a red commit can no longer publish an
  unrecoverable broken wheel; the rolling `dev` wheel is tested before it's
  published; and the manual `publish.yml` matrix matches CI (3.10–3.13, `[dev,all]`).
- README updates.

## [0.4.0](https://github.com/nimonkaranurag/agentpolicylayer/compare/v0.3.0...agent-policy-layer-v0.4.0) (2026-06-07)

### ⚠ BREAKING CHANGES

- **Fail-closed by default.** (See Security below for full details.)
- The `--stdio` serve flag is removed (stdio is the default, `--http` is the
  switch).
- `PolicyLayer.wrap()` raises `TypeError` on unsupported objects instead of
  silently returning them unwrapped (a no-op wrap = zero enforcement).
- Domain models are pydantic v2 with stricter validation. `Verdict` invariants
  are enforced (e.g. `MODIFY` requires ≥1 modification, `ESCALATE` requires
  escalation, `confidence` must be in `[0, 1]`).
- `ToolCall.function` is now required.
- `Message.role` relaxed from a `Literal` to `str` for provider pass-through.
- `Modification.target` widened to the seven targets the event table applies.
- HTTP server binds `127.0.0.1` by default (was `0.0.0.0`).
- CORS is now allow-list only (was unconditional `*`).

### Security

- **Fail-closed by default.** Every failure site — policy timeout, exception,
  non-200 response, missing response, or a non-`Verdict` return — now **denies**
  instead of allowing. Configurable via `FailMode {OPEN, CLOSED}`; unreachable
  policies raise `PolicyUnavailableError`; fail-open must be opted into and warns
  at startup.
- **Streaming is enforced** — streamed model output is buffered and evaluated
  instead of bypassing the layer.
- **Transport hardening** — the HTTP policy server binds `127.0.0.1` by default,
  uses a CORS allow-list (never `*`), supports optional bearer-token auth and a
  request-size limit, and returns a 4xx envelope instead of echoing exceptions.
- **Protocol-version check on connect** — a major-version mismatch denies rather
  than risking a silent semantic divergence.
- **Log-injection closed** — remote-sourced `verdict.reasoning` (and all
  interpolated log values) are markup-escaped, and `tracebacks_show_locals`
  defaults to `False` so prompts/keys/PII don't leak into logs.
- **Duplicate policy names fail closed** in the registry (`DuplicatePolicyError`)
  instead of silently dropping one.
- **Port auto-kill deleted** — the `SIGKILL`-an-arbitrary-process-on-`EADDRINUSE`
  behavior is gone; replaced with clean `errno`-based error reporting.

### Added

- `instrument(...)` context manager that always restores patches on exit.
- `PolicyLayer.fail_mode` property and the `FailMode` configuration.
- `Verdict.unavailable()` factory for fail-closed transport/timeout denials.
- `apl serve` flags: `--host`, `--auth-token`, `--cors-origin` (repeatable),
  `--max-body`.
- `APLGraphWrapper` exported via lazy module `__getattr__` — `from apl import
  APLGraphWrapper` works without pulling in `langgraph` on the common import path.
- One shared `apply_operation` dispatcher honoring all five `Modification.operation`
  values (replace/redact/append/prepend/patch-by-`path`).
- Release & CI engineering: automated release-please releases, rolling `dev`
  pre-release wheels on every push to main, CodeQL, Dependabot, SHA-pinned
  actions, build-provenance + SBOM, pre-commit hooks, and the `CONTRIBUTING` /
  `SECURITY` / `CODE_OF_CONDUCT` / issue + PR scaffolding.
- `pytest-asyncio` collected-async == executed-async guard in `conftest.py` — a
  missing plugin can never again silently skip async tests.

### Changed

- **Domain models migrated to pydantic v2** — validated on deserialize; clone via
  `model_copy`; the 6 hand-written serializers replaced by a 4-function codec.
- **Idempotent, transactional monkeypatching** with rollback, and reentrancy
  isolation via `ContextVar`.
- `PolicyLayer.wrap()` now delegates to the real `APLGraphWrapper` and raises
  `TypeError` on an unsupported object instead of silently returning it unwrapped.
- **Unified logging** through `get_logger` / `APLLogger`; `auto_instrument` /
  `uninstrument` no longer print to stdout.
- **CLI consolidated 33 → 11 files**; the misleading `--stdio` flag is removed
  (stdio is the default, `--http` is the switch) and serve chrome goes to stderr
  so stdout stays clean for the JSON protocol.
- **Events consolidated 15 → 2 files** — a declarative `EventSpec` table replaces
  the 15 near-identical event classes.
- **Transports consolidated 19 → 7 files** — `stdio.py`, `routes.py`,
  `middleware.py` replace the one-function-per-file layout.
- **Adapters consolidated 6 → 1 file** — `adapters/langgraph.py` with a
  running-loop-aware sync bridge (no more `asyncio.run` landmine).
- **Composition strategies now receive config** — `WeightedStrategy` honours
  per-policy `weights`, `FirstApplicableStrategy` honours `priority` ordering,
  and `UnanimousStrategy` implements real unanimity (was silently identical to
  deny-overrides).
- Layer-level `timeout_ms`/`on_timeout` wired via `asyncio.wait_for`.
- Version single-sourced from `apl/__init__.py` via `[tool.hatch.version]`;
  `PROTOCOL_VERSION` tracked separately.
- `Modification.target` widened to the seven targets the event table applies;
  `Message.role` relaxed from a `Literal` to `str` for provider pass-through.
- Transport reliability — client/server timeouts, stderr drain, and
  kill-escalation on close.
- Stdio server: a malformed frame is logged and skipped, no longer fatal.
- HTTP client errors return 4xx with a stable `{error, message, request_id}`
  envelope instead of raw 500s with exception strings.
- Request-id is now the outermost middleware (present on every error response).
- `ruff` (format + lint) replaces `black` + `isort`.

### Fixed

- `Modification.operation` is now honored everywhere (it was ignored at ~15 apply
  sites).
- `UnanimousStrategy` implements real unanimity (was silently identical to
  deny-overrides).
- `CompositionConfig.weights`, `.priority`, `.timeout_ms`, `.on_timeout` are no
  longer dead fields — all four are wired and tested.
- `AllowOverridesStrategy` empty-input returns ALLOW (LSP-consistent with other
  strategies).
- Composition correctness and declarative-engine correctness — YAML is validated
  **on load**, so a bad operator is refused up front instead of denying at the
  first event.
- Dot-path traversal resolves `Mapping` keys before attribute access (`items`,
  `keys`, `values` etc. no longer return dict methods).
- Unknown YAML condition operators raise at eval and are caught by the validator.
- CLI: `--http 0` now binds (was a truthiness bug); a bad `--event` exits with a
  usage error instead of a traceback; the directory loader imports each file under
  a unique module name (no `sys.modules` clobber).
- `started_at` now round-trips (was write-only, resetting to "now" every hop).
- An explicit `llm_prompt=[]` is preserved distinct from `None`.
- Missing/out-of-range `confidence` is rejected fail-closed (was silently
  defaulted to 1.0).
- LangGraph adapter: session-id uses `thread_id` (stable across nodes/turns);
  `MODIFY` verdicts are applied to graph state; sync bridge uses a persistent
  loop (no fresh `asyncio.run` per node).
- 8 async tests that were silently not executing now run (`pytest-asyncio` pinned).

## [0.3.0]

- Initial public release.

[Unreleased]: https://github.com/nimonkaranurag/agentpolicylayer/compare/agent-policy-layer-v0.5.1...HEAD
[0.3.0]: https://github.com/nimonkaranurag/agentpolicylayer/releases/tag/v0.3.0
