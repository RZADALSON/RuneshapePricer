"""Icon-recognition index for the experimental 'scan' mode.

Builds a database of every poe.ninja item's icon (a small perceptual hash) plus
its exalt price, so the app can recognise items *by their picture* on screen
(stash/inventory) and show each one's value.

Icons come from https://web.poecdn.com + the item's image path. Hashes are
cached to disk so only new icons are downloaded on later launches.
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PIL import Image

from .config import app_dir
from .prices import NINJA_URL, USER_AGENT

CDN = "https://web.poecdn.com"
_CACHE_PATH = os.path.join(app_dir(), "icon_hashes.json")
_HASH_SIZE = 8  # dHash grid -> 64-bit hash


def dhash(image: Image.Image, size: int = _HASH_SIZE) -> int:
    small = image.convert("L").resize((size + 1, size))
    bits = 0
    px = small.load()
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def avg_color(image: Image.Image) -> tuple[int, int, int]:
    """Average RGB of the central region (RGBA composited on black)."""
    img = image.convert("RGBA")
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    w, h = img.size
    central = img.crop((w // 4, h // 4, w * 3 // 4, h * 3 // 4)).resize((4, 4))
    px = list(central.getdata())
    n = len(px) or 1
    return (sum(p[0] for p in px) // n,
            sum(p[1] for p in px) // n,
            sum(p[2] for p in px) // n)


def color_dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _get_bytes(url: str, timeout: float = 25.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url: str, timeout: float = 25.0):
    return json.loads(_get_bytes(url, timeout).decode("utf-8"))


@dataclass
class IconEntry:
    name: str
    hash: int
    exalt: float
    color: tuple = (0, 0, 0)


class IconIndex:
    def __init__(self) -> None:
        self.entries: list[IconEntry] = []
        self.ready: bool = False
        self.status: str = "nie zbudowany"
        self.progress: tuple = (0, 0)  # (done, total) for the loading bar

    def _load_cache(self) -> dict:
        if os.path.exists(_CACHE_PATH):
            try:
                with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def build(self, league: str, categories: list[str]) -> bool:
        """Download/refresh icon hashes + prices. Cached hashes are reused.

        Two phases so the loading bar has a real total: first gather every
        item's (name, image, price), then hash/download each one.
        """
        if (league or "").strip().lower() == "auto":
            from .prices import detect_current_league
            league = detect_current_league() or "Standard"
        cache = self._load_cache()
        new_cache = dict(cache)

        # Phase 1: gather the full item list from all category overviews.
        self.status = "pobieram listy itemów..."
        self.progress = (0, 0)
        pending = []  # (name, image_path, exalt)
        for category in categories:
            try:
                url = f"{NINJA_URL}?" + urllib.parse.urlencode(
                    {"league": league, "type": category}
                )
                data = _get_json(url)
            except Exception as exc:
                print(f"[icons] {category}: {exc!r}")
                continue
            core = data.get("core") or {}
            rates = core.get("rates") or {}
            core_items = core.get("items") or []
            primary = core_items[0]["id"] if core_items else "divine"
            ex_per = 1.0 if primary == "exalted" else rates.get("exalted")
            if not ex_per:
                continue
            prices = {ln["id"]: ln.get("primaryValue")
                      for ln in (data.get("lines") or [])}
            for it in (data.get("items") or []):
                iid, img, name = it.get("id"), it.get("image"), it.get("name")
                pv = prices.get(iid)
                if img and name and pv is not None:
                    pending.append((name, img, float(pv) * ex_per))
            time.sleep(0.25)

        total = len(pending)
        self.progress = (0, total)

        # Phase 2: hash each icon (download only the ones not cached).
        entries: list[IconEntry] = []
        downloaded = 0
        for i, (name, img, ex) in enumerate(pending):
            cached = cache.get(img)
            if isinstance(cached, dict) and "h" in cached:
                h, col = cached["h"], tuple(cached.get("c", (0, 0, 0)))
            else:
                try:
                    im = Image.open(io.BytesIO(_get_bytes(CDN + img)))
                    h, col = dhash(im), avg_color(im)
                    new_cache[img] = {"h": int(h), "c": list(col)}
                    downloaded += 1
                    time.sleep(0.02)
                except Exception:
                    self.progress = (i + 1, total)
                    continue
            entries.append(IconEntry(name, int(h), ex, col))
            self.progress = (i + 1, total)

        self.entries = entries
        self.ready = bool(entries)
        try:
            with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(new_cache, fh)
        except Exception:
            pass
        self.status = f"{len(entries)} ikon ({downloaded} pobrano)"
        print(f"[icons] index: {self.status}")
        return self.ready

    def match(self, crop: Image.Image, threshold: int, margin: int = 0,
              color_tol: float = 80.0) -> tuple[IconEntry | None, int]:
        """Confident icon match for a crop, else (None, best_dist).

        Accepts only when the best match is (a) within `threshold`, (b) clearly
        better than the runner-up by `margin` bits (rejects ambiguous matches on
        UI/text), and (c) a similar colour (rejects grey UI matching a colourful
        item). These three gates cut the false positives a raw nearest-neighbour
        search produces when scanning a whole screen.
        """
        h = dhash(crop)
        b1d, b1, b2d = 999, None, 999
        for e in self.entries:
            d = hamming(h, e.hash)
            if d < b1d:
                b2d, b1d, b1 = b1d, d, e
            elif d < b2d:
                b2d = d
        if (b1 is not None and b1d <= threshold and (b2d - b1d) >= margin
                and color_dist(avg_color(crop), b1.color) <= color_tol):
            return b1, b1d
        return None, b1d
