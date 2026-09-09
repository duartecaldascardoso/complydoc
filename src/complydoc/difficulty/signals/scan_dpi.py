"""Effective scan resolution on pages that are really images."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.geometry import coverage_fraction
from complydoc.ingest.base import Document, DocumentFormat

_IMAGE_DOMINANT = 0.5


@signal
class ScanDpiSignal:
    id = "scan_dpi"
    name = "Scan resolution"
    unit = "DPI"
    why = "Below about 200 DPI, OCR starts confusing digits in amounts and accounts."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        measured: list[tuple[int, float]] = []
        for page in document.pages:
            if page.area_pt <= 0:
                continue
            image_share = coverage_fraction(
                [b.bbox for b in page.image_blocks], page.width_pt, page.height_pt
            )
            if image_share < _IMAGE_DOMINANT:
                continue
            dpi = page.estimated_dpi()
            if dpi:
                measured.append((page.number, dpi))

        if not measured:
            return Measurement.na(
                "no page is mostly a scanned image, so there is no scan resolution to "
                "measure. Resolution is only meaningful where the page really is a picture"
            )

        lowest = min(dpi for _, dpi in measured)
        return Measurement(
            value=round(lowest, 1),
            display=f"{lowest:.0f} DPI at the lowest page",
            detail={
                "pages_measured": [n for n, _ in measured],
                "per_page_dpi": {str(n): round(d, 1) for n, d in measured},
                "note": "derived from embedded image pixel size against placed page size",
            },
        )
