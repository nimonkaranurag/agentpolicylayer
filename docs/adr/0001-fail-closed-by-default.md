# 0001. Fail closed by default

- **Status:** Accepted
- **Date:** 2026-06-07

## Context

APL is a guardrails layer: agents call it to *constrain* behavior (block PII, confirm
destructive tool calls, enforce budgets). Such a layer has many failure sites — a policy
server is unreachable, a policy times out, a handler raises, a policy returns something
that is not a `Verdict`, the layer-level timeout fires. Each of those has two possible
defaults: treat the failure as *allow* (let the action through) or as *deny* (block it).

A layer that allows on failure is worse than no layer at all, because it advertises
enforcement it does not deliver: the moment a policy server hiccups, every constraint
silently evaporates while the dashboard still says "protected". For a security control,
the dangerous default is the permissive one.

## Decision

We will **fail closed by default**. An *unavailable* policy — timeout, exception,
non-`Verdict` return, missing `confidence`, unreachable server, or expired layer timeout
— resolves to **deny**, governed by a `FailMode` enum whose default is `CLOSED`.
Fail-open (`FailMode.OPEN`) exists for deployments that want it, but it MUST be selected
explicitly and it logs a warning at startup. (See `apl/types.py: FailMode`,
`Verdict.unavailable`, and `CompositionConfig`.)

## Consequences

- A flaky or unreachable policy server degrades to *blocking* rather than *silently
  permitting* — the safe direction for a security control.
- Operators must run policy servers with the availability they would give any
  in-band dependency; an outage denies traffic. This is the intended pressure.
- Fail-open is a deliberate, audited, logged choice, not an accident of a missing
  `try/except`. The whole 0.4.0 security sweep was about removing accidental fail-open
  paths.
- This default propagates into the wire protocol (SPEC §8) and the version-negotiation
  rule ([ADR 0003](0003-major-version-protocol-compatibility.md)): an
  incompatible server is "unavailable", hence a deny.
