"""Settings window (opened from the tray). Runs on the Tk main thread.

Lets the user change the hotkeys, toggle the developer calibration hotkey, pick
the price currency (Exalted or Divine Orbs), set how long prices stay on screen
(or keep them up until the Runeshape panel closes), and choose whether to scan
the whole screen or just the Runeshape panel (left side). On save it updates the
Config in place and calls ``on_save`` so the app can persist and re-apply (e.g.
re-register hotkeys).
"""

from __future__ import annotations

import tkinter as tk

from .i18n import LANGUAGES, t

_BG = "#1b1b22"
_FG = "#e6e6ea"
_SUB = "#a8a8b3"
_FIELD = "#2a2a33"

# A small, sensible set of hotkey choices (the app accepts any keyboard name).
_KEYS = [f"f{i}" for i in range(1, 13)] + ["insert", "home", "end", "delete",
                                          "page up", "page down", "`"]

# Display label -> config value. "scan" (mode 2) is hidden until it's accurate.
_MODES = [("Runeshape (panel kombinacji)", "runeshape")]

_open = {"win": None}  # ensure only one settings window at a time


def open_settings(root: tk.Misc, cfg, on_save) -> None:
    if _open["win"] is not None and tk.Toplevel.winfo_exists(_open["win"]):
        _open["win"].lift()
        _open["win"].focus_force()
        return

    lang = getattr(cfg, "language", "en")
    win = tk.Toplevel(root)
    _open["win"] = win
    win.title(t(lang, "set_title"))
    win.configure(bg=_BG)
    win.attributes("-topmost", True)
    win.resizable(False, False)

    frm = tk.Frame(win, bg=_BG, padx=22, pady=18)
    frm.pack(fill="both", expand=True)

    def header(text):
        tk.Label(frm, text=text, bg=_BG, fg=_FG,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")

    def label(text, pady=(10, 2)):
        tk.Label(frm, text=text, bg=_BG, fg=_SUB,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=pady)

    def combo(var, choices=_KEYS):
        om = tk.OptionMenu(frm, var, *choices)
        om.configure(bg=_FIELD, fg=_FG, activebackground=_FIELD,
                     activeforeground=_FG, highlightthickness=0, relief="flat",
                     width=18, anchor="w", font=("Consolas", 10))
        om["menu"].configure(bg=_FIELD, fg=_FG)
        om.pack(anchor="w")
        return om

    header(t(lang, "set_header"))

    # --- language ---
    lang_disp = next((d for d, v in LANGUAGES if v == lang), LANGUAGES[0][0])
    lang_var = tk.StringVar(value=lang_disp)
    label(t(lang, "set_language"))
    combo(lang_var, [d for d, _ in LANGUAGES])

    # --- currency (exalt / divine) ---
    currencies = [(t(lang, "currency_exalt"), "exalt"),
                  (t(lang, "currency_divine"), "divine")]
    cur_cur = getattr(cfg, "currency_display", "exalt")
    cur_disp = next((d for d, v in currencies if v == cur_cur), currencies[0][0])
    currency_var = tk.StringVar(value=cur_disp)
    label(t(lang, "set_currency"))
    combo(currency_var, [d for d, _ in currencies])

    # --- mode (only shown when more than one mode is available) ---
    cur_mode = getattr(cfg, "mode", "runeshape")
    mode_disp = next((d for d, v in _MODES if v == cur_mode), _MODES[0][0])
    mode_var = tk.StringVar(value=mode_disp)
    if len(_MODES) > 1:
        label(t(lang, "set_mode"))
        combo(mode_var, [d for d, _ in _MODES])

    # --- main hotkey ---
    label(t(lang, "set_hk_prices"))
    hotkey_var = tk.StringVar(value=str(cfg.hotkey))
    combo(hotkey_var)

    # --- calibration (developer) hotkey ---
    calib_var = tk.BooleanVar(value=bool(getattr(cfg, "calibrate_enabled", False)))
    calib_key_var = tk.StringVar(value=str(getattr(cfg, "calibrate_hotkey", "f4")))
    tk.Checkbutton(
        frm, text=t(lang, "set_calib"), variable=calib_var,
        bg=_BG, fg=_FG, selectcolor=_FIELD, activebackground=_BG,
        activeforeground=_FG, font=("Segoe UI", 10), anchor="w",
    ).pack(anchor="w", pady=(14, 2))
    label(t(lang, "set_hk_calib"), pady=(0, 2))
    combo(calib_key_var)

    # --- display seconds ---
    label(t(lang, "set_display"))
    secs_var = tk.StringVar(value=str(cfg.display_seconds))
    tk.Spinbox(frm, from_=1, to=30, increment=1, textvariable=secs_var, width=6,
               bg=_FIELD, fg=_FG, buttonbackground=_FIELD, relief="flat",
               insertbackground=_FG, font=("Consolas", 11),
               justify="center").pack(anchor="w")

    # --- persist until panel closes (overrides the display time above) ---
    persist_var = tk.BooleanVar(
        value=bool(getattr(cfg, "persist_until_closed", False)))
    tk.Checkbutton(
        frm, text=t(lang, "set_persist"), variable=persist_var,
        bg=_BG, fg=_FG, selectcolor=_FIELD, activebackground=_BG,
        activeforeground=_FG, font=("Segoe UI", 10), anchor="w",
    ).pack(anchor="w", pady=(8, 2))

    # --- scan area ---
    label(t(lang, "set_scan_area"))
    area_var = tk.StringVar(value="full" if getattr(cfg, "scan_full_screen", False)
                            else "panel")
    for text, val in ((t(lang, "area_panel"), "panel"),
                      (t(lang, "area_full"), "full")):
        tk.Radiobutton(frm, text=text, variable=area_var, value=val, bg=_BG,
                       fg=_FG, selectcolor=_FIELD, activebackground=_BG,
                       activeforeground=_FG, font=("Segoe UI", 10),
                       anchor="w").pack(anchor="w")

    # --- buttons ---
    def do_save():
        cfg.language = dict((d, v) for d, v in LANGUAGES).get(lang_var.get(),
                                                              cfg.language)
        cfg.mode = dict((d, v) for d, v in _MODES).get(mode_var.get(), cfg.mode)
        cfg.hotkey = (hotkey_var.get().strip().lower() or cfg.hotkey)
        cfg.calibrate_enabled = bool(calib_var.get())
        cfg.calibrate_hotkey = (calib_key_var.get().strip().lower()
                                or cfg.calibrate_hotkey)
        cfg.currency_display = dict(currencies).get(currency_var.get(),
                                                    cfg.currency_display)
        try:
            cfg.display_seconds = max(1.0, float(secs_var.get().replace(",", ".")))
        except ValueError:
            pass
        cfg.persist_until_closed = bool(persist_var.get())
        cfg.scan_full_screen = (area_var.get() == "full")
        _close()
        try:
            on_save()
        except Exception as exc:
            print(f"[settings] on_save failed: {exc!r}")

    def _close():
        _open["win"] = None
        win.destroy()

    btns = tk.Frame(frm, bg=_BG)
    btns.pack(fill="x", pady=(18, 0))
    tk.Button(btns, text=t(lang, "save"), command=do_save, width=12, relief="flat",
              bg="#51cf66", fg="#10220f", activebackground="#69db7c",
              font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="right")
    tk.Button(btns, text=t(lang, "cancel"), command=_close, width=10, relief="flat",
              bg="#3a3a44", fg=_FG, activebackground="#4a4a55",
              font=("Segoe UI", 10), cursor="hand2").pack(side="right", padx=(0, 8))

    win.protocol("WM_DELETE_WINDOW", _close)
    win.bind("<Escape>", lambda *_: _close())

    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
    win.lift()
    win.focus_force()
