from __future__ import annotations

import sys
from pathlib import Path

import click

from ... import __version__
from .. import cli, console
from ..branding import BannerRenderer, StatusPrinter
from ..formatting import RichCommand
from ..validators import PolicyValidatorRegistry

_banner = BannerRenderer(console, __version__)
_status = StatusPrinter(console)
_validator_registry = PolicyValidatorRegistry()


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
def validate(path: str):
    """
    Validate a policy file without running it.

    Examples:
      apl validate ./my_policy.py
      apl validate ./policy.yaml
    """
    _banner.render("mini")
    console.print()

    _status.print(
        f"Validating: [cyan]{path}[/cyan]", "loading"
    )

    try:
        path_obj = Path(path)
        errors = _validator_registry.validate(path_obj)

        if errors:
            _status.print("Validation failed", "error")
            for error in errors:
                console.print(f"    [red]•[/red] {error}")
            sys.exit(1)
        else:
            _status.print("Validation passed!", "success")

    except Exception as e:
        _status.print(f"Validation error: {e}", "error")
        sys.exit(1)
