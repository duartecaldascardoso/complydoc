"""Multi-column layout detection."""

from __future__ import annotations

import numpy as np

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat, Page

_BINS = 200
_MIN_GUTTER_FRACTION = 0.035
"""A vertical gap must be at least this fraction of the page width to be a gutter."""
_MIN_WORDS = 25


def _column_count(page: Page) -> int | None:
    """Count columns by looking for full-height vertical gaps between words.

    Projecting every word box onto the horizontal axis means a gap in the
    projection is a band no word anywhere on the page crosses, which is what a
    real gutter is. A gap inside a table does not qualify, because table cells on
    other rows cross it.
    """
    if page.width_pt <= 0 or len(page.text_blocks) < _MIN_WORDS:
        return None

    occupied = np.zeros(_BINS, dtype=bool)
    for block in page.text_blocks:
        start = int(np.clip(block.bbox.x0 / page.width_pt * _BINS, 0, _BINS - 1))
        end = int(np.clip(np.ceil(block.bbox.x1 / page.width_pt * _BINS), 1, _BINS))
        occupied[start:end] = True

    if not occupied.any():
        return None

    first, last = int(np.argmax(occupied)), _BINS - int(np.argmax(occupied[::-1]))
    interior = occupied[first:last]
    min_gap = max(1, int(_MIN_GUTTER_FRACTION * _BINS))

    gutters, run = 0, 0
    for filled in interior:
        if filled:
            if run >= min_gap:
                gutters += 1
            run = 0
        else:
            run += 1
    return gutters + 1


@signal
class ColumnCountSignal:
    id = "column_count"
    name = "Column layout"
    unit = "columns"
    why = (
        "Text extraction reads a page in the order the characters were written, not the "
        "order a person reads them, so a two-column page often comes out with the two "
        "columns interleaved line by line into nonsense."
    )
    applies_to = frozenset({DocumentFormat.PDF})

    def measure(self, document: Document) -> Measurement:
        counts = [c for c in (_column_count(p) for p in document.pages) if c is not None]
        if not counts:
            return Measurement.na(
                "no page carried enough positioned words for a column layout to be inferred"
            )
        worst = max(counts)
        return Measurement(
            value=worst,
            display=f"{worst} column(s) at the widest",
            detail={
                "per_page": counts,
                "pages_measured": len(counts),
                "multi_column_pages": sum(1 for c in counts if c > 1),
            },
        )
