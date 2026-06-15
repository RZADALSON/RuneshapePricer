"""Entry point for the Runeshape price overlay.

Usage:
    python main.py                 run the overlay (normal use)
    python main.py selftest        fetch prices once and print a sample
    python main.py ocr <image>     OCR an image file and print detected prices
                                   (handy for tuning the capture region)
"""

from __future__ import annotations

import os
import sys


def _init_console() -> None:
    # When packaged with --noconsole there is no stdout, so route logging to a
    # file next to the .exe (makes troubleshooting the build possible). When
    # running from source, just make stdout UTF-8 so non-cp1252 characters
    # (e.g. Polish letters from a non-English OCR pack) don't crash prints.
    if getattr(sys, "frozen", False):
        try:
            log_path = os.path.join(
                os.path.dirname(sys.executable), "runeshape_pricer.log"
            )
            fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            sys.stdout = fh
            sys.stderr = fh
        except Exception:
            pass
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _selftest() -> None:
    from runeshape_pricer.config import load_config
    from runeshape_pricer.prices import PriceBook

    cfg = load_config()
    book = PriceBook()
    print(f"Fetching prices for league '{cfg.league}'...")
    book.refresh(cfg.league, cfg.categories)
    print(f"Loaded {book.item_count} items.")
    for name in ("Exalted Orb", "Divine Orb", "Chaos Orb", "Regal Orb"):
        entry = book.lookup(name)
        print(f"  {name:14}: {entry.exalt:.3f} ex" if entry else f"  {name}: not found")


def _ocr_file(path: str) -> None:
    from PIL import Image

    from runeshape_pricer.config import load_config
    from runeshape_pricer.ocr import read_lines
    from runeshape_pricer.parsing import parse_output_line
    from runeshape_pricer.prices import PriceBook

    cfg = load_config()
    book = PriceBook()
    book.refresh(cfg.league, cfg.categories)

    img = Image.open(path).convert("RGB")
    print(f"OCR of {path} ({img.width}x{img.height}):")
    for ln in read_lines(img, cfg.ocr_language):
        parsed = parse_output_line(ln.text)
        tag = ""
        if parsed:
            entry = book.lookup(parsed.name)
            if entry:
                tag = f"  => {entry.exalt * parsed.quantity:.2f} ex"
            elif parsed.is_unique:
                tag = "  => ? (unique)"
            elif parsed.had_quantity:
                tag = "  => — (recognised, not on poe.ninja)"
        print(f"  [{ln.x:4.0f},{ln.y:4.0f}] {ln.text!r}{tag}")


def main() -> None:
    _init_console()
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
        return
    if len(sys.argv) > 2 and sys.argv[1] == "ocr":
        _ocr_file(sys.argv[2])
        return

    from runeshape_pricer.app import main as run_app
    run_app()


if __name__ == "__main__":
    main()
