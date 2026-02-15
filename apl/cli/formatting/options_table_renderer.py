from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.table import Table


class OptionsTableRenderer:
    def __init__(self, console: Console):
        self._console = console

    def render(self, params):
        opts = [
            p for p in params if isinstance(p, click.Option)
        ]
        if not opts:
            return

        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold",
            padding=(0, 2),
            show_edge=False,
        )
        table.add_column("Option", style="cyan")
        table.add_column("Type", style="dim")
        table.add_column("Description", style="white")

        for opt in opts:
            table.add_row(
                self._format_option_name(opt),
                self._format_option_type(opt),
                opt.help or "",
            )

        self._console.print(table)
        self._console.print()

    @staticmethod
    def _format_option_name(opt):
        opt_str = ", ".join(opt.opts)
        if opt.secondary_opts:
            opt_str += ", " + ", ".join(opt.secondary_opts)
        return opt_str

    @staticmethod
    def _format_option_type(opt):
        type_str = ""
        if opt.type and opt.type.name != "BOOL":
            type_str = opt.type.name
        has_visible_default = (
            opt.default is not None
            and opt.default != ()
            and not opt.is_flag
        )
        if has_visible_default:
            type_str += (
                f" [dim](default: {opt.default})[/dim]"
            )
        return type_str
