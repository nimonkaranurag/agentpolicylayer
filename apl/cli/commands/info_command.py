from __future__ import annotations

import sys

import click
from rich import box
from rich.table import Table

from ... import __version__
from .. import cli, console
from ..branding import BannerRenderer
from ..formatting import RichCommand

_banner = BannerRenderer(console, __version__)

TRANSPORT_ENTRIES = [
    (
        "[green]✓[/green]",
        "stdio",
        "Local subprocess communication",
    ),
    ("[green]✓[/green]", "HTTP", "REST API with SSE"),
    ("[yellow]○[/yellow]", "WebSocket", "Coming soon"),
]

ADAPTER_ENTRIES = [
    ("[green]✓[/green]", "LangGraph", "StateGraph wrapper"),
    ("[green]✓[/green]", "OpenAI", "Auto-instrumentation"),
    (
        "[green]✓[/green]",
        "Anthropic",
        "Auto-instrumentation",
    ),
    ("[green]✓[/green]", "LiteLLM", "Auto-instrumentation"),
    ("[green]✓[/green]", "LangChain", "ChatModel wrapper"),
    ("[yellow]○[/yellow]", "AutoGen", "Coming soon"),
    ("[yellow]○[/yellow]", "CrewAI", "Coming soon"),
]


class SystemInfoRenderer:
    def __init__(self):
        self._console = console

    def render(self):
        self._render_system_properties()
        self._render_capability_table(
            "Transports", TRANSPORT_ENTRIES, "Transport"
        )
        self._render_capability_table(
            "Framework Adapters",
            ADAPTER_ENTRIES,
            "Framework",
        )
        self._render_links()

    def _render_system_properties(self):
        table = Table(
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 2),
        )
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Version", __version__)
        table.add_row("Python", sys.version.split()[0])
        table.add_row("Platform", sys.platform)
        table.add_row("Protocol", "0.1.0")

        self._console.print(table)
        self._console.print()

    def _render_capability_table(
        self, title, entries, name_column_header
    ):
        self._console.print(f"  [bold]{title}[/bold]")
        table = Table(
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 1),
            show_edge=False,
        )
        table.add_column("Status", width=3)
        table.add_column(name_column_header)
        table.add_column("Description", style="dim")

        for status, name, description in entries:
            table.add_row(status, name, description)

        self._console.print(table)
        self._console.print()

    def _render_links(self):
        self._console.print("  [bold]Links[/bold]")
        self._console.print(
            "    [link=https://github.com/nimonkaranurag/"
            "agentpolicylayer]"
            "https://github.com/nimonkaranurag/"
            "agentpolicylayer[/link]"
        )
        self._console.print()


@cli.command(cls=RichCommand)
def info():
    """Show APL system information and status."""
    _banner.render("full")
    SystemInfoRenderer().render()
