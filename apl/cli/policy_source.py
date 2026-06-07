"""
Load and validate policy sources for the CLI.

One suffix-dispatched module replaces the parallel loader/validator class
hierarchies: a ``.py`` file, a ``.yaml``/``.yml`` file, or a directory of ``.py``
files all resolve through the same :func:`load_policy_server` /
:func:`validate_policy` entry points. The source kinds form a closed set, so plain
``if``/``elif`` dispatch is the right tool — no registry or ABC needed.

Two safety properties for a guardrails CLI:

* **Unique module names.** Each Python policy file is imported under a name derived
  from its absolute path, so loading several files never lets one clobber another in
  ``sys.modules`` (the old shared ``"policy_module"`` key did).
* **Fail closed on ambiguity.** A directory that defines two policies with the same
  name is rejected rather than silently keeping one; an invalid YAML policy is
  refused at load time instead of denying at the first matching event.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import Optional

from ..server import PolicyServer

YAML_SUFFIXES = (".yaml", ".yml")


def is_supported_path(path: Path) -> bool:
    """
    Return ``True`` if ``path`` is a policy source this module can load.
    """
    return path.is_dir() or path.suffix == ".py" or path.suffix in YAML_SUFFIXES


def load_policy_server(path: Path, logger) -> Optional[PolicyServer]:
    """
    Load a :class:`~apl.server.PolicyServer` from a file or directory.

    Returns ``None`` (and logs the reason) on any failure, including an unsupported
    suffix, an invalid YAML policy, or a duplicate policy name within a directory.
    """
    if path.is_dir():
        return _load_directory(path, logger)
    if path.suffix == ".py":
        return _load_python_file(path, logger)
    if path.suffix in YAML_SUFFIXES:
        return _load_yaml(path, logger)

    logger.error(f"Unsupported policy source: {path.suffix or path}")
    return None


def validate_policy(path: Path) -> list[str]:
    """
    Statically validate a policy source, returning a list of error strings.

    An empty list means the source is valid. Directories are validated file by file;
    YAML validation is delegated to the declarative engine's validator.
    """
    if path.is_dir():
        return _validate_directory(path)
    if path.suffix == ".py":
        return _validate_python(path)
    if path.suffix in YAML_SUFFIXES:
        from ..declarative_engine import validate_yaml_policy

        return validate_yaml_policy(path)

    return [f"Unsupported policy source: {path.suffix or path}"]


# ---------------------------------------------------------------------------
# Python files
# ---------------------------------------------------------------------------


def _load_python_file(path: Path, logger) -> Optional[PolicyServer]:
    try:
        module = _import_isolated_module(path)
    except Exception as exc:
        logger.error(f"Failed to load {path}: {exc}")
        return None

    server = _find_server_in_module(module)
    if server is None:
        logger.error(f"No PolicyServer instance found in {path}")
    return server


def _find_server_in_module(module) -> Optional[PolicyServer]:
    for name in dir(module):
        candidate = getattr(module, name)
        if isinstance(candidate, PolicyServer):
            return candidate
    return None


def _import_isolated_module(path: Path):
    """
    Import ``path`` as a module under a unique, path-derived name.

    Using a per-file name (rather than a shared ``"policy_module"`` key) keeps two
    policy files from overwriting each other in ``sys.modules`` and gives every loaded
    symbol a correct ``__module__`` for tracebacks and ``inspect``.
    """
    module_name = _unique_module_name(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _unique_module_name(path: Path) -> str:
    safe = re.sub(r"\W", "_", str(path.resolve()))
    return f"apl_policy_{safe}"


def _validate_python(path: Path) -> list[str]:
    try:
        source = path.read_text()
    except OSError as exc:
        return [f"Cannot read file: {exc}"]

    try:
        ast.parse(source)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]

    # Import directly (not via _load_python_file) so a load-time error — e.g. a
    # duplicate policy name raised by the registry — is surfaced verbatim rather
    # than masked as a generic "no PolicyServer".
    try:
        module = _import_isolated_module(path)
    except Exception as exc:
        return [f"Failed to load: {exc}"]

    server = _find_server_in_module(module)
    if server is None:
        return ["No PolicyServer instance found"]
    if not server.registry.all_policies():
        return ["PolicyServer has no registered policies"]
    return []


# ---------------------------------------------------------------------------
# Directories of Python files
# ---------------------------------------------------------------------------


def _loadable_python_files(path: Path) -> list[Path]:
    return sorted(
        file
        for file in path.iterdir()
        if file.suffix == ".py" and not file.name.startswith("_")
    )


def _load_directory(path: Path, logger) -> Optional[PolicyServer]:
    files = _loadable_python_files(path)
    if not files:
        logger.error(f"No loadable .py policies found in {path}")
        return None

    server = PolicyServer(name=path.name, version="1.0.0")
    defining_file: dict[str, str] = {}

    for file in files:
        sub_server = _load_python_file(file, logger)
        if sub_server is None:
            continue

        for policy in sub_server.registry.all_policies():
            if policy.name in defining_file:
                logger.error(
                    f"Duplicate policy name {policy.name!r} in {file.name} "
                    f"(already defined in {defining_file[policy.name]})"
                )
                return None  # fail closed: an ambiguous policy set is not served
            defining_file[policy.name] = file.name
            server.registry.register(policy)

    if not defining_file:
        logger.error(f"No PolicyServer instances found in {path}")
        return None
    return server


def _validate_directory(path: Path) -> list[str]:
    files = _loadable_python_files(path)
    if not files:
        return [f"No loadable .py policies found in {path}"]

    errors: list[str] = []
    for file in files:
        errors.extend(f"{file.name}: {error}" for error in _validate_python(file))
    return errors


# ---------------------------------------------------------------------------
# YAML files
# ---------------------------------------------------------------------------


def _load_yaml(path: Path, logger) -> Optional[PolicyServer]:
    from ..declarative_engine import load_yaml_policy, validate_yaml_policy

    # Validate before loading: a typo'd operator or malformed modification block
    # loads fine but denies at the first matching event, so refuse it up front.
    errors = validate_yaml_policy(path)
    if errors:
        logger.error(f"Invalid YAML policy {path}:")
        for error in errors:
            logger.error(f"  - {error}")
        return None

    try:
        return load_yaml_policy(path)
    except Exception as exc:
        logger.error(f"Failed to load YAML policy: {exc}")
        return None
