"""Configuration loading/saving.

A ``config.json`` file is created next to the executable (or the project root
when running from source) on first launch. Editing it lets the user change the
league, hotkey, capture region, etc. without touching the code.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field


def app_dir() -> str:
    """Folder where config.json lives.

    When frozen by PyInstaller we use the folder containing the .exe so the
    config sits next to it; otherwise the project root.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(app_dir(), "config.json")


# poe.ninja PoE2 economy categories (the `type` values) to pull prices from.
# These are poe.ninja's internal codenames, which don't always match the site's
# sidebar labels -- the comments give the displayed name:
DEFAULT_CATEGORIES = [
    "Currency",            # Currency (orbs)
    "Expedition",          # Expedition (artifacts, Flux)
    "Runes",               # Runes
    "Verisium",            # Alloys + Starlit Ore + Crests
    "Idols",               # Idols
    "LineageSupportGems",  # Lineage Gems
    "Fragments",           # Fragments
    "Essences",            # Essences
    "UncutGems",           # Uncut Gems (per level)
    "SoulCores",           # Soul Cores
    "Breach",              # Catalysts
    "Ritual",              # Ritual rewards + Omens
    "Delirium",            # Liquid Emotions
    "Abyss",               # Abyssal Bones
]


@dataclass
class Config:
    # UI language: "en" (default) or "pl".
    language: str = "en"

    # PoE2 league. "auto" detects the current challenge league from poe.ninja
    # (survives league rotations); or set an exact display name, e.g.
    # "Runes of Aldur".
    league: str = "auto"
    categories: list = field(default_factory=lambda: list(DEFAULT_CATEGORIES))

    # Which monitor PoE2 is on (1 = primary, 2 = second, ...). The capture and
    # the overlay both use this screen.
    monitor: int = 1

    # Global hotkey that triggers a screen read + price overlay.
    hotkey: str = "f3"
    # Open the settings window.
    settings_hotkey: str = "shift+f3"
    # Developer calibration view: off by default. When enabled, calibrate_hotkey
    # shows the capture area + what OCR reads (for tuning the region).
    calibrate_enabled: bool = False
    calibrate_hotkey: str = "f4"

    # Mode: "runeshape" reads the Runeshape Combinations panel (text OCR).
    #       "scan" recognises item ICONS on screen and prices each (experimental).
    mode: str = "runeshape"
    # Icon-scan mode tuning (calibrate against your stash/inventory).
    scan_cell: int = 0          # icon size in px; 0 = auto (screen height / 26)
    scan_threshold: int = 12    # max perceptual-hash distance to accept a match
                                # (lower = fewer but more confident matches)

    # Scan the whole screen, or just the Runeshape panel area (region_* / left).
    scan_full_screen: bool = False

    # Capture region as fractions of the primary screen (the Runeshape panel is
    # on the left). Defaults cover the left ~48% of the screen, full height.
    region_x: float = 0.0
    region_y: float = 0.0
    region_w: float = 0.48
    region_h: float = 1.0

    # How long (seconds) the prices stay on screen before they're gone.
    display_seconds: float = 6.0
    # The last `fade_seconds` of that time are spent fading out smoothly.
    fade_seconds: float = 2.0

    # When True, prices ignore display_seconds and stay on screen until the
    # Runeshape panel closes: the app keeps re-reading the panel and clears the
    # prices once it can no longer find any priceable rows (i.e. you closed it).
    persist_until_closed: bool = False

    # How often (minutes) prices are re-fetched from poe.ninja in the background.
    refresh_minutes: int = 30

    # Overlay appearance.
    font_family: str = "Segoe UI"
    font_size: int = 17
    # Thickness (px) of the dark halo drawn around price text so it stays
    # readable over any background. 0 = no outline.
    outline_width: int = 3
    label_offset_x: int = 12          # gap (px) between the row text and the price
    # Overlay opacity 0..255 (255 = solid). Lower makes the dark price tags a
    # bit see-through so they look nicer over the game.
    overlay_opacity: int = 210
    decimals: int = 1                  # decimal places for the exalt value
    currency_suffix: str = " ex"

    # Currency the prices are shown in: "exalt" (Exalted Orbs) or "divine"
    # (Divine Orbs). Divine uses the live divine->exalt rate from poe.ninja
    # (the Divine Orb's own exalt price). Switch it in the settings window.
    currency_display: str = "exalt"
    # Suffix drawn after a divine amount (mirrors currency_suffix for exalts).
    divine_suffix: str = " div"

    # Value-based colouring (exalt thresholds). Items at/above gold_value are
    # drawn gold, at/above high_value green, at/above mid_value white, below
    # that grey.
    gold_value: float = 800.0
    high_value: float = 50.0
    mid_value: float = 5.0

    # Lines that did parse as an output but could not be priced (e.g. "Unique
    # Jewellery") are shown as this marker instead of a number.
    unknown_marker: str = "?"

    # Output rows that have an explicit "Nx" but no poe.ninja price (e.g. the
    # Alloys tab -- alloys aren't tradeable on poe.ninja) get this marker, so a
    # blank row doesn't look like a bug. Set show_unpriced=false to hide them.
    unpriced_marker: str = "—"
    show_unpriced: bool = True

    # Don't bother showing values below this many exalts (set to 0 to show all).
    min_value: float = 0.0

    # OCR recognizer language. "auto" uses whatever Windows OCR pack is
    # installed (English preferred, otherwise your Windows language -- any
    # Latin-script pack reads PoE2 item names fine).
    ocr_language: str = "auto"
    # OCR upscale factor. Fixed at 1.0 = no upscale = fastest possible reads
    # (~0.5s on a 4K capture). Higher would be more accurate but slower.
    ocr_scale: float = 1.0

    # --- Licensing (Keygen) ------------------------------------------------
    # Your Keygen account id (from https://api.keygen.sh/v1/accounts/<HERE>/...).
    # Leave empty to disable licensing entirely (the app runs unlocked).
    keygen_account_id: str = ""
    # The end user's license key (filled on first run via the prompt; you can
    # also pre-fill it here for testing).
    license_key: str = ""
    # Timestamp of the last successful online validation (managed automatically).
    license_last_valid: float = 0.0
    # If the licensing server is unreachable, allow the app to keep running this
    # many days since the last successful validation (avoids lockouts on a
    # flaky connection). Set 0 to require a successful check every launch.
    license_grace_days: int = 14

    def save(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)


