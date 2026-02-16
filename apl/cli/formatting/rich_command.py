from __future__ import annotations

import click
from rich.console import Console

from ..branding import APL_LOGO_MINI
from .arguments_table_renderer import (
    ArgumentsTableRenderer,
)
from .options_table_renderer import (
    OptionsTableRenderer,
)


class RichCommand(click.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._console = None
        self._arguments_renderer = None
        self._options_renderer = None

    def _ensure_initialized(self, console: Console):
        if self._console is None:
            self._console = console
            self._arguments_renderer = (
                ArgumentsTableRenderer(console)
            )
            self._options_renderer = (
                OptionsTableRenderer(console)
            )

    def format_help(self, ctx, formatter):
        from ... import __version__
        from .. import console

        self._ensure_initialized(console)

        self._console.print(
            APL_LOGO_MINI.format(version=__version__)
        )
        self._console.print()
        self._render_command_header(ctx)
        self._render_usage_line(ctx)
        self._arguments_renderer.render(self.params)
        self._options_renderer.render(self.params)
        self._render_examples_section()

    def _render_command_header(self, ctx):
        self._console.print(
            f"  [bold cyan]{ctx.info_name}[/bold cyan]",
            end="",
        )
        if self.help:
            first_line = self.help.split(chr(10))[0]
            self._console.print(f" — {first_line}")
        else:
            self._console.print()
        self._console.print()

    def _render_usage_line(self, ctx):
        pieces = self.collect_usage_pieces(ctx)
        self._console.print(
            f"  [bold]Usage:[/bold]"
            f" [green]apl {ctx.info_name}[/green]"
            f" {' '.join(pieces)}"
        )
        self._console.print()

    def _render_examples_section(self):
        if (
            not self.help
            or "Examples:" not in self.help
        ):
            return

        start = self.help.index("Examples:")
        examples_text = self.help[start:]

        self._console.print("  [bold]Examples[/bold]")
        for line in examples_text.split("\n")[1:]:
            if line.strip():
                self._console.print(
                    f"  [dim]{line.strip()}[/dim]"
                )
        self._console.print()
