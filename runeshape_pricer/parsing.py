"""Turn OCR'd Runeshape-combination rows into (quantity, item name).

Each output row in the in-game panel looks like one of:

    "3x Exalted Orb"
    "1x Lady Hestra's Rune of Winter"
    "1x Uncut Spirit Gem (Level 19)"
    "Unique Jewellery"            <- variable reward, price unknown

We extract the leading "Nx" quantity (if present) and the item name, and
normalize names so OCR text matches poe.ninja's display names regardless of
punctuation/spacing/case.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Leading quantity, e.g. "3x", "3 x", "3X", "10x". The quantity token tolerates
# the characters OCR substitutes for digits: "1" often reads as I/l/L/|/ł and
# "0" as o/O (so "10x" can come back as "łox", "IOx", "lOx"). The trailing
# x/X/× multiplier gates the match so real item names aren't mistaken for one.
_QTY_RE = re.compile(r"^\s*([0-9IilL|łoO]{1,3})\s*[xX×]\s*(.*\S)\s*$")

# Strip common OCR noise characters from the edges of a recognized name.
_EDGE_JUNK = " \t\r\n.,:;|_-—–"


@dataclass
class OutputLine:
    quantity: int
    name: str           # cleaned display name (no quantity prefix)
    is_unique: bool     # True for generic "Unique ..." variable rewards
    had_quantity: bool  # True if an explicit "Nx" prefix was present


def normalize(name: str) -> str:
    """Collapse a name to a punctuation/space/accent-insensitive key.

    "Lady Hestra's Rune of Winter" -> "ladyhestrasruneofwinter"
    "Uncut Spirit Gem (Level 20)"  -> "uncutspiritgemlevel20"

    The "(Level N)" qualifier is *kept* on purpose: poe.ninja prices each gem
    level separately, so the level must stay in the key to match the right one.
    Accented letters a non-English OCR pack may emit (ł, ó, ...) fold to ASCII.
    """
    s = name.lower()
    s = s.replace("&", " and ").replace("ł", "l")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _qty_value(token: str) -> int:
    """Convert an OCR quantity token to an int, mapping I/l/L/|/ł -> 1, o/O -> 0."""
    t = token
    for ch in "IilL|ł":
        t = t.replace(ch, "1")
    for ch in "oO":
        t = t.replace(ch, "0")
    return int(t) if t.isdigit() else 1


def parse_output_line(text: str) -> OutputLine | None:
    """Parse a single OCR line into an OutputLine, or None if it's not a row.

    Returns None for empty strings; the caller decides what to do based on
    whether the (normalized) name is found in the price book.
    """
    if not text:
        return None
    raw = text.strip(_EDGE_JUNK)
    if not raw:
        return None

    m = _QTY_RE.match(raw)
    if m:
        qty = _qty_value(m.group(1))
        name = m.group(2).strip(_EDGE_JUNK)
        had_quantity = True
    else:
        qty = 1
        name = raw
        had_quantity = False

    if not name:
        return None
    is_unique = name.lower().lstrip().startswith("unique")
    return OutputLine(
        quantity=qty, name=name, is_unique=is_unique, had_quantity=had_quantity
    )
