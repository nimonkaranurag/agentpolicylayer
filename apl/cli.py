#!/usr/bin/env python3
"""
APL CLI - Agent Policy Layer Command Line Interface

A beautifully branded CLI for running and managing APL policy servers.
Features rich logging, status displays, and a distinctive security aesthetic.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .logging import setup_logging
from .server import PolicyServer

console = Console()

# =============================================================================
# BRANDING & AESTHETICS
# =============================================================================

APL_LOGO = """
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

APL_BANNER_SMALL = """[bold cyan]
  ▄▀█ █▀█ █░░   [white]Agent Policy Layer[/white]
  █▀█ █▀▀ █▄▄   [dim]v{version}[/dim]
[/bold cyan]"""

APL_MINI = (
    "[bold cyan]🛡️  APL[/bold cyan] [dim]v{version}[/dim]"
)


def print_banner(style: str = "full"):
    """Print the APL banner."""
    if style == "full":
        console.print(APL_LOGO.format(version=__version__))
    elif style == "small":
        console.print(
            APL_BANNER_SMALL.format(version=__version__)
        )
    else:
        console.print(APL_MINI.format(version=__version__))


def print_status(message: str, status: str = "info"):
    """Print a status message with appropriate styling."""
    icons = {
        "info": "[blue]ℹ[/blue]",
        "success": "[green]✓[/green]",
        "warning": "[yellow]⚠[/yellow]",
        "error": "[red]✗[/red]",
        "security": "[cyan]🛡️[/cyan]",
        "loading": "[cyan]⟳[/cyan]",
    }
    icon = icons.get(status, icons["info"])
    console.print(f"  {icon} {message}")


# =============================================================================
# CUSTOM HELP FORMATTING WITH RICH TABLES
# =============================================================================


class RichGroup(click.Group):
    """Custom Click Group with Rich-formatted help."""

    def format_help(self, ctx, formatter):
        """Format help with Rich tables."""
        print_banner("small")
        console.print()

        # Description
        if self.help:
            console.print(f"  {self.help}")
            console.print()

        # Commands table
        commands = []
        for name, cmd in self.commands.items():
            if not cmd.hidden:
                help_text = cmd.get_short_help_str(limit=50)
                commands.append((name, help_text))

        if commands:
            table = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
                border_style="dim",
                padding=(0, 2),
            )
            table.add_column("Command", style="green")
            table.add_column("Description", style="white")

            for name, help_text in commands:
                table.add_row(name, help_text)

            console.print("  [bold]Commands[/bold]")
            console.print()
            console.print(table)
            console.print()

        # Usage hint
        console.print(
            "  [dim]Run[/dim] [cyan]apl <command> --help[/cyan] [dim]for details on a specific command[/dim]"
        )
        console.print()


class RichCommand(click.Command):
    """Custom Click Command with Rich-formatted help."""

    def format_help(self, ctx, formatter):
        """Format help with Rich tables."""
        console.print(APL_MINI.format(version=__version__))
        console.print()

        # Command name and description
        console.print(
            f"  [bold cyan]{ctx.info_name}[/bold cyan]",
            end="",
        )
        if self.help:
            console.print(
                f" — {self.help.split(chr(10))[0]}"
            )
        else:
            console.print()
        console.print()

        # Usage
        pieces = self.collect_usage_pieces(ctx)
        console.print(
            f"  [bold]Usage:[/bold] [green]apl {ctx.info_name}[/green] {' '.join(pieces)}"
        )
        console.print()

        # Arguments
        args = [
            p
            for p in self.params
            if isinstance(p, click.Argument)
        ]
        if args:
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
                name = arg.name.upper()
                help_text = getattr(arg, "help", "") or ""
                required = (
                    "[red]*[/red]" if arg.required else ""
                )
                table.add_row(
                    f"{name} {required}", help_text
                )

            console.print(table)
            console.print()

        # Options table
        opts = [
            p
            for p in self.params
            if isinstance(p, click.Option)
        ]
        if opts:
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
                # Build option string
                opt_str = ", ".join(opt.opts)
                if opt.secondary_opts:
                    opt_str += ", " + ", ".join(
                        opt.secondary_opts
                    )

                # Type hint
                type_str = ""
                if opt.type and opt.type.name != "BOOL":
                    type_str = opt.type.name
                if (
                    opt.default is not None
                    and opt.default != ()
                    and not opt.is_flag
                ):
                    type_str += f" [dim](default: {opt.default})[/dim]"

                # Help text
                help_text = opt.help or ""

                table.add_row(opt_str, type_str, help_text)

            console.print(table)
            console.print()

        # Examples if available
        if self.help and "Examples:" in self.help:
            examples_start = self.help.index("Examples:")
            examples = self.help[examples_start:]
            console.print(f"  [bold]Examples[/bold]")
            for line in examples.split("\n")[1:]:
                if line.strip():
                    console.print(
                        f"  [dim]{line.strip()}[/dim]"
                    )
            console.print()


