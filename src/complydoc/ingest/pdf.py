"""PDF loader, covering both native-text and scanned documents.

Three permissively licensed libraries share the work: pypdf for the document
container (encryption, form fields, font descriptors), pdfplumber for page
content (words, images, tables, fonts), and pypdfium2 for rasterising pages that
have to be looked at as pixels. PyMuPDF would do all three, but it is AGPL and
this tool is meant to be redistributable.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pdfplumber
import pypdf

from complydoc.ingest.base import (
    Document,
    DocumentFormat,
    ExtractionSummary,
    ImageBlock,
    IngestOptions,
    LoaderError,
    Page,
    Rect,
    TableInfo,
    sha256_of,
)
from complydoc.ingest.extractors.base import Extraction, PageSource
from complydoc.ingest.extractors.registry import extractor_by_id
from complydoc.ingest.registry import register
from complydoc.text import count, plural

_ALIGNED_TABLE_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
_MAX_WORDS_CUT = 0.02
"""A column edge that slices through words is an artefact of the text strategy."""
_MIN_ALIGNED_ROWS = 3
_MIN_ALIGNED_COLS = 2

_FONT_FILE_KEYS = ("/FontFile", "/FontFile2", "/FontFile3")

# The PDF standard 14. A viewer is required to have these, so they are never
# embedded and their absence is not a portability problem.
_STANDARD_14 = frozenset(
    {
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Times-BoldItalic",
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
        "Symbol",
        "ZapfDingbats",
    }
)


@contextlib.contextmanager
def _quiet_pypdf() -> Iterator[None]:
    """Silence pypdf's own warnings; this loader reports problems in its own words."""
    logger = logging.getLogger("pypdf")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


def _base_font_name(obj: Any) -> str:
    raw = str(obj.get("/BaseFont", "") or "").lstrip("/")
    # Subset fonts are named like "ABCDEF+Vera"; strip the tag.
    return raw.split("+", 1)[-1] if "+" in raw else raw


def _rect_from(item: dict[str, Any]) -> Rect:
    return Rect(
        x0=float(item.get("x0", 0.0)),
        y0=float(item.get("top", 0.0)),
        x1=float(item.get("x1", 0.0)),
        y1=float(item.get("bottom", 0.0)),
    )


def _font_is_embedded(font: Any) -> bool:
    """True if the font carries its own glyph data, or is one of the standard 14.

    A standard-14 font is not embedded, but every viewer is required to have it,
    so it carries none of the glyph-substitution risk that a missing embedded
    font does. Counting it as a problem would flag almost every PDF ever made.
    """
    try:
        obj = font.get_object() if hasattr(font, "get_object") else font
        if _base_font_name(obj) in _STANDARD_14:
            return True
        descendants = obj.get("/DescendantFonts")
        if descendants:
            resolved = (
                descendants.get_object() if hasattr(descendants, "get_object") else descendants
            )
            return any(_font_is_embedded(child) for child in resolved)
        descriptor = obj.get("/FontDescriptor")
        if descriptor is None:
            return False
        descriptor = descriptor.get_object() if hasattr(descriptor, "get_object") else descriptor
        return any(key in descriptor for key in _FONT_FILE_KEYS)
    except Exception:
        return False


def _page_fonts_embedded(page: Any) -> bool | None:
    """True if every font on the page carries an embedded font file.

    Returns None when the page declares no fonts at all, which is a different
    thing from declaring fonts that are not embedded.
    """
    try:
        resources = page.get("/Resources")
        if resources is None:
            return None
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        fonts = resources.get("/Font")
        if not fonts:
            return None
        fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
        values = list(fonts.values())
        if not values:
            return None
        return all(_font_is_embedded(font) for font in values)
    except Exception:
        return None


