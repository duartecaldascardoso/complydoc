"""How much of the page area the text layer actually covers."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.geometry import coverage_fraction
from complydoc.ingest.base import Document, DocumentFormat


@signal
class TextCoverageSignal:
    id = "text_layer_coverage_pct"
    name = "Text layer coverage"
    unit = "%"
    why = "Almost no text on the page means the content is an image, not text."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        usable = [p for p in document.pages if p.area_pt > 0]
        if not usable:
            return Measurement.na(
                "page dimensions were not available, so coverage could not be computed"
            )
        per_page = [
            coverage_fraction([b.bbox for b in p.text_blocks], p.width_pt, p.height_pt) * 100
            for p in usable
        ]
        mean = sum(per_page) / len(per_page)
        return Measurement(
            value=round(mean, 2),
            display=f"{mean:.1f}% of page area",
            detail={
                "per_page_pct": [round(v, 2) for v in per_page],
                "lowest_page_pct": round(min(per_page), 2),
                "highest_page_pct": round(max(per_page), 2),
            },
        )