# =============================================================================
# CLI COMMANDS
# =============================================================================


@click.group(cls=RichGroup)
@click.version_option(version=__version__, prog_name="APL")
def cli():
    """Portable, composable policies for AI agents."""
    pass


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--http",
    "http_port",
    type=int,
    default=None,
    help="Enable HTTP transport on this port",
)
@click.option(
    "--host", default="0.0.0.0", help="HTTP host to bind to"
)
@click.option(
    "--stdio",
    is_flag=True,
    default=False,
    help="Use stdio transport (default)",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "-q", "--quiet", is_flag=True, help="Minimal output"
)
def serve(
    path: str,
    http_port: Optional[int],
    host: str,
    stdio: bool,
    verbose: bool,
    quiet: bool,
):
    """
    Run a policy server.

    Examples:
      apl serve ./pii_filter.py
      apl serve ./policies/
      apl serve ./policy.yaml
      apl serve ./my_policy.py --http 8080
    """
    if not quiet:
        print_banner("small")
        console.print()

    # Setup logging
    log_level = (
        "DEBUG"
        if verbose
        else "INFO" if not quiet else "WARNING"
    )
    logger = setup_logging(
        level=log_level, rich_output=not stdio
    )

    path_obj = Path(path)

    # Load policies
    if path_obj.is_dir():
        if not quiet:
            print_status(
                f"Loading policies from: [cyan]{path}[/cyan]",
                "loading",
            )
        server = _load_policies_from_directory(
            path_obj, logger
        )
    elif path_obj.suffix in (".yaml", ".yml"):
        if not quiet:
            print_status(
                f"Loading declarative policy: [cyan]{path}[/cyan]",
                "loading",
            )
        server = _load_yaml_policy(path_obj, logger)
    elif path_obj.suffix == ".py":
        if not quiet:
            print_status(
                f"Loading policy module: [cyan]{path}[/cyan]",
                "loading",
            )
        server = _load_python_policy(path_obj, logger)
    else:
        console.print(
            f"  [red]✗[/red] Unsupported file type: {path_obj.suffix}"
        )
        sys.exit(1)

    if server is None:
        console.print(
            "  [red]✗[/red] Failed to load policy server"
        )
        sys.exit(1)

    if not quiet:
        _display_loaded_policies(server)

    # Start server
    if http_port:
        if not quiet:
            print_status(
                f"Starting HTTP server on [cyan]http://{host}:{http_port}[/cyan]",
                "security",
            )
        _run_http_server(
            server, host, http_port, logger, quiet
        )
    else:
        if not quiet:
            print_status(
                "Starting stdio transport", "security"
            )
            console.print()
            console.print(
                "  [dim]Waiting for events on stdin...[/dim]"
            )
            console.print(
                "  [dim]Press Ctrl+C to stop[/dim]"
            )
            console.print()
        server.run(transport="stdio")


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
def validate(path: str):
    """
    Validate a policy file without running it.

    Examples:
      apl validate ./my_policy.py
      apl validate ./policy.yaml
    """
    print_banner("mini")
    console.print()

    path_obj = Path(path)
    print_status(
        f"Validating: [cyan]{path}[/cyan]", "loading"
    )

    try:
        if path_obj.suffix in (".yaml", ".yml"):
            from .declarative import validate_yaml_policy

            errors = validate_yaml_policy(path_obj)
        elif path_obj.suffix == ".py":
            errors = _validate_python_policy(path_obj)
        else:
            console.print(
                f"  [red]✗[/red] Unsupported file type: {path_obj.suffix}"
            )
            sys.exit(1)

        if errors:
            print_status("Validation failed", "error")
            for error in errors:
                console.print(f"    [red]•[/red] {error}")
            sys.exit(1)
        else:
            print_status("Validation passed!", "success")

    except Exception as e:
        print_status(f"Validation error: {e}", "error")
        sys.exit(1)


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "-e",
    "--event",
    default="output.pre_send",
    help="Event type to test",
)
@click.option(
    "-p", "--payload", default=None, help="JSON payload"
)
def test(path: str, event: str, payload: Optional[str]):
    """
    Test a policy with sample events.

    Examples:
      apl test ./pii_filter.py
      apl test ./policy.yaml -e tool.pre_invoke
    """
    import json

    print_banner("mini")
    console.print()

    print_status(f"Testing: [cyan]{path}[/cyan]", "loading")

    # Load the policy
    path_obj = Path(path)
    logger = setup_logging(
        level="WARNING", rich_output=True
    )

    if path_obj.suffix in (".yaml", ".yml"):
        server = _load_yaml_policy(path_obj, logger)
    else:
        server = _load_python_policy(path_obj, logger)

    if not server:
        print_status("Failed to load policy", "error")
        sys.exit(1)

    # Create test event
    import uuid

    from .types import (
        EventPayload,
        EventType,
        Message,
        PolicyEvent,
        SessionMetadata,
    )

    test_payloads = {
        "output.pre_send": EventPayload(
            output_text="Your SSN is 123-45-6789 and email is test@example.com"
        ),
        "tool.pre_invoke": EventPayload(
            tool_name="delete_file",
            tool_args={"path": "/important/data"},
        ),
        "llm.pre_request": EventPayload(llm_model="gpt-4"),
        "input.received": EventPayload(),
    }

    if payload:
        test_payload = EventPayload(**json.loads(payload))
    else:
        test_payload = test_payloads.get(
            event, EventPayload()
        )

    test_event = PolicyEvent(
        id=str(uuid.uuid4()),
        type=EventType(event),
        timestamp=datetime.now(),
        messages=[
            Message(role="user", content="Test message")
        ],
        payload=test_payload,
        metadata=SessionMetadata(
            session_id="test-session",
            user_id="test-user",
            token_count=1000,
            token_budget=10000,
        ),
    )

    console.print()
    print_status(
        f"Event type: [cyan]{event}[/cyan]", "info"
    )

    # Run evaluation
    async def run_test():
        return await server.evaluate(test_event)

    verdicts = asyncio.run(run_test())

    # Display results
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

    for v in verdicts:
        decision_style = {
            "allow": "[green]ALLOW[/green]",
            "deny": "[red]DENY[/red]",
            "modify": "[yellow]MODIFY[/yellow]",
            "escalate": "[magenta]ESCALATE[/magenta]",
            "observe": "[blue]OBSERVE[/blue]",
        }.get(v.decision.value, v.decision.value)

        table.add_row(
            v.policy_name or "unknown",
            decision_style,
            f"{v.confidence:.0%}",
            (
                f"{v.evaluation_ms:.2f}ms"
                if v.evaluation_ms
                else "-"
            ),
            (v.reasoning or "-")[:40],
        )

    console.print(table)

    # Show modification if any
    for v in verdicts:
        if v.modification:
            console.print()
            console.print(
                Panel(
                    f"[bold]Modified Output:[/bold]\n{v.modification.value}",
                    title="[yellow]Modification[/yellow]",
                    border_style="yellow",
                )
            )


