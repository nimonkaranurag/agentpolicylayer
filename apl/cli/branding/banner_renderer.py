from __future__ import annotations

from rich.console import Console

from .assets import APL_LOGO_MINI, BANNER_STYLE_MAP


class BannerRenderer:
    def __init__(self, console: Console, version: str):
        self._console = console
        self._version = version

    def render(self, style: str = "full"):
        template = BANNER_STYLE_MAP.get(
            style, APL_LOGO_MINI
        )
        self._console.print(
            template.format(version=self._version)
        )
