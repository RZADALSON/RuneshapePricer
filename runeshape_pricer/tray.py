"""System-tray icon so the app can run quietly in the background.

Provides a small menu: a status line, a manual price refresh, and Quit. If
pystray/Pillow aren't available the app still runs (see app.py) -- the tray is
a convenience, not a hard dependency.
"""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw

import pystray


def _make_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(28, 28, 34, 255), outline=(196, 150, 64, 255), width=3)
    # A simple rune-ish glyph.
    d.line((24, 18, 24, 46), fill=(230, 200, 120, 255), width=4)
    d.line((24, 18, 40, 30), fill=(230, 200, 120, 255), width=4)
    d.line((24, 34, 38, 46), fill=(230, 200, 120, 255), width=4)
    return img


class Tray:
    def __init__(
        self,
        on_quit: Callable[[], None],
        status_fn: Callable[[], str],
        on_settings: Callable[[], None] | None = None,
    ) -> None:
        self._on_quit = on_quit
        self._status = status_fn
        self._on_settings = on_settings

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings", self._settings),
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon(
            "RuneshapePricer", _make_image(), "Runeshape Pricer", menu
        )

    def _settings(self, icon, item) -> None:
        if self._on_settings:
            self._on_settings()

    def _quit(self, icon, item) -> None:
        self._on_quit()
        self.icon.stop()

    def run_detached(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
