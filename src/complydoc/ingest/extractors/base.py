"""What an extractor is asked for, and what it hands back.

An extractor reads the text layer of one page. It does not open the file, decide
its size, find its images or read its fonts — those are facts about the document
rather than choices about how to read it, and they stay with the loader.

Extractors differ in what they can offer. pdfplumber returns a box per word and
finds ruled tables; pdfium returns a box per line and finds none. Rather than
paper over that, an extractor declares what it provides, and the signals that
need what it cannot give report that they could not measure instead of
returning a number that means something else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from complydoc.ingest.base import Rect, TableInfo, TextBlock

__all__ = ["Extraction", "Extractor", "Granularity", "PageSource", "rect_from"]

Granularity = Literal["word", "line", "none"]
"""How finely the boxes divide the page.

Coverage from line boxes counts the gaps between words as text,, so the two are not
interchangeable. `"none"` is for a reader that returns text and no geometry at
all: it reports no coverage rather than nought per cent, which would read as an
empty page."""


@dataclass(frozen=True, slots=True)
class PageSource:
    """The handles a page can be read through.

    One per library, opened once by the loader. An extractor takes the handle it
    understands and ignores the rest, so adding a third does not mean opening the
    file a third time for the two that were already there.
    """

    plumber: Any = None
    pdfium: Any = None
    pypdf: Any = None
    """The reader the loader already opened, decrypted if the file was."""
    number: int = 1
    """Which page this is, one-based, for readers that index a whole document."""


@dataclass(slots=True)
class Extraction:
    """One page as one extractor read it."""

    text: str = ""
    blocks: list[TextBlock] = field(default_factory=list)
    granularity: Granularity = "word"
    raw_chars: str = ""
    """Characters before unicode normalisation, where the extractor exposes them.

    Empty when it does not: the garbled-character signal needs un-normalised text
    and will say it could not measure rather than guess from normalised text.
    """
    tables: list[TableInfo] = field(default_factory=list)
    tables_searched: bool = False
    """False when this extractor cannot look for tables at all, which is not the
    same as looking and finding none."""
    notes: list[str] = field(default_factory=list)

    @property
    def characters(self) -> int:
        return len(self.text.strip())

    def coverage_pct(self, width: float, height: float) -> float | None:
        """Share of the page covered by text boxes, or None if none were returned.

        A reader that hands back text without geometry has not measured nought
        per cent coverage; it has not measured coverage.
        """
        if self.granularity == "none":
            return None
        if width <= 0 or height <= 0:
            return 0.0
        covered = sum(b.bbox.area for b in self.blocks)
        return round(min(100.0, covered / (width * height) * 100), 2)


@runtime_checkable
class Extractor(Protocol):
    """Reads the text layer of one page."""

    id: str
    name: str
    provides_tables: bool
    provides_raw_chars: bool
    granularity: Granularity

    def available(self) -> bool:
        """Whether this extractor can run here at all."""
        ...

    def read(self, source: PageSource, width: float, height: float) -> Extraction: ...


def rect_from(box: dict[str, Any]) -> Rect:
    """A pdfplumber-shaped mapping as a rectangle in page points."""
    return Rect(
        x0=float(box.get("x0", 0.0)),
        y0=float(box.get("top", 0.0)),
        x1=float(box.get("x1", 0.0)),
        y1=float(box.get("bottom", 0.0)),
    )
