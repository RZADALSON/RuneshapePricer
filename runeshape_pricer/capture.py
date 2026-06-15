"""Screen capture of the panel region (read-only; never touches the game).

Uses ``mss`` to grab raw pixels from the primary monitor and returns a PIL
image plus the screen-space origin of the captured region, so the overlay can
translate OCR boxes back into absolute screen coordinates.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

import mss
from PIL import Image


def set_dpi_aware() -> None:
    """Make the process per-monitor DPI aware.

    Without this, capture (physical pixels) and the Tk overlay (logical pixels)
    disagree on Windows display scaling and the prices land in the wrong place.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class Capture:
    image: Image.Image
    origin_x: int       # screen x of the captured region's top-left
    origin_y: int
    screen_w: int
    screen_h: int


def _monitor_index(sct, monitor: int) -> int:
    # sct.monitors[0] is the whole virtual desktop; [1..] are physical screens.
    if 1 <= monitor < len(sct.monitors):
        return monitor
    return 1


def get_monitor_bounds(monitor: int = 1) -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the chosen monitor, in screen px."""
    with mss.mss() as sct:
        mon = sct.monitors[_monitor_index(sct, monitor)]
        return mon["left"], mon["top"], mon["width"], mon["height"]


def monitor_count() -> int:
    with mss.mss() as sct:
        return max(0, len(sct.monitors) - 1)


def grab_region(
    rx: float, ry: float, rw: float, rh: float, monitor: int = 1
) -> Capture:
    """Grab a fractional region of the chosen monitor.

    rx/ry/rw/rh are fractions in [0, 1] of that monitor's width/height.
    """
    with mss.mss() as sct:
        mon = sct.monitors[_monitor_index(sct, monitor)]
        sw, sh = mon["width"], mon["height"]
        left = mon["left"] + int(rx * sw)
        top = mon["top"] + int(ry * sh)
        width = max(1, int(rw * sw))
        height = max(1, int(rh * sh))
        raw = sct.grab({"left": left, "top": top, "width": width, "height": height})
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return Capture(
            image=img,
            origin_x=left,
            origin_y=top,
            screen_w=sw,
            screen_h=sh,
        )
