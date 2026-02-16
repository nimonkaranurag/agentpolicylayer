from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

DECISION_STYLE_MAP = {
    "allow": "[green]ALLOW[/green]",
    "deny": "[red]DENY[/red]",
    "modify": "[yellow]MODIFY[/yellow]",
    "escalate": "[magenta]ESCALATE[/magenta]",
    "observe": "[blue]OBSERVE[/blue]",
}


class VerdictTableRenderer:
    def __init__(self, console: Console):
        self._console = console

    def render(self, verdicts):
        self._render_table(verdicts)
        self._render_modifications(verdicts)

    def _render_table(self, verdicts):
        self._console.print()

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
        table.add_column(
            "Reasoning", style="dim", max_width=40
        )

        for v in verdicts:
            decision_display = DECISION_STYLE_MAP.get(
                v.decision.value, v.decision.value
            )
            timing_display = (
                f"{v.evaluation_ms:.2f}ms"
                if v.evaluation_ms
                else "-"
            )
            table.add_row(
                v.policy_name or "unknown",
                decision_display,
                f"{v.confidence:.0%}",
                timing_display,
                (v.reasoning or "-")[:40],
            )

        self._console.print(table)

    def _render_modifications(self, verdicts):
        for v in verdicts:
            for mod in v.modifications:
                self._console.print()
                self._console.print(
                    Panel(
                        f"[bold]Modified ({mod.target}):[/bold]\n"
                        f"{mod.value}",
                        title="[yellow]Modification[/yellow]",
                        border_style="yellow",
                    )
                )
