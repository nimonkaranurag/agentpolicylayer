# APL documentation

| Document | What it covers |
|---|---|
| [`../SPEC.md`](../SPEC.md) | **Normative** wire-protocol specification: frames, schemas, version negotiation, fail modes, conformance. Read this to build an interoperable client or server. |
| [`../README.md`](../README.md) | Product overview, install, quick start, and the Python/CLI/HTTP API surface. |
| [`adr/`](adr/) | Architecture Decision Records — the *why* behind the load-bearing design choices, captured at the point of decision. |

## Layout

- **`SPEC.md`** lives at the repository root so it sits beside `README.md` and is easy to
  find from the project page. It is versioned independently of the package (it tracks
  `PROTOCOL_VERSION` in [`apl/types.py`](../apl/types.py)).
- **`docs/adr/`** holds one immutable record per significant decision. ADRs are append-
  only: a decision is changed by adding a new ADR that supersedes an old one, never by
  editing history.

## Contributing to the docs

- A change to the **wire protocol** (a new field, a new frame, changed semantics) MUST
  update `SPEC.md` and bump `PROTOCOL_VERSION` according to the rules in SPEC §2.
- A new **design decision** of consequence SHOULD be recorded as an ADR using
  [`adr/template.md`](adr/template.md).
