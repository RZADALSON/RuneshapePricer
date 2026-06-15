# Runeshape Pricer

Nakładka do **Path of Exile 2** pokazująca ceny kombinacji *Runeshape* w **Exaltach** prosto na ekranie. Otwórz panel **Runeshape Combinations**, naciśnij **F3** — obok każdego wiersza pojawi się jego wartość (po chwili znika).

Ceny pobierane na żywo z **poe.ninja**. Program **nie ingeruje w grę** — tylko czyta ekran (OCR) i rysuje na wierzchu (przezroczysta, „przeklikiwalna" nakładka).

**Darmowe i otwarte (open-source).** Bez klucza, bez logowania.

## Użycie
1. Pobierz **`RuneshapePricer.exe`** z zakładki [**Releases**](../../releases) i trzymaj w zwykłym folderze (**nie** w `Program Files`).
2. W grze ustaw **Windowed Fullscreen** (nad *exclusive* fullscreen nakładki się nie pokazują).
3. Otwórz panel **Runeshape Combinations** i naciśnij **F3**.

Ikona w zasobniku → **Settings** (język, skrót, czas wyświetlania, obszar) i **Quit**. Domyślny język: angielski (w Settings można zmienić na polski).

## Wymagania
- Windows 10/11.
- Pakiet **OCR Windows** (dowolny język, np. polski): *Ustawienia → Czas i język → Język → Opcje → Optyczne rozpoznawanie znaków*.

## Kolory cen
🟡 ≥ 800 ex · 🟢 ≥ 50 ex · ⚪ ≥ 5 ex · ▫️ taniej · 🟡 `?` = nagroda zmienna (np. unikat) · `—` = brak ceny na poe.ninja.

## Budowanie ze źródeł
```
pip install -r requirements.txt
python main.py                # uruchom ze źródeł
pyinstaller --noconfirm --clean --distpath . --workpath build RuneshapePricer.spec
```
Wymaga Pythona 3.10+. Narzędzia do strojenia: `python main.py selftest` (ceny), `python main.py ocr <obraz>` (podgląd OCR).

---
*Nieoficjalne narzędzie. Niepowiązane z Grinding Gear Games ani poe.ninja. Dane cen: poe.ninja.*
