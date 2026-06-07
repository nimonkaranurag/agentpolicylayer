# Contributing to Agent Policy Layer

Thanks for contributing! APL is a security control for AI agents, so the bar is
high on correctness, types, and tests. This guide covers local setup, the exact
checks CI runs, and how releases work.

## Development setup

You need [uv](https://docs.astral.sh/uv/) — `brew install uv`, or
`curl -LsSf https://astral.sh/uv/install.sh | sh`. Then, from a clone:

```bash
source scripts/dev.sh
```

That one command creates a uv-managed virtualenv (`.venv`), installs APL with all
dev + optional dependencies, installs the pre-commit hooks, and activates the env
in your shell. It's idempotent — re-run it any time.

From here on, **`git commit` runs ruff (format + lint), docformatter, and mypy
automatically** via pre-commit, so formatting and linting are handled for you.

## What runs on every commit & PR

`pre-commit` runs these on your changes at commit time; [CI](.github/workflows/ci.yml)
runs them across the whole tree on every PR. You rarely need to run them by hand —
but `pre-commit run --all-files` runs the full set, and `pytest` runs the tests.

| Gate | Tool | Notes |
|---|---|---|
| Format | `ruff format` | Line length 88; replaces black. |
| Lint | `ruff check` | Rule set `E,F,W,I`. `E501` is off — the formatter owns line length. |
| Docstrings | `docformatter` | Config in `[tool.docformatter]`; `apl/templates.py` excluded (file templates, not docstrings). |
| Types | `mypy apl/` | `no_implicit_optional`, `warn_unused_ignores`, `warn_redundant_casts`; ships `py.typed`. |
| Tests | `pytest --cov` | `asyncio_mode = "auto"`; coverage must stay ≥ 80%. |
| Deps | `pip-audit` | Fails on known-vulnerable dependencies (CI). |

The Python tools in [.pre-commit-config.yaml](.pre-commit-config.yaml) run from
your `.venv` (`language: system`), so they always match the versions CI uses —
there's no second pinned version to drift.

## Coding conventions

- **Fail closed.** APL is a guardrail; on error, policies deny by default (see
  `FailMode`). New evaluation paths must never silently fall back to "allow."
- **Types are not optional.** Public APIs are fully typed. Domain models are
  pydantic v2 — clone with `model_copy`, and (de)serialize through the
  `apl.serialization` codec rather than hand-rolling serializers.
- Prefer adding to an existing, cohesive module over a new one-class file.
- Match the style of the surrounding code.

## Tests

- Put tests in `tests/`, named `test_*.py`. Async tests need no decorator
  (`asyncio_mode = "auto"`).
- Cover the failure path, not just the happy path — especially deny/escalate/
  modify verdicts, timeouts, and transport errors.
- Keep patch coverage ≥ 80% (enforced via [codecov.yml](codecov.yml)).

## Pull requests

1. Branch from `main` (e.g. `yourname/short-description`).
2. Make sure `pre-commit run --all-files` is green and tests pass.
3. Add an entry to [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]`.
4. Open the PR; [CODEOWNERS](CODEOWNERS) are requested automatically, and CI must
   be green to merge.

## Versioning & releasing

There are **two independent versions** — don't conflate them:

- **Package version** — `__version__` in [apl/\_\_init\_\_.py](apl/__init__.py). The
  single source of truth: `pyproject.toml` reads it dynamically
  (`[tool.hatch.version]`) and the CLI/manifest import it. **Bumping this one
  string is the whole release** — that's why there's no `RELEASING.md`.
- **Protocol version** — `PROTOCOL_VERSION` in [apl/types.py](apl/types.py). The
  wire-compatibility contract checked on connect. Bump it only when the
  event/verdict protocol changes, independently of package releases.

To cut a release:

1. Bump `__version__` in `apl/__init__.py` (semver).
2. Move `## [Unreleased]` entries under a new `## [X.Y.Z]` heading in `CHANGELOG.md`.
3. Merge to `main`, then publish a **GitHub Release** tagged `vX.Y.Z`.
4. [publish.yml](.github/workflows/publish.yml) builds and publishes to **PyPI**
   via OIDC trusted publishing (no API tokens to manage).

Dev builds are automatic — you don't manage them by hand:

- **Every push to `main`** publishes an installable **dev wheel**
  (`X.Y.Z.devN+gSHA`) to the rolling `dev` pre-release — the test-fest channel:
  ```bash
  gh release download dev --repo nimonkaranurag/agentpolicylayer --pattern '*.whl'
  pip install ./agent_policy_layer-*.whl
  ```
- Container images for `apl serve` go to **GHCR**
  (`ghcr.io/nimonkaranurag/agentpolicylayer`): `:dev` and `:sha-<short>` on main,
  `:X.Y.Z` and `:latest` on release.

## Security

Found a vulnerability? **Don't open a public issue** — see [SECURITY.md](SECURITY.md)
for private reporting.
