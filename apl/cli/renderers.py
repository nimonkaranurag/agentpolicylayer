"""
Rich renderers for CLI output: the policy tree, the HTTP server panel, and the verdict
table.

Each is a stateless function taking the target console.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from ..server import PolicyServer
    from ..types import Verdict

DECISION_STYLES = {
    "allow": "[green]ALLOW[/green]",
    "deny": "[red]DENY[/red]",
    "modify": "[yellow]MODIFY[/yellow]",
    "escalate": "[magenta]ESCALATE[/magenta]",
    "observe": "[blue]OBSERVE[/blue]",
}


def render_policy_tree(console: Console, server: PolicyServer) -> None:
    """
    Print the server's registered policies as a tree, with their events.
    """
    console.print()
    tree = Tree(f"[bold cyan]🛡️  {server.name}[/bold cyan] [dim]v{server.version}[/dim]")

    for policy in server.registry.all_policies():
        events_str = ", ".join(event.value for event in policy.events)
        branch = tree.add(
            f"[green]✓[/green] [white]{policy.name}[/white] [dim]({events_str})[/dim]"
        )
        if policy.description:
            branch.add(f"[dim]{policy.description}[/dim]")

    console.print(tree)
    console.print()


def render_server_panel(console: Console, host: str, port: int) -> None:
    """
    Print the "server running" panel with the HTTP endpoint URLs.
    """
    console.print()
    console.print(
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
    console.print()


def render_verdict_table(console: Console, verdicts: list[Verdict]) -> None:
    """
    Print a table of verdicts, followed by a panel for each modification.
    """
    console.print()

    table = Table(
        title="[bold]Policy Verdicts[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Policy", style="white")
    table.add_column("Decision", style="white")
    table.add_column("Confidence", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Reasoning", style="dim", max_width=40)

    for verdict in verdicts:
        decision_display = DECISION_STYLES.get(
            verdict.decision.value, verdict.decision.value
        )
        timing_display = (
            f"{verdict.evaluation_ms:.2f}ms" if verdict.evaluation_ms else "-"
        )
        table.add_row(
            verdict.policy_name or "unknown",
            decision_display,
            f"{verdict.confidence:.0%}",
            timing_display,
            (verdict.reasoning or "-")[:40],
        )

    console.print(table)

    for verdict in verdicts:
        for modification in verdict.modifications:
            console.print()
            console.print(
                Panel(
                    f"[bold]Modified ({modification.target}):[/bold]\n"
                    f"{modification.value}",
                    title="[yellow]Modification[/yellow]",
                    border_style="yellow",
                )
            )
