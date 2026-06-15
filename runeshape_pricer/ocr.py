"""OCR via the built-in Windows OCR engine (Windows.Media.Ocr).

Why Windows OCR: it ships with Windows 10/11, needs no external binary
(unlike Tesseract), and returns per-word bounding boxes -- which we union into
per-line boxes so the overlay can place each price next to the right row.

We access it through the small ``winocr`` wrapper. Different winocr versions
return either a winsdk ``OcrResult`` object or a plain dict, so the reader
below handles both shapes.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageOps

# Upscale the captured region before OCR; small in-game text recognizes far
# better at ~2x. Box coordinates are divided back down afterwards.
_OCR_SCALE = 2.0


def _preprocess(image: Image.Image) -> Image.Image:
    """Boost OCR accuracy on the textured parchment panel.

    The in-game panel is dark text on a noisy light parchment. Converting to
    greyscale and stretching contrast makes the glyph edges cleaner, which cuts
    misreads (a single mangled letter can stop a row from matching a price).
    """
    grey = image.convert("L")
    grey = ImageOps.autocontrast(grey, cutoff=2)
    return ImageEnhance.Contrast(grey).enhance(1.6)


@dataclass
class OcrLine:
    text: str
    x: float            # box in ORIGINAL capture pixels
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class OcrUnavailable(RuntimeError):
    pass


def _import_winocr():
    try:
        import winocr  # noqa: F401
        return winocr
    except Exception as exc:  # pragma: no cover - environment dependent
        raise OcrUnavailable(
            "Windows OCR (winocr) is not available. Install it with "
            "`pip install winocr`."
        ) from exc


# Resolved once and cached: the OCR language tag we actually feed to the engine.
_resolved_lang: str | None = None


def _resolve_language(preferred: str) -> str:
    """Pick a recognizer language that's actually installed.

    Any Latin-script recognizer (English, Polish, German, ...) reads PoE2 item
    names fine, so we prefer the requested language but happily fall back to
    whatever pack the user already has -- typically their Windows display
    language. This avoids forcing an English OCR pack install.
    """
    global _resolved_lang
    if _resolved_lang is not None:
        return _resolved_lang

    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language

    available = [l.language_tag for l in OcrEngine.available_recognizer_languages]
    if not available:
        raise OcrUnavailable(
            "No Windows OCR language pack is installed. Add one via Settings > "
            "Time & language > Language & region > (your language) > Language "
            "options > Optional features > add 'Optical character recognition'. "
            "Any language works (English, Polish, ...)."
        )

    def is_supported(tag: str) -> bool:
        try:
            return OcrEngine.is_language_supported(Language(tag))
        except Exception:
            return False

    candidates = []
    if preferred and preferred.lower() not in ("", "auto"):
        candidates.append(preferred)
    candidates += ["en", "en-US", "en-GB"]

    chosen = next((t for t in candidates if is_supported(t)), None)
    if chosen is None:
        chosen = available[0]  # use whatever pack exists (e.g. Polish)
        print(f"[ocr] using installed OCR language '{chosen}' (English pack not found)")

    _resolved_lang = chosen
    return chosen


def _rect_of(word) -> tuple[float, float, float, float] | None:
    """Pull (x, y, w, h) out of a word, whether dict-shaped or object-shaped."""
    rect = word.get("bounding_rect") if isinstance(word, dict) else getattr(
        word, "bounding_rect", None
    )
    if rect is None:
        return None
    if isinstance(rect, dict):
        return rect["x"], rect["y"], rect["width"], rect["height"]
    return rect.x, rect.y, rect.width, rect.height


def _iter_lines(result):
    """Yield (text, [words]) from a winocr result of either shape."""
    lines = result.get("lines") if isinstance(result, dict) else getattr(
        result, "lines", None
    )
    for line in lines or []:
        if isinstance(line, dict):
            yield line.get("text", ""), line.get("words") or []
        else:
            yield getattr(line, "text", ""), list(getattr(line, "words", []) or [])


def warm_up(language: str = "auto") -> None:
    """Pre-load the OCR engine on a tiny image so the first real F3 is fast.

    The cold path (import winocr, resolve the language, create the engine)
    costs a few hundred ms; doing it once in the background at startup means
    the user never waits for it when checking prices.
    """
    try:
        read_lines(Image.new("RGB", (48, 24), (250, 250, 250)), language)
    except Exception:
        pass


def read_lines(image: Image.Image, language: str = "en",
               scale: float | None = None) -> list[OcrLine]:
    """OCR a PIL image and return one OcrLine per recognized text line.

    ``scale`` upscales before OCR: higher = more accurate but slower (OCR time
    grows roughly with pixel count). 2.0 is most accurate; 1.0 is ~3x faster.
    """
    winocr = _import_winocr()
    language = _resolve_language(language)

    prepped = _preprocess(image)
    scale = _OCR_SCALE if scale is None else max(1.0, float(scale))
    if scale != 1.0:
        big = prepped.resize(
            (int(prepped.width * scale), int(prepped.height * scale)),
            Image.LANCZOS,
        )
    else:
        big = prepped

    try:
        # Use the RAW winrt result (recognize_pil) instead of recognize_pil_sync,
        # which `picklify`s the whole tree (slow). We read boxes directly below.
        import asyncio

        async def _await(aw):
            return await aw

        result = asyncio.run(_await(winocr.recognize_pil(big, language)))
    except Exception:
        try:
            result = winocr.recognize_pil_sync(big, language)  # fallback
        except Exception as exc:
            raise OcrUnavailable(f"Windows OCR failed: {exc!r}") from exc

    out: list[OcrLine] = []
    for text, words in _iter_lines(result):
        rects = [r for r in (_rect_of(w) for w in words) if r is not None]
        if not rects:
            continue
        xs = [r[0] for r in rects]
        ys = [r[1] for r in rects]
        xe = [r[0] + r[2] for r in rects]
        ye = [r[1] + r[3] for r in rects]
        x0, y0, x1, y1 = min(xs), min(ys), max(xe), max(ye)
        out.append(
            OcrLine(
                text=(text or "").strip(),
                x=x0 / scale,
                y=y0 / scale,
                w=(x1 - x0) / scale,
                h=(y1 - y0) / scale,
            )
        )
    return out
