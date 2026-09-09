"""Tesseract, through pytesseract.

Not shipped and not a dependency: it needs a system binary, which is exactly the
kind of install complydoc avoids imposing. It is here because OCR engines
genuinely disagree, and a second opinion on a scanned page is worth having when
somebody already has this one installed.

    brew install tesseract      # or the equivalent
    uv pip install pytesseract
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from complydoc.ingest.engines.base import Recognised
from complydoc.ingest.engines.registry import register

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

_MIN_CONFIDENCE = 0.0


@register
class TesseractEngine:
    id = "tesseract"
    name = "tesseract"

    def available(self) -> bool:
        return self.unavailable_reason() is None

    def unavailable_reason(self) -> str | None:
        try:
            import pytesseract
        except ImportError:
            return "pytesseract is not installed (uv pip install pytesseract)"
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            return "the tesseract binary is not on PATH (brew install tesseract)"
        return None

    def set_threads(self, count: int | None) -> None:
        """Tesseract takes its thread count from the environment, not from here."""

    def read(self, image: Image) -> Recognised:
        if not self.available():
            return Recognised("", None, 0)
        import pytesseract

        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception:  # pragma: no cover - a bad page should not kill the run
            return Recognised("", None, 0)

        words: list[str] = []
        scores: list[float] = []
        for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            if not str(text).strip():
                continue
            words.append(str(text))
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                continue
            if value >= _MIN_CONFIDENCE:
                # Tesseract reports 0-100 where the rest of complydoc uses 0-1.
                scores.append(value / 100.0)

        return Recognised(
            text=" ".join(words),
            confidence=round(sum(scores) / len(scores), 3) if scores else None,
            boxes=len(words),
        )
