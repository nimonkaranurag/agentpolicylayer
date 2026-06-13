"""
Console-script entry point for the ``apl`` command.

Kept *outside* the ``apl.cli`` package on purpose: importing any ``apl.cli`` submodule
first runs ``apl/cli/__init__.py``, which imports ``click``. By putting the entry here
we can catch a missing ``cli`` extra and print an actionable install hint instead of a
raw ``ImportError`` traceback.
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from apl.cli import main as _cli_main
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        sys.stderr.write(
            "The `apl` command-line tool requires the 'cli' extra:\n"
            "    pip install 'agent-policy-layer[cli]'\n"
            f"(missing dependency: {exc.name})\n"
        )
        raise SystemExit(1) from exc

    _cli_main()
