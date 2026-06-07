from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from ...logging import setup_logging
from .. import cli, err_console
from ..branding import print_status, render_banner
from ..formatting import RichCommand
from ..policy_source import is_supported_path, load_policy_server
from ..renderers import render_policy_tree, render_server_panel


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--http",
    "http_port",
    type=int,
    default=None,
    help="Serve over HTTP on this port (default: stdio)",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="HTTP host to bind to (use 0.0.0.0 to expose externally)",
)
@click.option(
    "--auth-token",
    default=None,
    help="Require this bearer token on HTTP requests",
)
@click.option(
    "--cors-origin",
    "cors_origins",
    multiple=True,
    help="Allowed CORS origin (repeatable); omit to send no CORS headers",
)
@click.option(
    "--max-body",
    "max_body_bytes",
    type=int,
    default=None,
    help="Max HTTP request body size in bytes",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output")
def serve(
    path: str,
    http_port: Optional[int],
    host: str,
    auth_token: Optional[str],
    cors_origins: tuple[str, ...],
    max_body_bytes: Optional[int],
    verbose: bool,
    quiet: bool,
):
    """
    Run a policy server.

    Serves over stdio by default; pass ``--http PORT`` to serve over HTTP instead.
    Human-readable output goes to stderr so stdout stays clean for the stdio
    protocol.

    Examples:
      apl serve ./pii_filter.py
      apl serve ./policies/
      apl serve ./policy.yaml
      apl serve ./my_policy.py --http 8080
    """
    if not quiet:
        render_banner(err_console, "small")
        err_console.print()

    log_level = "DEBUG" if verbose else "WARNING" if quiet else "INFO"
    logger = setup_logging(level=log_level)

    path_obj = Path(path)
    if not is_supported_path(path_obj):
        print_status(err_console, f"Unsupported source: {path_obj.suffix}", "error")
        sys.exit(1)

    if not quiet:
        print_status(err_console, f"Loading: [cyan]{path}[/cyan]", "loading")

    server = load_policy_server(path_obj, logger)
    if server is None:
        print_status(err_console, "Failed to load policy server", "error")
        sys.exit(1)

    if not quiet:
        render_policy_tree(err_console, server)

    # Port 0 is a valid request (the OS assigns an ephemeral port), so the switch
    # is "was --http given", not the truthiness of the port number.
    if http_port is not None:
        _serve_over_http(
            server,
            host=host,
            port=http_port,
            logger=logger,
            quiet=quiet,
            auth_token=auth_token,
            cors_origins=list(cors_origins),
            max_body_bytes=max_body_bytes,
        )
    else:
        _serve_over_stdio(server, quiet)


def _serve_over_http(
    server,
    *,
    host: str,
    port: int,
    logger,
    quiet: bool,
    auth_token: Optional[str],
    cors_origins: list[str],
    max_body_bytes: Optional[int],
):
    if not quiet:
        print_status(
            err_console,
            f"Starting HTTP server on [cyan]http://{host}:{port}[/cyan]",
            "security",
        )
        render_server_panel(err_console, host, port)

    run_kwargs = dict(
        transport="http",
        host=host,
        port=port,
        apl_logger=logger,
        auth_token=auth_token,
        cors_origins=cors_origins,
    )
    if max_body_bytes is not None:
        run_kwargs["max_request_bytes"] = max_body_bytes

    server.run(**run_kwargs)


def _serve_over_stdio(server, quiet: bool):
    if not quiet:
        print_status(err_console, "Starting stdio transport", "security")
        err_console.print()
        err_console.print("  [dim]Waiting for events on stdin...[/dim]")
        err_console.print("  [dim]Press Ctrl+C to stop[/dim]")
        err_console.print()
    server.run(transport="stdio")
