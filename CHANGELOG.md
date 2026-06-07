# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), and from the next
release onward versions are cut automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional
Commits.

## [0.4.0](https://github.com/nimonkaranurag/agentpolicylayer/compare/agent-policy-layer-v0.3.0...agent-policy-layer-v0.4.0) (2026-06-07)


### ⚠ BREAKING CHANGES

* release 0.4.0
* policies now fail closed (errors deny instead of allow); the `--stdio` serve flag is removed (stdio is the default, `--http` is the switch); PolicyLayer.wrap() raises TypeError on unsupported objects instead of silently no-op'ing; domain models are pydantic v2 with stricter validation.

### Features

* add contributor ecosystem, more engineering enhancements, bug fixes and doc-improvements ([99faea9](https://github.com/nimonkaranurag/agentpolicylayer/commit/99faea986d39a708e78b001e3d7b112b6d3b74da))
* agent context protocol (APL) ([ee4d461](https://github.com/nimonkaranurag/agentpolicylayer/commit/ee4d461b3354ebfbc64dbc24aa6bac05bd01239c))
* cleanup and demo ([0614259](https://github.com/nimonkaranurag/agentpolicylayer/commit/06142590cd25758dc4a5a72bc0559c1d36db2f46))
* release 0.4.0 ([d3a66af](https://github.com/nimonkaranurag/agentpolicylayer/commit/d3a66affdffe60faa1bb89893ccedfd2819b33c6))
* release 0.4.0 ([b1b167e](https://github.com/nimonkaranurag/agentpolicylayer/commit/b1b167edd6eec795408a2bd996d820758d04bc1b))
* release workflows ([31f03a6](https://github.com/nimonkaranurag/agentpolicylayer/commit/31f03a637115573d31e49aaaa5850a92262f5d68))


### Bug Fixes

* **ci:** add a jobs key to .yml ([2ea16c0](https://github.com/nimonkaranurag/agentpolicylayer/commit/2ea16c0fbd7e07ef896d88b7b4a7ae52e7bca3ff))

## [Unreleased]

The engineering revamp (WP-0 – WP-11): the layer no longer fails open, the wire
format is validated, and the over-decomposed structure is consolidated.

### Security
- **Fail-closed by default.** Every failure site — policy timeout, exception,
  non-200 response, missing response, or a non-`Verdict` return — now **denies**
  instead of allowing. Configurable via `FailMode {OPEN, CLOSED}`; unreachable
  policies raise `PolicyUnavailableError`; fail-open must be opted into and warns
  at startup. (WP-1)
- **Streaming is enforced** — streamed model output is buffered and evaluated
  instead of bypassing the layer. (WP-6)
- **Transport hardening** — the HTTP policy server binds `127.0.0.1` by default,
  uses a CORS allow-list (never `*`), supports optional bearer-token auth and a
  request-size limit, and returns a 4xx envelope instead of echoing exceptions. (WP-7, WP-9)
- **Protocol-version check on connect** — a major-version mismatch denies rather
  than risking a silent semantic divergence. (WP-5)
- **Log-injection closed** — remote-sourced `verdict.reasoning` (and all
  interpolated log values) are markup-escaped, and `tracebacks_show_locals`
  defaults to `False` so prompts/keys/PII don't leak into logs. (WP-8)
- **Duplicate policy names fail closed** in the registry (`DuplicatePolicyError`)
  instead of silently dropping one. (WP-9)

### Added
- `instrument(...)` context manager that always restores patches on exit. (WP-8)
- `PolicyLayer.fail_mode` property and the `FailMode` configuration. (WP-1, WP-8)
- `apl serve` flags: `--host`, `--auth-token`, `--cors-origin` (repeatable),
  `--max-body`. (WP-7, WP-9)
- Release & CI engineering: automated release-please releases, rolling `dev`
  pre-release wheels on every push to main, CodeQL,
  Dependabot, SHA-pinned actions, build-provenance + SBOM, pre-commit hooks, and
  the `CONTRIBUTING` / `SECURITY` / `CODE_OF_CONDUCT` / issue + PR scaffolding.

### Changed
- **Domain models migrated to pydantic v2** — validated on deserialize; clone via
  `model_copy`; six hand-written serializers replaced by one codec. (WP-5)
- **Idempotent, transactional monkeypatching** with rollback, and reentrancy
  isolation via `ContextVar`. (WP-6)
- `PolicyLayer.wrap()` now delegates to the real `APLGraphWrapper` and raises
  `TypeError` on an unsupported object instead of silently returning it unwrapped
  (a no-op wrap = zero enforcement). `APLGraphWrapper` is exported via a lazy
  module `__getattr__`, keeping the optional `langgraph` extra off the common
  import path. (WP-8, WP-10)
- **Unified logging** through `get_logger` / `APLLogger`; `auto_instrument` /
  `uninstrument` no longer print to stdout. (WP-8)
- **CLI consolidated 33 → 11 files**; the misleading `--stdio` flag is removed
  (stdio is the default, `--http` is the switch) and serve chrome goes to stderr
  so stdout stays clean for the JSON protocol. (WP-9)
- Version single-sourced from `apl/__init__.py` via `[tool.hatch.version]`;
  `PROTOCOL_VERSION` tracked separately. (WP-8, WP-11)
- `Modification.target` widened to the seven targets the event table applies;
  `Message.role` relaxed from a `Literal` to `str` for provider pass-through. (WP-4, WP-5)
- Transport reliability — client/server timeouts, stderr drain, and
  kill-escalation on close. (WP-7)

### Fixed
- `Modification.operation` is now honored everywhere (it was ignored at ~15 apply
  sites). (WP-4)
- Composition correctness (WP-2) and declarative-engine correctness — YAML is
  validated **on load**, so a bad operator is refused up front instead of denying
  at the first event. (WP-3, WP-9)
- CLI: `--http 0` now binds (was a truthiness bug); a bad `--event` exits with a
  usage error instead of a traceback; the directory loader imports each file under
  a unique module name (no `sys.modules` clobber). (WP-9)

## [0.3.0]

[Unreleased]: https://github.com/nimonkaranurag/agentpolicylayer/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nimonkaranurag/agentpolicylayer/releases/tag/v0.3.0
