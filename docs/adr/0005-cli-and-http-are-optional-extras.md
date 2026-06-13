# 0005. CLI and HTTP dependencies are optional extras

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The smallest useful APL deployment is an embedder evaluating policies **in process** or
over **stdio**. That path needs only the core runtime: `pydantic` (domain types),
`pyyaml` (declarative policies + serialization), and `rich` (the injection-safe log
renderer in `apl.logging`, used everywhere, not just the CLI).

Two genuine subsystems sit on top of that core and carry heavier dependencies: the `apl`
command-line tool (`click`) and the HTTP transport — both server and client — (`aiohttp`).
Forcing every consumer to install `click` and `aiohttp` taxes the common in-process/stdio
case for features it does not use, and enlarges the dependency and attack surface of a
security library.

## Decision

We will ship the CLI and HTTP subsystems as **optional extras**, with the base install
carrying only the core runtime:

- `pip install agent-policy-layer` → core (in-process + stdio).
- `agent-policy-layer[cli]` → the `apl` command (`click`).
- `agent-policy-layer[http]` → the HTTP transport (`aiohttp`).
- `agent-policy-layer[langgraph]` → the LangGraph adapter.
- `agent-policy-layer[all]` → every runtime feature.

Requesting a subsystem whose extra is not installed fails with an actionable install
hint, not a raw `ImportError`: the `apl` entry point is a thin shim
(`apl/_cli_entry.py`) that catches a missing `cli` extra and prints the hint. (This was a
breaking change, released in 0.5.0.)

## Consequences

- The default install is smaller and has a narrower dependency/attack surface — the right
  default for a security library.
- In-process and stdio embedders no longer drag in `click`/`aiohttp`.
- Consumers of the CLI or HTTP transport must request the matching extra. This is a
  documented breaking change (README "Install"; CHANGELOG 0.5.0) and the failure mode is
  a clear hint rather than a stack trace.
