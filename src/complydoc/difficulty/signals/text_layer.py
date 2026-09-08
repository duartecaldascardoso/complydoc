"""Does the document carry a usable text layer."""

from __future__ import annotations

from complydoc.difficulty.base import ALL_FORMATS, Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document


@signal
class TextLayerSignal:
    id = "text_layer_present"
    name = "Text layer present"
    unit = None
    why = (
        "With a text layer the words can be read straight out of the file, exactly as "
        "typed. Without one, every character has to be recognised from an image first, "
        "which costs more and introduces transcription errors that are hard to spot."
    )
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        if not document.pages:
            return Measurement.na("the document could not be opened, so nothing was read")
        native = sum(1 for p in document.pages if p.text_source == "native" and p.text.strip())
        ocr = sum(1 for p in document.pages if p.text_source == "ocr" and p.text.strip())
        none = len(document.pages) - native - ocr
        present = native > 0
        if present:
            display = f"yes, on {native} of {len(document.pages)} page(s)"
        elif ocr:
            display = f"no native text; {ocr} page(s) recovered by OCR"
        else:
            display = "no"
        return Measurement(
            value=present,
            display=display,
            detail={"native_pages": native, "ocr_pages": ocr, "unread_pages": none},
        )