@cli.command(cls=RichCommand)
def info():
    """Show APL system information and status."""
    print_banner("full")

    # System info table
    table = Table(
        box=box.SIMPLE, show_header=False, padding=(0, 2)
    )
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Version", __version__)
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)
    table.add_row("Protocol", "0.1.0")

    console.print(table)
    console.print()

    # Transports table
    console.print("  [bold]Transports[/bold]")
    transport_table = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        show_edge=False,
    )
    transport_table.add_column("Status", width=3)
    transport_table.add_column("Transport")
    transport_table.add_column("Description", style="dim")

    transport_table.add_row(
        "[green]✓[/green]",
        "stdio",
        "Local subprocess communication",
    )
    transport_table.add_row(
        "[green]✓[/green]", "HTTP", "REST API with SSE"
    )
    transport_table.add_row(
        "[yellow]○[/yellow]", "WebSocket", "Coming soon"
    )

    console.print(transport_table)
    console.print()

    # Adapters table
    console.print("  [bold]Framework Adapters[/bold]")
    adapter_table = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        show_edge=False,
    )
    adapter_table.add_column("Status", width=3)
    adapter_table.add_column("Framework")
    adapter_table.add_column("Description", style="dim")

    adapter_table.add_row(
        "[green]✓[/green]",
        "LangGraph",
        "StateGraph wrapper",
    )
    adapter_table.add_row(
        "[green]✓[/green]", "OpenAI", "Auto-instrumentation"
    )
    adapter_table.add_row(
        "[green]✓[/green]",
        "Anthropic",
        "Auto-instrumentation",
    )
    adapter_table.add_row(
        "[green]✓[/green]",
        "LiteLLM",
        "Auto-instrumentation",
    )
    adapter_table.add_row(
        "[green]✓[/green]", "LangChain", "ChatModel wrapper"
    )
    adapter_table.add_row(
        "[yellow]○[/yellow]", "AutoGen", "Coming soon"
    )
    adapter_table.add_row(
        "[yellow]○[/yellow]", "CrewAI", "Coming soon"
    )

    console.print(adapter_table)
    console.print()

    # Links
    console.print("  [bold]Links[/bold]")
    console.print(
        "    [link=https://github.com/nimonkaranurag/agent_policy_layer]https://github.com/nimonkaranurag/agent_policy_layer[/link]"
    )
    console.print()


