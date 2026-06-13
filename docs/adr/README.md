# Architecture Decision Records

An **Architecture Decision Record (ADR)** captures a single significant decision: the
context that forced it, the choice made, and the consequences accepted. The format is
Michael Nygard's; records are short, immutable, and numbered.

These ADRs document decisions that are **already implemented** in the codebase — they
exist to explain *why* the code is the way it is, not to propose changes.

| # | Title | Status |
|---|---|---|
| [0001](0001-fail-closed-by-default.md) | Fail closed by default | Accepted |
| [0002](0002-confidence-required-on-the-wire.md) | `confidence` is required on the wire | Accepted |
| [0003](0003-major-version-protocol-compatibility.md) | Protocol compatibility is gated on the major version | Accepted |
| [0004](0004-unknown-wire-fields-are-ignored.md) | Unknown wire fields are ignored (forward-compat) | Accepted |
| [0005](0005-cli-and-http-are-optional-extras.md) | CLI and HTTP dependencies are optional extras | Accepted |

## Adding an ADR

Copy [`template.md`](template.md) to `NNNN-short-title.md` (next number, zero-padded),
fill it in, and add a row above. To reverse a past decision, add a *new* ADR that
supersedes the old one and update the old one's status to `Superseded by NNNN` — never
rewrite an accepted record.
