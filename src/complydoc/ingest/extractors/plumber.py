"""pdfplumber: a box per word, and it finds ruled tables.

The default, and the richest. Several readiness signals exist only because it
reports word geometry and table structure — text coverage, column detection, the
whitespace-table discriminator, merged cells and header depth all read what this
extractor produces and nothing else can supply.
"""

from __future__ import annotations

from complydoc.ingest.base import TextBlock
from complydoc.ingest.extractors.base import Extraction, PageSource, rect_from
from complydoc.ingest.extractors.registry import register


@register
class PlumberExtractor:
    id = "pdfplumber"
    name = "pdfplumber"
    provides_tables = True
    provides_raw_chars = True
    granularity = "word"

    def available(self) -> bool:
        return True

    def read(self, source: PageSource, width: float, height: float) -> Extraction:
        found = Extraction(granularity="word", tables_searched=False)
        page = source.plumber
        if page is None:
            found.notes.append("pdfplumber was not given a page it could read")
            return found

        try:
            found.text = page.extract_text() or ""
        except Exception as exc:
            found.notes.append(f"text extraction failed: {exc}")

        try:
            for word in page.extract_words() or []:
                found.blocks.append(TextBlock(text=str(word.get("text", "")), bbox=rect_from(word)))
        except Exception as exc:
            found.notes.append(f"word geometry unavailable: {exc}")

        try:
            # `extract_text` NFKC-normalises, which turns a fi ligature into two
            # plain letters and destroys the evidence the garbled-character
            # signal reads. The characters as stored are kept alongside.
            found.raw_chars = "".join(str(c.get("text", "")) for c in page.chars)
        except Exception:
            found.raw_chars = ""

        return found
