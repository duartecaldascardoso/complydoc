"""Consistency of date formats across the document."""

from __future__ import annotations

import re
from collections import Counter

from complydoc.ingest.base import Document
from complydoc.readiness.base import ALL_FORMATS, Measurement
from complydoc.readiness.registry import signal
from complydoc.text import count

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ISO yyyy-mm-dd", re.compile(r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b")),
    ("slash d/m/yyyy", re.compile(r"\b\d{1,2}/\d{1,2}/(?:19|20)?\d{2}\b")),
    ("dotted d.m.yyyy", re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:19|20)?\d{2}\b")),
    ("dashed d-m-yyyy", re.compile(r"\b\d{1,2}-\d{1,2}-(?:19|20)?\d{2}\b")),
    ("long 1 January 2026", re.compile(rf"\b\d{{1,2}}\s+{_MONTH}\s+(?:19|20)\d{{2}}\b")),
    ("long January 1, 2026", re.compile(rf"\b{_MONTH}\s+\d{{1,2}},?\s+(?:19|20)\d{{2}}\b")),
)

_MIN_DATES = 3


@signal
class DateFormatConsistencySignal:
    id = "date_format_consistency"
    name = "Date format consistency"
    unit = "%"
    why = "Mixed formats force a parser to guess, and the guess changes the date."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        text = document.full_text
        counts: Counter[str] = Counter()
        for name, pattern in _FAMILIES:
            found = len(pattern.findall(text))
            if found:
                counts[name] = found

        total = sum(counts.values())
        if total < _MIN_DATES:
            return Measurement.na(
                f"only {count(total, 'date')} were found, which is too few to say anything about "
                f"consistency"
            )

        dominant, dominant_count = counts.most_common(1)[0]
        consistency = dominant_count / total * 100
        return Measurement(
            value=round(consistency, 2),
            display=(f"{consistency:.0f}% consistent" if len(counts) > 1 else "consistent"),
            detail={
                "dates_found": total,
                "formats_seen": dict(counts),
                "dominant_format": dominant,
            },
        )
