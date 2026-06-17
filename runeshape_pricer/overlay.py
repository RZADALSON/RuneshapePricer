"""Transparent, click-through, always-on-top overlay built on Tkinter.

The window covers one monitor but is invisible (a magenta key colour is made
transparent) and passes every mouse click straight through to the game
(WS_EX_TRANSPARENT), so it never interferes with play. It only ever draws
floating price labels, which auto-clear after a configurable delay.

All public ``request_*`` methods are thread-safe; the Tk loop owns the UI and
drains a queue on a short timer. Label/box coordinates are given in absolute
screen pixels; the window converts them to canvas-local so it works on any
monitor.
"""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass

from .capture import get_monitor_bounds

# A colour that never appears in our labels, used as the transparency key.
_TRANSPARENT_KEY = "#FF00FF"             # pure magenta
# Same colour as a Win32 COLORREF (0x00BBGGRR): B=FF, G=00, R=FF.
_TRANSPARENT_COLORREF = 0x00FF00FF

# Win32 constants for making the window layered + click-through.
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080      # keep it out of the taskbar / alt-tab
_WS_EX_NOACTIVATE = 0x08000000      # never steal focus from the game
_LWA_COLORKEY = 0x00000001
_LWA_ALPHA = 0x00000002


@dataclass
class Label:
    x: int              # absolute screen coordinates
    y: int
    text: str
    color: str
    anchor: str = "w"   # "w" = price to the right; "center" = centred on a point


@dataclass
class DebugBox:
    """A rectangle + label for the calibration view (absolute screen px)."""
    x: int
    y: int
    w: int
    h: int
    text: str
    color: str