def _table_shape(table: Any) -> TableInfo | None:
    """Row/column counts, spanning-cell count and header depth for one table.

    Column edges are derived from the distinct cell boundaries, and any cell
    covering more than one edge interval counts as merged. Header depth is the
    number of leading rows that contain such a cell, which is what makes a
    stacked three-row header visible as a three-row header.
    """
    try:
        rows = list(table.rows)
    except Exception:
        return None
    if not rows:
        return None

    cell_rows: list[list[tuple[float, float, float, float]]] = []
    for row in rows:
        cells = [c for c in getattr(row, "cells", []) or [] if c is not None]
        cell_rows.append([tuple(float(v) for v in c) for c in cells])  # type: ignore[misc]

    all_cells = [c for row in cell_rows for c in row]
    if not all_cells:
        return None

    edges = sorted({round(c[0], 1) for c in all_cells} | {round(c[2], 1) for c in all_cells})
    col_count = max(1, len(edges) - 1)

    def spans(cell: tuple[float, float, float, float]) -> int:
        left, right = round(cell[0], 1), round(cell[2], 1)
        return sum(1 for i in range(len(edges) - 1) if edges[i] >= left and edges[i + 1] <= right)

    merged = sum(1 for cell in all_cells if spans(cell) > 1)

    spanning_rows = 0
    for row_cells in cell_rows:
        if any(spans(cell) > 1 for cell in row_cells):
            spanning_rows += 1
        else:
            break
    # The row of leaf labels sitting under the spanning rows is part of the
    # header too, so a header of two merged rows plus its labels is three deep.
    header_depth = spanning_rows + 1 if spanning_rows else 1

    return TableInfo(
        rows=len(cell_rows),
        cols=col_count,
        header_depth=header_depth,
        merged_cells=merged,
    )


def _aligned_tables(plumber_page: Any, words: list[Any]) -> list[TableInfo]:
    """Tables held together by whitespace rather than ruling lines.

    Most invoices align their columns with spacing and draw no rules at all, so
    the line-based pass finds nothing in them. Running the text strategy alone is
    worse than useless — it finds a thirteen-column "table" in a page of prose —
    so a candidate is only accepted when its column edges fall in the gutters.
    A boundary that cuts through words is not a column.

    The words are passed in because the page has already been asked for them;
    clustering its characters into words a second time is one of the most
    expensive things this loader does.
    """
    if not words:
        return []
    try:
        candidates = plumber_page.find_tables(table_settings=_ALIGNED_TABLE_SETTINGS)
    except Exception:
        return []
    if not candidates:
        return []

    found: list[TableInfo] = []
    for candidate in candidates:
        # The gutter test first, because it is geometry and costs nothing, while
        # pulling the text out of a candidate walks every character against every
        # cell. On a page of prose the candidate is rejected here, and a book of
        # prose is most of what this ever sees.
        edges = sorted(
            {round(c[0], 1) for row in candidate.rows for c in row.cells if c}
            | {round(c[2], 1) for row in candidate.rows for c in row.cells if c}
        )
        interior = edges[1:-1]
        if not interior:
            continue
        cut = sum(
            1 for w in words if any(w["x0"] + 0.5 < edge < w["x1"] - 0.5 for edge in interior)
        )
        if cut / len(words) > _MAX_WORDS_CUT:
            continue

        try:
            grid = [[(cell or "").strip() for cell in row] for row in candidate.extract()]
        except Exception:
            continue
        filled = [row for row in grid if any(row)]
        columns = max((len(row) for row in filled), default=0)
        if len(filled) < _MIN_ALIGNED_ROWS or columns < _MIN_ALIGNED_COLS:
            continue

        found.append(
            TableInfo(
                rows=len(filled),
                cols=columns,
                # Without ruling lines there is nothing to read a span from, so
                # neither header depth nor merged cells can be measured here.
                header_depth=1,
                merged_cells=0,
                detected_by="alignment",
            )
        )
    return found


