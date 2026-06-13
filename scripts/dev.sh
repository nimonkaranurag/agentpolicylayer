#!/usr/bin/env bash
# One-command dev environment for agent-policy-layer.
#
#     source scripts/dev.sh
#
# Syncs a uv-managed virtualenv (.venv) from the committed uv.lock with all dev +
# optional dependencies (editable), installs the pre-commit hooks, and activates the
# env in your current shell. Idempotent — re-run it any time; uv caches everything.

# Repo root, resolved from git so this works from anywhere inside the tree
# (bash or zsh), without fragile $0 / BASH_SOURCE handling.
_apl_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$_apl_root" ]; then
  echo "error: run this from inside the agent-policy-layer git repository"
  return 1 2>/dev/null || exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed. Install it with one of:"
  echo "    brew install uv"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  return 1 2>/dev/null || exit 1
fi

echo "==> syncing env from uv.lock (.venv, python 3.12, all extras, editable)"
# `uv sync` installs the *locked* versions from uv.lock (creating/managing .venv
# itself) and installs this project editable — so local dev matches the committed
# lock instead of re-resolving floors every time. --all-extras pulls dev + cli +
# http + langgraph. CI verifies the lock stays in sync (uv lock --check).
( cd "$_apl_root" && uv sync --all-extras --python 3.12 ) \
  || { echo "error: uv sync failed"; return 1 2>/dev/null || exit 1; }

# shellcheck disable=SC1091
source "$_apl_root/.venv/bin/activate" \
  || { echo "error: failed to activate venv"; return 1 2>/dev/null || exit 1; }

echo "==> installing pre-commit hooks"
pre-commit install \
  || { echo "error: pre-commit install failed"; return 1 2>/dev/null || exit 1; }

echo ""
echo "✅ dev environment ready — .venv active, hooks installed."
echo "   commits now run ruff + docformatter + mypy automatically."
echo "   full check suite:  pre-commit run --all-files"
echo "   tests:             pytest"

# If executed instead of sourced, activation won't persist in the caller's shell.
if ! (return 0 2>/dev/null); then
  echo ""
  echo "note: you ran this script instead of sourcing it, so .venv is NOT active"
  echo "      in your shell. Re-run with:  source scripts/dev.sh"
fi
