# 0004. Unknown wire fields are ignored (forward-compatibility)

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

Under the major-version compatibility rule ([ADR 0003](0003-major-version-protocol-compatibility.md)),
a minor-newer peer may add fields a minor-older peer has never seen. The reader has to do
*something* with an unrecognized object member: reject the whole payload (`extra =
"forbid"`), preserve it untouched (`extra = "allow"`), or drop it (`extra = "ignore"`).

This is a deliberate posture decision for a **security** wire format, and a code review
flagged that it was undocumented — the behavior fell out of pydantic's default rather
than a stated choice, which is exactly the kind of implicit contract a security protocol
should not have.

- `forbid` would make every additive, minor-compatible change a hard break, defeating
  ADR 0003.
- `allow` (preserve and round-trip unknown members) is dangerous: it lets an unknown
  field ride through the system and potentially be reflected to another component that
  *does* attribute meaning to it — a smuggling channel.

## Decision

We will **ignore** unknown fields: accept them on read, drop them, and never round-trip
them. This is now stated normatively in SPEC §3 (rule 3) and §10, and asserted explicitly
in code on the top-level wire models (`PolicyEvent`, `Verdict`, `PolicyManifest`) via
`model_config = ConfigDict(extra="ignore")` with a comment pointing at this ADR — so the
posture is a written contract, not an inherited default.

The one field that is *never* optional remains verdict `confidence`
([ADR 0002](0002-confidence-required-on-the-wire.md)); forward-compat tolerance for
*additions* does not extend to *omissions* of required fields.

## Consequences

- Additive, minor-compatible protocol evolution works: an older reader silently tolerates
  a newer peer's extra fields.
- No unknown field can become a covert channel: unknown members are dropped, never
  reflected, and never granted meaning. Security-relevant semantics live only in the
  fields SPEC defines.
- Implementers in other languages have an explicit rule to match, instead of having to
  reverse-engineer pydantic's defaults.