def _wants_pdfium(options: IngestOptions) -> bool:
    """Whether any extractor asked for reads through pdfium."""
    from complydoc.ingest.extractors.registry import extractor_by_id

    for name in (options.extractor, *options.compare_extractors):
        engine = extractor_by_id(name)
        if engine is not None and getattr(engine, "id", "") == "pdfium":
            return True
    return False


def _open_pdfium(path: Path, password: str) -> Any:
    try:
        import pypdfium2 as pdfium

        return pdfium.PdfDocument(str(path), password=password or None)
    except Exception:  # pragma: no cover - a file pdfplumber opened may still fail here
        return None


def _render_pages(path: Path, password: str, indices: list[int], dpi: int) -> dict[int, Any]:
    """Rasterise selected pages to greyscale PIL images."""
    if not indices:
        return {}
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover - a core dependency
        return {}

    rendered: dict[int, Any] = {}
    try:
        pdf = pdfium.PdfDocument(str(path), password=password or None)
    except Exception:
        return {}
    try:
        scale = dpi / 72.0
        for index in indices:
            try:
                bitmap = pdf[index].render(scale=scale, grayscale=True)
                rendered[index] = bitmap.to_pil().convert("L")
            except Exception:
                continue
    finally:
        with contextlib.suppress(Exception):
            pdf.close()
    return rendered


