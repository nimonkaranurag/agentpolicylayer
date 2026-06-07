"""
APL console branding: logo banners and status lines.

The logos are Rich-markup templates with a ``{version}`` placeholder; the helpers are
plain functions that take the target :class:`~rich.console.Console`, so a caller can
send chrome to stderr (e.g. while serving the stdio protocol on stdout).
"""

from __future__ import annotations

from rich.console import Console

from .. import __version__

APL_LOGO_FULL = """
[bold cyan]
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     █████╗ ██████╗ ██╗         [white]Agent Policy Layer[/white]         ║
    ║    ██╔══██╗██╔══██╗██║         [dim]v{version}[/dim]                     ║
    ║    ███████║██████╔╝██║                                    ║
    ║    ██╔══██║██╔═══╝ ██║         [yellow]🛡️  Secure by Default[/yellow]       ║
    ║    ██║  ██║██║     ███████╗    [green]⚡ Fast & Composable[/green]       ║
    ║    ╚═╝  ╚═╝╚═╝     ╚══════╝    [blue]🔌 Runtime Agnostic[/blue]        ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
[/bold cyan]
"""

APL_LOGO_SMALL = """[bold cyan]
  ▄▀█ █▀█ █░░   [white]Agent Policy Layer[/white]
  █▀█ █▀▀ █▄▄   [dim]v{version}[/dim]
[/bold cyan]"""

APL_LOGO_MINI = "[bold cyan]🛡️  APL[/bold cyan] [dim]v{version}[/dim]"

_BANNER_STYLES = {
    "full": APL_LOGO_FULL,
    "small": APL_LOGO_SMALL,
    "mini": APL_LOGO_MINI,
}

_STATUS_ICONS = {
    "info": "[blue]ℹ[/blue]",
    "success": "[green]✓[/green]",
    "warning": "[yellow]⚠[/yellow]",
    "error": "[red]✗[/red]",
    "security": "[cyan]🛡️[/cyan]",
    "loading": "[cyan]⟳[/cyan]",
}


def render_banner(console: Console, style: str = "full") -> None:
    """
    Print the APL logo at the given ``style`` (``full``/``small``/``mini``).
    """
    template = _BANNER_STYLES.get(style, APL_LOGO_MINI)
    console.print(template.format(version=__version__))


def print_status(console: Console, message: str, status: str = "info") -> None:
    """
    Print a single status line prefixed with the icon for ``status``.
    """
    icon = _STATUS_ICONS.get(status, _STATUS_ICONS["info"])
    console.print(f"  {icon} {message}")
