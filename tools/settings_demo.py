"""Open the settings window standalone for a visual check."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from runeshape_pricer.config import load_config
from runeshape_pricer.settings_ui import open_settings

root = tk.Tk()
root.withdraw()
cfg = load_config()


def on_save():
    print("SAVED:", cfg.hotkey, "calib=", cfg.calibrate_enabled,
          cfg.calibrate_hotkey, "secs=", cfg.display_seconds,
          "full=", cfg.scan_full_screen)


open_settings(root, cfg, on_save)
root.after(15000, root.destroy)
root.mainloop()
