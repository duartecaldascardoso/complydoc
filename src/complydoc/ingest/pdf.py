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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pdfplumber
import pypdf

from complydoc.ingest.base import (
    Document,
    DocumentFormat,
    ImageBlock,
    IngestOptions,
    LoaderError,
    Page,
    Rect,
    TableInfo,
    TextBlock,
    sha256_of,
)
from complydoc.ingest.registry import register

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
            try:
                opened = bool(reader.decrypt(""))
            except Exception:
                opened = False
            if not opened:
                document.load_warnings.append(
                    "The file is password protected and no password was supplied, so its "
                    "content could not be read. Page count, text, tables and sensitive "
                    "data were all left unmeasured."
                )
                return document
            document.decrypted_with_empty_password = True
            document.load_warnings.append(
                "The file is encrypted but opened with an empty password, so it was read "
                "in full. Note that its contents are protected against casual opening only."
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

        needs_raster: list[int] = []
        with plumber, _quiet_pypdf():
            for index, plumber_page in enumerate(plumber.pages):
                page = self._build_page(index, plumber_page, reader, options, document)
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
        return document

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
    ) -> Page:
        width = float(plumber_page.width or 0.0)
        height = float(plumber_page.height or 0.0)
        rotation = int(getattr(plumber_page, "rotation", 0) or 0)

        page = Page(number=index + 1, width_pt=width, height_pt=height, rotation=rotation)

        try:
            page.text = plumber_page.extract_text() or ""
        except Exception as exc:
            page.notes.append(f"text extraction failed: {exc}")
            page.text = ""
        page.text_source = "native" if page.text.strip() else "none"

        try:
            for word in plumber_page.extract_words() or []:
                page.text_blocks.append(
                    TextBlock(text=str(word.get("text", "")), bbox=_rect_from(word))
                )
        except Exception as exc:
            page.notes.append(f"word geometry unavailable: {exc}")

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

        try:
            characters = plumber_page.chars
            page.fonts = {str(c["fontname"]) for c in characters if c.get("fontname")}
            page.raw_chars = "".join(str(c.get("text", "")) for c in characters)
        except Exception:
            page.fonts = set()
            page.raw_chars = ""

        if options.extract_tables:
            try:
                for table in plumber_page.find_tables():
                    info = _table_shape(table)
                    if info is not None:
                        page.tables.append(info)
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
    def _apply_ocr_compare(document: Document, options: IngestOptions, ocr_module: Any) -> None:
        """Read every rasterised page with OCR as well, for side-by-side comparison."""
        if not options.ocr_compare or not ocr_module.available():
            return
        for page in document.pages:
            if page.raster is None or page.ocr_text:
                continue
            page.ocr_text = ocr_module.run(page.raster)

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
                f"{len(candidates)} page(s) carry little or no text layer and OCR was not "
                f"requested, so their content was not read: "
                f"{', '.join(str(p.number) for p in candidates)}."
            )
            return

        if not ocr_module.available():
            document.load_warnings.append(
                f"{len(candidates)} page(s) carry little or no text layer and OCR is "
                f"unavailable ({ocr_module.unavailable_reason()}), so their content was "
                f"not read: {', '.join(str(p.number) for p in candidates)}."
            )
            return

        unread: list[int] = []
        for page in candidates:
            if page.raster is None:
                unread.append(page.number)
                continue
            text = ocr_module.run(page.raster)
            page.ocr_text = text
            if text.strip():
                page.text = text
                page.text_source = "ocr"
            else:
                unread.append(page.number)
        if unread:
            document.load_warnings.append(
                f"OCR produced no text for page(s) {', '.join(str(n) for n in unread)}."
            )


register(PdfLoader())
