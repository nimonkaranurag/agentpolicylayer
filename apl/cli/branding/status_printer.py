from __future__ import annotations

from rich.console import Console

from .assets import STATUS_ICON_MAP


class StatusPrinter:
    def __init__(self, console: Console):
        self._console = console

    def print(
        self, message: str, status: str = "info"
    ):
        icon = STATUS_ICON_MAP.get(
            status, STATUS_ICON_MAP["info"]
        )
        self._console.print(f"  {icon} {message}")
