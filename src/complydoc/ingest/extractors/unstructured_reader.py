"""unstructured: a reader that segments the page before it reads it.

The other three walk the text layer in the order the file stores it. This one
groups the page into titles, paragraphs and list items first, which is why it
gets a two-column layout right where a straight walk reads across the columns.
That segmentation is also the whole cost: it is slower than pdfplumber and much
slower than pdfium, so it earns its place as something to compare against rather
than something to read a folder with.

Only the `fast` strategy is used, and deliberately. `hi_res` and `ocr_only`
route the page through layout-detection models the library downloads from
Hugging Face on first use, which this tool does not do and will not do. `fast`
is pdfminer and arithmetic, entirely on this machine, and runs with the network
guard armed like everything else.

It is an optional install (`pip install "complydoc[loaders]"`) because it brings
about twenty packages with it, and a reader for comparing against should not be
in the way of people who never compare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from complydoc.ingest.base import Rect, TextBlock
from complydoc.ingest.extractors.base import Extraction, PageSource
from complydoc.ingest.extractors.registry import register

_CACHE: tuple[Path, dict[int, list[Any]]] | None = None


@register
class UnstructuredExtractor:
    id = "unstructured"
    name = "unstructured"
    provides_tables = False
    provides_raw_chars = False
    granularity = "block"
    needs_install = "complydoc[loaders]"

    def available(self) -> bool:
        try:
            import unstructured.partition.pdf  # noqa: F401
        except Exception:
            return False
        return True

    def read(self, source: PageSource, width: float, height: float) -> Extraction:
        found = Extraction(granularity="block", tables_searched=False)
        if source.path is None:
            found.notes.append("unstructured was not given the file to read")
            return found

        try:
            by_page = _elements_for(source.path)
        except Exception as exc:
            found.notes.append(f"text extraction failed: {exc}")
            return found

        elements = by_page.get(source.number, [])
        if not elements:
            # Silence here would look like a blank page. It is the reader
            # declining to segment this one, which is a different thing.
            found.notes.append(
                f"unstructured returned nothing for this page "
                f"(it segmented {sum(len(v) for v in by_page.values())} elements "
                f"across pages {sorted(by_page) or 'none'})"
            )
            return found

        pieces: list[str] = []
        for element in elements:
            text = str(element).strip()
            if text:
                pieces.append(text)
            box = _bbox(element)
            if box is not None:
                found.blocks.append(TextBlock(text="", bbox=box))
        found.text = "\n\n".join(pieces)
        return found


def _elements_for(path: Path) -> dict[int, list[Any]]:
    """The whole document, partitioned once, indexed by page.

    unstructured reads files rather than pages, so calling it per page would
    parse the document once per page. Only the file being read is held.
    """
    global _CACHE
    if _CACHE is not None and _CACHE[0] == path:
        return _CACHE[1]

    from unstructured.partition.pdf import partition_pdf

    by_page: dict[int, list[Any]] = {}
    for element in partition_pdf(str(path), strategy="fast", languages=["eng"]):
        number = getattr(element.metadata, "page_number", None) or 1
        by_page.setdefault(int(number), []).append(element)
    _CACHE = (path, by_page)
    return by_page


def _bbox(element: Any) -> Rect | None:
    """The element's box in page points, or None where it has none."""
    coordinates = getattr(element.metadata, "coordinates", None)
    points = getattr(coordinates, "points", None) if coordinates else None
    if not points:
        return None
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    return Rect(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
