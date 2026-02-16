from __future__ import annotations

import sys

import click
from rich.console import Console

from .. import __version__
from .formatting import RichGroup

console = Console()


@click.group(cls=RichGroup)
@click.version_option(
    version=__version__, prog_name="APL"
)
def cli():
    """Portable, composable policies for AI agents."""
    pass


from . import commands  # noqa: E402, F401


def main():
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down...[/dim]")
        sys.exit(0)
