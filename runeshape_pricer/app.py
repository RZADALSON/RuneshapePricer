"""Application orchestration: hotkey -> capture -> OCR -> price -> overlay.

Threading model
---------------
* main thread       : Tk overlay loop (must own the GUI)
* hotkey thread     : the ``keyboard`` library's hook; the callback just spawns
                      a short-lived worker so the hook never blocks
* worker thread     : capture + OCR + pricing for one F3 press
* refresh thread    : periodic poe.ninja re-fetch
* tray thread       : pystray detached icon loop
"""

from __future__ import annotations

import threading
import time

from . import __version__
from .capture import grab_region, set_dpi_aware
from .config import Config, load_config
from .icons import IconIndex
from .overlay import DebugBox, Label, Overlay
from .parsing import parse_output_line
from .prices import PriceBook

# Label colours.
_COLOR_GOLD = "#FFD700"      # very valuable (>= gold_value) -> gold
_COLOR_HIGH = "#51CF66"      # valuable -> green
_COLOR_MID = "#FFFFFF"       # decent -> white
_COLOR_LOW = "#ADB5BD"       # cheap -> grey
_COLOR_UNKNOWN = "#FFD43B"   # variable reward (e.g. unique) -> yellow
_COLOR_NOMATCH = "#FF8787"   # calibration only: parsed but no price -> red
_COLOR_REGION = "#4DABF7"    # calibration only: capture-area outline -> blue

# Icon-scan mode (mode 2) is disabled until the recognition is accurate enough.
# Flip to True (and re-add "scan" in settings_ui._MODES) to re-enable.
_SCAN_ENABLED = False


def _fmt_value(value: float, suffix: str) -> str:
    """Human-friendly exalt amount (no ugly '0.0 ex')."""
    if value < 0.095:
        body = "<0.1"
    elif value < 10:
        body = f"{value:.1f}"
    elif value < 1000:
        body = f"{value:.0f}"
    else:
        body = f"{value / 1000:.1f}k"
    return body + suffix


