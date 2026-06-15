"""Show the calibration (F4) view with sample boxes for a visual check."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runeshape_pricer.capture import set_dpi_aware
from runeshape_pricer.config import load_config
from runeshape_pricer.overlay import DebugBox, Overlay

set_dpi_aware()
cfg = load_config()
ov = Overlay(cfg)
ov.request_render_debug([
    DebugBox(700, 300, 300, 44, "1.9 ex  «3x Orb of Alchemy»", "#FFFFFF"),
    DebugBox(700, 360, 300, 44, "?  «Unique Jewellery»", "#FFD43B"),
    DebugBox(700, 420, 320, 44, "—  «Runeshape Combinations»", "#FF8787"),
    DebugBox(700, 480, 300, 44, "120 ex  «1x Aldur's Saga»", "#51CF66"),
], 60.0)
ov.root.after(15000, ov.root.destroy)
ov.run()
