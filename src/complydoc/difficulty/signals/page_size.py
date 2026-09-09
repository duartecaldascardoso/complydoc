"""Page size variance within a single document."""

from __future__ import annotations

from collections import Counter

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat


@signal
class PageSizeVarianceSignal:
    id = "page_size_variance"
    name = "Distinct page sizes"
    unit = "sizes"
    why = "Mixed page sizes break any rule that finds a value by its position."
    applies_to = frozenset({DocumentFormat.PDF})

    def measure(self, document: Document) -> Measurement:
        sizes = [p.size_key for p in document.pages if p.area_pt > 0]
        if not sizes:
            return Measurement.na("no page dimensions were available")
        counts = Counter(sizes)
        return Measurement(
            value=len(counts),
            display=("all pages the same size" if len(counts) == 1 else f"{len(counts)} sizes"),
            detail={
                "sizes_pt": {f"{w} x {h}": n for (w, h), n in counts.most_common()},
                "pages_measured": len(sizes),
            },
        )
