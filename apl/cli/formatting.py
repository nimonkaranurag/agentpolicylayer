"""
Rich-formatted Click help output.

:class:`RichCommand` and :class:`RichGroup` are genuine extension points — they subclass
Click to override ``format_help`` — so they stay classes. The argument and option tables
they render are stateless and live here as plain functions.
"""

from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.table import Table

from .branding import APL_LOGO_MINI, render_banner


def render_arguments_table(console: Console, params) -> None:
    """
    Print a table of the command's positional arguments, if any.
    """
    arguments = [param for param in params if isinstance(param, click.Argument)]
    if not arguments:
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

    for argument in arguments:
        required_marker = "[red]*[/red]" if argument.required else ""
        help_text = getattr(argument, "help", "") or ""
        table.add_row(f"{argument.name.upper()} {required_marker}", help_text)

    console.print(table)
    console.print()


def render_options_table(console: Console, params) -> None:
    """
    Print a table of the command's options, if any.
    """
    options = [param for param in params if isinstance(param, click.Option)]
    if not options:
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

    for option in options:
        table.add_row(
            _format_option_name(option),
            _format_option_type(option),
            option.help or "",
        )

    console.print(table)
    console.print()


def _format_option_name(option) -> str:
    name = ", ".join(option.opts)
    if option.secondary_opts:
        name += ", " + ", ".join(option.secondary_opts)
    return name


def _format_option_type(option) -> str:
    type_str = ""
    if option.type and option.type.name != "BOOL":
        type_str = option.type.name
    has_visible_default = (
        option.default is not None and option.default != () and not option.is_flag
    )
    if has_visible_default:
        type_str += f" [dim](default: {option.default})[/dim]"
    return type_str


class RichCommand(click.Command):
    """
    A :class:`click.Command` whose ``--help`` is rendered with Rich.
    """

    def format_help(self, ctx, formatter) -> None:
        from .. import __version__
        from . import console

        console.print(APL_LOGO_MINI.format(version=__version__))
        console.print()
        self._render_command_header(ctx, console)
        self._render_usage_line(ctx, console)
        render_arguments_table(console, self.params)
        render_options_table(console, self.params)
        self._render_examples_section(console)

    def _render_command_header(self, ctx, console: Console) -> None:
        console.print(f"  [bold cyan]{ctx.info_name}[/bold cyan]", end="")
        if self.help:
            first_line = self.help.split("\n")[0]
            console.print(f" — {first_line}")
        else:
            console.print()
        console.print()

    def _render_usage_line(self, ctx, console: Console) -> None:
        pieces = self.collect_usage_pieces(ctx)
        console.print(
            f"  [bold]Usage:[/bold]"
            f" [green]apl {ctx.info_name}[/green]"
            f" {' '.join(pieces)}"
        )
        console.print()

    def _render_examples_section(self, console: Console) -> None:
        if not self.help or "Examples:" not in self.help:
            return

        examples_text = self.help[self.help.index("Examples:") :]
        console.print("  [bold]Examples[/bold]")
        for line in examples_text.split("\n")[1:]:
            if line.strip():
                console.print(f"  [dim]{line.strip()}[/dim]")
        console.print()


class RichGroup(click.Group):
    """
    A :class:`click.Group` whose ``--help`` is rendered with Rich.
    """

    def format_help(self, ctx, formatter) -> None:
        from . import console

        render_banner(console, "small")
        console.print()

        if self.help:
            console.print(f"  {self.help}")
            console.print()

        self._render_commands_table(console)

        console.print(
            "  [dim]Run[/dim]"
            " [cyan]apl <command> --help[/cyan]"
            " [dim]for details on a specific command[/dim]"
        )
        console.print()

    def _render_commands_table(self, console: Console) -> None:
        visible_commands = [
            (name, command)
            for name, command in self.commands.items()
            if not command.hidden
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

        for name, command in visible_commands:
            table.add_row(name, command.get_short_help_str(limit=50))

        console.print("  [bold]Commands[/bold]")
        console.print()
        console.print(table)
        console.print()
