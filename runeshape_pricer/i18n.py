"""Tiny UI translation table. Default language is English.

Use ``t(lang, key)`` to look up a string; unknown keys / languages fall back
to English, then to the key itself.
"""

from __future__ import annotations

_TR = {
    "en": {
        # licensing / activation window
        "lic_title": "Runeshape Pricer — Activation",
        "lic_header": "License activation",
        "lic_prompt": "Enter your license key to run the program:",
        "activate": "Activate",
        "cancel": "Cancel",
        "lic_err_title": "Runeshape Pricer — license",
        "lic_enter_valid": "Enter a valid key.",
        "lic_empty": "The key cannot be empty.",
        "lic_offline_stored": ("No internet connection and the saved license "
                               "could not be verified. Check your connection."),
        "lic_offline_retry": ("No connection to the license server. Check your "
                              "internet and try again."),
        "lic_activate_fail": "Could not activate this computer.",
        "lic_not_allowed": ("License config error: enable license-key "
                            "authentication in the Keygen policy."),
        # Keygen validation codes
        "code_EXPIRED": "License has expired.",
        "code_SUSPENDED": "License is suspended.",
        "code_BANNED": "Account is banned.",
        "code_OVERDUE": "License needs to be re-verified.",
        "code_NO_MACHINE": "This computer is not activated.",
        "code_NO_MACHINES": "No activated computers.",
        "code_FINGERPRINT_SCOPE_MISMATCH": "Key is bound to a different computer.",
        "code_TOO_MANY_MACHINES": "Computer limit exceeded for this key.",
        "code_MACHINE_LIMIT_EXCEEDED": "Key is already used on another computer.",
        "code_NOT_FOUND": "No such key was found.",
        "code_INVALID": "License invalid ({code}).",
        # settings window
        "set_title": "Runeshape Pricer — Settings",
        "set_header": "Settings",
        "set_mode": "Mode:",
        "mode_runeshape": "Runeshape (combinations panel)",
        "set_hk_prices": "Hotkey — show prices:",
        "set_calib": "Calibration mode (developer)",
        "set_hk_calib": "Hotkey — calibration:",
        "set_display": "Price display time (seconds):",
        "set_scan_area": "Scan area:",
        "area_panel": "Only the Runeshape panel (left side)",
        "area_full": "Whole screen",
        "set_language": "Language:",
        "save": "Save",
        # status overlay
        "building_index": "Building icon index (first run, ~a minute)...",
        "startup_running": ("Runeshape Pricer is running in the background  ·  "
                            "F3 = prices  ·  Shift+F3 = settings"),
    },
    "pl": {
        "lic_title": "Runeshape Pricer — Aktywacja",
        "lic_header": "Aktywacja licencji",
        "lic_prompt": "Wprowadź klucz licencyjny, aby uruchomić program:",
        "activate": "Aktywuj",
        "cancel": "Anuluj",
        "lic_err_title": "Runeshape Pricer — licencja",
        "lic_enter_valid": "Wprowadź poprawny klucz.",
        "lic_empty": "Klucz nie może być pusty.",
        "lic_offline_stored": ("Brak połączenia z internetem, a zapisana licencja "
                               "nie mogła zostać sprawdzona. Sprawdź połączenie."),
        "lic_offline_retry": ("Brak połączenia z serwerem licencji. Sprawdź "
                              "internet i spróbuj ponownie."),
        "lic_activate_fail": "Nie udało się aktywować tego komputera.",
        "lic_not_allowed": ("Błąd konfiguracji licencji: włącz uwierzytelnianie "
                            "kluczem w Keygen Policy."),
        "code_EXPIRED": "Licencja wygasła.",
        "code_SUSPENDED": "Licencja zawieszona.",
        "code_BANNED": "Konto zablokowane.",
        "code_OVERDUE": "Licencja wymaga ponownej weryfikacji.",
        "code_NO_MACHINE": "Ten komputer nie jest aktywowany.",
        "code_NO_MACHINES": "Brak aktywowanych komputerów.",
        "code_FINGERPRINT_SCOPE_MISMATCH": "Klucz przypisany do innego komputera.",
        "code_TOO_MANY_MACHINES": "Przekroczono limit komputerów dla tego klucza.",
        "code_MACHINE_LIMIT_EXCEEDED": "Klucz jest już użyty na innym komputerze.",
        "code_NOT_FOUND": "Nie znaleziono takiego klucza.",
        "code_INVALID": "Licencja nieważna ({code}).",
        "set_title": "Runeshape Pricer — Ustawienia",
        "set_header": "Ustawienia",
        "set_mode": "Tryb:",
        "mode_runeshape": "Runeshape (panel kombinacji)",
        "set_hk_prices": "Skrót — pokaż ceny:",
        "set_calib": "Tryb kalibracji (deweloperski)",
        "set_hk_calib": "Skrót — kalibracja:",
        "set_display": "Czas wyświetlania cen (sekundy):",
        "set_scan_area": "Skanuj obszar:",
        "area_panel": "Tylko panel Runeshape (lewa strona)",
        "area_full": "Cały ekran",
        "set_language": "Język:",
        "save": "Zapisz",
        "building_index": "Buduję indeks ikon (pierwszy raz trwa ~minutę)...",
        "startup_running": ("Runeshape Pricer działa w tle  ·  "
                            "F3 = ceny  ·  Shift+F3 = ustawienia"),
    },
}

# Language picker options (display label, code).
LANGUAGES = [("English", "en"), ("Polski", "pl")]


def t(lang: str, key: str, **fmt) -> str:
    table = _TR.get(lang) or _TR["en"]
    s = table.get(key) or _TR["en"].get(key) or key
    return s.format(**fmt) if fmt else s
