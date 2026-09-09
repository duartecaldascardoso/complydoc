"""Named form fields. A positive signal, not a negative one."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat


@signal
class AcroFormSignal:
    id = "acroform_fields"
    name = "PDF form fields"
    unit = "fields"
    why = "Named form fields give labelled values, with no layout guesswork."
    applies_to = frozenset({DocumentFormat.PDF})

    def measure(self, document: Document) -> Measurement:
        if not document.pages and document.encrypted:
            return Measurement.na("the document is encrypted and could not be inspected")
        count = document.acroform_fields
        display = f"{count} named field(s)" if count else "none (values must be located by layout)"
        return Measurement(value=count, display=display, detail={"field_count": count})
