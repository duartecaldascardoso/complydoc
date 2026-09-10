"""pypdf: a third opinion on the text, for nothing.

The library is already a dependency — it is what reads encryption and document
metadata — so this reader costs no install and is always there to compare
against. It is a genuinely separate implementation from pdfplumber and pdfium
rather than a wrapper around either, which is the only reason a third reading is
worth having.

What it does not return is geometry. There are no word boxes, no line boxes and
no table structure, so a run using it reports coverage as not measured and the
signals that need boxes say the same. Its use is the text itself: whether two
libraries that share no code read the same words in the same order.
"""

from __future__ import annotations

from complydoc.ingest.extractors.base import Extraction, PageSource
from complydoc.ingest.extractors.registry import register


@register
class PypdfExtractor:
    id = "pypdf"
    name = "pypdf"
    provides_tables = False
    provides_raw_chars = False
    granularity = "none"

    def available(self) -> bool:
        return True

    def read(self, source: PageSource, width: float, height: float) -> Extraction:
        found = Extraction(granularity="none", tables_searched=False)
        if source.pypdf is None:
            found.notes.append("pypdf was not given the file to read")
            return found

        try:
            # The loader's own reader, already opened and already decrypted if
            # the file needed it. Opening the file again here would parse its
            # cross-reference table a second time for no gain.
            found.text = source.pypdf.pages[source.number - 1].extract_text() or ""
        except IndexError:
            found.notes.append(f"pypdf found no page {source.number}")
        except Exception as exc:
            found.notes.append(f"text extraction failed: {exc}")
        return found
