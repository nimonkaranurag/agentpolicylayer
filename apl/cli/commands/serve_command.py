from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from ... import __version__
from ...logging import setup_logging
from .. import cli, console
from ..branding import BannerRenderer, StatusPrinter
from ..formatting import RichCommand
from ..loaders import PolicyLoaderRegistry
from ..renderers import (
    PolicyTreeRenderer,
    ServerPanelRenderer,
)

_banner = BannerRenderer(console, __version__)
_status = StatusPrinter(console)
_loader_registry = PolicyLoaderRegistry()


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--http",
    "http_port",
    type=int,
    default=None,
    help="Enable HTTP transport on this port",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="HTTP host to bind to",
)
@click.option(
    "--stdio",
    is_flag=True,
    default=False,
    help="Use stdio transport (default)",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Minimal output",
)
def serve(
    path: str,
    http_port: Optional[int],
    host: str,
    stdio: bool,
    verbose: bool,
    quiet: bool,
):
    """
    Run a policy server.

    Examples:
      apl serve ./pii_filter.py
      apl serve ./policies/
      apl serve ./policy.yaml
      apl serve ./my_policy.py --http 8080
    """
    if not quiet:
        _banner.render("small")
        console.print()

    log_level = (
        "DEBUG"
        if verbose
        else "INFO" if not quiet else "WARNING"
    )
    logger = setup_logging(
        level=log_level, rich_output=not stdio
    )

    path_obj = Path(path)
    if not _loader_registry.find_loader_for_path(path_obj):
        _status.print(
            f"Unsupported file type: {path_obj.suffix}",
            "error",
        )
        sys.exit(1)

    if not quiet:
        _status.print(
            f"Loading: [cyan]{path}[/cyan]", "loading"
        )

    server = _loader_registry.load(path_obj, logger)
    if server is None:
        _status.print(
            "Failed to load policy server", "error"
        )
        sys.exit(1)

    if not quiet:
        PolicyTreeRenderer(console).render(server)

    if http_port:
        _serve_over_http(
            server, host, http_port, logger, quiet
        )
    else:
        _serve_over_stdio(server, quiet)


def _serve_over_http(server, host, port, logger, quiet):
    if not quiet:
        _status.print(
            f"Starting HTTP server on"
            f" [cyan]http://{host}:{port}[/cyan]",
            "security",
        )
        ServerPanelRenderer(console).render(host, port)

    server.run(
        transport="http",
        host=host,
        port=port,
        apl_logger=logger,
    )


def _serve_over_stdio(server, quiet):
    if not quiet:
        _status.print(
            "Starting stdio transport", "security"
        )
        console.print()
        console.print(
            "  [dim]Waiting for events on stdin...[/dim]"
        )
        console.print("  [dim]Press Ctrl+C to stop[/dim]")
        console.print()
    server.run(transport="stdio")
