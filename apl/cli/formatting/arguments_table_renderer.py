from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.table import Table


class ArgumentsTableRenderer:
    def __init__(self, console: Console):
        self._console = console

    def render(self, params):
        args = [
            p for p in params
            if isinstance(p, click.Argument)
        ]
        if not args:
            return

        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold",
            padding=(0, 2),
            show_edge=False,
        )
        table.add_column("Argument", style="yellow")
        table.add_column("Description", style="white")

        for arg in args:
            required_marker = (
                "[red]*[/red]" if arg.required else ""
            )
            help_text = getattr(arg, "help", "") or ""
            table.add_row(
                f"{arg.name.upper()} {required_marker}",
                help_text,
            )

        self._console.print(table)
        self._console.print()
