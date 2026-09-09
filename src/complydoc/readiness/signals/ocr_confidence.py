"""How sure the OCR engine was about what it read."""

from __future__ import annotations

from complydoc.ingest.base import Document, DocumentFormat
from complydoc.readiness.base import Measurement
from complydoc.readiness.registry import signal


@signal
class OcrConfidenceSignal:
    id = "ocr_confidence"
    name = "OCR confidence"
    unit = "%"
    why = "Recognised text is a guess, and a low-confidence guess is wrong in the details."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        scored = [
            (page.number, page.ocr_confidence)
            for page in document.pages
            if page.ocr_confidence is not None
        ]
        if not scored:
            return Measurement.na(
                "OCR did not run on this document, so there is no recognition "
                "confidence to report. It runs where a page has no text layer"
            )
        lowest = min(confidence for _, confidence in scored)
        return Measurement(
            value=round(lowest * 100, 1),
            display=f"{lowest * 100:.0f}% at the worst page",
            detail={
                "per_page": {str(number): round(c * 100, 1) for number, c in scored},
                "pages_measured": len(scored),
                "mean_pct": round(sum(c for _, c in scored) / len(scored) * 100, 1),
            },
        )
