from __future__ import annotations

import sys

import click

from ... import __version__
from .. import cli, console
from ..branding import BannerRenderer, StatusPrinter
from ..formatting import RichCommand

_banner = BannerRenderer(console, __version__)
_status = StatusPrinter(console)


@cli.command(cls=RichCommand)
@click.argument("name")
@click.option(
    "-t",
    "--template",
    type=click.Choice(
        ["basic", "pii", "budget", "confirm"]
    ),
    default="basic",
    help="Template to use",
)
def init(name: str, template: str):
    """
    Initialize a new policy project.

    Examples:
      apl init my-policy
      apl init compliance --template pii
    """
    _banner.render("mini")
    console.print()

    from ...templates import create_policy_project

    _status.print(
        f"Creating policy project:"
        f" [cyan]{name}[/cyan]",
        "loading",
    )

    try:
        project_path = create_policy_project(
            name, template
        )
        _status.print(
            f"Created project at:"
            f" [cyan]{project_path}[/cyan]",
            "success",
        )

        console.print()
        console.print("  [bold]Next steps:[/bold]")
        console.print(f"    [dim]$[/dim] cd {name}")
        console.print(
            f"    [dim]$[/dim] apl serve policy.py"
        )
        console.print()

    except Exception as e:
        _status.print(
            f"Failed to create project: {e}", "error"
        )
        sys.exit(1)
