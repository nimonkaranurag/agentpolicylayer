from __future__ import annotations

import sys

import click
from rich.console import Console

from .. import __version__
from .formatting import RichGroup

console = Console()
# Human-facing chrome for `serve` goes here so stdout stays clean for the
# newline-delimited JSON the stdio transport speaks.
err_console = Console(stderr=True)


@click.group(cls=RichGroup)
@click.version_option(version=__version__, prog_name="APL")
def cli():
    """
    Portable, composable policies for AI agents.
    """
    pass


from . import commands  # noqa: E402, F401


def main():
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down...[/dim]")
        sys.exit(0)
