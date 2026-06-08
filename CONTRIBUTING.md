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

After `source scripts/dev.sh`, the pre-commit hook runs **ruff (format + lint),
docformatter, and mypy automatically on every `git commit`** — you don't run them
yourself. [CI](.github/workflows/ci.yml) re-runs the same checks across the whole
tree on every PR:

| Gate | Tool | Notes |
|---|---|---|
| Format | `ruff format` | Line length 88; replaces black. |
| Lint | `ruff check` | Rule set `E,F,W,I`. `E501` is off — the formatter owns line length. |
| Docstrings | `docformatter` | Config in `[tool.docformatter]`; `apl/templates.py` excluded (file templates, not docstrings). |
| Types | `mypy apl/` | `no_implicit_optional`, `warn_unused_ignores`, `warn_redundant_casts`; ships `py.typed`. |
| Tests | `pytest --cov` | `asyncio_mode = "auto"`; coverage must stay ≥ 80%. |
| Deps | `pip-audit` | Fails on known-vulnerable dependencies (CI). |

The Python tools in [.pre-commit-config.yaml](.pre-commit-config.yaml) run from
your `.venv` (`language: system`), so they always match the versions CI uses.

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
2. Commit normally — the hook formats, lints, and type-checks for you; run
   `pytest` to cover tests.
3. Write [Conventional Commits](#commit-messages-drive-releases-important) —
   release-please builds the changelog from them, so you don't touch `CHANGELOG.md`.
4. Open the PR; [CODEOWNERS](CODEOWNERS) are requested automatically, and CI must
   be green to merge.

## Versioning & releasing (FYI)

Two independent versions, and **you bump neither by hand**:

- **Package version** — `__version__` in [apl/__init__.py](apl/__init__.py), the
  single source the build reads (`[tool.hatch.version]`). **release-please owns
  it** — it writes the next value via the `# x-release-please-version` annotation
  when it opens the release PR. Editing it manually just fights the tooling.
- **Protocol version** — `PROTOCOL_VERSION` in [apl/types.py](apl/types.py). The
  wire-compatibility contract checked on connect; bump it by hand only when the
  event/verdict format changes, independently of package releases.

### Commit messages drive releases (important)

Releases are computed from **[Conventional Commits](https://www.conventionalcommits.org/)**,
so the commit *type* is what picks the next version — the format is not optional:

| Prefix | Example | Version effect (while on `0.x`) |
|---|---|---|
| `fix:` | `fix: bind --http 0 correctly` | patch — `0.3.0` → `0.3.1` |
| `feat:` | `feat: add serve --max-body flag` | minor — `0.3.0` → `0.4.0` |
| `feat!:` / `BREAKING CHANGE:` in body | `feat!: remove --stdio flag` | minor pre-1.0 — `0.3.0` → `0.4.0` |
| `chore:` `docs:` `refactor:` `test:` `ci:` `perf:` | `docs: fix a typo` | no release on their own |

Optional scope (`feat(cli): …`); keep the subject imperative and ≤ ~72 chars.

### Cutting a release

You don't tag or publish anything by hand:

1. Merge Conventional-Commit PRs to `main`.
2. [release-please](.github/workflows/release-please.yml) keeps an open
   **"chore: release X.Y.Z" PR** that bumps the version and updates
   [CHANGELOG.md](CHANGELOG.md) from your commits.
3. **Merge that release PR** → it tags `vX.Y.Z`, creates the GitHub Release, and
   publishes to **PyPI** via OIDC.

Dev builds need no action either: every push to `main` runs
[dev-release.yml](.github/workflows/dev-release.yml), which builds a wheel + sdist,
attests their build provenance, and replaces a single rolling **`dev`** GitHub
pre-release. The version is the *next* patch as a PEP 440 dev release
(`X.Y.Z.devN+gSHA`), so it sorts above the last stable tag.

### Installing a dev build

Dev builds let you try an unreleased fix before it reaches PyPI. **They are not for
production** — the `dev` pre-release is mutable and unsupported.

Pull the latest wheel from the rolling pre-release into a throwaway environment:

```bash
# isolate it — never install a dev build into your global interpreter
python -m venv .venv-dev && source .venv-dev/bin/activate   # or: uv venv .venv-dev

gh release download dev --repo nimonkaranurag/agentpolicylayer --pattern '*.whl'
pip install ./agent_policy_layer-*.whl                      # or: uv pip install ./agent_policy_layer-*.whl
```

Three practices keep this reproducible and safe:

- **Pin the resolved version, not the `dev` tag.** The pre-release is *rolling* — its
  artifacts are overwritten on every push to `main` — so "the dev build" is a moving
  target. Capture the exact `X.Y.Z.devN+gSHA` (`pip show agent-policy-layer`) and the
  commit it was cut from; that string is what makes a result reproducible later.
- **Verify provenance before you install.** Each artifact ships a build attestation,
  so you can confirm CI built it from this repo rather than trusting the download:
  ```bash
  gh attestation verify ./agent_policy_layer-*.whl --repo nimonkaranurag/agentpolicylayer
  ```
- **Keep it out of shared lockfiles.** Don't commit a dev wheel into a project's
  pinned requirements; use it only in a scratch env, and switch back to a released
  build from PyPI (`pip install agent-policy-layer`) for anything you ship.

## Security

Found a vulnerability? **Don't open a public issue** — see [SECURITY.md](SECURITY.md)
for private reporting.
