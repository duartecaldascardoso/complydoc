"""How much of the page is image rather than text."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.geometry import coverage_fraction
from complydoc.ingest.base import Document, DocumentFormat


@signal
class ImageAreaSignal:
    id = "image_area_ratio_pct"
    name = "Page area that is image"
    unit = "%"
    why = "Images of text cannot be read directly; they need OCR or a vision model."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        usable = [p for p in document.pages if p.area_pt > 0]
        if not usable:
            return Measurement.na(
                "page dimensions were not available, so image coverage could not be computed"
            )
        per_page = [
            coverage_fraction([b.bbox for b in p.image_blocks], p.width_pt, p.height_pt) * 100
            for p in usable
        ]
        mean = sum(per_page) / len(per_page)
        heavy = sum(1 for v in per_page if v > 50)
        return Measurement(
            value=round(mean, 2),
            display=f"{mean:.0f}% of page",
            detail={
                "per_page_pct": [round(v, 2) for v in per_page],
                "pages_over_half_image": heavy,
            },
        )