class PricerApp:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.book = PriceBook()
        self.icons = IconIndex()
        self.overlay = Overlay(cfg)
        self._stop = threading.Event()
        self._busy = threading.Lock()

    # ---- pricing --------------------------------------------------------
    def _refresh_prices(self) -> None:
        self.book.refresh(self.cfg.league, self.cfg.categories)

    def _refresh_loop(self) -> None:
        # Prices are fetched ONCE at startup only (no periodic refresh, no
        # manual refresh) to keep load on poe.ninja minimal.
        self._refresh_prices()

    # ---- the F3 / F4 actions -------------------------------------------
    def _run_locked(self, target) -> None:
        """Run ``target`` in a worker, but never two reads at once."""
        if not self._busy.acquire(blocking=False):
            return
        try:
            threading.Thread(target=target, daemon=True).start()
        except Exception:
            self._busy.release()
            raise

    def on_hotkey(self) -> None:
        # Shift+F3 opens settings; don't also fire the price overlay then.
        try:
            import keyboard
            if keyboard.is_pressed("shift"):
                return
        except Exception:
            pass
        if _SCAN_ENABLED and getattr(self.cfg, "mode", "runeshape") == "scan":
            self._run_locked(self._scan_and_show)
        else:
            self._run_locked(self._read_and_show)

    def on_calibrate(self) -> None:
        self._run_locked(self._calibrate)

    def _grab(self):
        """Capture either the whole screen or just the panel region."""
        if getattr(self.cfg, "scan_full_screen", False):
            return grab_region(0.0, 0.0, 1.0, 1.0, self.cfg.monitor)
        return grab_region(
            self.cfg.region_x, self.cfg.region_y,
            self.cfg.region_w, self.cfg.region_h, self.cfg.monitor,
        )

    def _color_for(self, value: float) -> str:
        if value >= getattr(self.cfg, "gold_value", 800.0):
            return _COLOR_GOLD
        if value >= self.cfg.high_value:
            return _COLOR_HIGH
        if value >= self.cfg.mid_value:
            return _COLOR_MID
        return _COLOR_LOW

    def _read_and_show(self) -> None:
        try:
            if self.book.item_count == 0:
                print("[app] prices not loaded yet, ignoring hotkey")
                return

            cap = self._grab()

            # Import OCR lazily so a missing OCR pack doesn't stop the app from
            # starting (it'll just report on first use).
            from .ocr import read_lines, OcrUnavailable
            try:
                lines = read_lines(cap.image, self.cfg.ocr_language,
                                   getattr(self.cfg, "ocr_scale", 1.5))
            except OcrUnavailable as exc:
                print(f"[app] {exc}")
                return

            priced: list[tuple] = []  # (right_edge_x, center_y, text, color)
            for ln in lines:
                parsed = parse_output_line(ln.text)
                if parsed is None:
                    continue
                entry = self.book.lookup(parsed.name)
                if entry is not None:
                    value = entry.exalt * parsed.quantity
                    if value < self.cfg.min_value:
                        continue
                    text = _fmt_value(value, self.cfg.currency_suffix)
                    color = self._color_for(value)
                elif parsed.is_unique:
                    text = self.cfg.unknown_marker
                    color = _COLOR_UNKNOWN
                elif parsed.had_quantity and self.cfg.show_unpriced:
                    # An output row we recognised but poe.ninja can't price
                    # (e.g. Alloys) -> a dash, so it doesn't look broken.
                    text = self.cfg.unpriced_marker
                    color = _COLOR_LOW
                else:
                    continue  # a header or unmatched noise -> show nothing
                priced.append((ln.x + ln.w, ln.cy, text, color))

            if not priced:
                print("[app] no priceable rows detected")
                self.overlay.request_clear()
                return

            # Align all prices into a single column just right of the panel.
            column_x = max(p[0] for p in priced) + self.cfg.label_offset_x
            labels = [
                Label(
                    x=int(cap.origin_x + column_x),
                    y=int(cap.origin_y + cy),
                    text=text,
                    color=color,
                )
                for (_right, cy, text, color) in priced
            ]
            self.overlay.request_render(labels)
            print(f"[app] showed {len(labels)} prices")
        except Exception as exc:  # never let the worker thread kill the app
            print(f"[app] read failed: {exc!r}")
        finally:
            self._busy.release()

    def _calibrate(self) -> None:
        """Show the capture area + exactly what OCR read for each row.

        Use it on the live game to verify the region covers the panel and that
        the rows are recognised, then tune ``region_*`` / ``monitor`` if not.
        """
        try:
            cap = self._grab()
            from .ocr import read_lines, OcrUnavailable
            try:
                lines = read_lines(cap.image, self.cfg.ocr_language,
                                   getattr(self.cfg, "ocr_scale", 1.5))
            except OcrUnavailable as exc:
                print(f"[app] {exc}")
                return

            boxes = [DebugBox(
                cap.origin_x, cap.origin_y,
                cap.image.width, cap.image.height,
                "capture area", _COLOR_REGION,
            )]
            for ln in lines:
                parsed = parse_output_line(ln.text)
                label, color = ln.text, _COLOR_LOW
                if parsed is not None:
                    entry = self.book.lookup(parsed.name)
                    if entry is not None:
                        value = entry.exalt * parsed.quantity
                        label = f"{_fmt_value(value, self.cfg.currency_suffix)}  «{ln.text}»"
                        color = self._color_for(value)
                    elif parsed.is_unique:
                        label = f"?  «{ln.text}»"
                        color = _COLOR_UNKNOWN
                    else:
                        label = f"—  «{ln.text}»"
                        color = _COLOR_NOMATCH
                boxes.append(DebugBox(
                    int(cap.origin_x + ln.x), int(cap.origin_y + ln.y),
                    int(ln.w), int(ln.h), label, color,
                ))
            self.overlay.request_render_debug(
                boxes, max(6.0, self.cfg.display_seconds * 2)
            )
            print(f"[app] calibration: {len(lines)} OCR lines")
        except Exception as exc:
            print(f"[app] calibrate failed: {exc!r}")
        finally:
            self._busy.release()

    # ---- scan mode (icon recognition) ----------------------------------
    def _ensure_icons_async(self) -> None:
        if self.icons.ready or getattr(self, "_icons_building", False):
            return
        self._icons_building = True

        def work():
            try:
                self.icons.build(self.cfg.league, self.cfg.categories)
            finally:
                self._icons_building = False

        threading.Thread(target=work, daemon=True).start()
        threading.Thread(target=self._progress_loop, daemon=True).start()

    def _progress_loop(self) -> None:
        while getattr(self, "_icons_building", False):
            done, total = self.icons.progress
            if total:
                self.overlay.request_progress(
                    f"Ładowanie ikon: {done}/{total}", done / total)
            else:
                self.overlay.request_progress("Pobieram listy itemów...", 0.0)
            time.sleep(0.25)
        self.overlay.request_clear()

    def _status_overlay(self, text: str) -> None:
        from .capture import get_monitor_bounds
        left, top, _w, _h = get_monitor_bounds(getattr(self.cfg, "monitor", 1))
        self.overlay.request_render([Label(left + 80, top + 80, text, "#FFD43B")])

    def _scan_and_show(self) -> None:
        """Mode 'scan': recognise item icons on screen and price each.

        This mode ALWAYS scans the whole screen (stash/inventory can be
        anywhere). Empty/uniform cells are skipped, and matches go through a
        margin + colour gate (see IconIndex.match) plus position NMS to keep
        one price per item and limit false positives.
        """
        try:
            if not self.icons.ready:
                self._ensure_icons_async()  # progress bar is shown by _progress_loop
                return

            cap = grab_region(0.0, 0.0, 1.0, 1.0, getattr(self.cfg, "monitor", 1))
            img = cap.image
            gray = img.convert("L")
            cell = int(self.cfg.scan_cell) or max(48, img.height // 26)
            thr = int(self.cfg.scan_threshold)
            step = max(10, cell // 2)

            candidates = []  # (dist, cx, cy, entry)
            gy = 0
            while gy + cell <= img.height:
                gx = 0
                while gx + cell <= img.width:
                    lo, hi = gray.crop((gx, gy, gx + cell, gy + cell)).getextrema()
                    if hi - lo >= 40:  # skip flat/empty cells
                        entry, dist = self.icons.match(
                            img.crop((gx, gy, gx + cell, gy + cell)), thr
                        )
                        if entry is not None:
                            candidates.append((dist, gx + cell // 2, gy + cell // 2, entry))
                    gx += step
                gy += step

            # Non-maximum suppression: best match wins, suppress overlaps.
            candidates.sort(key=lambda c: c[0])
            sep = cell * 0.7
            kept = []
            for dist, cx, cy, entry in candidates:
                if all(abs(cx - kx) > sep or abs(cy - ky) > sep
                       for _, kx, ky, _ in kept):
                    kept.append((dist, cx, cy, entry))

            # Price shown centred on the icon that was recognised.
            labels = [
                Label(
                    int(cap.origin_x + cx),
                    int(cap.origin_y + cy),
                    _fmt_value(entry.exalt, self.cfg.currency_suffix),
                    self._color_for(entry.exalt),
                    anchor="center",
                )
                for (dist, cx, cy, entry) in kept
                if entry.exalt >= self.cfg.min_value
            ]
            if labels:
                self.overlay.request_render(labels)
                print(f"[app] scan: {len(labels)} items priced")
            else:
                self.overlay.request_clear()
                print("[app] scan: nothing recognised (try calibrating scan_cell)")
        except Exception as exc:
            print(f"[app] scan failed: {exc!r}")
        finally:
            self._busy.release()

    # ---- hotkeys & settings --------------------------------------------
    def apply_hotkeys(self) -> None:
        """(Re)register global hotkeys from the current config."""
        try:
            import keyboard
            keyboard.unhook_all()
            keyboard.add_hotkey(self.cfg.hotkey, self.on_hotkey)
            keyboard.add_hotkey(self.cfg.settings_hotkey, self.open_settings)
            msg = (f"{self.cfg.hotkey.upper()} = prices, "
                   f"{self.cfg.settings_hotkey.upper()} = settings")
            if getattr(self.cfg, "calibrate_enabled", False):
                keyboard.add_hotkey(self.cfg.calibrate_hotkey, self.on_calibrate)
                msg += f", {self.cfg.calibrate_hotkey.upper()} = calibration"
            print(f"[app] hotkeys: {msg}")
        except Exception as exc:
            print(f"[app] could not register hotkeys: {exc!r}")

    def open_settings(self) -> None:
        # Must build the Tk window on the main (overlay) thread.
        self.overlay.request_call(self._open_settings_window)

    def _open_settings_window(self) -> None:
        try:
            from .settings_ui import open_settings
            open_settings(self.overlay.root, self.cfg, self._on_settings_saved)
        except Exception as exc:
            print(f"[app] settings window failed: {exc!r}")

    def _on_settings_saved(self) -> None:
        try:
            self.cfg.save()
        except Exception as exc:
            print(f"[app] could not save config: {exc!r}")
        self.apply_hotkeys()
        if _SCAN_ENABLED and getattr(self.cfg, "mode", "runeshape") == "scan":
            self._ensure_icons_async()
        print("[app] settings saved")

    # ---- lifecycle ------------------------------------------------------
    def status_text(self) -> str:
        if self.book.last_update == 0:
            return "Prices: loading..."
        age = int(time.time() - self.book.last_update)
        return f"{self.book.active_league}: {self.book.item_count} items ({age}s ago)"

    def stop(self) -> None:
        self._stop.set()
        self.overlay.request_stop()


def main() -> None:
    set_dpi_aware()
    cfg = load_config()

    # Free & open: no license gate. (See licensing.py — kept but unused.)
    print(f"Runeshape Pricer v{__version__}")
    print(f"  league   : {cfg.league}")
    print(f"  hotkey   : {cfg.hotkey.upper()}  (press it with the Runeshape panel open)")
    print(f"  categories: {', '.join(cfg.categories)}")

    app = PricerApp(cfg)

    # Background price refresh (once).
    threading.Thread(target=app._refresh_loop, daemon=True).start()

    # Warm up the OCR engine so the very first F3 is instant.
    def _warm():
        try:
            from .ocr import warm_up
            warm_up(cfg.ocr_language)
            print("[app] OCR warmed up")
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()

    # Pre-build the icon index if starting in scan mode (disabled for now).
    if _SCAN_ENABLED and getattr(cfg, "mode", "runeshape") == "scan":
        app._ensure_icons_async()

    # Global hotkeys (respects calibrate_enabled).
    app.apply_hotkeys()

    # System tray (optional).
    tray = None
    try:
        from .tray import Tray
        tray = Tray(
            on_settings=app.open_settings,
            on_quit=app.stop,
            status_fn=app.status_text,
        )
        tray.run_detached()
    except Exception as exc:
        print(f"[app] tray unavailable ({exc!r}); running without it. "
              f"Close this window to quit.")

    try:
        app.overlay.run()  # blocks until Quit
    finally:
        app._stop.set()
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        if tray is not None:
            tray.stop()


if __name__ == "__main__":
    main()
