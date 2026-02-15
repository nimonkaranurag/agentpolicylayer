from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ..branding import BannerRenderer


class RichGroup(click.Group):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._console = None
        self._banner = None

    def _ensure_initialized(
        self, console: Console, version: str
    ):
        if self._console is None:
            self._console = console
            self._banner = BannerRenderer(console, version)

    def format_help(self, ctx, formatter):
        from ... import __version__
        from .. import console

        self._ensure_initialized(console, __version__)
        self._banner.render("small")
        self._console.print()

        if self.help:
            self._console.print(f"  {self.help}")
            self._console.print()

        self._render_commands_table()

        self._console.print(
            "  [dim]Run[/dim]"
            " [cyan]apl <command> --help[/cyan]"
            " [dim]for details on a specific command[/dim]"
        )
        self._console.print()

    def _render_commands_table(self):
        visible_commands = [
            (name, cmd)
            for name, cmd in self.commands.items()
            if not cmd.hidden
        ]
        if not visible_commands:
            return

        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            padding=(0, 2),
        )
        table.add_column("Command", style="green")
        table.add_column("Description", style="white")

        for name, cmd in visible_commands:
            table.add_row(
                name, cmd.get_short_help_str(limit=50)
            )

        self._console.print("  [bold]Commands[/bold]")
        self._console.print()
        self._console.print(table)
        self._console.print()
