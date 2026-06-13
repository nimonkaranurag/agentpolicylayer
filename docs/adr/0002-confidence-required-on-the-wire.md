# 0002. `confidence` is required on the wire

- **Status:** Accepted
- **Date:** 2026-06-07

## Context

A `Verdict` carries a `confidence` in `[0, 1]`. The `weighted` composition strategy sums
`weight × confidence` across verdicts to decide between allow and deny, so `confidence`
is not decorative — it is a vote weight in a safety decision.

Pydantic gives `confidence` a default of `1.0`. If the wire codec accepted a verdict that
omitted `confidence`, a server (buggy, older, or hostile) could send `{"decision":
"allow"}` and have it silently count as a **maximally confident** allow — the single most
effective value for overturning a real deny in weighted composition. The permissive
default points the wrong way for a security system.

## Decision

We will make `confidence` **required on the wire**, even though the general codec rule is
"omit `null`s" (SPEC §3). `verdict_from_wire` rejects any payload that lacks `confidence`
before validation, and a rejected verdict is treated as *unavailable* — hence fail-closed
per [ADR 0001](0001-fail-closed-by-default.md). (See
`apl/serialization/__init__.py: verdict_from_wire`.)

## Consequences

- A verdict can never silently inherit `1.0`. An under-specified verdict denies (closed)
  rather than scoring as a confident allow.
- Conforming servers MUST always serialize `confidence`. The reference `to_wire` does, so
  same-implementation traffic is unaffected; the rule only bites malformed or adversarial
  payloads.
- This is the one documented exception to the "absent field = default" rule, and SPEC
  §4.8 calls it out explicitly so independent implementers do not treat it as an
  oversight.
