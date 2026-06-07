from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apl.cli.policy_source import validate_policy

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"


def test_python_policy_examples_validate_clean():
    for filename in (
        "pii_filter.py",
        "budget_limiter.py",
        "confirm_destructive.py",
    ):
        assert validate_policy(EXAMPLES_DIR / filename) == []


def test_usage_demo_runs_from_an_arbitrary_working_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "usage_demo.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Modified output: Your SSN is [SSN REDACTED]" in result.stdout
    assert "ESCALATION REQUIRED" in result.stdout
    assert "Final Decision: deny" in result.stdout
