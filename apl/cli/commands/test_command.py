from __future__ import annotations

import asyncio
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
from ..renderers import VerdictTableRenderer
from ..testing import TestEventFactory

_banner = BannerRenderer(console, __version__)
_status = StatusPrinter(console)
_loader_registry = PolicyLoaderRegistry()
_event_factory = TestEventFactory()
_verdict_renderer = VerdictTableRenderer(console)


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "-e", "--event", default="output.pre_send",
    help="Event type to test",
)
@click.option(
    "-p", "--payload", default=None,
    help="JSON payload",
)
def test(
    path: str, event: str, payload: Optional[str]
):
    """
    Test a policy with sample events.

    Examples:
      apl test ./pii_filter.py
      apl test ./policy.yaml -e tool.pre_invoke
    """
    _banner.render("mini")
    console.print()
    _status.print(
        f"Testing: [cyan]{path}[/cyan]", "loading"
    )

    path_obj = Path(path)
    logger = setup_logging(
        level="WARNING", rich_output=True
    )

    server = _loader_registry.load(path_obj, logger)
    if not server:
        _status.print(
            "Failed to load policy", "error"
        )
        sys.exit(1)

    test_event = _event_factory.build(event, payload)

    console.print()
    _status.print(
        f"Event type: [cyan]{event}[/cyan]", "info"
    )

    verdicts = asyncio.run(
        server.evaluate(test_event)
    )
    _verdict_renderer.render(verdicts)
