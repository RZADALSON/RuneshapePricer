"""PoE2 Runeshape price overlay.

Reads the Runeshape Combinations panel from the screen (OCR), prices each
output line using poe.ninja PoE2 economy data, and draws the value in Exalted
Orbs next to each row as a transparent, click-through overlay. Triggered by a
hotkey (default F3); the overlay auto-hides after a few seconds.
"""

__version__ = "1.0.0"
