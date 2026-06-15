"""poe.ninja PoE2 economy client and the in-memory price book.

Endpoint (reverse-engineered from poe.ninja's PoE2 site, validated live):

    GET https://poe.ninja/poe2/api/economy/exchange/current/overview
        ?league=<League Display Name>&type=<Category>

Response shape (relevant parts)::

    {
      "core":  {"items": [{"id": "divine", ...}, ...],   # items[0] = primary
                "rates": {"exalted": 140.4, "chaos": 12.58},
                "secondary": "exalted"},
      "items": [{"id": "alch", "name": "Orb of Alchemy", ...}, ...],  # id -> name
      "lines": [{"id": "alch", "primaryValue": 0.0071, ...}, ...]     # id -> price
    }

``primaryValue`` is the price expressed in the *primary* currency (Divine Orb
here).  To convert to Exalted Orbs we multiply by ``rates["exalted"]`` (exalts
per divine).  This was checked against known values: exalted -> 1.0, divine ->
140.4, chaos -> 11.16.
"""

from __future__ import annotations

import difflib
import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .parsing import normalize

# Minimum similarity (0..1) for the fuzzy fallback to accept an OCR'd name.
_FUZZY_CUTOFF = 0.86

NINJA_URL = "https://poe.ninja/poe2/api/economy/exchange/current/overview"
NINJA_LEAGUES_URL = "https://poe.ninja/poe2/api/data/build-index-state"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "RuneshapePricer/1.0 (+local desktop overlay)"
)

# Permanent (non-challenge) leagues we skip when auto-detecting.
_PERMANENT = {"standard", "hardcore"}


def _http_json(url: str, timeout: float = 25.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def detect_current_league() -> str | None:
    """Return the current PoE2 challenge league name from poe.ninja.

    poe.ninja's build index lists every league with a player ``total``; the
    live challenge league has by far the most builds, so we pick the highest
    total that isn't a permanent league.
    """
    try:
        data = _http_json(NINJA_LEAGUES_URL)
    except Exception as exc:
        print(f"[prices] league auto-detect failed: {exc!r}")
        return None
    best_name, best_total = None, -1
    for entry in data.get("leagueBuilds") or []:
        name = entry.get("leagueName")
        url = (entry.get("leagueUrl") or "").lower()
        total = entry.get("total") or 0
        if not name or url in _PERMANENT:
            continue
        if total > best_total:
            best_name, best_total = name, total
    return best_name


@dataclass
class PriceEntry:
    name: str          # display name, e.g. "Lady Hestra's Rune of Winter"
    exalt: float       # value of one unit in Exalted Orbs
    category: str      # poe.ninja category it came from


def fetch_category(league: str, category: str, timeout: float = 25.0) -> list[PriceEntry]:
    """Fetch one poe.ninja category and return priced entries (in exalts)."""
    query = urllib.parse.urlencode({"league": league, "type": category})
    data = _http_json(f"{NINJA_URL}?{query}", timeout=timeout)

    core = data.get("core") or {}
    core_items = core.get("items") or []
    rates = core.get("rates") or {}
    primary_id = core_items[0]["id"] if core_items else "divine"

    # Exalts per one unit of the primary currency.
    if primary_id == "exalted":
        ex_per_primary = 1.0
    else:
        ex_per_primary = rates.get("exalted")
    if not ex_per_primary:
        # No exalted rate available for this overview -> can't express in exalts.
        return []

    names = {it["id"]: it.get("name", it["id"]) for it in (data.get("items") or [])}

    entries: list[PriceEntry] = []
    for line in data.get("lines") or []:
        pv = line.get("primaryValue")
        item_id = line.get("id")
        if pv is None or item_id is None:
            continue
        entries.append(
            PriceEntry(
                name=names.get(item_id, item_id),
                exalt=float(pv) * ex_per_primary,
                category=category,
            )
        )
    return entries


class PriceBook:
    """Thread-safe lookup table from normalized item name -> PriceEntry.

    The whole table is rebuilt on refresh and swapped atomically, so reads from
    the OCR/render thread never see a half-updated map.
    """

    def __init__(self) -> None:
        self._by_norm: dict[str, PriceEntry] = {}
        self._keys: list[str] = []
        self._lock = threading.Lock()
        self.last_update: float = 0.0
        self.last_error: str | None = None
        self.item_count: int = 0
        self.active_league: str = "?"

    def lookup(self, name: str) -> PriceEntry | None:
        """Exact normalized lookup, with a fuzzy fallback for OCR errors.

        The fuzzy step rescues small misreads like "Stone" -> "Słone" by
        accepting the closest item name above a high similarity cutoff.
        """
        key = normalize(name)
        if not key:
            return None
        entry = self._by_norm.get(key)
        if entry is not None:
            return entry
        if len(key) >= 5 and self._keys:
            match = difflib.get_close_matches(key, self._keys, n=1, cutoff=_FUZZY_CUTOFF)
            if match:
                return self._by_norm[match[0]]
        return None

    def _fetch_all(self, league: str, categories: list[str]):
        """Fetch every category for one league -> (map, errors)."""
        new_map: dict[str, PriceEntry] = {}
        errors: list[str] = []
        for category in categories:
            try:
                for entry in fetch_category(league, category):
                    key = normalize(entry.name)
                    if not key:
                        continue
                    # First category wins on duplicate names (Currency is first,
                    # which keeps canonical orb names stable).
                    new_map.setdefault(key, entry)
            except Exception as exc:
                errors.append(f"{category}: {exc!r}")
            time.sleep(0.4)  # be gentle with poe.ninja's rate limit
        return new_map, errors

    def refresh(self, league: str, categories: list[str]) -> bool:
        """Re-fetch all categories. Returns True if at least one succeeded.

        Resolves ``league == "auto"`` to the current challenge league, and if an
        explicit league comes back empty (e.g. it rotated out) falls back to
        auto-detection so the app keeps working without a config edit.
        """
        resolved = league
        if (league or "").strip().lower() == "auto":
            resolved = detect_current_league() or "Standard"
            print(f"[prices] auto-detected league: {resolved}")

        new_map, errors = self._fetch_all(resolved, categories)

        if not new_map and (league or "").strip().lower() != "auto":
            detected = detect_current_league()
            if detected and detected != resolved:
                print(f"[prices] '{resolved}' returned nothing; "
                      f"falling back to current league '{detected}'")
                resolved = detected
                new_map, errors = self._fetch_all(resolved, categories)

        if not new_map:
            self.last_error = "; ".join(errors) or "no data"
            print(f"[prices] refresh failed (league={resolved!r}): {self.last_error}")
            return False

        with self._lock:
            self._by_norm = new_map
            self._keys = list(new_map.keys())
            self.item_count = len(new_map)
            self.last_update = time.time()
            self.last_error = "; ".join(errors) if errors else None
            self.active_league = resolved
        print(
            f"[prices] refreshed {self.item_count} items from "
            f"{len(categories)} categories (league={resolved})"
            + (f" (some errors: {self.last_error})" if errors else "")
        )
        return True
