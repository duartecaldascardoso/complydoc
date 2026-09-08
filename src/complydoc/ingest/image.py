"""Standalone image loader (PNG, JPG).

An image file is a scan with no text layer by definition, so everything depends
on OCR. Without the OCR extra the page is reported as unread rather than as
empty.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from complydoc.ingest.base import (
    Document,
    DocumentFormat,
    ImageBlock,
    IngestOptions,
    LoaderError,
    Page,
    Rect,
    sha256_of,
)
from complydoc.ingest.registry import register

_DEFAULT_DPI = 72.0


class ImageLoader:
    extensions = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
    format = DocumentFormat.IMAGE

    def load(self, path: Path, options: IngestOptions) -> Document:
        from complydoc.ingest import ocr as ocr_module

        document = Document(path=path, sha256=sha256_of(path), format=self.format)

        try:
            image = PILImage.open(path)
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise LoaderError(f"Pillow could not open the image: {exc}") from exc

        width_px, height_px = image.size
        dpi_pair = image.info.get("dpi")
        dpi_x = float(dpi_pair[0]) if dpi_pair and dpi_pair[0] else _DEFAULT_DPI
        dpi_y = float(dpi_pair[1]) if dpi_pair and len(dpi_pair) > 1 and dpi_pair[1] else dpi_x

        width_pt = width_px / dpi_x * 72.0
        height_pt = height_px / dpi_y * 72.0

        page = Page(number=1, width_pt=width_pt, height_pt=height_pt)
        page.image_blocks.append(
            ImageBlock(
                bbox=Rect(0.0, 0.0, width_pt, height_pt),
                width_px=width_px,
                height_px=height_px,
            )
        )
        page.raster = image.convert("L")
        if not dpi_pair:
            page.notes.append(
                "The file records no DPI, so 72 DPI was assumed when converting pixels "
                "to page dimensions. The reported scan DPI is derived from that assumption."
            )
        document.pages.append(page)

        if not options.ocr:
            document.load_warnings.append(
                "This is an image file with no text layer and OCR was not requested, so "
                "its content was not read at all."
            )
        elif not ocr_module.available():
            document.load_warnings.append(
                "This is an image file with no text layer and OCR is unavailable "
                f"({ocr_module.unavailable_reason()}), so its content was not read."
            )
        else:
            text = ocr_module.run(page.raster)
            if text.strip():
                page.text = text
                page.text_source = "ocr"
            else:
                document.load_warnings.append("OCR produced no text for this image.")

        return document


register(ImageLoader())
