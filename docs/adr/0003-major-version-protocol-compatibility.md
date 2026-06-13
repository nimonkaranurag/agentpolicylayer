# 0003. Protocol compatibility is gated on the major version

- **Status:** Accepted
- **Date:** 2026-06-07

## Context

A client and a policy server are versioned independently and may be built from different
releases. The protocol carries a `PROTOCOL_VERSION` (`MAJOR.MINOR.PATCH`) in the
manifest. We need a compatibility rule that is strict enough to refuse genuinely
incompatible wire semantics but loose enough that a routine minor-version skew between an
agent and its policy servers does not take the whole layer down.

The options span a spectrum: require an exact version match (too brittle — every release
breaks every deployment), ignore the version entirely (unsafe — a client trusts wire
semantics it cannot guarantee), or gate on a component of the version.

## Decision

We will gate on the **major version only** (SemVer semantics). On connect the client
compares the server's `PROTOCOL_VERSION` to its own:

- equal → proceed;
- same major, differing minor/patch → proceed with a warning;
- **differing major → reject as unavailable** (fail closed,
  [ADR 0001](0001-fail-closed-by-default.md));
- unparseable on either side → proceed with a warning.

This binds the version numbers to a contract: a breaking wire change MUST be a major
bump; a backward-compatible addition is a minor bump (which older readers tolerate via
the forward-compat rule, [ADR 0004](0004-unknown-wire-fields-are-ignored.md)). (See
`apl/layer/policy_client.py: _assert_protocol_compatible`.)

## Consequences

- Minor/patch skew between an agent and its policy servers is a warning, not an outage.
- A major mismatch denies rather than risking silent semantic divergence — the safe
  failure.
- Maintainers take on a real obligation: a change that alters existing field meaning,
  removes a field, or changes a frame grammar MUST bump the major version. SPEC §2
  codifies this so the obligation is auditable, not folklore.
