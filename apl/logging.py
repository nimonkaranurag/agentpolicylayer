"""
APL Logging Module

Provides rich, beautiful logging for APL policy servers with:
- Colored output with security-themed aesthetics
- Structured log format for production
- Performance timing
- Policy verdict highlighting

Usage:
    from apl.logging import setup_logging, APLLogger

    logger = setup_logging(level="DEBUG")
    logger.policy_evaluated("my-policy", verdict, elapsed_ms=1.5)
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

from .types import Decision, Verdict

# =============================================================================
# SHARED CONSOLE
# =============================================================================

console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "warning": "yellow",
            "error": "bold red",
            "debug": "dim",
        }
    )
)


# =============================================================================
# CUSTOM THEME
# =============================================================================

APL_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "debug": "dim",
        "policy.name": "bold white",
        "policy.allow": "bold green",
        "policy.deny": "bold red",
        "policy.modify": "bold yellow",
        "policy.escalate": "bold magenta",
        "policy.observe": "bold blue",
        "timing": "dim cyan",
        "event": "cyan",
        "security": "bold cyan",
    }
)


# =============================================================================
# CUSTOM LOG HANDLER
# =============================================================================


class APLRichHandler(RichHandler):
    """
    Custom Rich handler with APL-specific formatting.

    Adds:
    - Security-themed icons
    - Policy verdict coloring
    - Performance timing display
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("show_time", True)
        kwargs.setdefault("show_path", False)
        kwargs.setdefault("rich_tracebacks", True)
        kwargs.setdefault("tracebacks_show_locals", True)
        super().__init__(*args, **kwargs)

    def get_level_text(
        self, record: logging.LogRecord
    ) -> Text:
        """Custom level text with icons."""
        level_name = record.levelname

        icons = {
            "DEBUG": "🔍",
            "INFO": "ℹ️ ",
            "WARNING": "⚠️ ",
            "ERROR": "❌",
            "CRITICAL": "🚨",
            "POLICY": "🛡️",
            "SECURITY": "🔒",
        }

        icon = icons.get(level_name, "•")

        style = {
            "DEBUG": "dim",
            "INFO": "cyan",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red",
            "POLICY": "cyan",
            "SECURITY": "bold cyan",
        }.get(level_name, "white")

        return Text(f"{icon} {level_name:<8}", style=style)


# =============================================================================
# APL LOGGER
# =============================================================================


