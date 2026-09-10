"""pdfium: the same text, an order of magnitude quicker, at line granularity.

Measured against pdfplumber on a real 392-page book, the two agree on the text
within one to two per cent, and pdfium reads it about thirteen times faster.
What it does not give is a box per word or any table structure, so a run using
it reports the signals that need those as not measured rather than guessing.

The library is already a dependency: it is what rasterises pages for OCR.
"""

from __future__ import annotations

from complydoc.ingest.base import Rect, TextBlock
from complydoc.ingest.extractors.base import Extraction, PageSource
from complydoc.ingest.extractors.registry import register


@register
class PdfiumExtractor:
    id = "pdfium"
    name = "pdfium"
    provides_tables = False
    provides_raw_chars = False
    granularity = "line"

    def available(self) -> bool:
        try:
            import pypdfium2  # noqa: F401
        except ImportError:  # pragma: no cover - it is a hard dependency
            return False
        return True

    def read(self, source: PageSource, width: float, height: float) -> Extraction:
        found = Extraction(granularity="line", tables_searched=False)
        native = source.pdfium
        if native is None:
            found.notes.append("pdfium was not given a page it could read")
            return found

        try:
            textpage = native.get_textpage()
        except Exception as exc:
            found.notes.append(f"text extraction failed: {exc}")
            return found

        try:
            found.text = textpage.get_text_range() or ""
        except Exception as exc:
            found.notes.append(f"text extraction failed: {exc}")

        try:
            for index in range(textpage.count_rects()):
                left, bottom, right, top = textpage.get_rect(index)
                # pdfium measures from the bottom of the page; everything else
                # here measures from the top.
                found.blocks.append(
                    TextBlock(
                        text="",
                        bbox=Rect(x0=left, y0=height - top, x1=right, y1=height - bottom),
                    )
                )
        except Exception as exc:
            found.notes.append(f"line geometry unavailable: {exc}")

        return found
