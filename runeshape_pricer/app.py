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

# Persist mode: the watcher cheaply diffs the panel region several times a
# second (no OCR) so prices vanish almost instantly when the panel closes,
# without burning CPU on constant OCR while it just sits open. OCR runs only on
# a moderate change (scroll / tab switch) to re-place the prices.
_WATCH_INTERVAL = 0.05     # seconds between cheap panel snapshots (~20 Hz)
_WATCH_DIFF_MIN = 0.045    # mean frame-to-frame change (0..1); below = unchanged
_WATCH_DIFF_GONE = 0.22    # a change this large = panel vanished -> clear at once


def _fmt_value(value: float, suffix: str, divine: bool = False) -> str:
    """Human-friendly currency amount (no ugly '0.0 ex').

    Divine amounts are small numbers (a divine is worth ~100+ exalts), so they
    keep more decimal places for the cheap rows instead of collapsing them all
    to a single "<0.1".
    """
    if divine:
        if value < 0.005:
            body = "<0.01"
        elif value < 1:
            body = f"{value:.2f}"
        elif value < 100:
            body = f"{value:.1f}"
        else:
            body = f"{value:.0f}"
    elif value < 0.095:
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
        # Persist-mode panel watcher: a generation counter cancels a running
        # watcher when a new read starts or settings change.
        self._watch_gen = 0
        self._watch_sig = ""

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

    def _watch_grab(self):
        """Cheap snapshot for the persist watcher: just the middle band of the
        capture region. Closing the panel swaps the whole area (parchment ->
        game world), so a thin band is enough to detect it — and grabbing ~1/3
        the pixels keeps the fast (~20 Hz) poll loop light on CPU.
        """
        if getattr(self.cfg, "scan_full_screen", False):
            return grab_region(0.0, 0.35, 1.0, 0.3, self.cfg.monitor)
        h = self.cfg.region_h * 0.3
        y = self.cfg.region_y + (self.cfg.region_h - h) / 2
        return grab_region(self.cfg.region_x, y, self.cfg.region_w, h,
                           self.cfg.monitor)

    def _color_for(self, value: float) -> str:
        if value >= getattr(self.cfg, "gold_value", 800.0):
            return _COLOR_GOLD
        if value >= self.cfg.high_value:
            return _COLOR_HIGH
        if value >= self.cfg.mid_value:
            return _COLOR_MID
        return _COLOR_LOW

    def _price_parts(self, exalt_value: float) -> tuple[str, str]:
        """Return ``(number_text, icon)`` for an exalt value in the chosen
        currency. ``icon`` is "exalt" or "divine" — the overlay draws the
        matching orb image instead of a textual suffix. Colours are still
        decided from the exalt value, so the thresholds keep their meaning. If
        divine is selected but the rate is unknown (no Currency data), fall
        back to exalts.
        """
        if (getattr(self.cfg, "currency_display", "exalt") == "divine"
                and self.book.divine_rate > 0):
            return _fmt_value(exalt_value / self.book.divine_rate, "",
                              divine=True), "divine"
        return _fmt_value(exalt_value, "", divine=False), "exalt"

    def _format_price(self, exalt_value: float) -> str:
        """Textual price (number + suffix) — used by the calibration view."""
        text, icon = self._price_parts(exalt_value)
        suffix = (getattr(self.cfg, "divine_suffix", " div") if icon == "divine"
                  else self.cfg.currency_suffix)
        return text + suffix

    def _compute_labels(self) -> tuple[list, str]:
        """Capture + OCR + price the panel; return ``(labels, signature)``.

        ``signature`` changes whenever the rendered prices change, so the
        persist watcher can skip redundant redraws. Returns ``([], "")`` when no
        priceable rows are visible (panel closed / not open). Does not touch the
        overlay — callers decide what to render.
        """
        cap = self._grab()

        # Import OCR lazily so a missing OCR pack doesn't stop the app from
        # starting (it'll just report on first use).
        from .ocr import read_lines, OcrUnavailable
        try:
            lines = read_lines(cap.image, self.cfg.ocr_language,
                               getattr(self.cfg, "ocr_scale", 1.5))
        except OcrUnavailable as exc:
            print(f"[app] {exc}")
            return [], ""

        priced: list[tuple] = []  # (right_edge_x, center_y, text, color, icon)
        for ln in lines:
            parsed = parse_output_line(ln.text)
            if parsed is None:
                continue
            entry = self.book.lookup(parsed.name)
            icon = None
            if entry is not None:
                value = entry.exalt * parsed.quantity
                if value < self.cfg.min_value:
                    continue
                text, icon = self._price_parts(value)
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
            priced.append((ln.x + ln.w, ln.cy, text, color, icon))

        if not priced:
            return [], ""

        # Align all prices into a single column just right of the panel.
        column_x = max(p[0] for p in priced) + self.cfg.label_offset_x
        labels = [
            Label(
                x=int(cap.origin_x + column_x),
                y=int(cap.origin_y + cy),
                text=text,
                color=color,
                icon=icon,
            )
            for (_right, cy, text, color, icon) in priced
        ]
        sig = "|".join(f"{lab.y}:{lab.text}:{lab.icon}" for lab in labels)
        return labels, sig

    def _read_and_show(self) -> None:
        try:
            if self.book.item_count == 0:
                print("[app] prices not loaded yet, ignoring hotkey")
                return

            labels, sig = self._compute_labels()
            if not labels:
                print("[app] no priceable rows detected")
                self.overlay.request_clear()
                self._watch_gen += 1  # cancel any persist watcher
                return

            persist = bool(getattr(self.cfg, "persist_until_closed", False))
            self.overlay.request_render(labels, persist=persist)
            print(f"[app] showed {len(labels)} prices"
                  + (" (persist)" if persist else ""))
            if persist:
                self._start_watch(sig)
            else:
                self._watch_gen += 1  # drop any stale watcher pinning the prices
        except Exception as exc:  # never let the worker thread kill the app
            print(f"[app] read failed: {exc!r}")
        finally:
            self._busy.release()

    # ---- persist-mode panel watcher ------------------------------------
    def _start_watch(self, signature: str) -> None:
        """Spawn the watcher that clears the prices once the panel closes."""
        self._watch_gen += 1
        gen = self._watch_gen
        self._watch_sig = signature
        threading.Thread(target=self._watch_loop, args=(gen,),
                         daemon=True).start()

    def _watch_loop(self, gen: int) -> None:
        from PIL import Image, ImageChops, ImageStat

        def snapshot():
            """Tiny greyscale thumbnail of the panel band for cheap diffing.
            NEAREST just samples a few thousand pixels, so it's near-free."""
            return self._watch_grab().image.resize((64, 32), Image.NEAREST).convert("L")

        ref = None
        last_sig = self._watch_sig
        while not self._stop.is_set() and self._watch_gen == gen:
            time.sleep(_WATCH_INTERVAL)
            if self._stop.is_set() or self._watch_gen != gen:
                return
            try:
                small = snapshot()
            except Exception as exc:
                print(f"[app] watch grab failed: {exc!r}")
                continue
            if ref is None:
                ref = small  # baseline (taken once the prices are on screen)
                continue
            diff = ImageStat.Stat(ImageChops.difference(small, ref)).mean[0] / 255.0
            ref = small  # compare frame-to-frame, so ambient motion is ignored
            if diff < _WATCH_DIFF_MIN:
                continue  # panel unchanged -> keep prices up, no OCR (cheap)
            if diff >= _WATCH_DIFF_GONE:
                print(f"[app] panel closed (change={diff:.2f}); clearing prices")
                self.overlay.request_clear()
                return
            # Moderate change (scroll / tab / partial close) -> OCR to decide.
            if not self._busy.acquire(blocking=False):
                continue
            try:
                labels, sig = self._compute_labels()
            except Exception as exc:
                print(f"[app] watch read failed: {exc!r}")
                labels, sig = None, ""
            finally:
                self._busy.release()
            if self._watch_gen != gen:
                return  # a newer read superseded us while we were reading
            if labels is None:
                continue  # transient error -> keep the prices, try again
            if not labels:
                print(f"[app] panel closed (change={diff:.2f}); clearing prices")
                self.overlay.request_clear()
                return
            if sig != last_sig:  # panel scrolled / changed -> re-place prices
                self.overlay.request_render(labels, persist=True)
                last_sig = sig
            ref = None  # rebuild the baseline after the (possible) re-render

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
                        label = f"{self._format_price(value)}  «{ln.text}»"
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
            labels = []
            for (dist, cx, cy, entry) in kept:
                if entry.exalt < self.cfg.min_value:
                    continue
                text, icon = self._price_parts(entry.exalt)
                labels.append(Label(
                    int(cap.origin_x + cx),
                    int(cap.origin_y + cy),
                    text,
                    self._color_for(entry.exalt),
                    anchor="center",
                    icon=icon,
                ))
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
        # Drop any persistent prices + watcher so currency/persist changes take
        # effect cleanly on the next F3 (a stale watcher could keep old prices
        # in a now-different currency pinned on screen).
        self._watch_gen += 1
        self.overlay.request_clear()
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

    # Brief on-screen notice that the program is running in the background.
    try:
        from .capture import get_monitor_bounds
        from .i18n import t
        left, top, mw, mh = get_monitor_bounds(getattr(cfg, "monitor", 1))
        app.overlay.request_render([Label(
            left + mw // 2, top + int(mh * 0.10),
            t(cfg.language, "startup_running"), "#d6ead9", anchor="center",
        )])
    except Exception as exc:
        print(f"[app] startup notice failed: {exc!r}")

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