class APLLogger:
    """
    High-level logging interface for APL.

    Provides semantic logging methods for policy operations:
    - policy_evaluated()
    - event_received()
    - server_started()
    - etc.

    Example:
        logger = APLLogger("my-server")
        logger.policy_evaluated("pii-filter", verdict, elapsed_ms=1.2)
    """

    def __init__(self, name: str, level: str = "INFO"):
        """
        Initialize APL logger.

        Args:
            name: Logger name (typically server name)
            level: Log level (DEBUG, INFO, WARNING, ERROR)
        """
        self.name = name
        self._logger = logging.getLogger(f"apl.{name}")
        self._logger.setLevel(
            getattr(logging, level.upper())
        )
        self._console = Console(theme=APL_THEME)

    def _log(self, level: int, message: str, **kwargs):
        """Internal log method."""
        extra = {"markup": True, **kwargs}
        self._logger.log(level, message, extra=extra)

    # =========================================================================
    # SEMANTIC LOGGING METHODS
    # =========================================================================

    def server_started(
        self, transport: str, address: Optional[str] = None
    ):
        """Log server startup."""
        if address:
            self._log(
                logging.INFO,
                f"[security]🛡️  Server started[/security] on [cyan]{transport}://{address}[/cyan]",
            )
        else:
            self._log(
                logging.INFO,
                f"[security]🛡️  Server started[/security] with [cyan]{transport}[/cyan] transport",
            )

    def server_stopped(self):
        """Log server shutdown."""
        self._log(logging.INFO, "[dim]Server stopped[/dim]")

    def policy_registered(
        self, policy_name: str, events: list[str]
    ):
        """Log policy registration."""
        events_str = ", ".join(events)
        self._log(
            logging.DEBUG,
            f"[policy.name]{policy_name}[/policy.name] registered for events: [event]{events_str}[/event]",
        )

    def event_received(
        self, event_type: str, event_id: str
    ):
        """Log incoming event."""
        self._log(
            logging.DEBUG,
            f"[event]Event received:[/event] {event_type} [dim]({event_id[:8]}...)[/dim]",
        )

    def policy_evaluated(
        self,
        policy_name: str,
        verdict: Verdict,
        elapsed_ms: Optional[float] = None,
    ):
        """Log policy evaluation result."""
        decision_styles = {
            Decision.ALLOW: "[policy.allow]ALLOW[/policy.allow]",
            Decision.DENY: "[policy.deny]DENY[/policy.deny]",
            Decision.MODIFY: "[policy.modify]MODIFY[/policy.modify]",
            Decision.ESCALATE: "[policy.escalate]ESCALATE[/policy.escalate]",
            Decision.OBSERVE: "[policy.observe]OBSERVE[/policy.observe]",
        }

        decision_str = decision_styles.get(
            verdict.decision, str(verdict.decision)
        )
        timing_str = (
            f" [timing]({elapsed_ms:.2f}ms)[/timing]"
            if elapsed_ms
            else ""
        )

        message = f"[policy.name]{policy_name}[/policy.name] → {decision_str}{timing_str}"

        if verdict.reasoning:
            message += f" [dim]// {verdict.reasoning}[/dim]"

        level = (
            logging.WARNING
            if verdict.decision == Decision.DENY
            else logging.INFO
        )
        self._log(level, message)

    def composition_result(
        self,
        total_policies: int,
        final_decision: Decision,
        elapsed_ms: float,
    ):
        """Log verdict composition result."""
        decision_styles = {
            Decision.ALLOW: "[policy.allow]ALLOW[/policy.allow]",
            Decision.DENY: "[policy.deny]DENY[/policy.deny]",
            Decision.MODIFY: "[policy.modify]MODIFY[/policy.modify]",
            Decision.ESCALATE: "[policy.escalate]ESCALATE[/policy.escalate]",
            Decision.OBSERVE: "[policy.observe]OBSERVE[/policy.observe]",
        }

        decision_str = decision_styles.get(
            final_decision, str(final_decision)
        )

        self._log(
            logging.INFO,
            f"[security]Composed {total_policies} verdicts[/security] → {decision_str} [timing]({elapsed_ms:.2f}ms)[/timing]",
        )

    def client_connected(
        self, client_id: str, address: str
    ):
        """Log client connection."""
        self._log(
            logging.INFO,
            f"[green]Client connected:[/green] {client_id} from {address}",
        )

    def client_disconnected(self, client_id: str):
        """Log client disconnection."""
        self._log(
            logging.DEBUG,
            f"[dim]Client disconnected: {client_id}[/dim]",
        )

    def error(self, message: str, exc_info: bool = False):
        """Log error."""
        self._logger.error(message, exc_info=exc_info)

    def warning(self, message: str):
        """Log warning."""
        self._log(
            logging.WARNING, f"[warning]{message}[/warning]"
        )

    def info(self, message: str):
        """Log info."""
        self._log(logging.INFO, message)

    def debug(self, message: str):
        """Log debug."""
        self._log(logging.DEBUG, f"[dim]{message}[/dim]")


# =============================================================================
# SETUP FUNCTION
# =============================================================================


def setup_logging(
    level: str = "INFO",
    rich_output: bool = True,
    log_file: Optional[str] = None,
) -> APLLogger:
    """
    Configure APL logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        rich_output: Enable rich console output (disable for stdio transport)
        log_file: Optional file path for log output

    Returns:
        APLLogger instance

    Example:
        logger = setup_logging(level="DEBUG", rich_output=True)
        logger.info("Server starting...")
    """
    # Configure root APL logger
    root_logger = logging.getLogger("apl")
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.handlers.clear()

    if rich_output:
        # Rich console handler
        console = Console(theme=APL_THEME, stderr=True)
        handler = APLRichHandler(
            console=console,
            show_time=True,
            show_path=False,
        )
        handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        root_logger.addHandler(handler)
    else:
        # Simple stream handler for stdio transport
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)

    if log_file:
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(file_handler)

    return APLLogger("main", level)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_logger(name: str) -> APLLogger:
    """
    Get or create an APL logger instance.

    Args:
        name: Logger name

    Returns:
        APLLogger instance
    """
    return APLLogger(name)
