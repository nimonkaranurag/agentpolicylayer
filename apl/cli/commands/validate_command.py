from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import cli, console
from ..branding import print_status, render_banner
from ..formatting import RichCommand
from ..policy_source import validate_policy


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
def validate(path: str):
    """
    Validate a policy file without running it.

    Examples:
      apl validate ./my_policy.py
      apl validate ./policy.yaml
    """
    render_banner(console, "mini")
    console.print()

    print_status(console, f"Validating: [cyan]{path}[/cyan]", "loading")

    errors = validate_policy(Path(path))
    if errors:
        print_status(console, "Validation failed", "error")
        for error in errors:
            console.print(f"    [red]•[/red] {error}")
        sys.exit(1)

    print_status(console, "Validation passed!", "success")