class PdfLoader:
    extensions: tuple[str, ...] = (".pdf",)
    format: DocumentFormat = DocumentFormat.PDF

    def load(self, path: Path, options: IngestOptions) -> Document:
        from complydoc.ingest import ocr as ocr_module

        document = Document(path=path, sha256=sha256_of(path), format=self.format)

        try:
            with _quiet_pypdf():
                reader = pypdf.PdfReader(str(path))
        except Exception as exc:
            raise LoaderError(f"pypdf could not open the file: {exc}") from exc

        password = ""
        if reader.is_encrypted:
            document.encrypted = True
            opened = False
            # The supplied password first, then an empty one, which opens a file
            # that is protected against casual opening but not against reading.
            for candidate in (options.password, ""):
                if candidate is None:
                    continue
                try:
                    if reader.decrypt(candidate):
                        opened, password = True, candidate
                        break
                except Exception:
                    continue
            if not opened:
                document.load_warnings.append(
                    "The file is password protected and neither the supplied password nor "
                    "an empty one opened it, so its content could not be read. Page count, "
                    "text, tables and sensitive data were all left unmeasured."
                    if options.password
                    else "The file is password protected and no password was supplied, so "
                    "its content could not be read. Page count, text, tables and sensitive "
                    "data were all left unmeasured. Pass --password to open it."
                )
                return document
            document.decrypted_with_empty_password = password == ""
            if password == "":
                document.load_warnings.append(
                    "The file is encrypted but opened with an empty password, so it was "
                    "read in full. Its contents are protected against casual opening only."
                )

        try:
            fields = reader.get_fields()
            document.acroform_fields = len(fields) if fields else 0
        except Exception:
            document.acroform_fields = 0

        try:
            meta = reader.metadata
            document.producer = str(meta.producer) if meta and meta.producer else None
        except Exception:
            document.producer = None

        try:
            with _quiet_pypdf():
                plumber = pdfplumber.open(str(path), password=password)
        except Exception as exc:
            raise LoaderError(f"pdfplumber could not open the file: {exc}") from exc

        # Opened once, and only when an extractor that reads through it was
        # asked for. The default run never touches it here.
        pdfium_doc = None
        if _wants_pdfium(options):
            pdfium_doc = _open_pdfium(path, password)

        needs_raster: list[int] = []
        with plumber, _quiet_pypdf():
            for index, plumber_page in enumerate(plumber.pages):
                native = None
                if pdfium_doc is not None and index < len(pdfium_doc):
                    try:
                        native = pdfium_doc[index]
                    except Exception:
                        native = None
                page = self._build_page(
                    index, plumber_page, reader, options, document, pdfium_page=native
                )
                document.pages.append(page)
                if len(needs_raster) < options.max_render_pages and self._needs_raster(
                    page, options
                ):
                    needs_raster.append(index)

        rasters = _render_pages(path, password, needs_raster, options.render_dpi)
        for index, image in rasters.items():
            document.pages[index].raster = image

        self._apply_ocr(document, options, ocr_module, needs_raster)
        self._apply_ocr_compare(document, options, ocr_module)
        self._apply_second_engines(document, options)
        return document

    @staticmethod
    def _extract(
        page: Page,
        source: PageSource,
        width: float,
        height: float,
        options: IngestOptions,
    ) -> Extraction:
        """Read the page with each extractor asked for, and keep one of them.

        The kept one is the only one that reaches a finding. The others are
        measured and recorded so the report can say where they disagreed, and
        they never change what the report concludes.
        """
        wanted = [options.extractor, *options.compare_extractors]
        kept: Extraction | None = None

        for index, name in enumerate(dict.fromkeys(wanted)):
            engine = extractor_by_id(name)
            if engine is None or not engine.available():
                if index == 0:
                    page.notes.append(f"extractor {name!r} is not available")
                continue
            started = time.perf_counter()
            try:
                found = engine.read(source, width, height)
            except Exception as exc:  # pragma: no cover - an extractor may fail
                page.notes.append(f"extractor {name!r} failed: {exc}")
                continue
            seconds = time.perf_counter() - started

            page.extractions.append(
                ExtractionSummary(
                    extractor=name,
                    characters=found.characters,
                    coverage_pct=found.coverage_pct(width, height),
                    seconds=round(seconds, 4),
                    granularity=found.granularity,
                    tables_found=len(found.tables) if engine.provides_tables else None,
                )
            )
            if options.keep_readings and found.text.strip():
                page.readings[name] = found.text
            if kept is None:
                kept = found

        return kept if kept is not None else Extraction()

    @staticmethod
    def _needs_raster(page: Page, options: IngestOptions) -> bool:
        if options.render_all_pages:
            return True
        thin_text = len(page.text.strip()) < options.ocr_min_chars
        image_heavy = page.image_area_pt > 0.4 * page.area_pt if page.area_pt else False
        return thin_text or image_heavy

    def _build_page(
        self,
        index: int,
        plumber_page: Any,
        reader: pypdf.PdfReader,
        options: IngestOptions,
        document: Document,
        pdfium_page: Any = None,
    ) -> Page:
        width = float(plumber_page.width or 0.0)
        height = float(plumber_page.height or 0.0)
        rotation = int(getattr(plumber_page, "rotation", 0) or 0)

        page = Page(number=index + 1, width_pt=width, height_pt=height, rotation=rotation)

        source = PageSource(plumber=plumber_page, pdfium=pdfium_page)
        kept = self._extract(page, source, width, height, options)
        page.text = kept.text
        page.text_source = "native" if page.text.strip() else "none"
        page.text_blocks.extend(kept.blocks)
        page.notes.extend(kept.notes)

        # Word geometry from the extractor that was kept. The alignment table
        # pass reuses it rather than clustering the characters a second time.
        words: list[Any] = []
        if kept.granularity == "word":
            try:
                words = plumber_page.extract_words() or []
            except Exception:
                words = []

        try:
            for image in plumber_page.images or []:
                srcsize = image.get("srcsize") or (None, None)
                page.image_blocks.append(
                    ImageBlock(
                        bbox=_rect_from(image),
                        width_px=int(srcsize[0]) if srcsize[0] else None,
                        height_px=int(srcsize[1]) if srcsize[1] else None,
                    )
                )
        except Exception as exc:
            page.notes.append(f"image geometry unavailable: {exc}")

        page.raw_chars = kept.raw_chars
        try:
            # Fonts are a fact about the page rather than a reading of it, so
            # they come from the file whichever extractor was used.
            page.fonts = {str(c["fontname"]) for c in plumber_page.chars if c.get("fontname")}
        except Exception:
            page.fonts = set()

        # Only the extractor that was kept gets to speak for the page. Reading
        # tables through pdfplumber while the report is built from pdfium would
        # both claim structure the chosen extractor never saw and spend the time
        # that choosing it was meant to save.
        engine = extractor_by_id(options.extractor)
        reads_tables = engine is None or engine.provides_tables
        if options.extract_tables and reads_tables:
            try:
                for table in plumber_page.find_tables():
                    info = _table_shape(table)
                    if info is not None:
                        page.tables.append(info)
                if not page.tables:
                    page.tables.extend(_aligned_tables(plumber_page, words))
            except Exception as exc:
                page.notes.append(f"table detection failed: {exc}")
                document.load_warnings.append(
                    f"Table structure on page {index + 1} could not be analysed ({exc})."
                )

        try:
            page.embedded_fonts = _page_fonts_embedded(reader.pages[index])
        except Exception:
            page.embedded_fonts = None

        return page

    @staticmethod
    def _apply_second_engines(document: Document, options: IngestOptions) -> None:
        """Read every rasterised page with the other OCR engines as well.

        Unlike the PDF extractors, which agree on a page's text to within a per
        cent, OCR engines genuinely disagree — they read different words and
        differ about how sure they are. Only the selected engine's reading is
        used; the rest are here to be read beside it.
        """
        if not options.compare_engines or not options.keep_readings:
            return
        from complydoc.ingest.engines.registry import engine_by_id

        for name in dict.fromkeys(options.compare_engines):
            engine = engine_by_id(name)
            if engine is None or not engine.available():
                continue
            for page in document.pages:
                if page.raster is None:
                    continue
                try:
                    read = engine.read(page.raster)
                except Exception as exc:  # pragma: no cover - a bad page is not fatal
                    page.notes.append(f"OCR engine {name!r} failed: {exc}")
                    continue
                if read.text.strip():
                    page.readings[name] = read.text

    @staticmethod
    def _apply_ocr_compare(document: Document, options: IngestOptions, ocr_module: Any) -> None:
        """Read every rasterised page with OCR as well, for side-by-side comparison."""
        if not options.ocr_compare or not ocr_module.available():
            return
        for page in document.pages:
            if page.raster is None or page.ocr_text:
                continue
            read = ocr_module.run(page.raster)
            page.ocr_text = read.text
            page.ocr_confidence = read.confidence

    @staticmethod
    def _apply_ocr(
        document: Document, options: IngestOptions, ocr_module: Any, rendered: list[int]
    ) -> None:
        candidates = [
            page
            for page in document.pages
            if page.text_source == "none" or len(page.text.strip()) < options.ocr_min_chars
        ]
        if not candidates:
            return

        if not options.ocr:
            document.load_warnings.append(
                f"{count(len(candidates), 'page')} carry little or no text layer and OCR was not "
                f"requested, so their content was not read: "
                f"{', '.join(str(p.number) for p in candidates)}."
            )
            return

        if not ocr_module.available():
            document.load_warnings.append(
                f"{count(len(candidates), 'page')} carry little or no text layer and OCR is "
                f"unavailable ({ocr_module.unavailable_reason()}), so their content was "
                f"not read: {', '.join(str(p.number) for p in candidates)}."
            )
            return

        unread: list[int] = []
        for page in candidates:
            if page.raster is None:
                unread.append(page.number)
                continue
            read = ocr_module.run(page.raster)
            page.ocr_text = read.text
            page.ocr_confidence = read.confidence
            if read.text.strip():
                page.text = read.text
                page.text_source = "ocr"
                if options.keep_readings:
                    page.readings[ocr_module.engine_name()] = read.text
            else:
                unread.append(page.number)
        if unread:
            document.load_warnings.append(
                f"OCR produced no text for {plural(len(unread), 'page')} "
                f"{', '.join(str(n) for n in unread)}."
            )


register(PdfLoader())
