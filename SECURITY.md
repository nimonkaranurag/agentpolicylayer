# Security Policy

Agent Policy Layer is a guardrail that enforces policies on AI agents, so we take
security issues seriously.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Use GitHub's private vulnerability reporting instead:

1. Go to the [Security tab → Report a vulnerability](https://github.com/nimonkaranurag/agentpolicylayer/security/advisories).
2. Describe the issue, affected versions, and a reproduction if you have one.

You'll get an acknowledgement within a few business days. We'll work with you on a
fix and coordinated disclosure, and credit you in the advisory unless you prefer
otherwise.

## What we're most interested in

- **Fail-open bypasses** — any path where a policy error, timeout, or malformed
  response causes an action to be *allowed* instead of denied. APL defaults to
  fail-closed; regressions here are high severity.
- Transport issues in the HTTP/stdio policy servers — auth bypass, CORS
  misconfiguration, request smuggling, resource exhaustion.
- Instrumentation bypasses where patched LLM calls escape policy evaluation.

## Hardening when you deploy

- Keep the HTTP policy server bound to `127.0.0.1` (the default) unless you
  intend to expose it, and require the bearer token when you do.
- Keep dependencies current — `pip-audit` runs in CI and Dependabot proposes
  updates weekly.