class Overlay:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._hide_after_id: str | None = None
        self._fade_after_id: str | None = None
        self._hwnd = None
        self._user32 = None
        self._base_alpha = max(40, min(255, int(getattr(cfg, "overlay_opacity", 210))))

        # Which monitor to draw on (matches the capture monitor).
        left, top, width, height = get_monitor_bounds(getattr(cfg, "monitor", 1))
        self._win_x, self._win_y = left, top

        self.root = tk.Tk()
        # Keep the window hidden until the transparency is applied, otherwise the
        # full-screen magenta key colour flashes for a frame on first launch.
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", _TRANSPARENT_KEY)
        self.root.config(bg=_TRANSPARENT_KEY)
        self.root.geometry(f"{width}x{height}+{left}+{top}")

        self.canvas = tk.Canvas(
            self.root,
            width=width,
            height=height,
            bg=_TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._font = tkfont.Font(family=cfg.font_family, size=cfg.font_size,
                                 weight="bold")
        self._small_font = tkfont.Font(family=cfg.font_family,
                                       size=max(9, cfg.font_size - 5))

        # Realize the (still-hidden) window so its HWND exists, then apply the
        # click-through + colour key while hidden. The window STAYS hidden until
        # there's something to show (see _show/_clear) — so when idle it never
        # flashes and never blocks the desktop or other windows.
        self.root.update_idletasks()
        self._make_click_through()
        self.root.after(16, self._poll)

    # ---- window styling -------------------------------------------------
    def _make_click_through(self) -> None:
        """Make the window click-through AND colour-key transparent.

        We set WS_EX_LAYERED ourselves and then *explicitly* apply the colour
        key with SetLayeredWindowAttributes. Relying only on Tk's
        ``-transparentcolor`` is fragile: re-writing the extended style (to add
        click-through) can clear the key Tk set, and a layered window without a
        key renders fully opaque/black. Re-applying it here is the fix.
        """
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetLayeredWindowAttributes.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_ubyte, ctypes.c_uint32
            ]
            # The OUTER top-level window receives mouse hit-testing, so
            # WS_EX_TRANSPARENT must go there (not the inner content window) or
            # clicks won't pass through to the game/desktop.
            hwnd = user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = user32.GetParent(self.canvas.winfo_id())

            ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ex |= (
                _WS_EX_LAYERED
                | _WS_EX_TRANSPARENT
                | _WS_EX_TOOLWINDOW
                | _WS_EX_NOACTIVATE
            )
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
            self._hwnd = hwnd
            self._user32 = user32
            # Magenta = transparent (colour key) AND a global alpha we can
            # animate for the fade-out. Start fully opaque.
            self._set_alpha(self._base_alpha)
        except Exception as exc:  # pragma: no cover - platform dependent
            print(f"[overlay] could not set click-through style: {exc!r}")

    def _show(self) -> None:
        """Show the window, then (re)apply click-through to the now-visible window.

        The outer top-level HWND only exists once the window is mapped, so we
        deiconify first and apply the styles afterwards.
        """
        try:
            self.root.deiconify()
            self.root.update_idletasks()
        except Exception:
            pass
        self._make_click_through()

    def _hide(self) -> None:
        """Hide the window so it never blocks the desktop / other windows."""
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _set_alpha(self, alpha: float) -> None:
        """Set the window's global opacity (0..255), keeping magenta transparent."""
        if self._hwnd is None or self._user32 is None:
            return
        a = int(max(0, min(255, alpha)))
        try:
            self._user32.SetLayeredWindowAttributes(
                self._hwnd, _TRANSPARENT_COLORREF, a, _LWA_COLORKEY | _LWA_ALPHA
            )
        except Exception:
            pass

    # ---- thread-safe API ------------------------------------------------
    def request_render(self, labels: list[Label], persist: bool = False) -> None:
        """Show ``labels``. When ``persist`` is True they stay until cleared
        (no auto-hide / fade) — the app clears them when the panel closes."""
        self._q.put(("render", (labels, persist)))

    def request_render_debug(self, boxes: list[DebugBox], seconds: float) -> None:
        self._q.put(("debug", (boxes, seconds)))

    def request_progress(self, text: str, frac: float) -> None:
        self._q.put(("progress", (text, frac)))

    def request_clear(self) -> None:
        self._q.put(("clear", None))

    def request_call(self, fn) -> None:
        """Run ``fn()`` on the Tk main thread (e.g. to open a settings window)."""
        self._q.put(("call", fn))

    def request_stop(self) -> None:
        self._q.put(("stop", None))

    # ---- Tk loop --------------------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "render":
                    self._render(*payload)
                elif kind == "debug":
                    self._render_debug(*payload)
                elif kind == "progress":
                    self._render_progress(*payload)
                elif kind == "clear":
                    self._clear()
                elif kind == "call":
                    try:
                        payload()
                    except Exception as exc:
                        print(f"[overlay] call failed: {exc!r}")
                elif kind == "stop":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(16, self._poll)

    # canvas-local coordinates from absolute screen coordinates
    def _lx(self, x: float) -> float:
        return x - self._win_x

    def _ly(self, y: float) -> float:
        return y - self._win_y

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        """A rounded rectangle (smoothed polygon) for the price tags."""
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _draw_text(self, x: float, y: float, text: str, color: str, font=None,
                   anchor: str = "w") -> None:
        """Draw a price as colour text on a rounded, semi-dark 'pill'.

        The pill gives crisp contrast over any background and avoids the magenta
        colour-key fringing that anti-aliased outlines produce. Text is drawn
        *after* the pill so its anti-aliased edges blend against the dark pill,
        not the transparent key colour.
        """
        font = font or self._font
        cx, cy = self._lx(x), self._ly(y)
        tw = font.measure(text)
        th = font.metrics("linespace")
        x0 = cx if anchor == "w" else cx - tw / 2
        y0 = cy - th / 2
        padx, pady = 9, 4
        self._round_rect(
            x0 - padx, y0 - pady, x0 + tw + padx, y0 + th + pady, r=9,
            fill="#0d0d12", outline="#3a3a46", width=1,
        )
        self.canvas.create_text(cx, cy, text=text, fill=color, font=font,
                                anchor=anchor)

    def _render(self, labels: list[Label], persist: bool = False) -> None:
        self._clear_timer()
        self._show()
        self.canvas.delete("all")
        for lab in labels:
            self._draw_text(lab.x, lab.y, lab.text, lab.color,
                            anchor=getattr(lab, "anchor", "w"))
        if persist:
            # Keep the prices up until the app clears them (panel closed). Reset
            # to full opacity in case a previous fade had dimmed the window.
            self._set_alpha(self._base_alpha)
            return
        # Stay fully visible for (display - fade) seconds, then fade out over
        # the last `fade_seconds` so prices dissolve instead of blinking off.
        full = float(self.cfg.display_seconds)
        fade = max(0.0, min(float(getattr(self.cfg, "fade_seconds", 2.0)), full))
        hold_ms = int(max(0.0, full - fade) * 1000)
        self._hide_after_id = self.root.after(hold_ms, lambda: self._start_fade(fade))

    def _start_fade(self, fade: float) -> None:
        self._hide_after_id = None
        if fade <= 0:
            self._clear()
            return
        steps = max(1, int(fade / 0.07))      # ~70 ms per step
        self._fade_alpha = float(self._base_alpha)
        self._fade_dec = float(self._base_alpha) / steps
        self._fade_interval = max(20, int(fade * 1000 / steps))
        self._fade_tick()

    def _fade_tick(self) -> None:
        self._fade_alpha -= self._fade_dec
        if self._fade_alpha <= 0:
            self._fade_after_id = None
            self._clear()
            return
        self._set_alpha(self._fade_alpha)
        self._fade_after_id = self.root.after(self._fade_interval, self._fade_tick)

    def _render_debug(self, boxes: list[DebugBox], seconds: float) -> None:
        self._clear_timer()
        self._show()
        self.canvas.delete("all")
        for b in boxes:
            x0, y0 = self._lx(b.x), self._ly(b.y)
            x1, y1 = self._lx(b.x + b.w), self._ly(b.y + b.h)
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=b.color, width=2)
            if b.text:
                self._draw_text(b.x + b.w + 8, b.y + b.h / 2, b.text, b.color,
                                font=self._small_font)
        self._hide_after_id = self.root.after(int(seconds * 1000), self._clear)

    def _render_progress(self, text: str, frac: float) -> None:
        """A persistent loading bar at the top of the screen (no auto-hide)."""
        self._clear_timer()
        self._show()
        self.canvas.delete("all")
        frac = max(0.0, min(1.0, frac))
        bw, bh = 460, 40
        bx = self._lx(self._win_x) + (self.canvas.winfo_width() - bw) // 2
        by = 70
        self.canvas.create_rectangle(bx - 2, by - 2, bx + bw + 2, by + bh + 2,
                                     fill="#0d0d12", outline="#33333d", width=1)
        if frac > 0:
            self.canvas.create_rectangle(bx, by, bx + int(bw * frac), by + bh,
                                         fill="#51cf66", width=0)
        self.canvas.create_text(bx + bw // 2, by + bh // 2, text=text,
                                fill="#ffffff", font=self._small_font)

    def _clear(self) -> None:
        self._clear_timer()
        self.canvas.delete("all")
        self._hide()  # hide the window so it never blocks the desktop when idle

    def _clear_timer(self) -> None:
        for attr in ("_hide_after_id", "_fade_after_id"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
                setattr(self, attr, None)

    def run(self) -> None:
        self.root.mainloop()
