"""Per-page wireframes showing where the cost and the risk actually sit.

A page is drawn as geometry only: rectangles for the words, shaded blocks for
the images, marks where sensitive values were found. No pixels from the document
are ever rendered, and no character of its text reaches the output.

That restriction is the point. A thumbnail of the page would show the reader
exactly the bank account number the scan just took care to mask, and the report
is meant to be forwardable. Geometry answers the useful question — which pages
are expensive, where the risk is concentrated — without answering the dangerous
one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from complydoc.ingest.base import Document, Page, Rect
from complydoc.sensitive.scanner import ScanResult

__all__ = ["Box", "PagePreview", "build_previews"]

_IMAGE_WIDTH_PX = 560
"""Rendered width of an embedded page image. Twice the display width, for sharpness."""
_IMAGE_QUALITY = 72

_MIN_WORDS_FOR_COLUMNS = 25
_MAX_MATCH_WIDTH_FRACTION = 0.6
"""An identifier never spans most of a page. A wider hit crossed a column."""
_MAX_MATCH_LINE_HEIGHTS = 2.5
"""Nor does it wrap over several lines."""


@dataclass(frozen=True, slots=True)
class Box:
    """A rectangle in normalised page space, 0.0 to 1.0 on both axes."""

    x: float
    y: float
    w: float
    h: float
    label: str | None = None

    @classmethod
    def normalised(cls, rect: Rect, width: float, height: float, label: str | None = None) -> Box:
        return cls(
            x=round(max(0.0, rect.x0 / width), 4),
            y=round(max(0.0, rect.y0 / height), 4),
            w=round(min(1.0, (rect.x1 - rect.x0) / width), 4),
            h=round(min(1.0, (rect.y1 - rect.y0) / height), 4),
            label=label,
        )


@dataclass(slots=True)
class PagePreview:
    number: int
    width_pt: float
    height_pt: float
    rotation: int
    text_blocks: list[Box] = field(default_factory=list)
    image_blocks: list[Box] = field(default_factory=list)
    sensitive: list[Box] = field(default_factory=list)
    gutters: list[Box] = field(default_factory=list)
    text_coverage_pct: float = 0.0
    image_coverage_pct: float = 0.0
    sensitive_count: int = 0
    image_data_uri: str | None = None
    """The page itself, as a JPEG data URI. Only set when --page-images is used.

    This is real document content. Everything else in a preview is geometry, and
    the default report contains no page images at all.
    """
    unlocated_sensitive: int = 0
    """Matches the scan found but could not be placed on the page."""
    unreadable: bool = False

    @property
    def flags(self) -> list[tuple[str, str]]:
        """What is wrong with this page, as (severity, label) chips.

        The difficulty signals are folder-wide and document-wide; these put the
        same facts on the page they came from, which is where a reader looking at
        a thumbnail actually wants them.
        """
        found: list[tuple[str, str]] = []
        if self.unreadable:
            found.append(("bad", "not read"))
        if self.rotation:
            found.append(("bad", f"rotated {self.rotation}\u00b0"))
        if self.image_coverage_pct >= 60:
            found.append(("warn", f"{self.image_coverage_pct:.0f}% image"))
        if self.text_coverage_pct < 3 and not self.unreadable:
            found.append(("warn", "almost no text"))
        elif self.text_coverage_pct >= 30:
            found.append(("ok", f"{self.text_coverage_pct:.0f}% text"))
        if len(self.gutters) >= 1:
            found.append(("warn", f"{len(self.gutters) + 1} columns"))
        if self.sensitive_count:
            found.append(("bad", f"{self.sensitive_count} sensitive"))
        return found

    @property
    def aspect(self) -> float:
        if self.width_pt <= 0 or self.height_pt <= 0:
            return 1.4142
        return self.height_pt / self.width_pt


def _normalise(value: str) -> str:
    """Compare values ignoring whitespace and separators, which words split on."""
    return "".join(c for c in value.lower() if c.isalnum())


def _plausible(rect: Rect, page: Page) -> bool:
    """Reject a located box that cannot be a single identifier.

    Words are matched in extraction order, which on a multi-column page runs
    across the gutter rather than down one column. A run that starts in the left
    column and finishes in the right produces a box spanning the whole page, and
    drawing it would point the reader at the wrong place. Dropping it and
    reporting the match as unplaced is the honest outcome.
    """
    if page.width_pt <= 0:
        return False
    if (rect.x1 - rect.x0) > _MAX_MATCH_WIDTH_FRACTION * page.width_pt:
        return False
    heights = sorted(b.bbox.y1 - b.bbox.y0 for b in page.text_blocks if b.bbox.y1 > b.bbox.y0)
    if heights:
        median = heights[len(heights) // 2]
        if median > 0 and (rect.y1 - rect.y0) > _MAX_MATCH_LINE_HEIGHTS * median:
            return False
    return True


def _locate(value: str, page: Page) -> Rect | None:
    """The bounding box of the run of words that produced `value`.

    Extracted text and positioned words come from two different passes, so there
    is no offset mapping between them. Matching on the alphanumeric content of
    consecutive words recovers the link for the cases that matter: an identifier
    is almost always one word, or a few words split on spaces and hyphens.
    """
    target = _normalise(value)
    if not target or not page.text_blocks:
        return None

    blocks = page.text_blocks
    for start in range(len(blocks)):
        joined = ""
        for end in range(start, min(start + 8, len(blocks))):
            joined += _normalise(blocks[end].text)
            if not target.startswith(joined[: len(target)]) and not joined.startswith(target):
                break
            if target in joined:
                spans = [b.bbox for b in blocks[start : end + 1]]
                found = Rect(
                    x0=min(s.x0 for s in spans),
                    y0=min(s.y0 for s in spans),
                    x1=max(s.x1 for s in spans),
                    y1=max(s.y1 for s in spans),
                )
                return found if _plausible(found, page) else None
            if len(joined) >= len(target):
                break
    return None


def _value_at(page: Page, line: int, column: int, length: int) -> str | None:
    lines = page.text.split("\n")
    if not 1 <= line <= len(lines):
        return None
    text = lines[line - 1]
    if column >= len(text):
        return None
    return text[column : column + length]


def _gutters(page: Page) -> list[Box]:
    """Vertical bands no word crosses, which is what a column gutter is."""
    if page.width_pt <= 0 or len(page.text_blocks) < _MIN_WORDS_FOR_COLUMNS:
        return []

    bins = 200
    occupied = [False] * bins
    for block in page.text_blocks:
        start = max(0, min(bins - 1, int(block.bbox.x0 / page.width_pt * bins)))
        end = max(1, min(bins, int(-(-block.bbox.x1 / page.width_pt * bins // 1))))
        for i in range(start, end):
            occupied[i] = True

    if not any(occupied):
        return []
    first = occupied.index(True)
    last = bins - occupied[::-1].index(True)
    min_gap = max(1, int(0.035 * bins))

    found: list[Box] = []
    run_start = None
    for i in range(first, last):
        if occupied[i]:
            if run_start is not None and i - run_start >= min_gap:
                found.append(
                    Box(
                        x=round(run_start / bins, 4),
                        y=0.0,
                        w=round((i - run_start) / bins, 4),
                        h=1.0,
                        label="gutter",
                    )
                )
            run_start = None
        elif run_start is None:
            run_start = i
    return found


def _encode_page(raster: object) -> str | None:
    """A page raster as a JPEG data URI, downscaled to preview size."""
    import base64
    import io

    from PIL import Image as PILImage

    if not isinstance(raster, PILImage.Image):
        return None
    image = raster.convert("L")
    if image.width > _IMAGE_WIDTH_PX:
        ratio = _IMAGE_WIDTH_PX / image.width
        image = image.resize(
            (_IMAGE_WIDTH_PX, max(1, round(image.height * ratio))), PILImage.Resampling.LANCZOS
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=_IMAGE_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_previews(
    document: Document, scan: ScanResult | None, page_images: bool = False
) -> list[PagePreview]:
    """One wireframe per page.

    Geometry only, unless `page_images` is set, in which case each page is also
    embedded as an image. That is opt-in because it puts real document content
    into a file the report is otherwise safe to forward.
    """
    by_page: dict[int, list[tuple[int, int, int, str]]] = {}
    if scan is not None:
        for match in scan.matches:
            by_page.setdefault(match.page, []).append(
                (match.line, match.column, match.length, match.severity)
            )

    previews: list[PagePreview] = []
    for page in document.pages:
        width, height = page.width_pt, page.height_pt
        preview = PagePreview(
            number=page.number,
            width_pt=width,
            height_pt=height,
            rotation=page.rotation,
            unreadable=not page.text.strip() and not page.image_blocks,
        )
        if width <= 0 or height <= 0:
            if page_images and page.raster is not None:
                preview.image_data_uri = _encode_page(page.raster)
            previews.append(preview)
            continue

        preview.text_blocks = [
            Box.normalised(b.bbox, width, height) for b in page.text_blocks if b.bbox.area > 0
        ]
        preview.image_blocks = [
            Box.normalised(b.bbox, width, height) for b in page.image_blocks if b.bbox.area > 0
        ]
        preview.gutters = _gutters(page)

        for line, column, length, severity in by_page.get(page.number, []):
            preview.sensitive_count += 1
            value = _value_at(page, line, column, length)
            rect = _locate(value, page) if value else None
            if rect is None:
                preview.unlocated_sensitive += 1
                continue
            preview.sensitive.append(Box.normalised(rect, width, height, label=severity))

        from complydoc.geometry import coverage_fraction

        preview.text_coverage_pct = round(
            coverage_fraction([b.bbox for b in page.text_blocks], width, height) * 100, 1
        )
        preview.image_coverage_pct = round(
            coverage_fraction([b.bbox for b in page.image_blocks], width, height) * 100, 1
        )
        if page_images and page.raster is not None:
            preview.image_data_uri = _encode_page(page.raster)

        previews.append(preview)

    return previews