def load_config() -> Config:
    """Load config.json, creating it with defaults if missing.

    Unknown keys in the file are ignored; missing keys fall back to defaults,
    so the file survives version upgrades.
    """
    cfg = Config()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)

            # Pick up newly-added default categories on upgrade (so an old
            # config.json still gets e.g. Verisium/Idols) without losing any
            # custom ones the user added.
            added = [c for c in DEFAULT_CATEGORIES if c not in cfg.categories]
            if added:
                cfg.categories = list(cfg.categories) + added
                print(f"[config] added new categories: {', '.join(added)}")

            # Self-heal: if the file predates the current version it may be
            # missing whole fields (e.g. the licensing keys). Rewrite it in full
            # so every current option shows up in config.json.
            missing = set(asdict(cfg).keys()) - set(data.keys())
            if added or missing:
                try:
                    cfg.save()
                    if missing:
                        print(f"[config] added new fields: {', '.join(sorted(missing))}")
                except Exception:
                    pass
        except Exception as exc:  # corrupt file -> keep defaults, don't crash
            print(f"[config] failed to read {CONFIG_PATH}: {exc!r}; using defaults")
    else:
        try:
            cfg.save()
            print(f"[config] wrote default config to {CONFIG_PATH}")
        except Exception as exc:
            print(f"[config] could not write {CONFIG_PATH}: {exc!r}")
    return cfg
