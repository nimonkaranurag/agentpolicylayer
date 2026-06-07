from __future__ import annotations

import sys

import click

from .. import cli, console
from ..branding import print_status, render_banner
from ..formatting import RichCommand


@cli.command(cls=RichCommand)
@click.argument("name")
@click.option(
    "-t",
    "--template",
    type=click.Choice(["basic", "pii", "budget", "confirm"]),
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
    render_banner(console, "mini")
    console.print()

    from ...templates import create_policy_project

    print_status(console, f"Creating policy project: [cyan]{name}[/cyan]", "loading")

    try:
        project_path = create_policy_project(name, template)
    except Exception as exc:
        print_status(console, f"Failed to create project: {exc}", "error")
        sys.exit(1)

    print_status(console, f"Created project at: [cyan]{project_path}[/cyan]", "success")
    console.print()
    console.print("  [bold]Next steps:[/bold]")
    console.print(f"    [dim]$[/dim] cd {name}")
    console.print("    [dim]$[/dim] apl serve policy.py")
    console.print()
