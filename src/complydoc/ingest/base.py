"""The normalised document model every component reads.

Format-specific code lives in the loader modules and stops there. Cost
estimation, readiness signals and the sensitive data scan all consume the
`Document` produced here and never touch a PDF or a spreadsheet directly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = [
    "Document",
    "DocumentFormat",
    "ExtractionSummary",
    "ImageBlock",
    "IngestOptions",
    "Loader",
    "LoaderError",
    "Page",
    "Rect",
    "SkipRecord",
    "TableInfo",
    "TextBlock",
    "TextSource",
    "sha256_of",
]


class DocumentFormat(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    XLSX = "xlsx"


TextSource = Literal["native", "ocr", "none"]


class LoaderError(RuntimeError):
    """A file could not be opened or parsed. Always caught; never fatal to a run."""


@dataclass(frozen=True, slots=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    bbox: Rect


@dataclass(frozen=True, slots=True)
class ImageBlock:
    bbox: Rect
    """Placement on the page, in points."""
    width_px: int | None = None
    height_px: int | None = None
    """Intrinsic pixel size of the embedded image, when the format reports it."""


@dataclass(frozen=True, slots=True)
class TableInfo:
    rows: int
    cols: int
    header_depth: int
    """How many stacked rows form the header. More than one means a nested header."""
    merged_cells: int
    detected_by: Literal["lines", "alignment"] = "lines"
    """How the table was found. Alignment carries no ruling lines, so its header
    depth and merged-cell counts cannot be measured and are reported as unknown."""


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    """What one extractor made of one page, for comparing them against each other.

    Comparison lives inside a run: the same page, the same machine, the same
    moment. Two runs of different extractors would differ for reasons that have
    nothing to do with the extractors.
    """

    extractor: str
    characters: int
    coverage_pct: float
    seconds: float
    granularity: str
    tables_found: int | None
    """None when the extractor cannot look for tables, which is not zero tables."""
    similarity: float = 1.0
    """How closely this reading matches the one that was kept, 0 to 1.

    Compared in order, not as a bag of characters. Two extractors reading a
    two-column page can return the same characters and the same count while one
    reads straight across the columns and scrambles the sentences — which a
    count cannot see and this can.
    """

    @property
    def reads_tables(self) -> bool:
        return self.tables_found is not None


@dataclass(slots=True)
class Page:
    number: int
    """1-indexed."""
    width_pt: float
    height_pt: float
    rotation: int = 0
    text: str = ""
    text_source: TextSource = "none"
    text_blocks: list[TextBlock] = field(default_factory=list)
    image_blocks: list[ImageBlock] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)
    fonts: set[str] = field(default_factory=set)
    embedded_fonts: bool | None = None
    ocr_text: str = ""
    ocr_confidence: float | None = None
    """The engine's mean confidence in what it read, 0 to 1. None if it did not run."""
    """What OCR read, kept separately from `text`.

    Normally OCR only runs where there is no text layer, and its output becomes
    `text`. With `ocr_compare` it runs on every page as well, so the text layer
    and the recognised text can be put side by side — which is how you tell a
    document that extracts badly from an extractor that reads it badly.
    """
    raw_chars: str = ""
    """Page characters as stored, before any unicode normalisation.

    `text` comes from the extractor's own text assembly, which NFKC-normalises —
    turning a fi ligature into two plain letters. That is usually helpful, but it
    destroys exactly the evidence the garbled-character signal needs, so the
    un-normalised characters are kept alongside. Word spacing is absent here, so
    this is only useful for character-level questions.
    """
    extractions: list[ExtractionSummary] = field(default_factory=list)
    """One per extractor asked for, including the one whose output was kept."""
    readings: dict[str, str] = field(default_factory=dict)
    """What each extractor and OCR engine made of this page, by name.

    Only populated for the readers a run was asked to compare, and only when the
    run is keeping text at all. It is the page's words several times over, so it
    is the largest thing a comparison adds to a report.
    """
    raster: Image | None = None
    """Populated only for pages a signal actually needs to look at as pixels."""
    notes: list[str] = field(default_factory=list)

    @property
    def area_pt(self) -> float:
        return max(0.0, self.width_pt) * max(0.0, self.height_pt)

    @property
    def text_area_pt(self) -> float:
        return sum(b.bbox.area for b in self.text_blocks)

    @property
    def image_area_pt(self) -> float:
        return sum(b.bbox.area for b in self.image_blocks)

    @property
    def size_key(self) -> tuple[int, int]:
        """Rounded page size, for counting distinct sizes within one document."""
        return (round(self.width_pt), round(self.height_pt))

    def estimated_dpi(self) -> float | None:
        """Effective scan resolution, from the largest embedded image on the page.

        Only meaningful where the page really is a scan; a page whose images are
        small logos will report a number that means nothing, so callers check
        image coverage first.
        """
        candidates = [
            b for b in self.image_blocks if b.width_px and b.height_px and b.bbox.area > 0
        ]
        if not candidates or self.width_pt <= 0:
            return None
        biggest = max(candidates, key=lambda b: b.bbox.area)
        placed_width_in = (biggest.bbox.x1 - biggest.bbox.x0) / 72.0
        if placed_width_in <= 0:
            return None
        return float(biggest.width_px or 0) / placed_width_in


@dataclass(slots=True)
class Document:
    path: Path
    sha256: str
    format: DocumentFormat
    pages: list[Page] = field(default_factory=list)
    encrypted: bool = False
    decrypted_with_empty_password: bool = False
    acroform_fields: int = 0
    producer: str | None = None
    page_count_known: bool = True
    """False for formats with no fixed pagination until they are rendered."""
    load_warnings: list[str] = field(default_factory=list)
    """Non-fatal problems. These become entries in the report's limitations."""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def has_text_layer(self) -> bool:
        return any(p.text_source == "native" and p.text.strip() for p in self.pages)


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """A file complydoc could not open. Reported, never fatal."""

    path: Path
    reason: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class IngestOptions:
    ocr: bool = False
    """Run local OCR on pages with no usable text layer."""
    ocr_min_chars: int = 40
    """Below this many native characters, a page counts as having no text layer."""
    render_dpi: int = 150
    """Resolution used when rasterising a page for OCR or skew measurement."""
    max_render_pages: int = 50
    """Cap on how many pages of one document are rasterised, to bound memory."""
    extract_tables: bool = True
    extractor: str = "pdfplumber"
    """Which extractor's output the report is built from."""
    compare_extractors: tuple[str, ...] = ()
    """Others to run alongside, for comparison only. They never change a finding."""
    compare_engines: tuple[str, ...] = ()
    """OCR engines to read every rasterised page with, beside the one in use."""
    keep_readings: bool = False
    """Whether to hold on to what each reader made of the page, not just how much."""
    password: str = ""
    """Tried on encrypted files before falling back to an empty password."""
    ocr_compare: bool = False
    """Also OCR pages that already have a text layer, so the two can be compared."""
    render_all_pages: bool = False
    """Rasterise every page, not only the ones a signal needs to look at.

    Set when the report is going to show the page next to what was extracted
    from it. Off by default: rasterising costs time and memory, and the default
    report deliberately carries no page images.
    """


@runtime_checkable
class Loader(Protocol):
    """What every format loader must provide."""

    extensions: tuple[str, ...]
    format: DocumentFormat

    def load(self, path: Path, options: IngestOptions) -> Document: ...


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
