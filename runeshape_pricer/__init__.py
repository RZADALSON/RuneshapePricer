"""PoE2 Runeshape price overlay.

Reads the Runeshape Combinations panel from the screen (OCR), prices each
output line using poe.ninja PoE2 economy data, and draws the value (in Exalted
or Divine Orbs) next to each row as a transparent, click-through overlay.
Triggered by a hotkey (default F3); the overlay auto-hides after a few seconds,
or stays up until the panel closes (optional).
"""

__version__ = "1.0.5"
