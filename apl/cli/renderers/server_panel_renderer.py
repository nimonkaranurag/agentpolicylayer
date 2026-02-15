from __future__ import annotations

from rich.console import Console
from rich.panel import Panel


class ServerPanelRenderer:
    def __init__(self, console: Console):
        self._console = console

    def render(self, host: str, port: int):
        self._console.print()
        self._console.print(
            Panel(
                f"[bold green]Server running![/bold green]\n\n"
                f"  Endpoint: [cyan]http://{host}:{port}/evaluate[/cyan]\n"
                f"  Health:   [cyan]http://{host}:{port}/health[/cyan]\n"
                f"  Metrics:  [cyan]http://{host}:{port}/metrics[/cyan]\n\n"
                f"[dim]Press Ctrl+C to stop[/dim]",
                title="[bold cyan]🛡️  APL Policy Server[/bold cyan]",
                border_style="cyan",
            )
        )
        self._console.print()
