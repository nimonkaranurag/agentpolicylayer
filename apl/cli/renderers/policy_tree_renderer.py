from __future__ import annotations

from rich.console import Console
from rich.tree import Tree

from ...server import PolicyServer


class PolicyTreeRenderer:
    def __init__(self, console: Console):
        self._console = console

    def render(self, server: PolicyServer):
        self._console.print()

        tree = Tree(
            f"[bold cyan]🛡️  {server.name}[/bold cyan]"
            f" [dim]v{server.version}[/dim]"
        )

        for policy in server.registry.all_policies():
            events_str = ", ".join(
                e.value for e in policy.events
            )
            branch = tree.add(
                f"[green]✓[/green]"
                f" [white]{policy.name}[/white]"
                f" [dim]({events_str})[/dim]"
            )
            if policy.description:
                branch.add(
                    f"[dim]{policy.description}[/dim]"
                )

        self._console.print(tree)
        self._console.print()
