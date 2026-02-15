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

APL_LOGO_MINI = (
    "[bold cyan]🛡️  APL[/bold cyan] [dim]v{version}[/dim]"
)

BANNER_STYLE_MAP = {
    "full": APL_LOGO_FULL,
    "small": APL_LOGO_SMALL,
    "mini": APL_LOGO_MINI,
}

STATUS_ICON_MAP = {
    "info": "[blue]ℹ[/blue]",
    "success": "[green]✓[/green]",
    "warning": "[yellow]⚠[/yellow]",
    "error": "[red]✗[/red]",
    "security": "[cyan]🛡️[/cyan]",
    "loading": "[cyan]⟳[/cyan]",
}
