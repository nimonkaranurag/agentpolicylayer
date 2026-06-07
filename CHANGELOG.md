# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Release engineering: rolling `dev` pre-release wheels on every push to `main`
  (`X.Y.Z.devN+gSHA`), a GHCR container image for `apl serve`, build-provenance
  attestation, and an SBOM on release.
- Supply-chain hardening: CodeQL analysis, Dependabot (pip + GitHub Actions), and
  all workflow actions pinned to commit SHAs.
- Contributor scaffolding: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  pre-commit hooks, `.editorconfig`, and issue/PR templates.

### Changed
- The package version is now single-sourced from `apl/__init__.py` and read
  dynamically by the build (`[tool.hatch.version]`), so a release is one string to
  bump. The wire-protocol version (`PROTOCOL_VERSION`) is tracked separately.

## [0.3.0]

Baseline of the engineering revamp — fail-closed defaults, pydantic v2 domain
models, and hardened transports and instrumentation.

[Unreleased]: https://github.com/nimonkaranurag/agentpolicylayer/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nimonkaranurag/agentpolicylayer/releases/tag/v0.3.0