@cli.command(cls=RichCommand)
@click.argument("name")
@click.option(
    "-t",
    "--template",
    type=click.Choice(
        ["basic", "pii", "budget", "confirm"]
    ),
    default="basic",
    help="Template to use",
)
def init(name: str, template: str):
    """
    Initialize a new policy project.

    Examples:
      apl init my-policy
      apl init compliance --template pii
    """
    print_banner("mini")
    console.print()

    from .templates import create_policy_project

    print_status(
        f"Creating policy project: [cyan]{name}[/cyan]",
        "loading",
    )

    try:
        project_path = create_policy_project(name, template)
        print_status(
            f"Created project at: [cyan]{project_path}[/cyan]",
            "success",
        )

        console.print()
        console.print("  [bold]Next steps:[/bold]")
        console.print(f"    [dim]$[/dim] cd {name}")
        console.print(
            f"    [dim]$[/dim] apl serve policy.py"
        )
        console.print()

    except Exception as e:
        print_status(
            f"Failed to create project: {e}", "error"
        )
        sys.exit(1)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _load_python_policy(
    path: Path, logger
) -> Optional[PolicyServer]:
    """Load a Python policy module."""
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(
            "policy_module", path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["policy_module"] = module
        spec.loader.exec_module(module)

        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, PolicyServer):
                return obj

        logger.error(f"No PolicyServer found in {path}")
        return None

    except Exception as e:
        logger.error(f"Failed to load {path}: {e}")
        return None


def _load_yaml_policy(
    path: Path, logger
) -> Optional[PolicyServer]:
    """Load a declarative YAML policy."""
    from .declarative import load_yaml_policy

    try:
        return load_yaml_policy(path)
    except Exception as e:
        logger.error(f"Failed to load YAML policy: {e}")
        return None


def _load_policies_from_directory(
    path: Path, logger
) -> Optional[PolicyServer]:
    """Load all policies from a directory."""
    server = PolicyServer(name=path.name, version="1.0.0")

    loaded = 0
    for file in path.iterdir():
        if (
            file.suffix == ".py"
            and not file.name.startswith("_")
        ):
            sub_server = _load_python_policy(file, logger)
            if sub_server:
                for (
                    policy
                ) in sub_server.registry.all_policies():
                    server.registry.register(policy)
                loaded += 1

    return server if loaded > 0 else None


def _validate_python_policy(path: Path) -> list[str]:
    """Validate a Python policy file."""
    errors = []

    try:
        import ast

        with open(path) as f:
            ast.parse(f.read())
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
        return errors

    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(
            "policy_module", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        found_server = False
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, PolicyServer):
                found_server = True
                if not obj.registry.all_policies():
                    errors.append(
                        "PolicyServer has no registered policies"
                    )

        if not found_server:
            errors.append("No PolicyServer instance found")

    except Exception as e:
        errors.append(f"Load error: {e}")

    return errors


def _display_loaded_policies(server: PolicyServer):
    """Display loaded policies."""
    console.print()

    tree = Tree(
        f"[bold cyan]🛡️  {server.name}[/bold cyan] [dim]v{server.version}[/dim]"
    )

    for policy in server.registry.all_policies():
        events_str = ", ".join(
            e.value for e in policy.events
        )
        policy_branch = tree.add(
            f"[green]✓[/green] [white]{policy.name}[/white] [dim]({events_str})[/dim]"
        )
        if policy.description:
            policy_branch.add(
                f"[dim]{policy.description}[/dim]"
            )

    console.print(tree)
    console.print()


def _run_http_server(
    server: PolicyServer,
    host: str,
    port: int,
    logger,
    quiet: bool,
):
    """Run HTTP server."""
    from .transports.http import HTTPTransport

    if not quiet:
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

    transport = HTTPTransport(
        server, host=host, port=port, apl_logger=logger
    )
    transport.run()


def main():
    """Main entry point."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down...[/dim]")
        sys.exit(0)


if __name__ == "__main__":
    main()
