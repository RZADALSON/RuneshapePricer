"""Show the overlay with sample prices for a while (visual sanity check)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runeshape_pricer.capture import set_dpi_aware
from runeshape_pricer.config import load_config
from runeshape_pricer.overlay import Label, Overlay

set_dpi_aware()
cfg = load_config()
cfg.display_seconds = 60  # keep prices up long enough to screenshot
ov = Overlay(cfg)
ov.request_render([
    Label(x=700, y=300, text="1056 ex", color="#FFD700"),   # gold (>800)
    Label(x=700, y=370, text="120 ex", color="#51CF66"),    # green
    Label(x=700, y=440, text="3.0 ex", color="#FFFFFF"),    # white
    Label(x=700, y=510, text="?", color="#FFD43B"),         # unknown
])
ov.root.after(15000, ov.root.destroy)  # auto-close so it never lingers
ov.run()
